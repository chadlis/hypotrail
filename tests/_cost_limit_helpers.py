"""Shared by the tests of the Episode cost limit: a price list file, and Inspect's mock model made priceable.

Inspect prices a model only when its model database knows it (`set_model_cost` refuses an unknown name), and neither
Inspect's mock model nor the helpers' `anthropic/claude-test-1` is in it. `priceable` registers both, with no price,
so that the price list a test writes is what prices them; it clears Inspect's registry afterwards, so no later test of
the process sees a cost it did not set.
"""

import contextlib
import json
from pathlib import Path

from inspect_ai.model import ModelInfo, set_model_info
from inspect_ai.model._model_info import clear_model_info_cache

MOCK = "mockllm/model"
TEST_MODEL = "anthropic/claude-test-1"
SOURCE = {"url": "https://example.com/pricing", "read_on": "2026-11-26"}
# USD per million tokens: the prices of D-146's illustration (2 / 10, cache write 2.5), and a cache read of 0.2
PRICES = {"input": 2.0, "output": 10.0, "input_cache_write": 2.5, "input_cache_read": 0.2}


def price_list(models=(TEST_MODEL, MOCK), *, source=SOURCE, prices=PRICES) -> dict:
    content = {"models": {name: dict(prices) for name in models}}
    if source is not None:
        content["source"] = dict(source)
    return content


def write_price_list(folder, content=None, name="price-list.json") -> Path:
    path = Path(folder) / name
    path.write_text(json.dumps(price_list() if content is None else content, indent=2), encoding="utf-8")
    return path


@contextlib.contextmanager
def priceable(*models):
    """Inspect's model database knows `models` (default: the mock model and the test model) while the block runs."""
    for name in models or (MOCK, TEST_MODEL):
        set_model_info(name, ModelInfo(organization="test", model=name))
    try:
        yield
    finally:
        clear_model_info_cache()
