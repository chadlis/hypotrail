"""Ticket #66: `assess` writes an Assessment record valid against the contract schema."""

import json

from _assess_helpers import assess, fresh_study, observation_set_id, references_id
from _study_helpers import sha256

from hypotrail.core import canonical, contracts


def test_assess_writes_an_assessment_valid_against_the_contract_schema(tmp_path):
    study, attempts = fresh_study(tmp_path, "seasonal_7")
    obs = observation_set_id(study, attempts["seasonal_7"])
    code, payload, err = assess(study, obs, "regression_mae_v1", references_id(study))
    assert code == 0, (payload, err)
    record = payload["assessment"]
    contracts.validate(record)
    folder = study / "assessments" / record["assessment_id"]
    assert (folder / "assessment.json").read_bytes() == canonical.dumps(record)
    assert json.loads((folder / "assessment.json").read_text()) == record
    assert record["kind"] == "assessment" and record["observation_set_id"] == obs
    scorer = record["scorer"]
    assert scorer["id"] == "regression_mae_v1" and scorer["version"] == "1"
    assert scorer["config_digest"] == canonical.digest({"criterion": "absolute_error", "metric": "mae", "direction": "lower_is_better"})
    assert record["references_ref"]["role"] == "references"
    assert record["references_ref"]["sha256"] == sha256(study / "artifacts" / "references.csv")
    assert record["per_item_ref"]["path"] == f"assessments/{record['assessment_id']}/per_item.csv"
    assert record["per_item_ref"]["sha256"] == sha256(folder / "per_item.csv")
    assert record["limitations"] and record["metrics"][0]["id"] == "mae"
    assert required_fields_of_the_ticket() <= set(record) | {"scorer_id", "scorer_version", "scorer_config_digest"}


def required_fields_of_the_ticket() -> set:
    """SPEC §5: assessment_id, observation_set_id, references_ref, scorer_id/version/config_digest, counts, per_item_ref, metrics, limitations."""
    return {
        "assessment_id", "observation_set_id", "references_ref", "scorer_id", "scorer_version", "scorer_config_digest",
        "counts", "per_item_ref", "metrics", "limitations",
    }
