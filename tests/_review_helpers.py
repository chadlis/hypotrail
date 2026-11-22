"""Shared by the tests of the review decision in `status --json`: a Study of each Track holding a Comparison, and the commands that follow it.

A Track here gives a Study with two assessed sides compared (the Control first), a later `assess` of a side, a new revision that changes the
Reference of an assessed Item or of none, and `compare`. Nothing here calls a model: the Chinook sides are Imports of the kit's authored answers.
"""

import json
import shutil
from pathlib import Path

from _study_helpers import run_json

BIKE_SCORER = "regression_mae_v1"
CHINOOK_SCORER = "chinook_contract_v1"


def read(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def status(study) -> dict:
    code, payload, err = run_json("status", "--study", study)
    assert code == 0, (payload, err)
    return payload


def sequence(study) -> int:
    return status(study)["write_sequence"]


def copy_of(study, target) -> Path:
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(study, target)
    return target


def assessment_file(study, assessment_id) -> Path:
    return Path(study) / "assessments" / assessment_id / "assessment.json"


def comparison_file(study, comparison_id) -> Path:
    return Path(study) / "comparisons" / comparison_id / "comparison.json"


def assessment_files(study) -> dict:
    """{assessment_id: the parsed file} of every `assessments/*/assessment.json` of the Study folder."""
    return {read(p)["assessment_id"]: read(p) for p in sorted(Path(study).glob("assessments/*/assessment.json"))}


def comparison_files(study) -> dict:
    """{comparison_id: the parsed file} of every `comparisons/*/comparison.json` of the Study folder."""
    return {read(p)["comparison_id"]: read(p) for p in sorted(Path(study).glob("comparisons/*/comparison.json"))}


def journal(study) -> list:
    return [read(p) for p in sorted(Path(study).glob("write_journal/*.json"))]


def positions(study, kind) -> dict:
    """{id: the position, from 1, of the first write-journal entry that names it}, for the records of one kind."""
    found = {}
    for position, entry in enumerate(journal(study), 1):
        for item in entry.get("written", []):
            if item["kind"] == kind:
                found.setdefault(item["id"], position)
    return found


def exposure_count(study) -> int:
    return len(list(Path(study).glob("exposures/*.json")))


def files(study) -> dict:
    """{relative path: bytes} of every file of the Study folder but `writer.lock`."""
    return {p.relative_to(study).as_posix(): p.read_bytes() for p in sorted(Path(study).rglob("*")) if p.is_file() and p.name != "writer.lock"}


def decide(study, cited, *, request_id, question="Which Configuration do we keep?", option="Keep the Candidate") -> dict:
    flags = ["--study", study, "--question", question, "--option", option, "--author", "human", "--request-id", request_id, "--read-sequence", sequence(study)]
    code, payload, err = run_json("decide", *flags, *[part for cited_id in cited for part in ("--artifact", cited_id)])
    assert code == 0, (payload, err)
    return payload["decision"]


def decision_row(study, decision_id) -> dict:
    return next(row for row in status(study)["decisions"] if row["decision_id"] == decision_id)


def compare(study, control_id, candidate_id) -> dict:
    code, payload, err = run_json("compare", "--study", study, "--control", control_id, "--candidate", candidate_id)
    assert code == 0, (payload, err)
    return payload["comparison"]


class BikeReview:
    name = "bike"
    scorer = BIKE_SCORER
    configs = ("seasonal_7", "ridge_v1")

    def compared(self, base):
        """(Study, Control Assessment, Candidate Assessment, Comparison): `seasonal_7` (Control) against `ridge_v1` (Candidate) on `dev`."""
        from _compare_helpers import assessed

        study, _, sides = assessed(Path(base), *self.configs)
        control, candidate = sides[self.configs[0]], sides[self.configs[1]]
        return study, control, candidate, compare(study, control["assessment_id"], candidate["assessment_id"])

    def assess_again(self, study, assessment) -> dict:
        """One more `assess` of the Observation set of `assessment`, by the same Scorer id, against the current References."""
        from _assess_helpers import assess, references_id

        code, payload, err = assess(study, assessment["observation_set_id"], self.scorer, references_id(study))
        assert code == 0, (payload, err)
        return payload["assessment"]

    def _revise(self, study, base, day, name) -> str:
        from _revision_helpers import new_revision
        from _study_helpers import examples_copy

        def corrected(table):
            row = next(r for r in table if r["dteday"] == day)
            row["cnt"], row["registered"] = str(int(row["cnt"]) + 100), str(int(row["registered"]) + 100)

        code, payload, err = new_revision(study, "--examples-dir", examples_copy(Path(base), rows=corrected, name=name))
        assert code == 0, (payload, err)
        return payload["study"]["revision"]

    def revise_an_assessed_item(self, study, base, name="revised") -> str:
        """A new revision whose References correct one `dev` day: the verdict of that Item changes."""
        return self._revise(study, base, "2012-03-15", name)

    def revise_no_assessed_item(self, study, base, name="elsewhere") -> str:
        """A new revision whose References correct one `public_check` day: no `dev` Item's verdict changes."""
        return self._revise(study, base, "2012-09-15", name)


class ChinookReview:
    name = "chinook"
    scorer = CHINOOK_SCORER

    def compared(self, base, *, failed=(), repeats=1):
        """(Study, Control Assessment, Candidate Assessment, Comparison): two Imports of the kit's authored answers, `failed` Episodes on the Control's."""
        from _agent_compare_helpers import answer_lines, imported
        from _chinook_helpers import init_chinook

        base = Path(base)
        base.mkdir(parents=True, exist_ok=True)
        study = init_chinook(base)[0]
        _, control = imported(base, study, "plain", answer_lines(failed=set(failed), repeats=repeats), repeats=repeats)
        _, candidate = imported(base, study, "verify", answer_lines(repeats=repeats), repeats=repeats)
        return study, control, candidate, compare(study, control["assessment_id"], candidate["assessment_id"])

    def assess_again(self, study, assessment) -> dict:
        from _chinook_helpers import references_id

        code, payload, err = run_json("assess", "--study", study, "--observations", assessment["observation_set_id"], "--scorer", self.scorer, "--references", references_id(study))
        assert code == 0, (payload, err)
        return payload["assessment"]

    def _revise(self, study, base, edit, name) -> str:
        from _revision_helpers import corrected_chinook_references, new_revision

        code, payload, err = new_revision(study, "--examples-dir", corrected_chinook_references(Path(base), edit, name=name))
        assert code == 0, (payload, err)
        return payload["study"]["revision"]

    def revise_an_assessed_item(self, study, base, name="revised") -> str:
        """A new revision whose References correct D03, a Case the answers cover: the verdict of its Episodes changes on two Criteria."""

        def correct_d03(records):
            records["D03"].update(rows=[[1300]], reference_version="chinook-references/2")

        return self._revise(study, base, correct_d03, name)

    def revise_no_assessed_item(self, study, base, name="elsewhere") -> str:
        """A new revision whose References correct D04, a Case the answers do not cover: no verdict changes."""

        def correct_d04(records):
            records["D04"].update(rows=[[7]])

        return self._revise(study, base, correct_d04, name)


TRACKS = {"bike": BikeReview(), "chinook": ChinookReview()}
