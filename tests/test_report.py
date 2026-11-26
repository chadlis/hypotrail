"""Ticket #85: `report` renders one self-contained HTML page per Study, from the Study's records and, for a Bike Study, the data profile
the command hands over (#261).

One test per acceptance criterion or Tightened line; a criterion that states several conditions is one test holding all of them.
"""

import html
import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path
from urllib.parse import unquote

import pytest
from _assess_helpers import assess, construct, fresh_study, observation_set_id, references_id
from _compare_helpers import compare, forged
from _report_tracks import TRACKS
from _report_helpers import (
    Doc,
    constructed_attempt,
    dates_of,
    dev_world,
    doc_of,
    edit_manifest,
    freeze_files,
    journal_of,
    observations_of,
    per_item_rows,
    report,
    sha_of,
    targets_of,
    tree,
)
from _study_helpers import ROOT, examples_copy, init_study, run_cli, run_json, run_ml

from hypotrail.core import canonical, exposure, lock
# Imported before a test spies on `os.replace`: on their first import, pytest's rewriting hook writes the bytecode of SciPy's
# `*_test.py` modules with it.
from hypotrail.ml import profile as _profile  # noqa: F401
from hypotrail.report import markup, render, render_profile

HANDBOOK = ROOT / "docs" / "handbook"
# The attributes an `svg` or a `rect` of the Data profile section may carry: its geometry, its class and the day a day rect stands for.
SVG_ATTRIBUTES = {"viewbox", "preserveaspectratio", "aria-hidden", "x", "y", "width", "height", "data-date"}
MARKUP = TRACKS["bike"].markup
_WORLDS = {}


class World(tuple):
    """`(study, facts, out, doc, payload)` of one Track's world, and the Track that built it."""

    track = None


def _world(name, tmp_path_factory):
    """A Study (folder name with markup characters) with two native Attempts, an Import whose declared fields hold markup, their Assessments and Comparisons; its page, in another folder."""
    if name not in _WORLDS:
        track = TRACKS[name]
        base = tmp_path_factory.mktemp(f"world-{name}")
        study, facts = track.world(base, name='st"<udy>')
        out = base / "elsewhere" / "deep" / "report.html"
        out.parent.mkdir(parents=True)
        code, payload, err = report(study, out)
        assert code == 0, (payload, err)
        _WORLDS[name] = world = World((study, facts, out, doc_of(out), payload))
        world.track = track
    return _WORLDS[name]


@pytest.fixture(scope="module", params=list(TRACKS))
def world(request, tmp_path_factory):
    return _world(request.param, tmp_path_factory)


@pytest.fixture(scope="module")
def bike_world(tmp_path_factory):
    return _world("bike", tmp_path_factory)


@pytest.fixture(params=list(TRACKS))
def track(request):
    return TRACKS[request.param]


# --- the command ------------------------------------------------------------------------------------------------------


def test_the_command_publishes_the_page_by_a_rename_prints_one_json_object_and_refuses_with_the_four_fields_and_the_exit_codes(track, tmp_path, monkeypatch):
    study = track.dev_study(tmp_path)
    out = tmp_path / "site" / "report.html"
    out.parent.mkdir()
    seen = []
    real = os.replace

    def spy(source, target, *args, **kwargs):
        seen.append((Path(source), Path(target), Path(source).read_bytes(), Path(target).exists()))
        return real(source, target, *args, **kwargs)

    monkeypatch.setattr(os, "replace", spy)
    code, stdout, stderr = run_cli("report", "--study", study, "--out", out, "--json")
    monkeypatch.setattr(os, "replace", real)
    payload = json.loads(stdout)  # the whole of stdout is one JSON object
    assert (code, payload["ok"], stderr) == (0, True, "")
    [(temporary, target, written, existed)] = seen
    assert target == out and temporary.parent == out.parent and temporary != out and not existed  # a temporary file, then a rename onto --out
    assert written == out.read_bytes() and [p.name for p in out.parent.iterdir()] == ["report.html"]
    # a refusal: stdout is one object whose error has the four fields, the human line is on stderr, and the exit codes are those of the spec
    code, stdout, stderr = run_cli("report", "--study", tmp_path / "nothing", "--out", out.parent / "no.html", "--json")
    error = json.loads(stdout)["error"]
    assert code == 2 and set(error) == {"code", "message", "stage", "details"} and error["code"] in stderr
    assert not (out.parent / "no.html").exists()
    broken, _ = init_study(tmp_path / "broken")
    (broken / "study.json").write_bytes(b"\xff\xfe not a StudySpec")  # unreadable: also exit 2
    code, payload, _ = report(broken, out.parent / "no.html")
    assert code == 2 and set(payload["error"]) == {"code", "message", "stage", "details"} and not (out.parent / "no.html").exists()
    tampered = tmp_path / "tampered"
    tampered.mkdir()
    study2 = track.dev_study(tampered)
    dataset = study2 / track.dataset
    dataset.write_bytes(dataset.read_bytes() + b"\n")
    code, payload, stderr = report(study2, out.parent / "no.html")
    assert (code, payload["error"]["code"]) == (3, "ARTIFACT_INTEGRITY") and "ARTIFACT_INTEGRITY" in stderr
    assert not (out.parent / "no.html").exists()
    exposed, _ = track.public_outputs(tmp_path, name="locked")
    with lock.writer_lock(exposed):
        code, payload, _ = report(exposed, out.parent / "no.html")
    assert (code, payload["error"]["code"]) == (6, "STUDY_LOCKED") and not (out.parent / "no.html").exists()
    assert journal_of(exposed) == []


def test_the_folder_of_out_is_fsynced_after_the_page_is_renamed_onto_out_on_the_path_without_the_lock_and_on_the_path_that_records_an_exposure(track, tmp_path, monkeypatch):
    from hypotrail.core import artifacts

    folders = []

    def spy(path):
        folders.append((Path(path), [p.name for p in Path(path).iterdir()]))

    monkeypatch.setattr(artifacts, "_fsync_dir", spy)
    studies = {"dev_only": (track.dev_study(tmp_path), False), "exposure": (track.public_outputs(tmp_path)[0], True)}
    for name, (study, records_an_exposure) in studies.items():
        out = tmp_path / f"site-{name}" / "report.html"
        out.parent.mkdir()
        folders.clear()
        code, payload, err = report(study, out)
        assert (code, payload["report"]["exposure"]["recorded"]) == (0, records_an_exposure), (name, payload, err)
        assert [seen for seen in folders if seen[0] == out.parent] == [(out.parent, ["report.html"])], name


def test_J_an_existing_output_is_replaced_and_an_output_inside_the_study_is_refused_before_anything_is_written(track, tmp_path):
    study = track.dev_study(tmp_path)
    out = tmp_path / "page.html"
    out.write_text("old", encoding="utf-8")
    code, payload, _ = report(study, out)
    assert code == 0 and out.read_text(encoding="utf-8").startswith("<!doctype html>")
    before = tree(study)
    for inside in (study / "report.html", study / "attempts" / "report.html", study / "new-folder" / "report.html", study):
        code, payload, _ = report(study, inside)
        assert (code, payload["error"]["code"]) == (2, "REPORT_OUTPUT_INVALID"), inside
        assert tree(study) == before and not (study / "new-folder").exists()
    code, payload, _ = report(study, tmp_path / "no-such-folder" / "page.html")
    assert (code, payload["error"]["code"]) == (2, "REPORT_OUTPUT_INVALID") and not (tmp_path / "no-such-folder").exists()


# --- the page: nothing loaded, nothing computed -----------------------------------------------------------------------


def test_A_nothing_is_loaded_from_outside_and_an_external_address_is_shown_as_text(world):
    """T22 (SPEC §10)."""
    _, facts, out, doc, _ = world
    for tag, attrs in doc.elements:
        assert tag not in ("link", "script", "iframe", "img", "object", "embed", "base"), tag
        for name, value in attrs.items():
            assert not re.match(r"^\s*(https?:|//)", value or "", re.I), (tag, name, value)
            assert not name.startswith("on"), (tag, name)
    assert "url(" not in doc.style and "@import" not in doc.style
    assert not re.search(r"https?:|(?<![\w:])//", doc.style)
    # the declared fields hold addresses: they are shown, escaped, as the text the Study records
    markup = world.track.markup
    for value in markup.values():
        assert value in doc.text
    producer = doc.body(f"producer-{facts['import_index']}")
    for claim in world.track.producer_claims:
        assert {row[0]: row[1] for row in producer}[claim] == markup[claim]


def test_B_every_relative_link_resolves_from_the_folder_of_the_output_to_the_artifact_it_names_with_its_sha256_beside_it(world):
    study, _, out, doc, _ = world
    links = 0
    for rows in doc.tables.values():
        for row in rows:
            for found in (c for c in row if c["links"]):
                for href in found["links"]:
                    assert not re.match(r"^[a-z][a-z0-9+.-]*:|^/", href, re.I), href
                    target = (out.parent / unquote(href)).resolve()
                    assert target.is_file() and target.is_relative_to(study.resolve()), href
                    assert any(sha_of(target) in c["text"] for c in row), (href, row)  # beside the link: in its row, or in its matrix cell
                    links += 1
    assert links > 20
    assert {href for _, attrs in doc.elements for name, href in attrs.items() if name == "href"} and all(
        tag == "a" for tag, attrs in doc.elements if "href" in attrs
    )


def test_C_the_page_holds_no_script_so_nothing_is_computed_when_it_is_opened(world):
    """T22 (SPEC §10)."""
    _, _, out, doc, _ = world
    text = out.read_text(encoding="utf-8").lower()
    assert not [tag for tag, _ in doc.elements if tag in ("script", "noscript")]
    assert "<script" not in text and "javascript:" not in text


def test_the_report_succeeds_with_the_network_guard_on_and_fit_prediction_generation_and_tools_replaced_by_functions_that_fail(world, tmp_path, network_guard, monkeypatch):
    """T10, T22 (SPEC §10)."""
    from _ml_helpers import fit_probe

    from hypotrail.agentic import inspect_log, runner, sql_tool
    from hypotrail.agentic import live as agentic_live
    from hypotrail.ml import baselines, ridge, run

    study, _, _, _, _ = world
    exposed, _ = world.track.public_outputs(tmp_path, name="pub")

    def forbidden(*args, **kwargs):
        raise AssertionError("report called something that fits, predicts, generates or uses a tool")

    for module, names in ((run, ["run_ml"]), (ridge, ["write_outputs"]), (baselines, ["write_seasonal_baseline"]), (runner, [n for n in dir(runner) if n.startswith(("run", "generate"))]),
                          (agentic_live, ["prepared_model", "live_model", "run_live"]), (inspect_log, ["read"]),
                          (sql_tool, ["run_query", "describe_schema", "query_readonly"])):
        for name in names:
            if callable(getattr(module, name, None)):
                monkeypatch.setattr(module, name, forbidden)
    with fit_probe(strict=True) as probe:
        for target in (study, exposed):
            code, payload, err = report(target, tmp_path / "offline.html")
            assert code == 0, (payload, err)
    assert probe.calls == [] and network_guard.attempts == []


def test_G_report_renders_a_study_in_a_fresh_interpreter_where_inspect_anthropic_sklearn_and_numpy_cannot_be_imported(world, tmp_path):
    """Bike (#85 G): `inspect_ai`, `anthropic`, `sklearn` and `numpy`; Chinook (#86 A): `inspect_ai` and `anthropic`, over an Import and Attempts projected from an Inspect log."""
    study, _, _, _, _ = world
    exposed, _ = world.track.public_outputs(tmp_path, name="pub")
    blocked = sorted(world.track.blocked)
    script = textwrap.dedent(
        """
        import importlib.abc, json, sys

        BLOCKED = set(json.loads(sys.argv[1]))

        class Blocker(importlib.abc.MetaPathFinder):
            def find_spec(self, name, path, target=None):
                if name.split(".")[0] in BLOCKED:
                    raise ImportError(f"{name} is blocked in this environment")

        sys.meta_path.insert(0, Blocker())
        for name in sorted(BLOCKED):
            try:
                __import__(name)
            except ImportError:
                pass
            else:
                raise SystemExit(f"{name} is importable: the blocker does not work")
        from hypotrail import cli

        pairs = sys.argv[2:]
        codes = [cli.main(["report", "--study", s, "--out", o, "--json"]) for s, o in zip(pairs[0::2], pairs[1::2])]
        sys.stderr.write(json.dumps({"codes": codes, "loaded": sorted(m for m in sys.modules if m.split(".")[0] in BLOCKED)}))
        """
    )
    done = subprocess.run(
        [sys.executable, "-c", script, json.dumps(blocked), str(study), str(tmp_path / "a.html"), str(exposed), str(tmp_path / "b.html")], capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stderr.splitlines()[-1]) == {"codes": [0, 0], "loaded": []}
    assert (tmp_path / "a.html").is_file() and (tmp_path / "b.html").is_file()


# --- the page: charter, English, sections -----------------------------------------------------------------------------


def test_D_the_pages_own_text_is_english_external_strings_are_shown_as_given_and_light_mode_is_fixed(track, tmp_path):
    french = "Au début du jour t, estimer le nombre de locations <b>du jour</b> : \u00ab cnt[t] \u00bb."
    study = track.question_study(tmp_path, french)
    out = tmp_path / "page.html"
    code, payload, err = report(study, out)
    assert code == 0, (payload, err)
    raw, doc = out.read_text(encoding="utf-8"), doc_of(out)
    [(_, html_attrs)] = [e for e in doc.elements if e[0] == "html"]
    assert html_attrs == {"lang": "en", "data-mode": "light"}
    assert "prefers-color-scheme" not in raw and "localStorage" not in raw and "?mode" not in raw
    assert french in doc.text and "<b>du jour</b>" not in raw  # given, escaped
    assert [s["headings"] for s in doc.sections] == [[heading] for _, heading in render.sections_of(track.domain)]


def test_I_the_page_uses_the_light_tokens_of_the_handbook_template_and_no_mode_switch(world):
    _, _, out, doc, _ = world
    template = (HANDBOOK / "template.html").read_text(encoding="utf-8")
    light = re.search(r':root\[data-mode="light"\]\{(?P<tokens>.*?)\}', template, re.S)["tokens"]
    declared = dict(re.findall(r"(--[a-z0-9]+):([^;]+);", light + ";"))
    root = dict(re.findall(r"(--(?:serif|sans|mono)):([^;]+);", re.search(r":root\{(.*?)\}", template, re.S)[1]))
    assert {"--bg", "--ink", "--ink2", "--gold", "--paper"} <= set(declared) and set(root) == {"--serif", "--sans", "--mono"}
    for name, value in {**{k: v for k, v in declared.items() if k not in ("--stars",)}, **root}.items():
        assert f"{name}:{value}" in doc.style.replace("\n", ""), name
    raw = out.read_text(encoding="utf-8")
    assert not [e for e in doc.elements if e[0] in ("script", "button")] and "doc-mode" not in raw and 'class="mode"' not in raw


def test_the_page_sets_out_its_sections_in_this_order_each_with_a_stable_id_and_data_profile_on_a_bike_page_only(world):
    _, _, _, doc, payload = world
    profile = ["data-profile"] if world.track.domain == "regression" else []
    assert [s["id"] for s in doc.sections] == [
        "question-mode", "data-licences", "protocol-partitions", *profile, "configurations", "coverage-statuses",
        "metrics-differences", "individual-errors", "limits", "artifact-origin", "exposure",
    ]
    assert [(s["id"], s["headings"]) for s in doc.sections] == [(i, [h]) for i, h in render.sections_of(world.track.domain)]
    assert payload["report"]["sections"] == [s["id"] for s in doc.sections]


def test_every_external_string_is_escaped_in_text_and_in_attributes(world):
    study, facts, out, doc, _ = world
    raw = out.read_text(encoding="utf-8")
    assert "<xx-marker" not in raw and "<script" not in raw and "<img" not in raw
    assert not [tag for tag, _ in doc.elements if tag in ("xx-marker", "img", "script")]
    for tag, attrs in doc.elements:
        assert not [name for name in attrs if name.startswith("on") or name == "src"], (tag, attrs)
        drawing = SVG_ATTRIBUTES if tag in ("svg", "rect") else set()
        assert set(attrs) <= {"lang", "data-mode", "charset", "name", "content", "id", "class", "style", "href", "data-attempt-id", "data-path", *drawing}, (tag, attrs)
    for claim, value in world.track.markup.items():
        assert value in doc.text, claim  # shown as the same characters
    hrefs = [attrs["href"] for tag, attrs in doc.elements if "href" in attrs]
    assert hrefs and all('"' not in h and "<" not in h and ">" not in h for h in hrefs)  # the quote and the angle bracket of the folder name never reach an attribute as they are
    assert all((out.parent / unquote(h)).resolve().is_file() for h in hrefs)


def test_E_the_pages_own_text_makes_no_claim_of_production_readiness_safety_or_independence(world):
    study, _, _, doc, _ = world
    handbook = (HANDBOOK / "chapters" / "14-report.html").read_text(encoding="utf-8")
    listed = re.findall(r'<tr data-denial="[^"]*"><td>(.*?)</td>', handbook, re.S)
    assert listed == [render.DENIAL]
    own = own_text(doc, study)
    banned = re.compile(r"production[- ]ready|\bsafe(ly)?\b|\bindependent(ly)?\b", re.I)
    assert banned.findall(own.replace(render.DENIAL, "")) == []
    assert render.DENIAL in own  # the listed denial is the one sentence that names the words
    # the scan has teeth: a page that says it fails
    assert banned.search(own.replace(render.DENIAL, "") + " This model can be deployed safely.")


def own_text(doc, study) -> str:
    """The page's text with every string the Study's records hold removed: what the code itself wrote."""
    strings = set()

    def walk(node):
        if isinstance(node, str):
            strings.add(node)
        elif isinstance(node, dict):
            [walk(v) for v in node.values()]
        elif isinstance(node, list):
            [walk(v) for v in node]

    for path in Path(study).rglob("*.json"):
        walk(json.loads(path.read_text(encoding="utf-8")))
    text = doc.text.replace(render.DENIAL, "\x00")  # the sentence the handbook lists stays whole, whatever words the records hold
    for string in sorted((s for s in strings if len(s) >= 4), key=len, reverse=True):
        text = text.replace(" ".join(string.split()), " ")
    return text.replace("\x00", render.DENIAL)


# --- what the page shows ----------------------------------------------------------------------------------------------


def test_each_attempt_shows_its_mode_status_request_id_and_outcome_unknown_each_observation_set_its_counts_and_each_criterion_its_reasons_a_null_is_unknown_never_zero_and_no_nan(tmp_path):
    study, attempts = fresh_study(tmp_path, "seasonal_7", "ridge_v1")
    refs = references_id(study)
    seasonal = attempts["seasonal_7"]

    def damage(rows):
        for i, row in enumerate(rows):
            if i < 3:
                row.update(status="failed", reason="timeout", y_pred_raw="", y_pred="")
            elif i < 5:
                row.update(status="missing", reason="absent", y_pred_raw="", y_pred="")
            elif i == 5:
                row.update(y_pred="nan", y_pred_raw="nan")
        return rows

    damaged = construct(study, seasonal, damage)
    damaged_attempt = next(a for a in (study / "attempts").iterdir() if a.name not in {x["attempt_id"] for x in attempts.values()}).name
    edit_manifest(study, damaged_attempt, lambda m: m.update(item_counts={"produced": 177, "failed": 3, "missing": 2}, outcome_unknown=True))
    everything_failed = construct(study, seasonal, lambda rows: [{**r, "status": "failed", "reason": "timeout", "y_pred_raw": "", "y_pred": ""} for r in rows])
    failed_attempt = next(a for a in (study / "attempts").iterdir() if a.name not in {x["attempt_id"] for x in attempts.values()} | {damaged_attempt}).name
    edit_manifest(study, failed_attempt, lambda m: m.update(item_counts={"produced": 0, "failed": 182, "missing": 0}))
    ids = {}
    for label, observation_set in (("damaged", damaged), ("failed", everything_failed)):
        code, payload, err = assess(study, observation_set, "regression_mae_v1", refs)
        assert code == 0, (payload, err)
        ids[label] = payload["assessment"]["assessment_id"]
    code, plain, err = assess(study, observation_set_id(study, seasonal), "regression_mae_v1", refs)
    assert code == 0, (plain, err)

    def not_a_number(rows):  # a per-Item file that holds numbers no finite value stands for, in rows it calls scored
        rows[0]["value"], rows[1]["value"], rows[2]["value"] = "nan", "inf", "-inf"
        return rows

    forged(study, plain["assessment"], per_item=not_a_number)
    running = constructed_attempt(study, "running", request_id="still-going")
    out = tmp_path / "page.html"
    code, payload, err = report(study, out)
    assert code == 0, (payload, err)
    doc, text = doc_of(out), doc_of(out).text
    attempts_table = {row[0]: row for row in doc.body("attempts")}
    assert attempts_table[damaged_attempt][1:] == ["native_ml", "completed", f"constructed-{damaged_attempt}", "yes", "177", "3", "2", "none"]
    assert attempts_table[attempts["seasonal_7"]["attempt_id"]][1:5] == ["native_ml", "completed", "ml-dev-seasonal_7", "no"]
    assert attempts_table[running][1:] == ["native_ml", "running", "still-going", "no", "unknown", "unknown", "unknown", "none"]
    assessed = {row[0]: row for row in doc.body("assessments")}
    # expected attempted produced scored unscored errored correct incorrect: the nulls of a numeric loss are unknown
    assert assessed[ids["damaged"]][3:] == ["182", "180", "177", "176", "6", "0", "unknown", "unknown"]
    assert assessed[ids["failed"]][3:] == ["182", "182", "0", "0", "182", "0", "unknown", "unknown"]
    tally = {}
    for row in doc.body("reasons"):
        tally[(row[0], row[2], row[3])] = row[4]
    assert {k: v for k, v in tally.items() if k[0] == ids["damaged"]} == {
        (ids["damaged"], "scored", "none"): "176",
        (ids["damaged"], "unscored", "item_failed"): "3",
        (ids["damaged"], "unscored", "item_missing"): "2",
        (ids["damaged"], "unscored", "prediction_invalid"): "1",
    }
    metrics = [{r[0]: r[1] for r in doc.body(f"assessment-{i}")} for i in range(len(doc.tables)) if f"assessment-{i}" in doc.tables]
    nothing_scored = next(m for m in metrics if m["Status"] == "unscored")
    assert nothing_scored["Value"] == "unknown" and nothing_scored["Reason"] == "no_scored_item" and nothing_scored["Denominator"] == "0"
    assert not re.search(r"\b(nan|inf|infinity)\b", text, re.I)


def test_F_a_running_attempt_is_shown_as_running_even_while_its_writer_lock_is_held_and_an_interrupted_one_as_interrupted(track, tmp_path):
    study = track.dev_study(tmp_path)
    running = constructed_attempt(study, "running", request_id="going", mode=track.native_mode)
    interrupted = constructed_attempt(study, "interrupted", request_id="stopped", outcome_unknown=True, mode=track.native_mode)
    holder = subprocess.Popen(
        [sys.executable, "-c", "import sys, time\nfrom hypotrail.core import lock\nwith lock.writer_lock(sys.argv[1]):\n    print('held', flush=True)\n    time.sleep(60)", str(study)],
        stdout=subprocess.PIPE, text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "held" and lock.is_held(study)
        out = tmp_path / "page.html"
        code, payload, err = report(study, out)
        assert code == 0, (payload, err)
        rows = {row[0]: row for row in doc_of(out).body("attempts")}
        assert rows[running][2] == "running" and rows[running][3] == "going"
        assert rows[interrupted][2] == "interrupted" and rows[interrupted][4] == "yes"
        assert "completed" not in (rows[running][2], rows[interrupted][2])
    finally:
        holder.kill()
        holder.wait()


def test_the_ten_largest_errors_show_their_date_true_predicted_difference_attempt_and_assessment(bike_world):
    study, facts, out, doc, _ = bike_world
    dates, truth = dates_of(study), targets_of(study)
    checked = 0
    for index in range(3):
        rows = doc.body(f"largest-errors-{index}")
        assessment_id = rows[0][8]
        attempt_id = rows[0][7]
        per_item = per_item_rows(study, assessment_id)
        predicted = observations_of(study, attempt_id)
        ranked = sorted(((float(r["value"]), r["row_id"]) for r in per_item if r["state"] == "scored"), key=lambda e: (-e[0], e[1]))[:10]
        assert len(rows) == 10 and [r[2] for r in rows] == [row_id for _, row_id in ranked]
        for row, (error, row_id) in zip(rows, ranked):
            expected_pred = float(predicted[row_id]["y_pred"])
            assert row[1] == dates[row_id] and row[7] == attempt_id and row[8] == assessment_id
            assert float(row[3]) == float(f"{truth[row_id]:.6g}") and float(row[4]) == float(f"{expected_pred:.6g}")
            assert float(row[5]) == float(f"{expected_pred - truth[row_id]:.6g}") and float(row[6]) == float(f"{error:.6g}")
            link = next(c["links"] for c in doc.tables[f"largest-errors-{index}"][rows.index(row) + 1] if c["links"])[0]
            target = (out.parent / unquote(link)).resolve()
            assert target == (study / "assessments" / assessment_id / "per_item.csv").resolve() and row_id in target.read_text()
            checked += 1
    assert checked == 30


def test_K_the_monthly_table_gives_the_items_and_the_mean_absolute_error_of_each_month_from_the_per_item_errors(bike_world):
    study, facts, _, doc, _ = bike_world
    dates = dates_of(study)
    seen = 0
    for index in range(3):
        rows = doc.body(f"monthly-{index}")
        assessment_id = doc.body("assessments")[index][0]
        months = {}
        for row in per_item_rows(study, assessment_id):
            months.setdefault(dates[row["row_id"]][:7], []).append(float(row["value"]))
        assert [r[0] for r in rows] == sorted(months) and len(rows) == 6
        for row in rows:
            errors = months[row[0]]
            assert int(row[1]) == len(errors) and int(row[2]) == len(errors)
            assert float(row[3]) == float(f"{sum(errors) / len(errors):.6g}")
            seen += 1
    assert seen == 18


def test_each_comparison_shows_its_sides_comparability_warnings_coverage_deltas_and_the_sign_sentence_and_an_import_comparison_is_descriptive_with_its_warning(bike_world):
    study, facts, out, doc, _ = bike_world
    tables = [{r[0]: r[1] for r in doc.body(f"comparison-{i}")} for i in range(2)]
    native = next(t for t in tables if t["Candidate Assessment"] == facts["assessments"]["ridge_v1"])
    descriptive = next(t for t in tables if t["Candidate Assessment"] == facts["import_assessment"])
    record = facts["comparison"]
    assert native["Control Assessment"] == facts["assessments"]["seasonal_7"] and native["Comparability"] == "compatible, with warning COMPARISON_SINGLE_FEATURE_BEATS"
    assert native["Coverage"] == f"expected {record['coverage']['expected']}, Control scored {record['coverage']['control_scored']}, Candidate scored {record['coverage']['candidate_scored']}, paired {record['coverage']['paired']}"
    assert native["Delta"] == f"mae {float(f'{record['delta']['value']:.6g}'):g} rentals per day" or native["Delta"].startswith("mae ")
    assert float(native["Delta"].split()[1]) == float(f"{record['delta']['value']:.6g}")
    assert "A positive delta means the Candidate is worse" in doc.text
    # the counts are those the record holds, whatever they are: the page recomputes none of them
    path = study / "comparisons" / record["comparison_id"] / "comparison.json"
    original = path.read_bytes()
    edited = {**record, "coverage": {"expected": 182, "control_scored": 180, "candidate_scored": 181, "paired": 179}}
    path.write_bytes(canonical.dumps(edited))
    try:
        edited_out = out.parent / "edited.html"
        assert report(study, edited_out)[0] == 0
        shown = [r[1] for i in range(2) for r in doc_of(edited_out).body(f"comparison-{i}") if r[0] == "Coverage"]
        assert sorted(shown) == ["expected 182, Control scored 180, Candidate scored 181, paired 179", "expected 182, Control scored 182, Candidate scored 182, paired 182"]
    finally:
        path.write_bytes(original)
        edited_out.unlink()
    assert descriptive["Comparability"] == "descriptive_only (descriptive)"
    warning = facts["descriptive"]["warnings"][0]
    assert f"Warning {warning['code']}." in doc.text and warning["message"] in doc.text
    assert warning["code"] == "COMPARISON_DESCRIPTIVE_IMPORT"


def test_the_artifacts_are_listed_with_path_sha256_size_and_role_the_producer_fields_with_their_origin_and_the_limits_with_every_recorded_limitation(world):
    study, facts, out, doc, _ = world
    listed = [row for rows in (doc.body(t) for t in doc.tables if t.startswith(("attempt-artifacts-", "study-artifacts", "record-artifacts"))) for row in rows]
    by_path = {row[0]: row for row in listed}
    for attempt_id in [next(iter(facts["attempts"].values()))["attempt_id"], facts["import"]["attempt_id"]]:
        manifest = json.loads((study / "attempts" / attempt_id / "attempt.json").read_text())
        for ref in manifest["output_refs"]:
            assert by_path[ref["path"]][1:] == [ref["sha256"], str(ref["size_bytes"]), ref["role"]], ref["path"]
    producer = {row[0]: row[1:] for row in doc.body(f"producer-{facts['import_index']}")}
    for claim in world.track.producer_claims:
        assert producer[claim] == [world.track.markup[claim], "declared"]
    assert producer["saw_public_check"] == ["unknown", "unknown"]
    recorded = json.loads((study / "study.json").read_text())["limitations"]
    recorded += [t for a in facts["assessments"].values() for t in json.loads((study / "assessments" / a / "assessment.json").read_text())["limitations"]]
    recorded += facts["comparison"]["limitations"] + facts["descriptive"]["limitations"]
    shown = {row[1] for row in doc.body("limitations")}
    assert set(recorded) <= shown and len(recorded) > 6


# --- Exposure ---------------------------------------------------------------------------------------------------------


def test_a_report_that_shows_public_check_items_records_the_freeze_record_then_one_entry_naming_what_it_shows_and_a_dev_only_report_records_nothing(track, tmp_path, monkeypatch):
    # a Study with Assessments and a Comparison of public_check Items: one more entry names all of them
    exposed, attempts, ids, both = track.public_world(tmp_path)
    before, freezes_before = journal_of(exposed), [f.read_bytes() for f in freeze_files(exposed)]
    code, payload, err = report(exposed, tmp_path / "p.html")
    assert code == 0, (payload, err)
    after = journal_of(exposed)
    assert len(after) == len(before) + 1 and after[:-1] == before and [f.read_bytes() for f in freeze_files(exposed)] == freezes_before
    entry = after[-1]
    assert entry["attempt_ids"] == sorted(a["attempt_id"] for a in attempts.values())
    assert entry["assessment_ids"] == sorted(ids) and entry["comparison_ids"] == [both["comparison_id"]]
    assert json.loads(freeze_files(exposed)[0].read_text())["freeze_id"] == entry["freeze_id"]
    # the report is the Study's first use of public_check: the freeze record is written first, then the entry
    first, _ = track.public_outputs(tmp_path, name="q")
    assert journal_of(first) == [] and freeze_files(first) == []
    roles = []
    real = exposure.artifacts.publish_record
    monkeypatch.setattr(exposure.artifacts, "publish_record", lambda *a, **k: (roles.append(k["role"]) if k["role"] != "write_journal" else None, real(*a, **k))[1])
    code, payload, err = report(first, tmp_path / "q.html")
    assert code == 0, (payload, err)
    assert roles == ["freeze", "exposure"]
    [freeze], [only] = freeze_files(first), journal_of(first)
    assert only["freeze_id"] == json.loads(freeze.read_text())["freeze_id"] and payload["report"]["exposure"]["recorded"] is True
    # a Study with dev Items only records nothing and takes no lock
    dev, _ = track.world(tmp_path, name="d", imported=False)
    snapshot_before = tree(dev)
    with lock.writer_lock(dev):
        code, payload, err = report(dev, tmp_path / "d.html")
    assert code == 0 and payload["report"]["exposure"] == {"recorded": False, "entry_id": None, "journal_entries": 0}
    assert tree(dev) == snapshot_before and journal_of(dev) == [] and freeze_files(dev) == []


def test_L_a_report_that_shows_only_public_check_outputs_with_no_assessment_is_an_exposure_and_a_dev_only_study_gains_no_entry(track, tmp_path):
    only_outputs, attempt = track.public_outputs(tmp_path, name="p")
    assert journal_of(only_outputs) == []
    code, payload, err = report(only_outputs, tmp_path / "p.html")
    assert code == 0, (payload, err)
    [entry] = journal_of(only_outputs)
    assert entry["attempt_ids"] == [attempt["attempt_id"]] and entry["assessment_ids"] == [] and entry["comparison_ids"] == []
    dev = track.dev_study(tmp_path, name="d")
    code, payload, err = report(dev, tmp_path / "d.html")
    assert code == 0 and journal_of(dev) == []


def test_the_exposure_section_states_that_earlier_exposure_is_unknown_and_names_every_check_informed_record(track, tmp_path):
    study, revised = track.exposed_study(tmp_path)
    out = tmp_path / "page.html"
    code, payload, err = report(study, out, "--examples-dir", revised)
    assert code == 0, (payload, err)
    doc = doc_of(out)
    assert exposure.EARLIER_EXPOSURE_STATEMENT in doc.text
    status = run_json("status", "--study", study)[1]
    expected = {(m["kind"], m["id"]) for m in status["check_informed"]}
    assert {kind for kind, _ in expected} == {"revision", "attempt", "assessment", "comparison"}
    assert {tuple(row) for row in doc.body("check-informed")} == expected
    journal = {row[0] for row in doc.body("journal")}
    assert journal == {e["entry_id"] for e in journal_of(study)}


def test_M_the_exposure_count_includes_the_entry_this_report_recorded(track, tmp_path):
    study, _ = track.public_assessed(tmp_path)
    assert len(journal_of(study)) == 1
    out = tmp_path / "page.html"
    code, payload, err = report(study, out)
    assert code == 0, (payload, err)
    assert len(journal_of(study)) == 2
    assert "Exposures recorded in this Study: 2." in doc_of(out).text and len(doc_of(out).body("journal")) == 2


def exposed_study(tmp_path, *, name="chapter"):
    return TRACKS["bike"].exposed_study(tmp_path, name=name)


def test_an_assessment_under_a_corrected_references_set_is_shown_with_its_revision_the_earlier_assessment_and_the_recorded_cause_and_the_earlier_one_stays(tmp_path):
    from _revision_helpers import new_revision

    study, attempts = fresh_study(tmp_path, "seasonal_7")
    observation_set = observation_set_id(study, attempts["seasonal_7"])
    code, first, err = assess(study, observation_set, "regression_mae_v1", references_id(study))
    assert code == 0, (first, err)

    def corrected_day(table):
        row = next(r for r in table if r["dteday"] == "2012-03-15")
        row["cnt"], row["registered"] = str(int(row["cnt"]) + 1000), str(int(row["registered"]) + 1000)

    code, payload, err = new_revision(study, "--examples-dir", examples_copy(tmp_path, rows=corrected_day, name="revised"))
    assert code == 0, (payload, err)
    code, second, err = assess(study, observation_set, "regression_mae_v1", references_id(study))
    assert code == 0, (second, err)
    earlier, later = first["assessment"], second["assessment"]
    assert later["rescoring"]["earlier_assessment_id"] == earlier["assessment_id"] and later["study_revision"]["number"] == 2
    before = tree(study)
    out = tmp_path / "page.html"
    code, payload, err = report(study, out)
    assert code == 0, (payload, err)
    assert tree(study) == before  # the records are read, never changed
    doc = doc_of(out)
    shown = {t: {r[0]: r[1] for r in doc.body(t)} for t in doc.tables if t.startswith("assessment-")}
    by_revision = {v["Revision"]: v for v in shown.values()}
    assert set(by_revision) == {"1", "2"}
    assert by_revision["1"]["Value"] == f"{earlier['metrics'][0]['value']:.6g} rentals per day"  # the earlier Assessment stays shown, unchanged
    assert by_revision["2"]["Value"] == f"{later['metrics'][0]['value']:.6g} rentals per day" and by_revision["1"]["Value"] != by_revision["2"]["Value"]
    assert by_revision["1"]["References set"] != by_revision["2"]["References set"]
    note = f"This Assessment follows Assessment {earlier['assessment_id']}"
    assert note in doc.text and "Recorded cause: references_version" in doc.text and doc.text.count("This Assessment follows") == 1
    assert earlier["assessment_id"] in {row[0] for row in doc.body("assessments")}


# --- #154: the single-feature check on an Assessment's card, and the warning beside the Comparison's status ------------------------

CHECKED = "checked: no declared lag feature beats this Assessment"
NOT_CHECKED = "not checked"


def generated_bike_rows(rows):
    """A Bike data file whose rentals are a weekday and month pattern, the same every year: ridge_v1 fits it better than any lag feature alone."""
    for row in rows:
        count = 2000 + 300 * int(row["weekday"]) + 200 * int(row["mnth"])
        row.update(cnt=str(count), registered=str(count), casual="0")


def card_of(page: str, assessment_id: str) -> str:
    """The text of the card of one Assessment in the metrics section, tags removed."""
    cards = re.findall(r'<div class="card"><p><b>Assessment </b>(.*?)</p>(.*?)(?=<div class="card">|<p class="sub2">Comparisons</p>)', page, re.S)
    found = [body for shown, body in cards if shown == assessment_id]
    assert len(found) == 1, (assessment_id, [shown for shown, _ in cards])
    return " ".join(re.sub(r"<[^>]+>", " ", found[0]).split())


def test_an_assessments_card_shows_one_of_the_three_states_of_the_check_and_the_comparability_cell_names_the_warning(tmp_path):
    from _revision_helpers import new_revision

    examples = examples_copy(tmp_path)
    study, _ = init_study(tmp_path, examples=examples)
    ids = {}
    for config in ("seasonal_7", "ridge_v1"):
        code, payload, err = run_ml(study, config, "dev", f"rev-1-{config}", "--examples-dir", examples)
        assert code == 0, (payload, err)
        code, payload, err = assess(study, observation_set_id(study, payload["attempt"]), "regression_mae_v1", references_id(study))
        assert code == 0, (payload, err)
        ids[config] = payload["assessment"]
    absent = forged(study, ids["ridge_v1"], lambda record: record.pop("single_feature_check", None))
    code, compared, err = compare(study, ids["seasonal_7"]["assessment_id"], ids["ridge_v1"]["assessment_id"])
    assert code == 0, (compared, err)
    # a second revision of the Study, on a generated series, where ridge_v1's lag features all lose
    generated = examples_copy(tmp_path, rows=generated_bike_rows, name="generated")
    code, payload, err = new_revision(study, "--examples-dir", generated)
    assert code == 0, (payload, err)
    code, payload, err = run_ml(study, "ridge_v1", "dev", "rev-2-ridge_v1", "--examples-dir", generated)
    assert code == 0, (payload, err)
    code, payload, err = assess(study, observation_set_id(study, payload["attempt"]), "regression_mae_v1", references_id(study))
    assert code == 0, (payload, err)
    losing = payload["assessment"]
    out = tmp_path / "out" / "report.html"
    out.parent.mkdir()
    assert report(study, out)[0] == 0
    page = out.read_text(encoding="utf-8")

    beaten = ids["ridge_v1"].get("single_feature_check", {}).get("beating", [])
    listed = "; ".join(f"{entry['feature']} {entry['value']:.6g} rentals per day" for entry in beaten)
    cards = {
        "beaten": (card_of(page, ids["ridge_v1"]["assessment_id"]), f"beaten by {listed}"),
        "no lag feature": (card_of(page, ids["seasonal_7"]["assessment_id"]), CHECKED),
        "all lose": (card_of(page, losing["assessment_id"]), CHECKED),
        "absent": (card_of(page, absent["assessment_id"]), NOT_CHECKED),
    }
    for name, (text, state) in cards.items():
        assert f"Single-feature check {state}" in text, (name, text)
        others = {f"Single-feature check {s}" for s in (f"beaten by {listed}", CHECKED, NOT_CHECKED)} - {f"Single-feature check {state}"}
        assert not any(other in text for other in others), (name, text)
    assert [entry["feature"] for entry in beaten] == ["mean_previous_7", "lag_1", "lag_7"]
    assert losing["single_feature_check"]["computed"] and losing["single_feature_check"]["beating"] == []  # its features were checked and all lose
    comparison = {row[0]: row[1] for row in doc_of(out).body("comparison-0")}
    assert comparison["Comparability"] == "compatible, with warning COMPARISON_SINGLE_FEATURE_BEATS", comparison


# --- #155: a Declared deviation, beside the status of a regression Comparison ------------------------------------------------------


def test_the_comparability_cell_of_a_regression_comparison_a_declaration_covers_names_its_code_and_one_with_only_the_import_warning_names_none(tmp_path):
    from _deviation_helpers import CODE, comparability_cells, compare_ids, declare, references_of
    from _report_helpers import dev_world

    study, facts = dev_world(tmp_path)
    assert [w["code"] for w in facts["descriptive"]["warnings"]] == ["COMPARISON_DESCRIPTIVE_IMPORT"]
    declare(study, [references_of(study)])
    covered = compare_ids(study, facts["assessments"]["seasonal_7"], facts["assessments"]["ridge_v1"])
    assert CODE in [w["code"] for w in covered["warnings"]]
    out = tmp_path / "out" / "report.html"
    out.parent.mkdir()
    from _deviation_helpers import rendered

    rendered(study, out)
    cells = comparability_cells(out)
    assert cells[covered["comparison_id"]].startswith("compatible") and CODE in cells[covered["comparison_id"]], cells
    assert cells[facts["descriptive"]["comparison_id"]] == "descriptive_only (descriptive)", cells


def test_the_page_shows_the_warning_a_comparison_recorded_and_nothing_computed_from_a_declaration_or_its_withdrawal(tmp_path):
    from _deviation_helpers import bike_world, the_report_shows_what_each_comparison_recorded_and_computes_nothing_from_the_declared_deviations

    world = bike_world(tmp_path, count=2)
    (tmp_path / "out").mkdir()
    the_report_shows_what_each_comparison_recorded_and_computes_nothing_from_the_declared_deviations(world, tmp_path / "out")


# --- the Data profile section of a Bike page (#261) ---------------------------------------------------------------------------------


def profile_section(raw: str) -> str:
    """The `section` element of the page whose id is `data-profile`."""
    [section] = re.findall(r'<section id="data-profile".*?</section>', raw, re.S)
    return section


def value_at(read, path: str):
    """The value of the profile read at a key path such as `columns[3].distribution.histogram[2].count`."""
    value = read
    for key, index in re.findall(r"([A-Za-z_0-9]+)(?:\[(\d+)\])?", path):
        value = value[key]
        if index:
            value = value[int(index)]
    return value


@pytest.fixture(scope="module")
def profiled(tmp_path_factory):
    """(the Study, the object of `profile --json`, the raw page, its Data profile section) of a fresh Bike Study with one Attempt on dev."""
    base = tmp_path_factory.mktemp("profiled")
    study, _ = fresh_study(base, "seasonal_7")
    code, read, err = run_json("profile", "--study", study)
    assert code == 0, (read, err)
    out = base / "page.html"
    code, payload, err = report(study, out)
    assert code == 0, (payload, err)
    raw = out.read_text(encoding="utf-8")
    return study, read, raw, profile_section(raw)


def test_every_svg_of_the_data_profile_holds_rects_only_with_no_text_or_style_and_the_page_holds_no_script_or_img(profiled):
    _, _, raw, section = profiled
    svgs = re.findall(r"<svg\b[^>]*>(.*?)</svg>", section, re.S)
    assert len(svgs) >= 4
    for body in svgs:
        assert re.sub(r'<rect\b[^<>]*></rect>', "", body) == ""
    assert not re.search(r"<(svg|rect)\b[^>]*\bstyle=", section)
    assert "<script" not in raw and "<img" not in raw


def test_each_number_of_the_data_profile_equals_the_read_at_its_key_path_and_the_target_has_358_days_none_after_2011(profiled):
    _, read, _, section = profiled
    spans = re.findall(r'<span data-path="([^"]+)">(.*?)</span>', section)
    paths = {path for path, _ in spans}
    assert {"items", "target.figures.quartiles.median", "associations.level", "columns[0].distribution.histogram[0].count"} <= paths
    assert any(path.startswith("against_target[") and ".values[" in path for path in paths)
    for path, text in spans:
        value = value_at(read, path)
        expected = value if isinstance(value, str) else str(markup.number(value))
        assert html.unescape(text) == expected, path
    days = re.findall(r'<rect\b[^>]*data-date="([^"]+)"', section)
    assert len(days) == 358 and max(days) <= "2011-12-31"
    shown = re.findall(r"\b20\d\d-\d\d-\d\d\b", re.sub(r'<table[^>]*id="profile-band".*?</table>', "", section, flags=re.S))
    assert [day for day in shown if day > "2011-12-31"] == []


def test_each_forbidden_column_of_the_matrix_says_not_available_at_prediction_time_and_no_available_column_does(profiled):
    _, read, _, section = profiled
    doc = Doc(section)
    rows = {row[1]: row[2] for row in doc.body("profile-order")}
    available = {column["name"]: column["available"] for column in read["columns"]}
    assert set(rows) == set(available)
    assert {name: text == "not available at prediction time" for name, text in rows.items()} == {name: not ok for name, ok in available.items()}


def test_a_script_tag_planted_in_a_column_name_of_the_data_is_escaped_on_the_page(tmp_path):
    planted = "<script>alert(1)</script>"
    examples = examples_copy(tmp_path)
    bike = examples / "bike_day"
    data = bike / "data" / "day.csv"
    text = data.read_text(encoding="utf-8")
    data.write_text(text.replace("instant,", f'"{planted}",', 1), encoding="utf-8")
    checks = json.loads((bike / "data-checks.json").read_text(encoding="utf-8"))
    checks["columns"][0] = planted
    (bike / "data-checks.json").write_text(json.dumps(checks), encoding="utf-8")
    lock_path = bike / "data-sources.lock.json"
    lock_file = json.loads(lock_path.read_text(encoding="utf-8"))
    lock_file["sources"][0].update(sha256=sha_of(data), size_bytes=data.stat().st_size)
    lock_path.write_text(json.dumps(lock_file), encoding="utf-8")
    study, _ = init_study(tmp_path, examples=examples)
    out = tmp_path / "page.html"
    code, payload, err = report(study, out, "--examples-dir", examples)
    assert code == 0, (payload, err)
    section = profile_section(out.read_text(encoding="utf-8"))
    assert "<script" not in section and "&lt;script&gt;alert(1)&lt;/script&gt;" in section


def test_a_refused_profile_read_leaves_one_sentence_with_its_code_and_a_changed_workload_adds_the_differs_sentence(tmp_path):
    study, _ = fresh_study(tmp_path / "study", "seasonal_7")
    missing = examples_copy(tmp_path, edit=lambda d: d.update(target_column="nonesuch"), name="missing")
    out = tmp_path / "refused.html"
    code, payload, err = report(study, out, "--examples-dir", missing)
    assert (code, payload.get("ok")) == (0, True), (payload, err)
    section = profile_section(out.read_text(encoding="utf-8"))
    paragraphs = re.findall(r"<p>(.*?)</p>", section, re.S)
    assert [re.sub(r"<[^>]+>", "", p) for p in paragraphs] == ["The data profile could not be read: COLUMN_MISSING."]
    assert "<svg" not in section and "<table" not in section
    changed = examples_copy(tmp_path, edit=lambda d: d["forbidden_features"].remove("temp"), name="changed")
    out = tmp_path / "differs.html"
    code, payload, err = report(study, out, "--examples-dir", changed)
    assert (code, payload.get("ok")) == (0, True), (payload, err)
    section = profile_section(out.read_text(encoding="utf-8"))
    assert f"<p>{markup.esc(render_profile.DIFFERS_SENTENCE)}</p>" in section and section.count("<svg") >= 4
