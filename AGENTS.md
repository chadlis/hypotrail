# Agent instructions

## Rules

- Everything committed to this repository is in English: code, comments, docs, file names, commit messages, issues and pull requests.
- Workload data keeps the language of its source; Workload data authored in this repository is English.
- `main` changes only through a pull request; agents may open and merge it.
- Live LLM calls are opt-in, bounded, and never run in CI.
- Reference answers are never shown to an evaluated agent, and a reference is never changed to improve a score.
  - Clarification, 2026-11-26: the first clause reads "the Reference of the Case being answered is never shown to the evaluated agent". A later turn may receive a scripted history built from earlier turns' Reference texts, declared by the Protocol (D-154 on chadlis/hypotrail#75, comment 7190632961, item 1).
- Leave the software license choice to the owner.
- Text you add or change quotes English with "…"; « » quotes French only. ADRs keep their recorded quotations (D-043 on chadlis/hypotrail#75).
- Keep `README.md` short and true: update it in the same pull request when a change affects what it says (purpose, status, install, usage, layout or where to look).

## Agent skills

### Issue tracker

GitHub Issues on chadlis/hypotrail (`gh` locally; `gh api` and GitHub MCP tools in cloud sessions). See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical roles, label strings unchanged. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.
