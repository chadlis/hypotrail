#!/usr/bin/env bash
# Usage: capture.sh <capture-dir> <step> <command...>
# Runs the command from the current directory. As it runs, writes <step>.argv, .start, .out, .err, .exit and .end
# into <capture-dir>, then prints their sha256 for the state comment. Exits with the command's own status.
set -u
dir=$1 step=$2
shift 2
mkdir -p "$dir"
{ printf '%q ' "$@"; echo; } > "$dir/$step.argv"
date -u +%FT%TZ > "$dir/$step.start"
"$@" > "$dir/$step.out" 2> "$dir/$step.err"
status=$?
echo "$status" > "$dir/$step.exit"
date -u +%FT%TZ > "$dir/$step.end"
sha256sum "$dir/$step.argv" "$dir/$step.start" "$dir/$step.out" "$dir/$step.err" "$dir/$step.exit" "$dir/$step.end"
exit "$status"
