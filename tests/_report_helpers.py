"""Shared by the report tests (#85): run `report`, read the page as a document, build the Studies it is rendered from."""

import json
import re
import uuid
from html.parser import HTMLParser
from pathlib import Path

from _assess_helpers import assess, fresh_study, observation_set_id, references_id, rows_of
from _compare_helpers import compare
from _import_helpers import import_ml, ready
from _study_helpers import run_json

from hypotrail.core import artifacts, canonical, contracts



def report(study, out, *more):
    """Run `report`; every page the suite renders is checked for the milestone status it must not state (#86 Tightened F)."""
    code, payload, err = run_json("report", "--study", study, "--out", out, *more)
    if code == 0:
        assert_no_milestone_status(Path(out).read_text(encoding="utf-8"))
    return code, payload, err


def assert_no_milestone_status(raw: str) -> None:
    """A per-Study page states no milestone status: `LIVE_ACCEPTED` and the live acceptance status are for the grid and the README (D-017 on chadlis/hypotrail#75 item 7)."""
    assert "LIVE_ACCEPTED" not in raw and "live acceptance" not in raw.lower(), "a per-Study page states a milestone status"


class Doc(HTMLParser):
    """The page as a document: its elements, attributes, text, tables (cells with their links) and sections."""

    def __init__(self, text):
        super().__init__()
        self.elements, self.text_pieces, self.tables, self.sections, self.style = [], [], {}, [], ""
        self.scoped = {}  # {data-attempt-id: the text pieces of every element marked with it}
        self._table, self._row, self._cell, self._section, self._in, self._scopes = None, None, None, None, [], []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.elements.append((tag, attrs))
        self._in.append(tag)
        self._scopes.append(attrs.get("data-attempt-id"))
        if attrs.get("data-attempt-id"):
            self.scoped.setdefault(attrs["data-attempt-id"], [])
        if tag == "section":
            self._section = {"id": attrs.get("id"), "headings": []}
            self.sections.append(self._section)
        elif tag == "table":
            self._table = self.tables.setdefault(attrs.get("id", f"t{len(self.tables)}"), [])
        elif tag == "tr" and self._table is not None:
            self._row = []
            self._table.append(self._row)
        elif tag in ("td", "th") and self._row is not None:
            self._cell = {"text": "", "links": [], "pieces": [], "lines": [""]}
            self._row.append(self._cell)
        elif tag == "a" and self._cell is not None and "href" in attrs:
            self._cell["links"].append(attrs["href"])
        if tag == "div" and self._cell is not None:
            self._cell["lines"].append("")

    def handle_endtag(self, tag):
        if tag in self._in:
            while self._in and self._in.pop() != tag:
                self._scopes.pop()
            self._scopes.pop()
        if tag in ("td", "th"):
            self._cell = None
        elif tag == "tr":
            self._row = None
        elif tag == "table":
            self._table = None

    def handle_data(self, data):
        if self._in and self._in[-1] == "style":
            self.style += data
            return
        self.text_pieces.append(data)
        for scope in {s for s in self._scopes if s}:
            self.scoped[scope].append(data)
        if self._cell is not None:
            self._cell["text"] += data
            self._cell["pieces"].append(data)
            self._cell["lines"][-1] += data
        if self._in and self._in[-1] == "h2" and self._section is not None:
            self._section["headings"].append(data)

    @property
    def text(self):
        return " ".join(" ".join(self.text_pieces).split())

    def rows(self, table_id):
        """The table as lists of cell texts, header row first."""
        return [[c["text"] for c in row] for row in self.tables[table_id]]

    def body(self, table_id):
        return self.rows(table_id)[1:]

    def cells(self, table_id):
        """The table's body as lists of cells, each `{"text", "links", "pieces"}`."""
        return self.tables[table_id][1:]

    def scope_text(self, attempt_id) -> str:
        return " ".join(" ".join(self.scoped.get(attempt_id, [])).split())


def doc_of(out) -> Doc:
    return Doc(Path(out).read_text(encoding="utf-8"))


def dev_world(tmp_path, *, name="world", imported=True, markup=None):
    """(study, facts): two native Attempts on dev, both assessed and compared, and an assessed Import compared with the first.

    `markup` maps a producer claim to the string the import declares; the request id of the import is `facts["import_request"]`.
    """
    base = tmp_path / name
    base.mkdir(parents=True, exist_ok=True)
    study, attempts = fresh_study(base, "seasonal_7", "ridge_v1")
    refs = references_id(study)
    ids = {}
    for config, attempt in attempts.items():
        code, payload, err = assess(study, observation_set_id(study, attempt), "regression_mae_v1", refs)
        assert code == 0, (payload, err)
        ids[config] = payload["assessment"]["assessment_id"]
    code, both, err = compare(study, ids["seasonal_7"], ids["ridge_v1"])
    assert code == 0, (both, err)
    facts = {"attempts": attempts, "assessments": ids, "comparison": both["comparison"]}
    if imported:
        source, mapping, population, digest = ready(base, **(markup or {}))
        facts["import_request"] = "import-a"
        code, imp, err = import_ml(study, source, mapping, population, facts["import_request"])
        assert code == 0, (imp, err)
        facts["import"] = imp["attempt"]
        code, payload, err = assess(study, observation_set_id(study, imp["attempt"]), "regression_mae_v1", refs)
        assert code == 0, (payload, err)
        facts["import_assessment"] = payload["assessment"]["assessment_id"]
        code, descriptive, err = compare(study, ids["seasonal_7"], facts["import_assessment"])
        assert code == 0, (descriptive, err)
        facts["descriptive"] = descriptive["comparison"]
    return study, facts


def manifest_path(study, attempt_id) -> Path:
    return Path(study) / "attempts" / attempt_id / "attempt.json"


def edit_manifest(study, attempt_id, edit):
    path = manifest_path(study, attempt_id)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    edit(manifest)
    contracts.validate(manifest)
    path.write_bytes(canonical.dumps(manifest))


def constructed_attempt(study, status, *, request_id=None, mode="native_ml", outcome_unknown=False):
    """A manifest of the given technical status with no outputs, as a writer that stopped leaves one."""
    attempt_id = str(uuid.uuid4())
    config = {"mode": mode, "partition": "dev"}
    manifest = {
        "kind": "attempt", "schema_version": "attempt/1", "attempt_id": attempt_id, "request_id": request_id or f"constructed-{attempt_id[:8]}",
        "operation": "execute", "mode": mode, "technical_status": status,
        "started_at": "2026-11-08T10:00:00+00:00", "finished_at": None if status == "running" else "2026-11-08T10:05:00+00:00",
        "effective_config": config, "effective_config_digest": canonical.digest(config),
        "input_refs": [], "code_environment": {}, "outcome_unknown": outcome_unknown, "retry_of": None,
    }
    if status == "interrupted":
        manifest["reason"] = "the writer ended before the terminal manifest"
    contracts.validate(manifest)
    artifacts.replace_bytes(study, f"attempts/{attempt_id}/attempt.json", canonical.dumps(manifest))
    return attempt_id


def per_item_rows(study, assessment_id):
    return rows_of(Path(study) / "assessments" / assessment_id / "per_item.csv")


def dates_of(study) -> dict:
    return {r["row_id"]: r["date"] for r in rows_of(Path(study) / "artifacts" / "memberships.csv")}


def sha_of(path) -> str:
    return canonical.sha256_hex(Path(path).read_bytes())


def targets_of(study) -> dict:
    return {r["row_id"]: float(r["y_true"]) for r in rows_of(Path(study) / "artifacts" / "references.csv")}


def observations_of(study, attempt_id) -> dict:
    return {r["row_id"]: r for r in rows_of(Path(study) / "attempts" / attempt_id / "observations.csv")}


def journal_of(study) -> list:
    folder = Path(study) / "exposures"
    return [json.loads(p.read_text()) for p in sorted(folder.glob("*.json"))] if folder.is_dir() else []


def freeze_files(study) -> list:
    return sorted((Path(study) / "revisions").glob("*/freeze.json")) if (Path(study) / "revisions").is_dir() else []


def tree(folder) -> dict:
    return {p.relative_to(folder).as_posix(): sha_of(p) for p in sorted(Path(folder).rglob("*")) if p.is_file()}


def lines_of(cell) -> list:
    """The lines of a table cell, one per element the page wrote for it, empty ones dropped."""
    return [" ".join(line.split()) for line in cell["lines"] if line.strip()]
