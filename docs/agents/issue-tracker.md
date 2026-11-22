# Issue tracker: GitHub

Issues and specs for this repo live as GitHub issues. Use the `gh` CLI for all operations.

## Conventions

- **Create an issue**: `gh issue create --title "..." --body "..."`. Use a heredoc for multi-line bodies.
- **Read an issue**: `gh issue view <number> --json number,title,body,labels,comments`.
- **List issues**: `gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'` with appropriate `--label` and `--state` filters.
- **Make an issue a sub-issue of a parent**: `gh issue create --parent <parent> ...`, or `gh issue edit <parent> --add-sub-issue <child>` afterwards (`gh` 2.94+). Older `gh`: `gh api --method POST repos/<owner>/<repo>/issues/<parent>/sub_issues -F sub_issue_id=<child-db-id>` (database id, as in **Blocking** below). Without sub-issues, put `Part of #<parent>` at the top of the child body.
- **Comment on an issue**: `gh issue comment <number> --body "..."`
- **Apply / remove labels**: `gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- **Close**: `gh issue close <number> --comment "..."`

The repo is `chadlis/hypotrail`. A cloud clone may point `origin` at an unrelated repository: never infer the repo from it, and pass `--repo chadlis/hypotrail` to `gh`.

## Pull requests as a triage surface

**PRs as a request surface: no.** _(Set to `yes` if this repo treats external PRs as feature requests; `/triage` reads this flag.)_

When set to `yes`, PRs run through the same labels and states as issues, using the `gh pr` equivalents:

- **Read a PR**: `gh pr view <number> --comments` and `gh pr diff <number>` for the diff.
- **List external PRs for triage**: `gh api --paginate 'repos/{owner}/{repo}/pulls?state=open' --jq '.[] | select(.author_association | IN("OWNER","MEMBER","COLLABORATOR") | not) | {number, title, author: .user.login, author_association, labels: [.labels[].name]}'`.
- **Comment / label / close**: `gh pr comment`, `gh pr edit --add-label`/`--remove-label`, `gh pr close`.

GitHub shares one number space across issues and PRs, so a bare `#42` may be either: resolve with `gh pr view 42` and fall back to `gh issue view 42`.

## When a skill says "publish to the issue tracker"

Create a GitHub issue.

## When a skill says "fetch the relevant ticket"

Read it as in **Read an issue** above.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a single issue with **child** issues as tickets.

- **Map**: a single issue labelled `wayfinder:map`, holding the Notes / Decisions-so-far / Fog body. `gh issue create --label wayfinder:map`.
- **Child ticket**: an issue linked to the map as a GitHub sub-issue (see **Make an issue a sub-issue of a parent**). Where sub-issues aren't enabled, add the child to a task list in the map body and put `Part of #<map>` at the top of the child body. Labels: `wayfinder:<type>` (`research`/`prototype`/`grilling`/`task`). Once claimed, the ticket is assigned to the driving dev.
- **Blocking**: GitHub's **native issue dependencies**, the canonical, UI-visible representation. Add an edge with `gh api --method POST repos/<owner>/<repo>/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>`, where `<blocker-db-id>` is the blocker's numeric **database id** (`gh api repos/<owner>/<repo>/issues/<n> --jq .id`, _not_ the `#number` or `node_id`). GitHub reports `issue_dependencies_summary.blocked_by` (open blockers only, the live gate). Where dependencies aren't available, fall back to a `Blocked by: #<n>, #<n>` line at the top of the child body. A ticket is unblocked when every blocker is closed.
- **Frontier query**: list the map's open children (`gh issue list --state open`, scoped to the map's sub-issues / task list), drop any with an open blocker (`issue_dependencies_summary.blocked_by > 0`, or an open issue in the `Blocked by` line) or an assignee; first in map order wins.
- **Claim**: `gh issue edit <n> --add-assignee @me`, the session's first write.
- **Resolve**: `gh issue comment <n> --body "<answer>"`, then `gh issue close <n>`, then append a context pointer (gist + link) to the map's Decisions-so-far.

## Cloud sessions

In Claude Code cloud sessions GraphQL is refused: `gh issue view` fails with « GitHub GraphQL is not available ». `gh api` on REST routes (`repos/chadlis/hypotrail/…`) works through the session's proxy, and so do the GitHub MCP tools.

**Changing part of a long body** (a `## Tightened` section, one line of a state comment): edit a local copy, so only the changed lines pass through your context. `issue_write` and `update_issue_comment` resend the whole body; keep them for short bodies and for state and labels.

```bash
S=<your scratchpad>
gh api repos/chadlis/hypotrail/issues/<n> --jq .body > "$S/b<n>.md"    # a comment: issues/comments/<id>
# change $S/b<n>.md with the Edit tool
gh api -X PATCH repos/chadlis/hypotrail/issues/<n> -F body=@"$S/b<n>.md" --jq .number
```

A tightening edits two texts: the body, where the replaced sentence leaves a pointer, and a new history comment that holds it struck. Post the comment first, so the pointer can name its ID.

If the PATCH is refused, use the MCP tool.

The MCP tools:

| Operation | Tool |
|---|---|
| Create / update / close an issue, apply labels | `issue_write` (`method: create` or `update`; `state: closed` with `state_reason`) |
| Read an issue, its comments, sub-issues, parent | `issue_read` with `method: get`, then `method: get_comments`: comments carry amendments that override the body |
| List issues | `list_issues` |
| Comment | `add_issue_comment` |
| Sub-issue | `issue_write` with `parent_issue_number`, or `sub_issue_write` |

These tools do not create labels: a label must already exist in the repository (create it in GitHub's UI), otherwise `issue_write` fails with "label not found". Native issue dependencies are not available
through these tools: use a `Blocked by: #<n>, #<n>` line at the top of the child body. A ticket is unblocked when every
listed blocker is closed.
