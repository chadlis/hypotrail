"""Ticket #64, AC4 and AC6: ArtifactRefs, path safety, integrity on read-back, atomic publication."""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from hypotrail.core import artifacts, canonical
from hypotrail.core.errors import EXIT_INTEGRITY_REFUSED, IntegrityError

REF_KEYS = {"path", "sha256", "size_bytes", "media_type", "role"}


def test_a_published_artifact_is_referenced_by_relative_path_digest_size_media_type_and_role(tmp_path):
    ref = artifacts.publish_bytes(tmp_path, "attempts/a/predictions.csv", b"row_id\n1\n", media_type="text/csv", role="predictions")
    assert set(ref) == REF_KEYS
    assert ref == {
        "path": "attempts/a/predictions.csv",
        "sha256": canonical.sha256_hex(b"row_id\n1\n"),
        "size_bytes": 9,
        "media_type": "text/csv",
        "role": "predictions",
    }
    assert (tmp_path / "attempts/a/predictions.csv").read_bytes() == b"row_id\n1\n"
    assert artifacts.read_verified(tmp_path, ref) == b"row_id\n1\n"


@pytest.mark.parametrize("bad", ["../outside.csv", "a/../../outside.csv", "/etc/passwd", "", "a//b/../../../c", "."])
def test_a_path_that_leaves_the_study_is_refused_with_a_code(tmp_path, bad):
    with pytest.raises(IntegrityError) as caught:
        artifacts.publish_bytes(tmp_path, bad, b"x", media_type="text/plain", role="r")
    assert caught.value.code == "ARTIFACT_PATH_OUTSIDE_STUDY"
    assert caught.value.exit_code == EXIT_INTEGRITY_REFUSED
    assert not (tmp_path.parent / "outside.csv").exists()


def test_a_symlink_pointing_outside_the_study_is_refused_for_writing_and_for_reading(tmp_path):
    study, elsewhere = tmp_path / "study", tmp_path / "elsewhere"
    study.mkdir()
    elsewhere.mkdir()
    (elsewhere / "secret.txt").write_bytes(b"s")
    (study / "link").symlink_to(elsewhere, target_is_directory=True)
    (study / "file-link").symlink_to(elsewhere / "secret.txt")
    with pytest.raises(IntegrityError) as written:
        artifacts.publish_bytes(study, "link/new.txt", b"x", media_type="text/plain", role="r")
    assert written.value.code == "ARTIFACT_PATH_OUTSIDE_STUDY"
    assert not (elsewhere / "new.txt").exists()
    ref = {"path": "file-link", "sha256": canonical.sha256_hex(b"s"), "size_bytes": 1, "media_type": "text/plain", "role": "r"}
    with pytest.raises(IntegrityError) as read:
        artifacts.read_verified(study, ref)
    assert read.value.code == "ARTIFACT_PATH_OUTSIDE_STUDY"


def test_a_symlink_that_stays_inside_the_study_is_not_a_traversal(tmp_path):
    (tmp_path / "real").mkdir()
    (tmp_path / "alias").symlink_to(tmp_path / "real", target_is_directory=True)
    ref = artifacts.publish_bytes(tmp_path, "alias/x.txt", b"x", media_type="text/plain", role="r")
    assert (tmp_path / "real" / "x.txt").read_bytes() == b"x"
    assert artifacts.read_verified(tmp_path, ref) == b"x"


def test_bytes_that_no_longer_match_the_digest_are_an_integrity_refusal_before_any_use(tmp_path):
    ref = artifacts.publish_bytes(tmp_path, "a.csv", b"1,2\n", media_type="text/csv", role="r")
    (tmp_path / "a.csv").write_bytes(b"1,3\n")
    with pytest.raises(IntegrityError) as caught:
        artifacts.read_verified(tmp_path, ref)
    assert caught.value.code == "ARTIFACT_INTEGRITY"
    assert caught.value.exit_code == EXIT_INTEGRITY_REFUSED
    assert caught.value.details["path"] == "a.csv"
    assert caught.value.details["expected_sha256"] == ref["sha256"]
    assert caught.value.details["actual_sha256"] == canonical.sha256_hex(b"1,3\n")


def test_a_referenced_artifact_that_disappeared_is_an_integrity_refusal(tmp_path):
    ref = artifacts.publish_bytes(tmp_path, "a.csv", b"x", media_type="text/csv", role="r")
    (tmp_path / "a.csv").unlink()
    with pytest.raises(IntegrityError) as caught:
        artifacts.read_verified(tmp_path, ref)
    assert caught.value.code == "ARTIFACT_MISSING"


def test_a_published_artifact_is_never_overwritten_with_other_bytes(tmp_path):
    artifacts.publish_bytes(tmp_path, "a.csv", b"one", media_type="text/csv", role="r")
    with pytest.raises(IntegrityError) as caught:
        artifacts.publish_bytes(tmp_path, "a.csv", b"two", media_type="text/csv", role="r")
    assert caught.value.code == "ARTIFACT_IMMUTABLE"
    assert (tmp_path / "a.csv").read_bytes() == b"one"


def test_a_write_stopped_before_publication_leaves_nothing_under_the_final_path(tmp_path):
    """The writing process is killed at the rename: the bytes were written to a temporary place only."""
    script = textwrap.dedent(
        """
        import os, sys
        from pathlib import Path
        from hypotrail.core import artifacts

        os.replace = lambda *args, **kwargs: os._exit(9)  # the publication step never happens
        artifacts.publish_bytes(Path(sys.argv[1]), "attempts/a/predictions.csv", b"data", media_type="text/csv", role="r")
        """
    )
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path)], capture_output=True, text=True)
    assert result.returncode == 9, result.stderr
    assert not (tmp_path / "attempts/a/predictions.csv").exists()
    leftovers = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert all(p.name.endswith(".tmp") for p in leftovers)  # only a temporary file, inside the Study


def test_the_temporary_place_is_inside_the_study(tmp_path):
    seen = []
    real_replace = os.replace

    def spy(source, target, *args, **kwargs):
        seen.append(Path(source))
        return real_replace(source, target, *args, **kwargs)

    os.replace = spy
    try:
        artifacts.publish_bytes(tmp_path, "x/y.txt", b"x", media_type="text/plain", role="r")
    finally:
        os.replace = real_replace
    assert len(seen) == 1 and seen[0].resolve().is_relative_to(tmp_path.resolve())
    assert not seen[0].exists()  # renamed away, not copied


def test_a_record_is_published_as_canonical_json_and_a_non_finite_value_writes_nothing(tmp_path):
    ref = artifacts.publish_record(tmp_path, "record.json", {"b": 1, "a": [1.5]}, role="record")
    assert (tmp_path / "record.json").read_bytes() == b'{"a":[1.5],"b":1}'
    assert ref["media_type"] == "application/json"
    with pytest.raises(Exception) as caught:
        artifacts.publish_record(tmp_path, "bad.json", {"mae": float("nan")}, role="record")
    assert caught.value.code == "NON_CANONICAL_VALUE"
    assert not (tmp_path / "bad.json").exists()
    assert not [p for p in tmp_path.rglob("*.tmp")]


def test_replace_atomically_fsyncs_the_file_then_renames_it_then_fsyncs_the_folder_and_creates_no_folder(tmp_path, monkeypatch):
    events = []
    real_fsync, real_replace = os.fsync, os.replace
    monkeypatch.setattr(os, "fsync", lambda fd: (events.append("fsync file"), real_fsync(fd))[1])
    monkeypatch.setattr(os, "replace", lambda source, target: (events.append(("replace", Path(target).name)), real_replace(source, target))[1])
    monkeypatch.setattr(artifacts, "_fsync_dir", lambda path: events.append(("fsync folder", Path(path), (Path(path) / "page.html").read_bytes())))
    target = tmp_path / "out" / "page.html"
    target.parent.mkdir()
    target.write_bytes(b"old")
    artifacts.replace_atomically(target, b"new")
    assert events == ["fsync file", ("replace", "page.html"), ("fsync folder", target.parent, b"new")]
    assert [p.name for p in target.parent.iterdir()] == ["page.html"]
    with pytest.raises(OSError):
        artifacts.replace_atomically(tmp_path / "missing" / "page.html", b"x")
    assert not (tmp_path / "missing").exists()


def test_the_module_and_replace_atomically_say_that_its_path_is_not_checked_against_the_study():
    assert "not checked against the Study" in artifacts.__doc__
    assert "not checked against the Study" in artifacts.replace_atomically.__doc__
