"""Verify a private ranking build and freeze only its development population and References."""

import csv
import io
import json
import os
import re
import stat
import uuid
from dataclasses import dataclass
from datetime import date
from functools import cache
from importlib import resources
from pathlib import Path

from jsonschema import Draft202012Validator

from hypotrail.core import artifacts, canonical, contracts, data, revisions, scorers, study_write
from hypotrail.core import study as layout
from hypotrail.core.errors import IntegrityError, InvalidInputError
from hypotrail.ml.partitions import DEV

TRACK = scorers.RANKING
BUILD = "build.json"
ITEMS = "items.csv"
REFERENCES = "references-dev.csv"
DEV_FILES = {ITEMS, REFERENCES}
ITEM_ID_PATTERN = re.compile(r"([A-Za-z0-9_-]+)@([0-9]{4}-[0-9]{2}-[0-9]{2})")
ITEM_COLUMNS = ("item_id", "entity_id", "as_of", "partition", "mature")
REFERENCE_COLUMNS = ("item_id", "label")


def _refuse(code, message, **details):
    return InvalidInputError(code, message, stage="study", details=details)


@cache
def _validator(schema_name):
    package = resources.files(__package__)
    schema = json.loads(package.joinpath(schema_name).read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


def _declaration(examples, workload):
    path = examples / workload / "workload.json"
    try:
        value = canonical.loads(path.read_bytes())
    except (OSError, InvalidInputError):
        raise _refuse("RANKING_WORKLOAD_INVALID", "the ranking Workload needs a readable declaration", workload=workload) from None
    if not _validator("ranking-study.schema.json").is_valid(value):
        raise _refuse("RANKING_WORKLOAD_INVALID", "the declaration does not match the ranking Workload schema", workload=workload)
    return value


def _private_directory(path):
    if path is None:
        raise _refuse("RANKING_BUILD_REQUIRED", "give --build-dir with the private ranking build")
    try:
        resolved = Path(path).resolve(strict=True)
    except (OSError, RuntimeError):
        raise _refuse("RANKING_BUILD_NOT_FOUND", "the private ranking build directory is missing") from None
    if not resolved.is_dir():
        raise _refuse("RANKING_BUILD_NOT_FOUND", "the private ranking build directory is missing")
    git_markers = (parent / ".git" for parent in (resolved, *resolved.parents))
    if any(marker.is_file() or (marker / "HEAD").is_file() for marker in git_markers):
        raise _refuse("RANKING_BUILD_IN_REPOSITORY", "stage the private ranking build outside every Git worktree")
    return resolved


def _read_source(folder, source):
    name = source["dataset_id"]
    path = folder / name
    try:
        entry = path.lstat()
        if not stat.S_ISREG(entry.st_mode) or entry.st_nlink != 1:
            raise OSError
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        with os.fdopen(os.open(path, flags), "rb") as handle:
            opened = os.fstat(handle.fileno())
            if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1 or not os.path.samestat(entry, opened):
                raise OSError
            raw = handle.read()
    except OSError:
        raise IntegrityError("DATA_MISSING", f"private build file missing or unreadable: {name}", stage="integrity", details={"file": name}) from None
    digest = canonical.sha256_hex(raw)
    if source["sha256"] != digest or source["size_bytes"] != len(raw):
        raise IntegrityError(
            "DATA_INTEGRITY",
            f"private build file does not match the manifest: {name}",
            stage="integrity",
            details={
                "file": name,
                "expected_sha256": source["sha256"],
                "actual_sha256": digest,
                "expected_size_bytes": source["size_bytes"],
                "actual_size_bytes": len(raw),
            },
        )
    return raw


def _verified_build(examples, workload, build_dir):
    folder = _private_directory(build_dir)
    declaration = _declaration(examples, workload)
    reports = data.verify_workloads(examples, [workload])
    names = [report["dataset_id"] for report in reports]
    if set(names) != DEV_FILES | {BUILD} or len(names) != len(set(names)) or any(report["status"] != "declared" for report in reports):
        raise _refuse(
            "RANKING_MANIFEST_INVALID",
            "the development manifest must declare build.json, items.csv and references-dev.csv once each",
            workload=workload,
        )
    raw = {report["dataset_id"]: _read_source(folder, report) for report in reports}
    try:
        build = canonical.loads(raw[BUILD])
        valid = _validator("contracts/ml-scores-1/ranking-build.schema.json").is_valid(build)
        if not valid:
            raise ValueError
        cutoff = date.fromisoformat(build["label_cutoff"])
    except (InvalidInputError, ValueError):
        raise _refuse("RANKING_BUILD_INVALID", "build.json does not match the ranking build contract", file=BUILD) from None

    expected = {r["dataset_id"]: (r["sha256"], r["size_bytes"]) for r in reports if r["dataset_id"] != BUILD}
    actual = {name: (entry["sha256"], entry["size_bytes"]) for name, entry in build["files"].items()}
    if expected != actual:
        raise IntegrityError(
            "DATA_INTEGRITY",
            "build.json and the manifest do not declare the same development files and digests",
            stage="integrity",
            details={"file": BUILD},
        )
    return declaration, raw, build, cutoff, reports


def verify(examples, workload, build_dir):
    """Check the bytes at the explicitly supplied build, without parsing its CSV files."""
    _, _, _, _, reports = _verified_build(examples, workload, build_dir)
    return [{**r, "status": "verified", "file": r["dataset_id"]} for r in reports]


def item_date(item_id):
    match = ITEM_ID_PATTERN.fullmatch(item_id)
    if match is None:
        raise ValueError("invalid Item ID")
    return date.fromisoformat(match[2])


def item_digest(item_id):
    return canonical.sha256_hex(item_id.encode("utf-8"))


def _table(raw, columns, code):
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8"), newline=""), strict=True)
        rows = list(reader)
    except (UnicodeError, csv.Error):
        raise _refuse(code, "the ranking CSV is unreadable") from None
    if tuple(reader.fieldnames or ()) != columns or any(None in row or None in row.values() for row in rows):
        raise _refuse(code, "the ranking CSV has unexpected columns")
    return rows


def _items(raw, cutoff, horizon):
    items = {}
    for row in _table(raw, ITEM_COLUMNS, "RANKING_ITEMS_INVALID"):
        item_id = row["item_id"]
        try:
            as_of = item_date(item_id)
        except ValueError:
            raise _refuse("RANKING_ITEMS_INVALID", "items.csv contains a malformed Item ID") from None
        mature = (cutoff - as_of).days >= horizon
        if (
            item_id in items
            or item_id != f"{row['entity_id']}@{row['as_of']}"
            or row["as_of"] != as_of.isoformat()
            or row["mature"] != str(mature).lower()
            or (not mature and row["partition"])
        ):
            raise _refuse("RANKING_ITEMS_INVALID", "items.csv contains inconsistent Item identities or maturity")
        items[item_id] = row
    return items


def _verify_references(raw, items):
    seen = set()
    for row in _table(raw, REFERENCE_COLUMNS, "RANKING_REFERENCES_INVALID"):
        item_id = row["item_id"]
        if item_id in seen:
            raise _refuse("REFERENCE_ROW_DUPLICATE", "the development References list an Item twice")
        item = items.get(item_id)
        if item is None:
            raise _refuse("REFERENCE_ITEM_UNKNOWN", "a Reference has an Item absent from items.csv")
        if item["mature"] != "true":
            raise _refuse("REFERENCE_ITEM_IMMATURE", "a Reference has an immature Item")
        if item["partition"] != DEV:
            raise _refuse("REFERENCE_ITEM_UNKNOWN", "the development References hold an Item outside their Partition")
        if row["label"] not in ("0", "1"):
            raise _refuse("REFERENCE_LABEL_NOT_BINARY", "a Reference label must be 0 or 1")
        seen.add(item_id)
    if seen != {item_id for item_id, item in items.items() if item["partition"] == DEV}:
        raise _refuse("RANKING_REFERENCES_INVALID", "the development References do not cover the development Partition")


def _dev_memberships(items):
    out = io.StringIO()
    columns = ITEM_COLUMNS[:-1]
    writer = csv.DictWriter(out, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows(items[item_id] for item_id in sorted(items) if items[item_id]["partition"] == DEV)
    return out.getvalue().encode("utf-8")


@dataclass(frozen=True)
class FrozenBuild:
    declaration: dict
    dataset: bytes
    memberships: bytes
    references: bytes


def freeze(examples, workload, build_dir):
    declaration, raw, build, cutoff, _ = _verified_build(examples, workload, build_dir)
    horizon = declaration["horizon_days"]
    items = _items(raw[ITEMS], cutoff, horizon)
    _verify_references(raw[REFERENCES], items)
    # Only the development Items are published in the Study. The digest lookup
    # identifies a cross-Partition request without copying other Item IDs.
    dataset = {
        "items_sha256": canonical.sha256_hex(raw[ITEMS]),
        "label_cutoff": cutoff.isoformat(),
        "horizon_days": horizon,
        "frame_digest": build["frame_digest"],
        "other_partition_items": sorted(item_digest(item) for item, row in items.items() if row["partition"] not in ("", DEV)),
    }
    return FrozenBuild(declaration, canonical.dumps(dataset), _dev_memberships(items), raw[REFERENCES])


def read_dataset(study, spec):
    """Read the frozen metadata and dev memberships through their Study digests."""
    dataset = canonical.loads(artifacts.read_verified(study, layout.dataset_ref(spec)))
    ref = next(entry["ref"] for entry in spec["artifacts"] if entry["ref"]["role"] == "memberships")
    members = _table(artifacts.read_verified(study, ref), ITEM_COLUMNS[:-1], "RANKING_ITEMS_INVALID")
    return dataset, {row["item_id"]: row for row in members}


def publish(study, workload, frozen, previous, write):
    config = frozen.declaration
    protocol = canonical.digest({
        "workload": workload,
        "scorer": scorers.get(scorers.RANKING_SCORER).config,
        "dataset_sha256": canonical.sha256_hex(frozen.dataset),
        "memberships_sha256": canonical.sha256_hex(frozen.memberships),
        "references_sha256": canonical.sha256_hex(frozen.references),
    })
    if previous is not None:
        revisions.refuse_unchanged(previous, protocol)
    write.begin()
    dataset, _ = revisions.place(
        study, layout.dataset_ref(previous) if previous is not None else None,
        "datasets/ranking-build.json", frozen.dataset, media_type="application/json", role="dataset",
    )
    previous_entries = {entry["ref"]["role"]: entry for entry in previous["artifacts"]} if previous is not None else {}
    memberships = revisions.artifact_entry(
        study, "memberships", previous_entries.get("memberships"),
        "artifacts/memberships.csv", frozen.memberships, media_type="text/csv", role="memberships",
    )
    references = revisions.artifact_entry(
        study, "references", previous_entries.get("references"),
        "artifacts/references.csv", frozen.references, media_type="text/csv", role="references",
    )
    spec = {
        "kind": "study",
        "schema_version": "study/1",
        "study_id": previous["study_id"] if previous is not None else str(uuid.uuid4()),
        "question": config["question"],
        "domain": TRACK,
        "objective": config["objective"],
        "protocol_id": f"ranking/{workload}",
        "protocol_digest": protocol,
        "dataset_refs": [dataset],
        "primary_metric": {"id": scorers.RANKING_METRIC, "direction": "higher_is_better", "unit": "proportion"},
        "limitations": config["limitations"],
        "workload": workload,
        "artifacts": [memberships, references],
        "revision_number": 1,
    }
    if previous is not None:
        spec.update(revisions.next_fields(study, previous))
    spec["revision"] = canonical.digest({key: value for key, value in spec.items() if key != "study_id"})
    contracts.validate(spec)
    if previous is None:
        artifacts.publish_record(study, layout.STUDY_FILE, spec, role="study_spec")
    else:
        revisions.publish(study, previous, spec)
    write.wrote(study_write.REVISION, spec["revision"])
    return spec
