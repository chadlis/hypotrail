"""The protected evaluator's aggregate receipt, cited from an ordinary ranking Study (D-265)."""

import re
from pathlib import Path

from hypotrail.core import artifacts, canonical, evaluator, intervals, study_write
from hypotrail.core import study as layout
from hypotrail.core.errors import IntegrityError, InvalidInputError

RECEIPTS_DIR = f"{layout.ARTIFACTS_DIR}/ranking-reviews"
SCHEMA_VERSION = "ranking-evaluation-review/1"
RULE = "mlkit-ranking-acceptance@1"
SOURCE = "https://github.com/chadlis/hypotrail/issues/75#issuecomment-7235501369"
QUESTION = "Confirm the protected ranking verdict"
QUESTION_ID = "confirm_ranking_verdict"
_OPTIONS = ("accepted", "keep_control")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_FIELDS = (
    "proxy_decision_id", "comparison_id", "frame_digest", "option", "rule", "source",
    "delta", "interval", "usable_resamples", "omitted_dates",
)


def _require_ordinary_ranking(study: Path) -> dict:
    spec = layout.read_spec(study)
    layout.require_domain(spec, "ranking", study_write.REVIEW_IMPORT)
    return spec


def _matches(pattern, value) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _number(value) -> bool:
    return type(value) in (int, float) and -1 <= value <= 1


def _interval(value) -> bool:
    return value is None or (
        isinstance(value, list) and len(value) == 2
        and all(_number(bound) for bound in value) and value[0] <= value[1]
    )


def _matches_verdict(record: dict) -> bool:
    """Check the published values against the declared Round 5 rule (D-247)."""
    bounds = record["interval"]
    usable = record["usable_resamples"]
    if usable > intervals.RESAMPLES or (bounds is None) != (usable == 0):
        return False
    delta = record["delta"]
    accepted = bounds is not None and bounds[0] > 0 and delta is not None and delta >= 0.01
    return record["option"] == ("accepted" if accepted else "keep_control")


def _read_receipt(path: Path, *, expected_digest: str | None = None) -> dict | None:
    """Read the allowlisted projection. Malformed bytes and fields never enter a diagnostic."""
    try:
        data = path.read_bytes()
        if expected_digest is not None and canonical.sha256_hex(data) != expected_digest:
            return None
        record = canonical.loads(data)
    except (OSError, InvalidInputError):
        return None
    if not isinstance(record, dict) or record.keys() != {*_FIELDS, "schema_version"}:
        return None
    if (
        record["schema_version"] != SCHEMA_VERSION
        or not _matches(_UUID, record["proxy_decision_id"])
        or not _matches(_UUID, record["comparison_id"])
        or not _matches(_DIGEST, record["frame_digest"])
        or record["option"] not in _OPTIONS
        or record["rule"] != RULE
        or record["source"] != f"{SOURCE} frame_digest={record['frame_digest']}"
        or (record["delta"] is not None and not _number(record["delta"]))
        or not _interval(record["interval"])
        or not all(type(record[field]) is int and record[field] >= 0 for field in ("usable_resamples", "omitted_dates"))
        or not _matches_verdict(record)
    ):
        return None
    return record


def _artifact_id(digest: str) -> str:
    return f"ranking-review-{digest}"


def _corrupt_receipt() -> IntegrityError:
    return IntegrityError(
        "RANKING_REVIEW_INTEGRITY", "A stored ranking review receipt does not match its recorded artifact",
        stage="review", details={},
    )


def records(study, spec: dict) -> dict:
    """The verified receipts keyed by citable artifact ID, with their exact aggregate field set."""
    if spec["domain"] != "ranking" or evaluator.is_protected(spec):
        return {}
    artifacts.resolve(study, RECEIPTS_DIR)
    found = {}
    proxy_ids = set()
    for name in layout.record_names(study, RECEIPTS_DIR):
        digest = name.removesuffix(".json")
        if not _matches(_DIGEST, digest):
            raise _corrupt_receipt()
        receipt = _read_receipt(artifacts.resolve(study, f"{RECEIPTS_DIR}/{name}"), expected_digest=digest)
        if receipt is None or receipt["proxy_decision_id"] in proxy_ids:
            raise _corrupt_receipt()
        found[_artifact_id(digest)] = receipt
        proxy_ids.add(receipt["proxy_decision_id"])
    return found


def check_choice(question: str, option: str, option_id: str) -> None:
    """Check the question and verdict IDs supplied in the ordinary Study's read."""
    if question != QUESTION or option != option_id or option not in _OPTIONS:
        raise study_write.invalid_arguments("Use the ranking review's question and verdict from status", study_write.DECIDE)


def _has_panel_words(decision: dict) -> bool:
    words = decision.get("words") or {}
    return decision["author"] == "human" and words.get("channel") == "panel" and any(text.strip() for text in words["texts"])


def require_confirmation(study, spec: dict, decision: dict) -> None:
    """A typed ranking Record must cite its own receipt and retain the person's panel words."""
    cited = decision["cited_ids"]
    receipt = records(study, spec).get(cited[0]) if len(cited) == 1 else None
    if receipt is None or decision["option"] != receipt["option"] or not _has_panel_words(decision):
        raise study_write.invalid_arguments(
            "A ranking confirmation cites its matching review and requires the person's panel words",
            study_write.DECIDE,
        )


def _projection(artifact_id: str, receipt: dict, history: list) -> dict:
    def confirms(decision: dict) -> bool:
        return (
            decision["applies"] and decision["cited_ids"] == [artifact_id] and _has_panel_words(decision)
            and decision["question"] == QUESTION and decision.get("question_id") == QUESTION_ID
            and decision["option"] == receipt["option"] and decision.get("option_id") == receipt["option"]
        )

    return {
        "artifact_id": artifact_id,
        **{key: receipt[key] for key in _FIELDS},
        "question": QUESTION,
        "question_id": QUESTION_ID,
        "option_id": receipt["option"],
        "pending": not any(confirms(decision) for decision in history),
    }


def listing(study, spec: dict, history: list) -> list:
    """The read-only verdicts and whether each still needs the owner's applicable panel Record."""
    return [_projection(artifact_id, receipt, history) for artifact_id, receipt in records(study, spec).items()]


def import_receipt(study, path: Path, *, read_sequence: int) -> dict:
    """Keep the canonical aggregate receipt after checking the writer sequence and destination."""
    from hypotrail.core import decisions

    study = Path(study)
    study_write.check_read_sequence(study_write.REVIEW_IMPORT, read_sequence)
    if read_sequence is None:
        raise study_write.invalid_arguments("--read-sequence is required", study_write.REVIEW_IMPORT)
    _require_ordinary_ranking(study)
    with study_write.locked(study, study_write.REVIEW_IMPORT, read_sequence=read_sequence) as write:
        spec = _require_ordinary_ranking(study)
        write.require_current()
        receipt = _read_receipt(path)
        if receipt is None:
            raise InvalidInputError(
                "RANKING_REVIEW_INVALID", "Expected an aggregate ranking review receipt with the declared rule and source",
                stage="review", details={},
            )
        digest = canonical.digest(receipt)
        artifact_id = _artifact_id(digest)
        existing = records(study, spec)
        if artifact_id in existing:
            return _projection(artifact_id, receipt, decisions.history(study))
        if any(earlier["proxy_decision_id"] == receipt["proxy_decision_id"] for earlier in existing.values()):
            raise InvalidInputError(
                "RANKING_REVIEW_INVALID", "The Study already holds a different receipt for this proxy Decision",
                stage="review", details={},
            )
        write.begin()
        artifacts.publish_record(study, f"{RECEIPTS_DIR}/{digest}.json", receipt, role=study_write.RANKING_REVIEW)
        write.wrote(study_write.RANKING_REVIEW, artifact_id)
        return _projection(artifact_id, receipt, [])
