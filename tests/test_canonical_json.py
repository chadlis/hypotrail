"""Ticket #64, AC5: records are serialised canonically (UTF-8, sorted keys, fixed separators, strict types)."""

import math

import pytest

from hypotrail.core import canonical
from hypotrail.core.errors import InvalidInputError


def test_keys_are_sorted_separators_are_fixed_and_the_text_is_utf8():
    assert canonical.dumps({"b": 1, "a": [True, None, "é"]}) == '{"a":[true,null,"é"],"b":1}'.encode("utf-8")


def test_a_configuration_declared_with_its_keys_in_another_order_has_the_same_digest():
    one = {"ridge": {"alpha": 1.0, "solver": "svd"}, "kind": "ridge_pipeline", "columns": ["a", "b"]}
    other = {"columns": ["a", "b"], "kind": "ridge_pipeline", "ridge": {"solver": "svd", "alpha": 1.0}}
    assert canonical.digest(one) == canonical.digest(other)
    assert canonical.digest(one) != canonical.digest({**one, "ridge": {"alpha": 10.0, "solver": "svd"}})


def test_the_order_of_a_list_is_part_of_the_digest():
    assert canonical.digest({"x": [1, 2]}) != canonical.digest({"x": [2, 1]})


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_nan_and_infinity_are_refused_never_written(value):
    """T21 (SPEC §10)."""
    with pytest.raises(InvalidInputError) as caught:
        canonical.dumps({"metrics": {"mae": value}})
    assert caught.value.code == "NON_CANONICAL_VALUE"
    assert caught.value.details["path"] == "/metrics/mae"


@pytest.mark.parametrize("text", ['{"a": NaN}', '{"a": Infinity}', '{"a": -Infinity}'])
def test_reading_refuses_nan_and_infinity(text):
    with pytest.raises(InvalidInputError) as caught:
        canonical.loads(text)
    assert caught.value.code == "NON_CANONICAL_VALUE"


def test_types_are_strict_a_key_that_is_not_a_string_or_a_value_that_is_not_json_is_refused():
    for bad in ({1: "x"}, {"a": {1, 2}}, {"a": object()}, {"a": b"bytes"}):
        with pytest.raises(InvalidInputError) as caught:
            canonical.dumps(bad)
        assert caught.value.code == "NON_CANONICAL_VALUE"


def test_an_integer_and_a_float_of_the_same_value_stay_distinct_and_a_bool_is_not_an_integer():
    assert canonical.dumps({"a": 1}) == b'{"a":1}'
    assert canonical.dumps({"a": 1.0}) == b'{"a":1.0}'
    assert canonical.dumps({"a": True}) == b'{"a":true}'


def test_a_duplicate_key_is_refused_when_reading():
    with pytest.raises(InvalidInputError) as caught:
        canonical.loads('{"a": 1, "a": 2}')
    assert caught.value.code == "NON_CANONICAL_VALUE"


def test_what_is_written_reads_back_and_is_canonical():
    value = {"z": [1.5, {"k": 'v\n"é"'}], "a": None}
    data = canonical.dumps(value)
    assert canonical.loads(data) == value
    assert canonical.is_canonical(data)
    assert not canonical.is_canonical(b'{"b": 1, "a": 2}')


def test_source_files_are_hashed_on_their_bytes_separately():
    assert canonical.sha256_hex(b"a,b\n") != canonical.sha256_hex(b"a, b\n")
    assert len(canonical.sha256_hex(b"")) == 64
