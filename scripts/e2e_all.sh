#!/usr/bin/env bash
# The manual proof runs each lane independently and reports only results and aggregate counts.
set -euo pipefail
umask 077

if [[ $# != 2 || "$1" == -* || ! -d "$1" || ! -w "$1" ]]; then
    echo "Usage: $0 SCRATCH_PARENT CACHED_UCI_WORKBOOK" >&2
    exit 2
fi
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
scratch=$(cd -- "$1" && mktemp -d "$PWD/hypotrail-e2e.XXXXXX")
twin=$2
export HYPOTRAIL_E2E_READS="$scratch/reads"
mkdir -p "$HYPOTRAIL_E2E_READS"
unset HYPOTRAIL_LESSON_PACKS HYPOTRAIL_ANTHROPIC_API_KEY ANTHROPIC_API_KEY OPENAI_API_KEY
unset PYTEST_ADDOPTS HYPOTRAIL_CHECKOUT AGENTKIT_REQUIRE_TWIN MLKIT_E2E
export GIT_TERMINAL_PROMPT=0 NPM_CONFIG_AUDIT=false NPM_CONFIG_FUND=false
export XDG_DATA_HOME="$scratch/data" XDG_STATE_HOME="$scratch/state" XDG_CONFIG_HOME="$scratch/config"
export NPM_CONFIG_CACHE="${NPM_CONFIG_CACHE:-$scratch/npm-cache}" UV_CACHE_DIR="${UV_CACHE_DIR:-$scratch/uv-cache}"
mkdir -p "$XDG_DATA_HOME" "$XDG_STATE_HOME" "$XDG_CONFIG_HOME"

passed=0 failures=0 skipped=0
declare -A ready
pass() { printf 'PASS %s\n' "$1"; passed=$((passed+1)); }
fail() { printf 'FAIL %s\n' "$1"; failures=$((failures+1)); }
skip() { printf 'SKIPPED %s\n' "$1"; skipped=$((skipped+1)); }

# Never echo tool output. A failed assertion could show protected test fixture text.
step() {
    local label=$1 status
    shift
    if ("$@") >/dev/null 2>&1; then
        pass "$label"
        return 0
    else
        status=$?
        fail "$label (exit $status)"
        return 1
    fi
}

clone_main() {
    git clone --branch main "https://github.com/chadlis/$1.git" "$scratch/$1"
}

for repo in hypotrail hypotrail-lessons mlkit agentkit; do
    if step "C1 clone $repo" clone_main "$repo"; then
        ready["$repo"]=1
        printf 'HEAD %s %s\n' "$repo" "$(git -C "$scratch/$repo" rev-parse HEAD)"
    fi
done

product="$scratch/hypotrail"
lessons="$scratch/hypotrail-lessons"
mlkit="$scratch/mlkit"
agentkit="$scratch/agentkit"

# Local copies share the already cloned object's history. A missing commit fails here
# rather than fetching another ref or running against a different pin.
checkout_pin() {
    local repo=$1 pin
    [[ ${ready[hypotrail]:-0} == 1 && ${ready[$repo]:-0} == 1 ]] || return 1
    pin=$(<"$scratch/$repo/hypotrail.pin") || return 1
    [[ "$pin" =~ ^[0-9a-f]{40}$ ]] || return 1
    git -C "$product" cat-file -e "$pin^{commit}" || return 1
    git clone --shared --no-checkout --local "$product" "$scratch/$repo/hypotrail" || return 1
    git -C "$scratch/$repo/hypotrail" -c advice.detachedHead=false checkout --detach "$pin"
}

report_pin() {
    local repo=$1
    if step "C1 explicit Hypotrail pin for $repo" checkout_pin "$repo"; then
        ready["$repo-pin"]=1
        printf 'PIN %s %s\n' "$repo" "$(<"$scratch/$repo/hypotrail.pin")"
    fi
}

for repo in hypotrail-lessons mlkit; do
    report_pin "$repo"
done

at() {
    local directory=$1
    shift
    cd "$directory" && "$@"
}

product_setup() {
    at "$product" uv sync --frozen --all-extras --all-groups || return 1
    at "$product/clients/vscode" npm ci || return 1
    at "$product/clients/vscode" npm run compile
}

python_suite() {
    at "$product" env -u HYPOTRAIL_LESSON_PACKS uv run --frozen python -m pytest \
        -n 8 --dist loadfile -q -p no:cacheprovider -rE
}

actual_node_passes() {
    "$@" 2>&1 | awk '
        /^(#|ℹ)[[:space:]]+pass[[:space:]]+[1-9][0-9]*[[:space:]]*$/ { passed=1 }
        /^(#|ℹ)[[:space:]]+skip(ped)?[[:space:]]+0[[:space:]]*$/ { no_skips=1 }
        END { exit !(passed && no_skips) }
    '
}

client_suite() {
    local chrome="${HYPOTRAIL_CHROME:-/usr/bin/google-chrome}"
    [[ -x "$chrome" ]] || return 1
    actual_node_passes at "$product/clients/vscode" timeout 5m npm test
}

if step "C1 install and compile Hypotrail" product_setup; then
    # A retry runs immediately after the other setup work, without another active suite.
    if ! step "C2 Hypotrail suite, first run" python_suite; then
        step "C2 Hypotrail suite, isolated retry" python_suite || true
    fi
    step "C2 VS Code client suite (five-minute limit)" client_suite || true
    ready[product-build]=1
fi

kit_suite() {
    at "$1" uv sync --locked || return 1
    at "$1" uv run --locked pytest
}

step "C2 MLkit CI suite" kit_suite "$mlkit" || true
step "C2 Agentkit CI suite" kit_suite "$agentkit" || true
report_pin agentkit

# Test on the workflow's cache-hit path. The file must already exist before
# mlkit fetch is called, so that command only checks the workbook digest.
mlkit_prepare() {
    [[ ${ready[mlkit-pin]:-0} == 1 ]] || return 1
    local member
    member=$(python3 - "$mlkit/data.lock.json" <<'PY'
import json
import re
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    source, = json.load(handle)["sources"]
member = source["local_path"]
if not re.fullmatch(r"[a-zA-Z0-9_.-]+\.xlsx", member):
    raise SystemExit("Expected one local workbook basename")
print(member)
PY
    ) || return 1
    mkdir -p "$mlkit/data" || return 1
    cp -- "$twin" "$mlkit/data/$member" || return 1
    at "$mlkit" uv run --locked mlkit fetch || return 1
    at "$mlkit" uv pip install ./hypotrail
}

mlkit_gate_state() {
    local status=0 state
    state=$(at "$mlkit" uv run --locked --no-sync mlkit gate --json) || status=$?
    python3 -c '
import json
import re
import sys

status = int(sys.argv[1])
reply = json.load(sys.stdin)
if not isinstance(reply, dict) or type(reply.get("exit")) is not int or reply["exit"] != status:
    raise SystemExit(1)
if not (
    (status == 0 and reply.get("ok") is True and reply.get("code") == "OK")
    or (status == 7 and reply.get("ok") is False and reply.get("code") == "GATE_BLOCKED")
):
    raise SystemExit(1)
details = reply.get("details")
if not isinstance(details, dict) or "phase" not in details:
    raise SystemExit(1)
opened, phase = details.get("open"), details["phase"]
if not isinstance(opened, list) or not all(isinstance(command, str) for command in opened):
    raise SystemExit(1)
if status == 0 and phase is not None:
    raise SystemExit(1)
if status == 7 and not (isinstance(phase, str) and re.fullmatch(r"[a-z_]+", phase)):
    raise SystemExit(1)
if {"run", "export"} <= set(opened):
    print("open")
elif status == 7:
    print("blocked:" + phase)
else:
    raise SystemExit(1)
' "$status" <<<"$state"
}

mlkit_e2e() {
    local gate=$1
    at "$mlkit" env MLKIT_E2E=1 HYPOTRAIL_CHECKOUT=hypotrail \
        uv run --locked --no-sync pytest -q tests/e2e -rsxX 2>&1 | python3 -c '
import re
import sys

lines = [line for line in sys.stdin.read().splitlines() if line.strip()]
if not lines:
    raise SystemExit(1)
summary = re.fullmatch(r"([1-9][0-9]*) passed(?:, ([0-9]+) skipped)? in [0-9.]+s(?: \([^\n]+\))?", lines[-1].strip(" ="))
if summary is None:
    raise SystemExit(1)
skipped = int(summary[2] or "0")
if sys.argv[1] == "open":
    raise SystemExit(skipped != 0)
phase = re.escape(sys.argv[1].removeprefix("blocked:"))
gated = [
    int(match[1]) for line in lines
    if (match := re.match(r"^SKIPPED \[([0-9]+)\] .*: blocked: the gate is closed \(phase " + phase + r"\b", line))
]
raise SystemExit(not skipped or sum(gated) != skipped)
' "$gate"
}

agentkit_e2e() {
    [[ ${ready[agentkit-pin]:-0} == 1 ]] || return 1
    at "$agentkit" uv pip install ./hypotrail || return 1
    at "$agentkit" env HYPOTRAIL_CHECKOUT=hypotrail AGENTKIT_REQUIRE_TWIN=1 \
        uv run --locked --no-sync pytest "$@"
}

check_packs() {
    [[ ${ready[hypotrail-lessons-pin]:-0} == 1 ]] || return 1
    local pinned="$lessons/hypotrail" pack
    at "$pinned" uv sync --frozen --all-extras --all-groups || return 1
    at "$pinned" uv run --frozen python -m hypotrail lesson check \
        tests/fixtures/lesson_packs/minimal --kept clients/vscode/test/cli || return 1
    for pack in "$lessons"/packs/*; do
        [[ -d "$pack" ]] || return 1
        at "$pinned" uv run --frozen python -m hypotrail lesson check "$pack" \
            --kept clients/vscode/test/cli || return 1
    done
}

if [[ ! -f "$twin" || ! -r "$twin" ]]; then
    fail "C2 MLkit pinned workflow: readable public twin cache required"
elif step "C2 prepare the pinned MLkit workflow on the public twin" mlkit_prepare; then
    ready[mlkit-ready]=1
    if phase=$(mlkit_gate_state 2>/dev/null); then
        if [[ $phase == open ]]; then
            if step "C2 MLkit pinned workflow on the local public twin" mlkit_e2e "$phase"; then
                ready[mlkit-e2e]=1
            fi
        elif step "C2 MLkit pinned workflow checks independent of the owner gate" mlkit_e2e "$phase"; then
            skip "C2 MLkit pinned run and export tests: owner ${phase#blocked:} gate"
        fi
    else
        fail "C2 MLkit run and export gate could not be verified"
    fi
fi
step "C2 Agentkit pinned workflow" agentkit_e2e || true
step "C2 lesson-pack pinned fixture and published packs" check_packs || true

proof_pack() {
    python3 - "$lessons/packs" <<'PY'
import json
import sys
from pathlib import Path

matches = [
    manifest.parent
    for manifest in Path(sys.argv[1]).glob("*/pack.json")
    if "temporal_regression" in json.loads(manifest.read_bytes())["tracks"]
]
if len(matches) != 1:
    raise SystemExit("The proof requires exactly one temporal-regression pack")
print(matches[0])
PY
}

journey() {
    [[ ${ready[product-build]:-0} == 1 && ${ready[hypotrail-lessons]:-0} == 1 ]] || return 1
    local pack
    pack=$(proof_pack) || return 1
    # Copy the harness only, so the test runs under the cloned Hypotrail conftest
    # and uses that clone's helpers and offline guard.
    cp -- "$here/e2e_journey.py" "$product/tests/manual_e2e_journey.py" || return 1
    at "$product" env HYPOTRAIL_LESSON_PACKS="$pack" \
        uv run --frozen python -m pytest -q -p no:cacheprovider --tb=no \
        "tests/manual_e2e_journey.py::$1"
}

step "C3 Bike dev journey, immutable lesson reads and public-check isolation" journey test_bike_journey || true
step "C3 literal protected-word check on every Bike lesson read" journey test_literal_wall || true
step "C4 Chinook scripted journey and incompatible-pack behaviour" journey test_chinook_journey || true
if step "C5 Study panel in Chromium with the actual journey reads" \
    at "$product/clients/vscode" node --require ./out/test/vscode-stub-hook.js --test "$here/e2e_panel.cjs"; then
    printf 'SHEET %s\n' "$HYPOTRAIL_E2E_READS/panel-sheet/index.html"
fi
step "C6 model-free Guide contract and dev tools" \
    at "$product" uv run --frozen python -m pytest -q tests/test_guide_agent.py || true
step "C6 Guide pack read and declared held-out boundary" journey test_guide_pack_tool || true
skip "C6 actual Guide reply at the held-out station: owner D-235/G6 model gate"

# Pytest exits zero for a suite of skipped or expected-failing tests. Require
# actual passes for the proof's focused tests. Only the aggregate terminal
# summary is inspected and no captured test output is copied to the report.
actual_passes() {
    "$@" 2>&1 | awk '
        /^[[:space:]=]*[0-9]+ passed([ ,=]|$)/ && !/(failed|error|skipped|xfailed|xpassed)/ { passed=1 }
        END { exit !passed }
    '
}

gate=invalid
if [[ ${ready[mlkit-ready]:-0} == 1 ]]; then
    gate=$(mlkit_gate_state 2>/dev/null) || gate=invalid
fi
if [[ $gate == blocked:* ]]; then
    skip "C7 MLkit run and Hypotrail ranking round trip: owner ${gate#blocked:} gate"
elif [[ $gate == open && ${ready[mlkit-e2e]:-0} == 1 ]]; then
    step "C7 MLkit build, reference run, export, import, Assessment and Comparison" \
        actual_passes at "$mlkit" env MLKIT_E2E=1 HYPOTRAIL_CHECKOUT=hypotrail \
            uv run --locked --no-sync pytest -q tests/e2e/test_dev_end_to_end.py -rxX || true
else
    fail "C7 MLkit needs a passed pinned workflow and a verified run and export gate"
fi
step "C7 Agentkit dev loop, Hypotrail import and Assessment, synthetic evaluator and aggregate boundary" \
    actual_passes agentkit_e2e -q tests/e2e/test_dev_end_to_end.py tests/e2e/test_evaluate.py tests/e2e/test_conduct.py || true
step "C8 Hypotrail protected ranking guard, lesson and ordinary CLI refusals" \
    actual_passes at "$product" uv run --frozen python -m pytest -q -p no:cacheprovider \
        tests/test_ranking_evaluator.py tests/test_ranking_read_surfaces.py || true
step "C8 client panel and chat tool refusals" \
    actual_node_passes at "$product/clients/vscode" node --require ./out/test/vscode-stub-hook.js --test \
        --test-name-pattern='protected ranking refusal|request for the held_out Partition|without forwarding the evaluator' \
        out/test/panel-read.test.js out/test/tools-read.test.js out/test/tools-run.test.js || true
step "C9 MLkit synthetic protected evaluator, proxy verdict, aggregate output and exits 8 and 9" \
    actual_passes at "$mlkit" env -u GITHUB_ACTIONS -u GITHUB_TOKEN -u GH_TOKEN \
        MLKIT_E2E=1 HYPOTRAIL_CHECKOUT=hypotrail uv run --locked --no-sync pytest -q \
        tests/e2e/test_held_out_rehearsal.py || true

printf 'SUMMARY %d passed, %d failed, %d skipped\n' "$passed" "$failures" "$skipped"
printf 'ARTIFACTS %s\n' "$scratch"
[[ $failures == 0 ]]
