"""Reading an Inspect log for `import agent`, through Inspect's public log API only (ADR 0001, SPEC IMP-03).

This is the one module of the import that imports Inspect; `hypotrail.agentic.imports` loads it only
for a source that is an Inspect log, after checking that Inspect is importable. The log is read once
(`read_eval_log`), never parsed by hand, and nothing in it is executed. The Episodes are the
projection of `hypotrail.agentic.projection` (the one `rescore_log` uses), so a log gives the same
Episodes whichever way it is scored. What the header states is returned as plain values, and only
the fields listed in `HEADER_FIELDS`: nothing else of the header (model arguments, base URL,
environment) is copied.
"""

from inspect_ai.log import read_eval_log

from hypotrail.agentic import imports, limits, projection
from hypotrail.core.errors import HypotrailError, InvalidInputError

STAGE = "import"
MOCK_PROVIDER = "mockllm"
# What the header states and the import records as `declared`.
HEADER_FIELDS = (
    "model",
    "generation_time",
    "configuration",
    "system_text",
    "mode",
    "limits",
    "inspect_version",
    "log_format_version",
    "log_status",
)


def _refuse(code, message, **details):
    return InvalidInputError(code, message, stage=STAGE, details=details)


def read(location, *, header_only=False):
    """The log, read through the public API; a file Inspect cannot read is refused (only the error's type is reported)."""
    try:
        return read_eval_log(str(location), header_only=header_only)
    except Exception as error:
        raise _refuse(
            "LOG_NOT_READABLE",
            "the source is not an Inspect log the installed Inspect can read",
            source=str(location),
            error_type=type(error).__name__,
        ) from None


def is_mock(model) -> bool:
    return isinstance(model, str) and model.split("/", 1)[0] == MOCK_PROVIDER


def header_of(log) -> dict:
    """The values the log header states, as plain data; None where the header does not state one."""
    header = log.eval
    metadata = header.metadata if isinstance(header.metadata, dict) else {}
    try:
        stated_limits = limits.effective_limits(log)
    except HypotrailError:
        stated_limits = None
    return {
        "model": header.model,
        "generation_time": header.created,
        "configuration": metadata.get("configuration"),
        "system_text": metadata.get("system_text"),
        "mode": metadata.get("mode"),
        "limits": stated_limits,
        "inspect_version": (header.packages or {}).get("inspect_ai"),
        "log_format_version": log.version,
        "log_status": log.status,
    }


def usage_by_key(log) -> dict:
    """{(case_id, repeat): {"latency_seconds", "tokens"}} of the samples the log holds, as the log states them.

    Latency is the sample's `total_time`; tokens are `total_tokens` summed over the models the sample used (the
    cached input tokens included). A figure the log does not give is None, never zero (CMP-06).
    """
    out = {}
    for sample in log.samples or []:
        totals = [u.total_tokens for u in (sample.model_usage or {}).values() if u.total_tokens is not None]
        out[(str(sample.id), sample.epoch - 1)] = {
            "latency_seconds": None if sample.total_time is None else float(sample.total_time),
            "tokens": sum(totals) if totals else None,
        }
    return out


def checked_episodes(log, keys: list, partition: str, partition_of: dict) -> tuple[list, int]:
    """(the projected Episode of every expected key, the number of samples read).

    A sample outside the population, or two samples for one (Case, Repeat), is refused; an expected
    Episode the log does not hold is `missing`, as the projection decides.
    """
    expected = set(keys)
    cases_listed = {case_id for case_id, _ in keys}
    seen = set()
    samples = log.samples or []
    for sample in samples:
        key = (str(sample.id), sample.epoch - 1)
        case_id, repeat = key
        if key not in expected:
            raise _refuse(
                "LOG_EPISODE_OUTSIDE_POPULATION",
                f"({case_id}, repeat {repeat}) is in the log and is not an Episode of the population",
                case_id=case_id,
                repeat=repeat,
                problem=imports.problem_outside_population(case_id, partition, partition_of, cases_listed),
            )
        if key in seen:
            raise _refuse("LOG_EPISODE_DUPLICATE", f"({case_id}, repeat {repeat}) appears twice in the log", case_id=case_id, repeat=repeat)
        seen.add(key)
    return projection.project_episodes(log, expected=keys), len(samples)
