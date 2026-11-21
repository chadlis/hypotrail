"""Each Track defines its Partition roles in its own partitions module, and the agent Track guards `assess` with its own rule."""

import pytest

from hypotrail.agentic import partitions as agent_partitions
from hypotrail.core.errors import InvalidInputError
from hypotrail.ml import partitions as ml_partitions


def guard(partition):
    return agent_partitions.requires_exposure(partition, not_dev_code="ASSESSMENT_PARTITION_NOT_DEV", what="an Assessment", stage="assess")


def test_the_agent_guard_needs_no_exposure_on_dev():
    assert guard("dev") is False


def test_the_agent_guard_needs_an_exposure_on_public_check():
    assert guard("public_check") is True


@pytest.mark.parametrize("partition", ["train", "holdout", ""])
def test_the_agent_guard_refuses_any_other_partition_with_the_assess_code_stage_and_details(partition):
    with pytest.raises(InvalidInputError) as raised:
        guard(partition)
    error = raised.value
    assert (error.code, error.stage, error.details) == ("ASSESSMENT_PARTITION_NOT_DEV", "assess", {"partition": partition})
    assert str(error) == f"an Assessment is computed on dev or public_check only, not on {partition!r}"


def test_the_agent_roles_are_dev_and_public_check():
    assert agent_partitions.ROLES == ("dev", "public_check")


def test_the_temporal_regression_roles_are_train_dev_and_public_check():
    assert getattr(ml_partitions, "ROLES", None) == ("train", "dev", "public_check")
