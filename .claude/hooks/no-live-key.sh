#!/usr/bin/env bash
# PreToolUse hook on Bash (D-048 on chadlis/hypotrail#75).
# Prefixes every command with an unset of the provider key, so that no command run
# by hand or from a scratch script can reach the provider. The one exemption: a single
# simple command whose first word is the drive's capture.sh, the only path a paid run takes.
# Fails closed: any error exits 2, which blocks the command.
set -u
trap 'echo "no-live-key hook failed; command blocked" >&2; exit 2' ERR
command -v jq >/dev/null || { echo "no-live-key hook: jq missing; command blocked" >&2; exit 2; }
input=$(cat)
tool_input=$(jq -ce '.tool_input | objects' <<<"$input") || { echo "no-live-key hook: no tool_input; command blocked" >&2; exit 2; }
cmd=$(jq -re '.command | strings' <<<"$tool_input") || { echo "no-live-key hook: no command; command blocked" >&2; exit 2; }

first=${cmd%%[[:space:]]*}
case $cmd in
  *';'*|*'&'*|*'|'*|*$'\n'*|*'$('*|*'`'*) simple=no ;;
  *) simple=yes ;;
esac
if [[ $simple == yes && $first =~ ^([^[:space:]]*/)?\.claude/skills/drive/capture\.sh$ ]]; then
  exit 0
fi
jq -c --arg cmd "unset HYPOTRAIL_ANTHROPIC_API_KEY"$'\n'"$cmd" \
  '{hookSpecificOutput: {hookEventName: "PreToolUse", updatedInput: (.command = $cmd)}}' <<<"$tool_input"
