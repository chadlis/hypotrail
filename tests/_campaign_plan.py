"""The plan of the Chinook `dev` Campaign (#235) read as a test reads it: its lines, which of them run, and their placeholders filled.

`docs/handbook/traces/campaign-chinook-dev/plan.json` holds each line as an argv list with named placeholders, and names for each
placeholder the earlier step it is read from and how. `Filler` keeps what each step printed and fills a line from it. Which optional
line runs (a rerun, one of the two Decision lines) is decided here by the plan's rules, from the Study and the outputs: the rehearsal
runs the lines this module selects, and the drive runs the same lines through `capture.sh`.
"""

import json
import re
from pathlib import Path

PLAN_PATH = Path("docs/handbook/traces/campaign-chinook-dev/plan.json")
LAUNCHER = ["uv", "run", "python", "-m", "hypotrail"]
PLACEHOLDER = re.compile(r"<[A-Z_]+>")
# the B2 sentence of D-146 on chadlis/hypotrail#75: "an Episode `missing`, or `failed` with a reason other than `turn_limit`, `token_limit` or `cost_limit`"
NOT_TECHNICAL = ("turn_limit", "token_limit", "cost_limit")
SIDES = ("plain", "verify")


def read_plan(root: Path) -> dict:
    return json.loads((Path(root) / PLAN_PATH).read_text(encoding="utf-8"))


def line_of(plan: dict, step: str) -> list:
    (line,) = [entry["argv"] for entry in plan["lines"] if entry["step"] == step]
    return list(line)


def technical_failures(observations_file: Path) -> list:
    """(case_id, repeat, status, reason) of each Episode of an Attempt that is a technical failure, read from its execution statuses."""
    found = []
    for text in Path(observations_file).read_text(encoding="utf-8").splitlines():
        if not text.strip():
            continue
        episode = json.loads(text)
        if episode["status"] == "missing" or (episode["status"] == "failed" and episode["reason"] not in NOT_TECHNICAL):
            found.append((episode["case_id"], episode["repeat"], episode["status"], episode["reason"]))
    return found


def rule_option(delta: float) -> str:
    """The option the plan's rule gives: `plain` is the Control, `verify` the Candidate; a tie keeps `plain`."""
    return "Keep the Candidate" if delta > 0 else "Keep the Control"


def unscored_episodes(matrix: dict) -> str:
    """The Episodes of a Comparison's matrix whose `contract_success` is not scored, as the plan writes them, `plain` first."""
    shown = []
    for role, side in (("control", "plain"), ("candidate", "verify")):
        for case in matrix[role]["cases"]:
            for episode in case["episodes"]:
                cell = episode["criteria"]["contract_success"]
                if cell["state"] != "scored":
                    shown.append(f"{side} {case['case_id']} repeat {episode['repeat']} ({cell['reason']})")
    return ", ".join(shown)


class Filler:
    """What each step printed, and the plan's placeholders filled from it."""

    def __init__(self, plan: dict, root: Path):
        self.plan = plan
        self.root = Path(root)  # the working directory the lines run from
        self.outputs = {}  # step -> stdout

    def ran(self, step: str, stdout: str) -> None:
        self.outputs[step] = stdout

    def value(self, placeholder: str) -> str:
        source = self.plan["placeholders"][placeholder]
        step = next(s for s in source["steps"] if s in self.outputs)  # the first of the named steps that ran
        out = self.outputs[step]
        if placeholder == "<RULE_OPTION>":
            return rule_option(float(re.search(source["pattern"], out, re.M).group(1)))
        if placeholder == "<UNSCORED_EPISODES>":
            path = source["read"].replace("<COMPARISON_ID>", self.value("<COMPARISON_ID>"))
            return unscored_episodes(json.loads((self.root / path).read_text(encoding="utf-8")))
        if "key" in source:
            return str(json.loads(out)[source["key"]])
        return re.search(source["pattern"], out, re.M).group(1)

    def fill(self, step: str) -> list:
        filled = []
        for word in line_of(self.plan, step):
            for placeholder in PLACEHOLDER.findall(word):
                word = word.replace(placeholder, self.value(placeholder))
            filled.append(word)
        return filled

    def delta_is_null(self) -> bool:
        return "no value (coverage_incomplete)" in self.outputs["compare"]


def spend_of(run_record: dict, bound: float) -> float:
    """What one paid invocation cost: its Episodes' recorded cost; an Attempt with an Episode of unknown cost counts at its ceiling."""
    episodes = run_record["episodes"]
    if any(episode.get("cost") is None for episode in episodes):
        return len(episodes) * bound
    return sum(episode["cost"] for episode in episodes)
