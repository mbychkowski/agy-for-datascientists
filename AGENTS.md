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

Make every change in its own worktree and land it through a PR; the main checkout only pulls `main`.

- **Issue work**: `.worktree/issue-<3-digit-id>` on branch `issue<3-digit-id>/<slug>` (e.g. `.worktree/issue-019`, `issue019/fix-preflight`).
- **Chores** (small config, docs, or dependency changes with no issue): `.worktree/chore-<slug>` on branch `chore/<slug>`; the PR body states the reason in place of `Closes #<n>`.
- Create it from fresh `main`: `git fetch origin && git worktree add -b <branch> .worktree/<dir> origin/main`, then run every command inside that directory, starting with `npm ci` (installs the husky pre-commit hook for that worktree).

### PR & protected-`main` workflow

- `main` is branch-protected (`GH006`) and requires the `CI / Check & Test` GitHub Actions status check on pull requests.
- Never run `git push origin main`. Always push the worktree branch, create a PR (`gh pr create`), wait for checks (`gh pr checks <N> --watch`), squash-merge (`gh pr merge <N> --squash --delete-branch`), then pull `main` from the main checkout. `--delete-branch` usually removes the worktree too, so check `git worktree list` and run `git worktree remove` only if it is still listed; don't chain it before the pull.
- Run a two-axis `/code-review` (Standards + Spec) against each issue PR diff before moving to the next issue.

### Architecture & security invariants (ADR 0001 & ADR 0002)

- **Presenter-Identity-Only Execution (ADR 0002)**: Never pass `--service-account` to Dataproc Serverless batches (`bin/preflight`, `bin/*`), and never declare `google_project`, `google_folder`, `google_billing_*`, `google_org_policy`, `google_service_account`, or `google_*_iam_*` resources in `infra/*.tf`.
- **No Compute Metadata Fallback**: Any tool or wrapper invoking `mcp_proxy_bundle.cjs` must verify user OAuth ADC (`type: authorized_user` plus live `gcloud auth application-default print-access-token`) and export `BILLING_QUOTA_PROJECT_ID` and `GOOGLE_APPLICATION_CREDENTIALS`.
- **Withheld Evaluation Data (ADR 0001)**: Never expose live `answer_key.json` or `reveal.csv` paths to the demo workspace or agent investigation prompts; committed copies are permitted only under `fixtures/mock_withheld/` for automated tests.

### Verification guardrail

Every commit runs the full guardrail (`.husky/pre-commit`, mirrored by CI): ruff, glossary, tests, shellcheck and Terraform checks, about 3 minutes. Run single test files while iterating; for docs-only changes run `make check-docs` instead. Commit once per finished step and wait for the commit to finish before staging more changes.
