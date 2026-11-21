"""The two Tracks a report is rendered for (#85 Bike, #86 Chinook): the Studies each test builds, behind one interface.

A test parametrised over `TRACKS` asks a Track for a Study and reads the page; nothing in the test names Bike or Chinook.
"""

from pathlib import Path

import pytest
from _assess_helpers import assess, fresh_study, observation_set_id, references_id
from _compare_helpers import compare
from _report_helpers import dev_world
from _study_helpers import examples_copy, init_study, run_ml


class Bike:
    name = "bike"
    native_mode = "native_ml"
    dataset = "datasets/day.csv"
    blocked = {"inspect_ai", "sklearn", "numpy", "anthropic"}
    # strings an Import declares: each is shown as the same characters, nothing created from it
    markup = {
        "model": 'https://evil.example/model <script>alert(1)</script> "><xx-marker>m</xx-marker>',
        "generated_at": "//evil.example/generated <img src=x onerror=alert(1)>",
        "historical_protocol": 'x" onmouseover="alert(1)" y="',
        "tool_use": "</td><xx-marker>t</xx-marker> &amp; &lt;b&gt;",
    }
    producer_claims = ("model", "historical_protocol")
    configs = ("seasonal_7", "ridge_v1")

    def world(self, tmp_path, *, name="world", imported=True):
        study, facts = dev_world(tmp_path, name=name, imported=imported, markup=self.markup if imported else None)
        facts["import_index"] = self.import_index(study, facts) if imported else None
        return study, facts

    @staticmethod
    def import_index(study, facts):
        return index_of_attempt(study, facts["import"]["attempt_id"])

    def dev_study(self, tmp_path, *, name="dev"):
        return fresh_study(tmp_path / name, "seasonal_7")[0]

    def public_world(self, tmp_path, *, name="public"):
        """(study, {config: Attempt}, [Assessment ids], Comparison): two Attempts on public_check, assessed and compared (one Exposure each)."""
        study, attempts = fresh_study(tmp_path / name, *self.configs, partition="public_check")
        ids = []
        for config in self.configs:
            code, payload, err = assess(study, observation_set_id(study, attempts[config]), "regression_mae_v1", references_id(study))
            assert code == 0, (payload, err)
            ids.append(payload["assessment"]["assessment_id"])
        code, both, err = compare(study, ids[0], ids[1])
        assert code == 0, (both, err)
        return study, attempts, ids, both["comparison"]

    def public_outputs(self, tmp_path, *, name="outputs"):
        """(study, Attempt): one Attempt on public_check, no Assessment."""
        study, attempts = fresh_study(tmp_path / name, "seasonal_7", partition="public_check")
        return study, attempts["seasonal_7"]

    def public_assessed(self, tmp_path, *, name="one"):
        """(study, Attempt): one Attempt on public_check, assessed once (one journal entry)."""
        study, attempts = fresh_study(tmp_path / name, "seasonal_7", partition="public_check")
        code, payload, err = assess(study, observation_set_id(study, attempts["seasonal_7"]), "regression_mae_v1", references_id(study))
        assert code == 0, (payload, err)
        return study, attempts["seasonal_7"]

    def question_study(self, tmp_path, question):
        examples = examples_copy(tmp_path, edit=lambda d: d.update(question=question))
        return init_study(tmp_path, examples=examples)[0]

    def exposed_study(self, tmp_path, *, name="chapter"):
        """A Study with a freeze record, journal entries and one record of each kind marked check_informed; the examples to report with."""
        from _revision_helpers import new_revision

        study, attempts = fresh_study(tmp_path / name, "seasonal_7", partition="public_check")
        _, first, _ = assess(study, observation_set_id(study, attempts["seasonal_7"]), "regression_mae_v1", references_id(study))
        changed = examples_copy(tmp_path / name, edit=lambda d: d["configurations"]["ridge_v1"]["ridge"].update(alpha=2.5))
        _, ridge, _ = run_ml(study, "ridge_v1", "public_check", "changed", "--examples-dir", changed)
        _, second, _ = assess(study, observation_set_id(study, ridge["attempt"]), "regression_mae_v1", references_id(study), "--examples-dir", changed)
        code, both, err = compare(study, first["assessment"]["assessment_id"], second["assessment"]["assessment_id"], "--examples-dir", changed)
        assert code == 0, (both, err)

        def corrected_day(table):
            row = next(r for r in table if r["dteday"] == "2012-03-15")
            row["cnt"], row["registered"] = str(int(row["cnt"]) + 1000), str(int(row["registered"]) + 1000)

        code, payload, err = new_revision(study, "--examples-dir", examples_copy(tmp_path / name, rows=corrected_day, name="revised"))
        assert code == 0, (payload, err)
        return study, tmp_path / name / "revised"


class Chinook:
    name = "chinook"
    native_mode = "llm_live"
    dataset = "datasets/Chinook_Sqlite.sqlite"
    blocked = {"inspect_ai", "anthropic"}
    markup = {
        "generation_time": "//evil.example/generated <img src=x onerror=alert(1)>",
        "historical_protocol": 'x" onmouseover="alert(1)" y="',
        "answer": '<script>alert(1)</script> </td><xx-marker>t</xx-marker> "><b onclick=x> &amp; &lt;b&gt;',
    }
    producer_claims = ("generation_time", "historical_protocol")
    configs = ("plain", "verify")
    cases = ["D01", "D03", "D07", "D08"]
    repeats = 2

    def world(self, tmp_path, *, name="world", imported=True):
        from _agent_compare_helpers import answer_lines
        from _agent_compare_helpers import assess as assess_agent
        from _agent_compare_helpers import compare as compare_agent
        from _agent_compare_helpers import imported as import_lines
        from _agent_compare_helpers import observation_set_of
        from _chinook_helpers import FIXTURE_CASES
        from _run_agent_helpers import live, ok, patch_model, study_of

        base = tmp_path / name
        base.mkdir(parents=True, exist_ok=True)
        study = study_of(base)
        with pytest.MonkeyPatch.context() as mp:
            patch_model(mp)
            attempts = {c: ok(live(study, c, f"live-{c}", cases=FIXTURE_CASES, repeats=self.repeats)) for c in self.configs}
        assessments = {c: assess_agent(study, observation_set_of(study, a)) for c, a in attempts.items()}
        code, both, err = compare_agent(study, assessments["plain"], assessments["verify"])
        assert code == 0, (both, err)
        facts = {"attempts": attempts, "assessments": {c: a["assessment_id"] for c, a in assessments.items()}, "comparison": both["comparison"]}
        if imported:
            lines = answer_lines(repeats=self.repeats, model=None, tool_use=None, mode=None)
            for line in lines:
                line.setdefault("producer", {}).update(generation_time=self.markup["generation_time"], historical_protocol=self.markup["historical_protocol"])
            lines[0].pop("final_answer")
            lines[0]["raw_answer"] = self.markup["answer"] + ' {"status": "not_answerable", "reason_code": "field_not_available", "columns": [], "rows": [], "unit": null, "evidence": []}'
            attempt, assessment = import_lines(base, study, "import-a", lines, repeats=self.repeats)
            code, descriptive, err = compare_agent(study, assessments["plain"], assessment)
            assert code == 0, (descriptive, err)
            facts.update({"import": attempt, "import_assessment": assessment["assessment_id"], "descriptive": descriptive["comparison"], "import_request": "import-a"})
            facts["import_index"] = index_of_attempt(study, attempt["attempt_id"])
        else:
            facts["import_index"] = None
        return study, facts

    def dev_study(self, tmp_path, *, name="dev"):
        from _run_agent_helpers import live, ok, patch_model, study_of

        (tmp_path / name).mkdir()
        study = study_of(tmp_path / name)
        with pytest.MonkeyPatch.context() as mp:
            patch_model(mp)
            ok(live(study, "plain", "dev-plain", cases=["D03", "D05"], repeats=1))
        return study

    def _public_live(self, study, config, request_id, *more):
        from _run_agent_helpers import live, ok

        return ok(live(study, config, request_id, *more, partition="public_check", cases=["E01", "E02"], repeats=1))

    def public_world(self, tmp_path, *, name="public"):
        from _agent_compare_helpers import assess as assess_agent
        from _agent_compare_helpers import compare as compare_agent
        from _agent_compare_helpers import observation_set_of
        from _run_agent_helpers import patch_model, study_of

        (tmp_path / name).mkdir()
        study = study_of(tmp_path / name)
        with pytest.MonkeyPatch.context() as mp:
            patch_model(mp)
            attempts = {c: self._public_live(study, c, f"public-{c}") for c in self.configs}
        ids = []
        assessments = []
        for config in self.configs:
            assessment = assess_agent(study, observation_set_of(study, attempts[config]))
            assessments.append(assessment)
            ids.append(assessment["assessment_id"])
        code, both, err = compare_agent(study, assessments[0], assessments[1])
        assert code == 0, (both, err)
        return study, attempts, ids, both["comparison"]

    def public_outputs(self, tmp_path, *, name="outputs"):
        from _run_agent_helpers import patch_model, study_of

        (tmp_path / name).mkdir()
        study = study_of(tmp_path / name)
        with pytest.MonkeyPatch.context() as mp:
            patch_model(mp)
            attempt = self._public_live(study, "plain", "public-plain")
        return study, attempt

    def public_assessed(self, tmp_path, *, name="one"):
        from _agent_compare_helpers import assess as assess_agent
        from _agent_compare_helpers import observation_set_of

        study, attempt = self.public_outputs(tmp_path, name=name)
        assess_agent(study, observation_set_of(study, attempt))
        return study, attempt

    def question_study(self, tmp_path, question):
        from _chinook_helpers import chinook_examples, init_chinook

        examples = chinook_examples(tmp_path, edit=lambda d: d.update(question=question))
        return init_chinook(tmp_path, examples=examples)[0]

    def exposed_study(self, tmp_path, *, name="chapter"):
        from _agent_compare_helpers import assess as assess_agent
        from _agent_compare_helpers import observation_set_of
        from _chinook_helpers import chinook_examples
        from _exposure_helpers import correct_e01, edit_chinook_references
        from _revision_helpers import new_revision
        from _run_agent_helpers import patch_model, study_of

        base = tmp_path / name
        base.mkdir()
        study = study_of(base)
        with pytest.MonkeyPatch.context() as mp:
            patch_model(mp)
            plain = self._public_live(study, "plain", "first")
            first = assess_agent(study, observation_set_of(study, plain))
            changed = chinook_examples(base, edit=lambda d: d["configurations"]["verify"].update(added_instruction="\nCheck your joins.\n"), name="changed")
            verify = self._public_live(study, "verify", "changed", "--examples-dir", changed)
        second = assess_agent_with(study, observation_set_of(study, verify), changed)
        code, both, err = compare_agent_with(study, first, second, changed)
        assert code == 0, (both, err)
        revised = edit_chinook_references(base, correct_e01, name="revised")
        code, payload, err = new_revision(study, "--examples-dir", revised)
        assert code == 0, (payload, err)
        return study, revised


def assess_agent_with(study, observation_set, examples):
    from _agent_compare_helpers import SCORER
    from _chinook_helpers import references_id as chinook_references_id
    from _study_helpers import run_json

    code, payload, err = run_json(
        "assess", "--study", study, "--observations", observation_set, "--scorer", SCORER, "--references", chinook_references_id(study), "--examples-dir", examples
    )
    assert code == 0, (payload, err)
    return payload["assessment"]


def compare_agent_with(study, control, candidate, examples):
    from _agent_compare_helpers import compare

    return compare(study, control, candidate, "--examples-dir", examples)


def index_of_attempt(study, attempt_id) -> int:
    """The position of an Attempt on the page: the page orders Attempts by start time, then ID."""
    import json

    manifests = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((Path(study) / "attempts").glob("*/attempt.json"))]
    ordered = sorted(manifests, key=lambda m: (m["started_at"], m["attempt_id"]))
    return [m["attempt_id"] for m in ordered].index(attempt_id)


TRACKS = {"bike": Bike(), "chinook": Chinook()}
