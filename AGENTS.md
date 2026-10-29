# Agent Instructions

## Agent skills

### Issue tracker

Issues and specs are tracked via GitHub Issues. See `docs/agents/issue-tracker.md`.

### Triage labels

Canonical triage label vocabulary. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout (`GLOSSARY.md` and `docs/adr/` at the repo root). See `docs/agents/domain.md`.

## Workspace conventions

### Worktree execution

Worktrees follow the path convention `.worktree/issue-<3-digit-id>` (e.g. `.worktree/issue-019`) on branch `issue<3-digit-id>/<slug>`. Always execute commands inside that directory (e.g. `cd .worktree/issue-019 && ...`).

### Verification guardrail

Run `make test` (or `python3 -m unittest discover -s tests`) to execute syntax checks and test suites.

