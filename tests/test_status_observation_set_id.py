"""`attempts[].observation_set_id` in `status --json` (D-157 on chadlis/hypotrail#75): the id of the Observation set each Attempt produced, read
from the Attempt's own record, or null; it lets a client match an Assessment to the Attempt it cites. The CLI is run in process, offline."""

from _assess_helpers import observation_set_id
from _client_helpers import compared_study
from _study_helpers import run_json


def read(study) -> dict:
    code, payload, err = run_json("status", "--study", study)
    assert code == 0, (payload, err)
    return payload


def test_each_assessment_of_a_bike_study_matches_one_dev_attempt_by_the_observation_set_id_status_lists(tmp_path):
    payload = read(compared_study(tmp_path))
    assert len(payload["assessments"]) == 2
    for assessment in payload["assessments"]:
        cited = [attempt for attempt in payload["attempts"] if attempt.get("observation_set_id") == assessment["observation_set_id"]]
        assert [attempt["request_id"] for attempt in cited] in (["ml-dev-seasonal_7"], ["ml-dev-ridge_v1"]), assessment["assessment_id"]


def test_the_observation_set_id_of_an_attempt_is_the_one_its_own_record_names_and_null_for_an_attempt_that_produced_none(tmp_path):
    from test_run_ml import killed

    study = compared_study(tmp_path / "compared")
    for attempt in read(study)["attempts"]:
        assert attempt["observation_set_id"] == observation_set_id(study, attempt)
    killed_study, _ = killed(tmp_path / "killed", kill_at=4)
    [running] = read(killed_study)["attempts"]
    assert running["technical_status"] == "running" and running["observation_set_id"] is None
