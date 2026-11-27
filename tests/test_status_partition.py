"""`attempts[].partition` in `status --json`: the Partition of the Observation set each Attempt produced, read from that record's
`provenance.partition`, or null. The run tool reads it to refuse a `public_check` read before it starts a command. The CLI is run in
process, offline."""

import json

from _assess_helpers import observation_set_id
from _client_helpers import chinook_pending_study, public_check_study
from _study_helpers import run_json


def attempts_of(study) -> list:
    code, payload, err = run_json("status", "--study", study)
    assert code == 0, (payload, err)
    return payload["attempts"]


def provenance_partition(study, attempt) -> str:
    """The Partition the Observation set record of an Attempt names, read from the Study's files."""
    [path] = (study / "attempts" / attempt["attempt_id"]).glob("observation_set.json")
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["observation_set_id"] == observation_set_id(study, attempt)
    return record["provenance"]["partition"]


def test_each_attempt_of_a_bike_study_gives_the_partition_its_observation_set_names_dev_or_public_check(tmp_path):
    study = public_check_study(tmp_path)
    attempts = attempts_of(study)
    by_request = {attempt["request_id"]: attempt["partition"] for attempt in attempts}
    assert by_request == {"ml-dev-seasonal_7": "dev", "ml-dev-ridge_v1": "dev", "ml-public_check-seasonal_7": "public_check"}
    for attempt in attempts:
        assert attempt["partition"] == provenance_partition(study, attempt), attempt["attempt_id"]


def test_each_import_of_a_chinook_study_gives_the_partition_of_its_population(tmp_path):
    study = chinook_pending_study(tmp_path)
    attempts = attempts_of(study)
    assert len(attempts) == 2
    for attempt in attempts:
        assert attempt["partition"] == provenance_partition(study, attempt) == "dev", attempt["attempt_id"]


def test_an_attempt_that_produced_no_observation_set_gives_a_null_partition(tmp_path):
    from test_run_ml import killed

    study, _ = killed(tmp_path, kill_at=4)
    [running] = attempts_of(study)
    assert running["technical_status"] == "running" and running["observation_set_id"] is None
    assert "partition" in running and running["partition"] is None
