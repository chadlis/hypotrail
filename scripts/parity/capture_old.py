"""Capture the pinned legacy Auto MPG reference outside CI."""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


LEGACY_COMMIT = "4ef4925af0568dbf57ec02ed872a1af2b1f00b14"
STATE = re.compile(r"[0-9]{2}-[a-z_]+(?:-[a-z_]+)?")


def replay_signature(log):
    """Match the order and the original pause contract without comparing translated copy."""
    signature = []
    for entry in log:
        if STATE.fullmatch(entry["name"]):
            action = entry["payload"]["summary"]["next_action"]
            pause = action.get("pause") or {}
            signature.append((entry["name"], action["kind"], pause.get("kind"),
                              pause.get("position"), pause.get("options")))
    return signature


def _run(argv, *, cwd, env=None):
    process = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True)
    if process.returncode:
        raise RuntimeError(f"{Path(argv[0]).name} exited {process.returncode}")
    return process.stdout


def _env(old, replay):
    environment = os.environ.copy()
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "HYPOTRAIL_ANTHROPIC_API_KEY"):
        environment.pop(key, None)
    environment.update(
        OLD_HYPOTRAIL=str(old),
        REPLAY_ROOT=str(replay),
        STUDY=str(replay / "study-mpg"),
        HYPOTRAIL_COMPANION="1",
        HYPOTRAIL_COMPANION_STAGE="v3",
    )
    return environment


def _legacy(old, replay, study, *args):
    cli = old / "framework/.venv/bin/hypotrail"
    return _run([cli, *args, "--study", study], cwd=old, env=_env(old, replay))


def _log(replay):
    return json.loads((replay / "cap/log.json").read_text(encoding="utf-8"))


def verify_french_replay(old, bundle, french):
    approved_log = _log(bundle)
    recorded = replay_signature(approved_log)
    current = replay_signature(_log(french))
    if len(recorded) != 18 or current != recorded:
        raise RuntimeError("The French walk differs from the approved replay signature")
    summaries = {entry["name"]: entry["payload"]["summary"] for entry in approved_log
                 if STATE.fullmatch(entry["name"])}
    for name, kind, _, position, _ in recorded:
        recording = bundle / "rec" / f"{name}.json"
        tape = json.loads(recording.read_text(encoding="utf-8"))["tape"]
        panel = next(
            response["model"]
            for exchange in tape
            for response in exchange["res"]
            if response["type"] == "snapshot"
        )
        panel_position = {
            "step_id": (panel["currentStep"] or {}).get("id"),
            "completed": sum(step["status"] == "done" for step in panel["plan"]),
            "total": len(panel["plan"]),
        }
        panel_options = panel["texts"]["fr"]["options"]
        summary = summaries[name]
        digest = json.loads(_legacy(
            old, french, french / "snaps" / name, "status", "--summary", "--digest", "--fields", "texts",
        ))
        # The digest omits options on automatic runs, just as the panel does.
        options = digest["texts"]["fr"]["options"] or {}
        if (panel["revision"] != summary["revision"]
                or digest["revision"] != panel["revision"]
                or panel["nextAction"]["kind"] != kind
                or panel_position != position
                or panel_options != [{"id": key, "label": label} for key, label in options.items()]):
            raise RuntimeError(f"The {name} panel recording disagrees with its French CLI state")


def walk(old, bundle, capture, language):
    """Replay only a disposable old Study with the approved scripted answers."""
    capture.mkdir()
    for name in ("hy.py", "walk.py", "rest.json"):
        shutil.copyfile(bundle / name, capture / name)
    if language == "en":
        rest_path = capture / "rest.json"
        rest = json.loads(rest_path.read_text(encoding="utf-8"))
        rest["model_choice"]["words"] = (
            "Yes, I adopt the linear model, because it is the simplest within one standard error of the best."
        )
        rest["final_test"]["words"] = "Yes, I open the final test now, because my choices are fixed."
        rest["conclusion"]["words"] = (
            "Yes, I adopt the linear model, because the criterion fixed in advance "
            "is met on the final test, with its limits."
        )
        rest["conclusion"]["value"]["text"] = (
            "On the 80 rows of the final test, set aside before any look, the linear model is off "
            "by 2.88 mpg on average. The criterion fixed in advance is met. The study says nothing "
            "about cars more recent than these data, nor about why: weight is associated with "
            "fuel efficiency, nothing more."
        )
        rest_path.write_text(json.dumps(rest, ensure_ascii=False), encoding="utf-8")
    _legacy(
        old, capture, capture / "study-mpg", "init",
        "--case", old / "use-cases/auto-mpg", "--lang", language,
    )
    _run([sys.executable, capture / "walk.py"], cwd=capture, env=_env(old, capture))
    if _log(capture)[-1]["tag"] != "done":
        raise RuntimeError(f"The {language} walk did not reach Study finished")


def _keep(out, name, payload, paths):
    document = json.dumps(payload, ensure_ascii=False, indent=2)
    for private, token in paths:
        document = document.replace(str(private), token)
    (out / f"{name}.json").write_text(document + "\n", encoding="utf-8")


def write_fixtures(old, capture, out):
    """Keep the exact English reads, with disposable machine paths normalized."""
    out.mkdir(parents=True, exist_ok=True)
    states = replay_signature(_log(capture))
    if len(states) != 18:
        raise RuntimeError(f"Expected 18 reference states, got {len(states)}")
    for name, *_ in states:
        study = capture / "snaps" / name
        summary = json.loads(_legacy(old, capture, study, "status", "--summary"))
        digest = json.loads(_legacy(old, capture, study, "status", "--summary", "--digest"))
        if summary.get("language") != "en" or not summary.get("ok") or not digest.get("ok"):
            raise RuntimeError(f"{name} did not produce an English Study read")
        card = _legacy(old, capture, study, "data", "--format", "text")
        _keep(
            out, name, {"summary": summary, "digest": digest, "data_card": card},
            ((study, "STUDY"), (capture, "REPLAY"), (old, "OLD_HYPOTRAIL")),
        )


def write_branches(old, capture, out, change_observations=None):
    """Capture the old options, alternative proposals and a real refusal."""
    choices = {
        "success_criterion": {
            "20-percent": ({"business_max_error": 4.5, "metric": "mae_reduction", "min_share": 0.2},
                           "Require at least a 20% reduction in mean absolute error and at most 4.5 mpg."),
        },
        "model_choice": {
            "ebm": ("fit.variant:2", "Choose the Explainable Boosting Machine."),
            "reference": ("fit.baseline", "Choose the mean baseline."),
        },
        "conclusion": {
            "keep-reference": ({"verdict": "keep_baseline", "text": "Keep the reference model."},
                               "Keep the reference (predict the mean)."),
            "do-not-conclude": ({"verdict": "inconclusive", "text": "The study is inconclusive."},
                                "Do not conclude (inconclusive)."),
        },
    }
    branches = capture / "branches"
    branches.mkdir()
    for entry in _log(capture):
        if not STATE.fullmatch(entry["name"]) or not entry["tag"].endswith("-pause"):
            continue
        state = entry["name"]
        payload = entry["payload"]
        action = payload["summary"]["next_action"]
        decision = action["decision"]
        source = capture / "snaps" / state
        scrub = ((source, "STUDY"), (capture, "REPLAY"), (old, "OLD_HYPOTRAIL"))
        if change_observations is not None:
            observation = json.loads((change_observations / f"{decision}.json").read_text(encoding="utf-8"))
            revision = payload["summary"]["revision"]
            if (observation["decision"] != decision
                    or observation["selected"] != {"id": "change", "label": action["pause"]["option_labels"]["change"]}
                    or observation["confirmation_count"] != 0
                    or not observation["prompt"]
                    or observation["revisionBefore"] != revision
                    or observation["revisionAfter"] != revision):
                raise RuntimeError(f"{state} does not match the observed Change branch")
            _keep(out, f"{state}.change", {
                "observation": observation,
                "pause": action["pause"],
                "before_proposal": payload["pre_summary"]["next_action"],
            }, scrub)
        for branch, (value, label) in choices.get(decision, {}).items():
            study = branches / f"{state}.{branch}"
            shutil.copytree(source, study)
            proposal = json.loads(_legacy(
                old, capture, study, "decide", "propose", decision, "--value-json",
                json.dumps(value), "--restatement", label, "--rationale", "Scripted alternative.",
                "--request-id", f"parity-{branch}", "--expected-revision",
                str(payload["summary"]["revision"]),
            ))
            read = json.loads(_legacy(old, capture, study, "status", "--summary"))
            if read["next_action"]["kind"] != "await_user_words":
                raise RuntimeError(f"{state}.{branch} did not reach an adoption pause")
            _keep(out, f"{state}.{branch}", {"proposal": proposal, "summary": read},
                  ((study, "STUDY"), *scrub))
    state = "02-prediction_time-pause"
    study = branches / f"{state}.refusal"
    shutil.copytree(capture / "snaps" / state, study)
    summary = json.loads(_legacy(old, capture, study, "status", "--summary"))
    refused = subprocess.run(
        [old / "framework/.venv/bin/hypotrail", "decide", "confirm", "missing-proposal",
         "--user-words", "I adopt this decision", "--channel", "choice",
         "--request-id", "parity-refusal", "--expected-revision", str(summary["revision"]),
         "--study", study],
        cwd=old, env=_env(old, capture), capture_output=True, text=True,
    )
    refusal = json.loads(refused.stdout)
    if not refused.returncode or refusal["ok"]:
        raise RuntimeError("The legacy confirmation did not refuse the missing proposal")
    after = json.loads(_legacy(old, capture, study, "status", "--summary"))
    if after["revision"] != summary["revision"]:
        raise RuntimeError("The refusal changed the Study revision")
    _keep(out, f"{state}.refusal", {"refusal": refusal, "summary": after},
          ((study, "STUDY"), (capture, "REPLAY"), (old, "OLD_HYPOTRAIL")))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-hypotrail", required=True, type=Path)
    parser.add_argument("--replay", required=True, type=Path)
    parser.add_argument("--scratch", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--change-observations", type=Path,
                        help="browser evidence from observe-change.js in the private English twin")
    args = parser.parse_args()
    old, bundle, scratch, out = (path.resolve() for path in
                                 (args.old_hypotrail, args.replay, args.scratch, args.out))
    if _run(["git", "rev-parse", "HEAD"], cwd=old).strip() != LEGACY_COMMIT:
        parser.error("The old checkout must be at the pinned legacy commit")
    scratch.mkdir(parents=True, exist_ok=True)
    french, english = scratch / "fr", scratch / "en"
    walk(old, bundle, french, "fr")
    verify_french_replay(old, bundle, french)
    walk(old, bundle, english, "en")
    if replay_signature(_log(english)) != replay_signature(_log(bundle)):
        raise RuntimeError("The English walk differs from the approved replay signature")
    write_fixtures(old, english, out)
    write_branches(old, english, out, args.change_observations)


if __name__ == "__main__":
    main()
