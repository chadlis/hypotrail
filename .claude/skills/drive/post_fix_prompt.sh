#!/usr/bin/env bash
# Usage: post_fix_prompt.sh <slice issue> <slice label> <round> <prompt file> <worktree> [--out <file>]
#        post_fix_prompt.sh --compare <comment id> <file>
#
# Posts a fix prompt word for word as its own comment on the slice issue, before the builder starts, and prints the
# comment's ID. In order, it:
#   1. runs `premises.py <prompt file> <worktree>`, and stops on a non-zero exit;
#   2. runs `fix_prompt_check.py --strict <prompt file>`, and stops on a non-zero exit: a quotation that is not a whole
#      sentence or item of its source (text the prompt removes included), a prompt that names no finding ID, or one that
#      does not contain "This is a review fix";
#   3. builds the comment: the heading `## <slice label>, round <round>: fix prompt (to slice-builder), word for word`, the
#      prompt in a four-backtick fence, then the sheet each check printed;
#   4. posts it with `gh api repos/chadlis/hypotrail/issues/<slice issue>/comments -F body=@<built file>`, or, with
#      `--out <file>`, writes it to <file> and prints that path, for a session that refuses this post; it calls no `gh`.
# Nothing is posted or written while either check refuses the prompt; the refusal's report is printed, and the exit is the check's.
#
# `post_fix_prompt.sh --compare <comment id> <file>` reads the body of the comment once it is posted and compares it with the
# file `--out` wrote: exit 0 when they are the same, trailing line breaks aside; exit 1 with the difference printed otherwise.
set -euo pipefail

usage() {
  echo "usage: post_fix_prompt.sh <slice issue> <slice label> <round> <prompt file> <worktree> [--out <file>]" >&2
  echo "       post_fix_prompt.sh --compare <comment id> <file>" >&2
  exit 2
}
if [ "${1-}" = "--compare" ]; then
  [ "$#" -eq 3 ] || usage
  posted=$(gh api "repos/chadlis/hypotrail/issues/comments/$2" --jq .body)
  if ! diff <(printf '%s\n' "$posted") <(printf '%s\n' "$(cat "$3")"); then
    echo "post_fix_prompt: comment $2 differs from $3" >&2
    exit 1
  fi
  exit 0
fi
out=
if [ "$#" -eq 7 ] && [ "$6" = "--out" ]; then
  out=$7
elif [ "$#" -ne 5 ]; then
  usage
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

if [ -n "$out" ]; then
  cp "$scratch/comment.md" "$out"
  echo "$out"
else
  gh api "repos/chadlis/hypotrail/issues/$issue/comments" -F "body=@$scratch/comment.md" --jq .id
fi
