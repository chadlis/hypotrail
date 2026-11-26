"""The price list of an `llm_live` Attempt and its Episode cost limit, checked before the key is read and before Inspect is imported.

The file has the shape D-146 on chadlis/hypotrail#75 and the drive's answer C3 on chadlis/hypotrail#232 give: "The
price list file is `{"source": {"url": …, "read_on": "YYYY-MM-DD"}, "models": {<Inspect's model_cost_config map>}}`.
Hypotrail validates both, passes only `models` to Inspect, and `run.json` records the content, its sha256, the URL and
the date." Each entry of `models` holds Inspect's four `ModelCost` prices, in USD per million tokens. The prices belong
to the request of an Attempt, not to the Workload, so nothing here is part of the Protocol.
"""

import datetime
import json
import math
from pathlib import Path

from hypotrail.core import canonical
from hypotrail.core.errors import InvalidInputError

PRICE_FIELDS = ("input", "output", "input_cache_write", "input_cache_read")
SOURCE_FIELDS = ("url", "read_on")


def _invalid(path: Path, problem: str) -> InvalidInputError:
    return InvalidInputError("PRICE_LIST_INVALID", f"the price list {path} is refused: {problem}", stage="config", details={"path": str(path), "problem": problem})


def _is_price(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def _checked_source(path: Path, source) -> dict:
    if not isinstance(source, dict) or set(source) != set(SOURCE_FIELDS):
        raise _invalid(path, "`source` is an object with exactly `url` and `read_on`")
    url, read_on = source["url"], source["read_on"]
    if not isinstance(url, str) or not url.startswith(("https://", "http://")):
        raise _invalid(path, "`source.url` is the http(s) URL of the provider's price page")
    try:
        valid_date = isinstance(read_on, str) and datetime.date.fromisoformat(read_on).isoformat() == read_on
    except ValueError:
        valid_date = False
    if not valid_date:
        raise _invalid(path, "`source.read_on` is the date the page was read, as YYYY-MM-DD")
    return source


def _checked_models(path: Path, models) -> dict:
    if not isinstance(models, dict) or not models:
        raise _invalid(path, "`models` is a non-empty object mapping a model to its prices")
    for name, prices in models.items():
        if not isinstance(prices, dict) or set(prices) != set(PRICE_FIELDS) or not all(_is_price(prices[f]) for f in PRICE_FIELDS):
            raise _invalid(path, f"the prices of {name!r} are exactly {', '.join(PRICE_FIELDS)}, each a number of USD per million tokens, 0 or more")
    return models


def read_price_list(path: Path) -> dict:
    """The checked price list: {"content", "sha256", "url", "read_on"}, as `run.json` records it, or `PRICE_LIST_INVALID` (exit 2)."""
    path = Path(path)
    try:
        data = path.read_bytes()
        content = json.loads(data)
    except (OSError, ValueError):
        raise _invalid(path, "the file cannot be read as JSON") from None
    if not isinstance(content, dict):
        raise _invalid(path, "the file holds one JSON object")
    for key in ("source", "models"):
        if key not in content:
            raise _invalid(path, f"the `{key}` key is missing")
    if set(content) != {"source", "models"}:
        raise _invalid(path, "the object holds exactly `source` and `models`")
    source = _checked_source(path, content["source"])
    _checked_models(path, content["models"])
    return {"content": content, "sha256": canonical.sha256_hex(data), "url": source["url"], "read_on": source["read_on"]}


def models_of(price_list: dict) -> dict:
    """The `models` map of a checked price list: the only part Inspect is given, as its `model_cost_config`."""
    return price_list["content"]["models"]


def require_priced(price_list: dict, model: str) -> None:
    """`MODEL_NOT_PRICED` (exit 2) for a requested model the price list does not price: nothing is sent unpriced."""
    priced = sorted(models_of(price_list))
    if model not in priced:
        raise InvalidInputError(
            "MODEL_NOT_PRICED",
            f"the price list does not price the model {model!r}; it prices {', '.join(priced)}",
            stage="config",
            details={"model": model, "priced": priced},
        )


def require_cost_limit(value) -> float:
    """The Episode cost limit in USD, a finite number above 0, or `COST_LIMIT_OUT_OF_BOUNDS` (exit 2)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise InvalidInputError(
            "COST_LIMIT_OUT_OF_BOUNDS",
            f"--episode-cost-limit-usd is a number of USD above 0, not {value!r}",
            stage="config",
            details={"cost_limit_usd": value},
        )
    return float(value)
