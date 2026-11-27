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
unset PYTEST_ADDOPTS
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

for repo in hypotrail-lessons mlkit agentkit; do
    if step "C1 explicit Hypotrail pin for $repo" checkout_pin "$repo"; then
        ready["$repo-pin"]=1
        printf 'PIN %s %s\n' "$repo" "$(<"$scratch/$repo/hypotrail.pin")"
    fi
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

client_suite() {
    local chrome="${HYPOTRAIL_CHROME:-/usr/bin/google-chrome}"
    [[ -x "$chrome" ]] || return 1
    at "$product/clients/vscode" timeout 5m npm test 2>&1 | awk '
        /^(#|ℹ)[[:space:]]+pass[[:space:]]+[1-9][0-9]*[[:space:]]*$/ { passed=1 }
        /^(#|ℹ)[[:space:]]+skip(ped)?[[:space:]]+0[[:space:]]*$/ { no_skips=1 }
        END { exit !(passed && no_skips) }
    '
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

# Test on the workflow's cache-hit path. The file must already exist before
# mlkit fetch is called, so that command only checks the workbook digest.
mlkit_e2e() {
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
    at "$mlkit" uv pip install ./hypotrail || return 1
    at "$mlkit" env MLKIT_E2E=1 HYPOTRAIL_CHECKOUT=hypotrail \
        uv run --locked --no-sync pytest tests/e2e -rxX
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
elif step "C2 MLkit pinned workflow on the local public twin" mlkit_e2e; then
    ready[mlkit-e2e]=1
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
step "C6 scripted Guide turns and held-out boundary" journey test_scripted_guide || true

# Pytest exits zero for a suite of skipped or expected-failing tests. Require
# actual passes for the explicit C7 round trips. Only the aggregate terminal
# summary is inspected and no captured test output is copied to the report.
actual_passes() {
    "$@" 2>&1 | awk '
        /^[[:space:]=]*[0-9]+ passed([ ,=]|$)/ && !/(failed|error|skipped|xfailed|xpassed)/ { passed=1 }
        END { exit !passed }
    '
}

gate=0
(at "$mlkit" uv run --locked --no-sync mlkit gate) >/dev/null 2>&1 || gate=$?
if [[ $gate == 7 ]]; then
    skip "C7 MLkit run and Hypotrail ranking round trip: owner framing gate (mlkit gate exit 7)"
elif [[ $gate == 0 && ${ready[mlkit-e2e]:-0} == 1 ]]; then
    step "C7 MLkit build, reference run, export, import, Assessment and Comparison" \
        actual_passes at "$mlkit" env MLKIT_E2E=1 HYPOTRAIL_CHECKOUT=hypotrail \
            uv run --locked --no-sync pytest -q tests/e2e/test_dev_end_to_end.py -rxX || true
else
    fail "C7 MLkit gate or prerequisite (gate exit $gate)"
fi
step "C7 Agentkit dev loop, Hypotrail import and Assessment, synthetic evaluator and aggregate boundary" \
    actual_passes agentkit_e2e -q tests/e2e/test_dev_end_to_end.py tests/e2e/test_evaluate.py tests/e2e/test_conduct.py || true

printf 'SUMMARY %d passed, %d failed, %d skipped\n' "$passed" "$failures" "$skipped"
printf 'ARTIFACTS %s\n' "$scratch"
[[ $failures == 0 ]]
