"""The ordinary client reads stop at protected ranking Study metadata."""

import pytest
from _ranking_helpers import command, initialize, ranking_paths

from hypotrail.core import artifacts
from hypotrail.core import study as layout


@pytest.mark.parametrize("read", ["status", "figures", "profile", "lesson"])
@pytest.mark.parametrize("inherited_evaluator", [False, True])
def test_client_reads_refuse_before_opening_protected_ranking_records(read, inherited_evaluator, ranking_paths, monkeypatch):
    _, _, study = ranking_paths
    code, _, err = initialize(ranking_paths)
    assert code == 0, err
    spec = {**layout.read_spec(study), "partition": "held_out"}
    # Plant just the protected metadata. The Study holds no protected payload.
    monkeypatch.setattr(layout, "read_spec", lambda _: spec)
    if inherited_evaluator:
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        monkeypatch.setenv("GITHUB_WORKFLOW_REF", "chadlis/mlkit/.github/workflows/evaluator.yml@refs/heads/main")
    else:
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        monkeypatch.delenv("GITHUB_WORKFLOW_REF", raising=False)

    with monkeypatch.context() as guarded:
        for name in ("attempt_ids", "read_record", "read_records", "comparison_records"):
            guarded.setattr(layout, name, lambda *_: pytest.fail("opened protected ranking records"))
        guarded.setattr(artifacts, "read_verified", lambda *_: pytest.fail("opened a protected ranking artifact"))
        code, answer, err = command(read, "--study", study)

    assert code == 2, (answer, err)
    assert answer["error"]["code"] == "RANKING_HELD_OUT_REFUSED"
