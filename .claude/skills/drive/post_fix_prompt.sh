#!/usr/bin/env bash
# Usage: post_fix_prompt.sh <slice issue> <slice label> <round> <prompt file> <worktree>
#
# Posts a fix prompt word for word as its own comment on the slice issue, before the builder starts, and prints the
# comment's ID. In order, it:
#   1. runs `premises.py <prompt file> <worktree>`, and stops on a non-zero exit;
#   2. runs `fix_prompt_check.py --strict <prompt file>`, and stops on a non-zero exit: a quotation that is not a whole
#      sentence or item of its source (text the prompt removes included), or a prompt that names no finding ID;
#   3. builds the comment: the heading `## <slice label>, round <round>: fix prompt (to slice-builder), word for word`, the
#      prompt in a four-backtick fence, then the sheet each check printed;
#   4. posts it with `gh api repos/chadlis/hypotrail/issues/<slice issue>/comments -F body=@<built file>`.
# Nothing is posted while either check refuses the prompt; the refusal's report is printed, and the exit is the check's.
set -euo pipefail

if [ "$#" -ne 5 ]; then
  echo "usage: post_fix_prompt.sh <slice issue> <slice label> <round> <prompt file> <worktree>" >&2
  exit 2
fi
issue=$1 label=$2 round=$3 prompt=$4 worktree=$5
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT

set +e
python3 -I "$here/premises.py" "$prompt" "$worktree" >"$scratch/premises" 2>&1
status=$?
set -e
if [ "$status" -ne 0 ]; then
  cat "$scratch/premises" >&2
  echo "post_fix_prompt: premises.py exited $status; nothing is posted" >&2
  exit "$status"
fi

set +e
CLAUDE_PROJECT_DIR=$worktree python3 -I "$here/fix_prompt_check.py" --strict "$prompt" >"$scratch/check" 2>&1
status=$?
set -e
if [ "$status" -ne 0 ]; then
  cat "$scratch/check"
  echo "post_fix_prompt: fix_prompt_check.py --strict exited $status; nothing is posted" >&2
  exit "$status"
fi

{
  printf '## %s, round %s: fix prompt (to slice-builder), word for word\n\n````\n' "$label" "$round"
  cat "$prompt"
  if [ -n "$(tail -c 1 "$prompt")" ]; then echo; fi
  printf '````\n\n### `premises.py`\n\n'
  if [ -s "$scratch/premises" ]; then cat "$scratch/premises"; else echo "No premise line or claim: nothing to check."; fi
  printf '\n### `fix_prompt_check.py --strict`\n\n'
  cat "$scratch/check"
} >"$scratch/comment.md"

gh api "repos/chadlis/hypotrail/issues/$issue/comments" -F "body=@$scratch/comment.md" --jq .id
