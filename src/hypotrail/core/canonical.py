"""Canonical JSON: the one byte form of every record and of every digest of a configuration.

UTF-8, object keys sorted by Unicode code point, compact separators (`,` and `:`), strict types
(SPEC ID-02): `null`, booleans, integers, finite floats, strings, lists and objects with string
keys, and nothing else. `NaN` and `Infinity` are refused, in both directions, and never written.
An integer and a float of the same value stay distinct (`1` and `1.0`), and a boolean is not an
integer. A duplicate key is refused when reading.

Source files are not canonicalised: they are hashed on their bytes, separately (`sha256_hex`).

Copied from `hypotrail/hypotrail` at commit `4ef4925`, file
`framework/mlkit/study/understanding/canonical.py` (canonical JSON v1: string escaping, strict
reading, duplicate keys, depth), and owned here (chadlis/hypotrail#64, Tightened D); nothing is
imported from that project. Changed from the source: a finite float is written as its shortest
round-trip text (`repr`) instead of being refused in favour of a `{"decimal": ...}` object,
because the contract schema types its metrics and parameters as JSON numbers; the errors are
`InvalidInputError`s of this project; the helpers for decimal objects and sorted sets are not copied.
"""

import hashlib
import json
import math
from typing import Any

from hypotrail.core.errors import InvalidInputError

MAX_SAFE = 2**53 - 1
MAX_DEPTH = 32
_SHORT = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\t": "\\t", "\n": "\\n", "\f": "\\f", "\r": "\\r"}


def _refuse(message: str, path: str = "") -> InvalidInputError:
    return InvalidInputError(
        "NON_CANONICAL_VALUE",
        f"{message} at {path or '<root>'}",
        stage="canonical",
        details={"path": path or "", "reason": message},
    )


def _string(text: str, path: str) -> str:
    out = ['"']
    for char in text:
        code = ord(char)
        if 0xD800 <= code <= 0xDFFF:
            raise _refuse("lone surrogate in a string", path)
        if char in _SHORT:
            out.append(_SHORT[char])
        elif code < 0x20:
            out.append(f"\\u{code:04x}")
        else:
            out.append(char)
    out.append('"')
    return "".join(out)


def _write(value: Any, path: str, depth: int, out: list) -> None:
    if depth > MAX_DEPTH:
        raise _refuse("nesting deeper than the limit", path)
    if value is None:
        out.append("null")
    elif value is True:
        out.append("true")
    elif value is False:
        out.append("false")
    elif isinstance(value, int):
        if not -MAX_SAFE <= value <= MAX_SAFE:
            raise _refuse("integer outside the safe range", path)
        out.append(str(int(value)))
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise _refuse("a non-finite number (NaN or Infinity)", path)
        out.append(repr(float(value)))
    elif isinstance(value, str):
        out.append(_string(value, path))
    elif isinstance(value, dict):
        for key in value:
            if not isinstance(key, str):
                raise _refuse("object key is not a string", path)
        out.append("{")
        for index, key in enumerate(sorted(value)):
            if index:
                out.append(",")
            out.append(_string(key, path))
            out.append(":")
            _write(value[key], f"{path}/{key}", depth + 1, out)
        out.append("}")
    elif isinstance(value, (list, tuple)):
        out.append("[")
        for index, item in enumerate(value):
            if index:
                out.append(",")
            _write(item, f"{path}/{index}", depth + 1, out)
        out.append("]")
    else:
        raise _refuse(f"unsupported type {type(value).__name__}", path)


def dumps(value: Any) -> bytes:
    """The canonical bytes of `value`; a value outside canonical JSON is an `InvalidInputError`."""
    out: list[str] = []
    _write(value, "", 0, out)
    return "".join(out).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest(value: Any) -> str:
    """SHA-256 (hex) of the canonical bytes of `value`."""
    return sha256_hex(dumps(value))


def _pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise _refuse(f"duplicate key {key!r}")
        out[key] = value
    return out


def _no_constant(text):
    raise _refuse(f"{text} is not allowed")


def _int(text):
    value = int(text)
    if not -MAX_SAFE <= value <= MAX_SAFE:
        raise _refuse("integer outside the safe range")
    return value


def _float(text):
    value = float(text)
    if not math.isfinite(value):
        raise _refuse("a number beyond the double range")
    return value


def loads(data: bytes | str) -> Any:
    """Parse JSON strictly (duplicates, `NaN`, `Infinity`, out-of-range numbers refused).

    It does not require the input to be in canonical form: use `is_canonical` for that.
    """
    if isinstance(data, bytes):
        try:
            data = data.decode("utf-8")
        except UnicodeDecodeError:
            raise _refuse("not UTF-8") from None
    try:
        value = json.loads(
            data, object_pairs_hook=_pairs, parse_constant=_no_constant, parse_int=_int, parse_float=_float
        )
    except InvalidInputError:
        raise
    except (ValueError, RecursionError) as error:
        raise _refuse(f"not JSON: {type(error).__name__}") from None
    dumps(value)  # depth, surrogates
    return value


def is_canonical(data: bytes) -> bool:
    try:
        return dumps(loads(data)) == data
    except InvalidInputError:
        return False
