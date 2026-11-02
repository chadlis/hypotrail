# Agent instructions

## Rules

- Everything committed to this repository is in English: code, comments, docs, file names, commit messages, issues and pull requests.
- `main` changes only through a pull request; agents may open and merge it.
- Live LLM calls are opt-in, bounded, and never run in CI.
- Reference answers are never shown to an evaluated agent, and a reference is never changed to improve a score.
- Leave the software license choice to the owner.

## Agent skills

### Issue tracker

GitHub Issues on chadlis/hypotrail (`gh` locally, GitHub MCP tools in cloud sessions). See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical roles, label strings unchanged. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.
