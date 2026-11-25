"""What the two import commands, `import ml` (`hypotrail.ml.imports`) and `import agent` (`hypotrail.agentic.imports`), share.

- `read_input`: the bytes of an input file, or its refusal;
- `strict_json_or_none`: the strict JSON read that identifies a request, which gives None where an input is not strict JSON;
- `SERIALIZED_SUFFIXES`, `SERIALIZED_MAGIC` and `require_not_serialized`: the refusal of a source that is a serialized object,
  which is never loaded;
- `producer_entry`, with `UNKNOWN` and `DECLARED`: how a producer field is recorded.

Each refusal has the stage `import`. The core knows no Track, so each command passes what differs: the code and the word of an
input file, and what it adopts in place of a serialized source.
"""

from pathlib import Path

from hypotrail.core import canonical
from hypotrail.core.errors import InvalidInputError

STAGE = "import"
UNKNOWN = "unknown"
DECLARED = "declared"
SERIALIZED_SUFFIXES = (".pkl", ".pickle", ".joblib", ".npy", ".npz")
SERIALIZED_MAGIC = b"\x80"  # pickle protocol 2 and later


def read_input(path, code: str, what: str) -> bytes:
    """The bytes of the input file `what` (`source`, `mapping` or `population`); a file that cannot be read is refused with `code`."""
    try:
        return Path(path).read_bytes()
    except OSError:
        raise InvalidInputError(code, f"the {what} file cannot be read: {path}", stage=STAGE, details={what: str(path)}) from None


def strict_json_or_none(raw: bytes):
    """The value of `raw` read as strict JSON, or None when it is not: used only to identify a request, never to accept an input."""
    try:
        return canonical.loads(raw)
    except InvalidInputError:
        return None


def require_not_serialized(raw: bytes, source_path, *, adopts: str) -> None:
    """Refuse with `SOURCE_SERIALIZED` a source whose suffix or first byte is that of a serialized object; `adopts` names what the command adopts instead."""
    if Path(source_path).suffix.lower() in SERIALIZED_SUFFIXES or raw.startswith(SERIALIZED_MAGIC):
        raise InvalidInputError(
            "SOURCE_SERIALIZED",
            f"the source is a serialized object (pickle, joblib or an array dump); an import adopts {adopts} and loads nothing",
            stage=STAGE,
            details={"source": str(source_path)},
        )


def producer_entry(value) -> dict:
    """A producer field as it is recorded: its value, `declared`, or `unknown` when the value is None or empty."""
    return {"value": value, "origin": UNKNOWN if value in (None, "") else DECLARED}
