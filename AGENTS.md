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

### PR & protected-`main` workflow

- `main` is branch-protected (`GH006`) and requires the `CI / Check & Test` GitHub Actions status check on pull requests.
- Never run `git push origin main`. Always push the worktree branch, create a PR (`gh pr create`), wait for checks (`gh pr checks <N> --watch`), squash-merge (`gh pr merge <N> --squash --delete-branch`), pull `main`, and remove the worktree.
- Run a two-axis `/code-review` (Standards + Spec) against each issue PR diff before moving to the next issue.

### Architecture & security invariants (ADR 0001 & ADR 0002)

- **Presenter-Identity-Only Execution (ADR 0002)**: Never pass `--service-account` to Dataproc Serverless batches (`bin/preflight`, `bin/*`), and never declare `google_project`, `google_folder`, `google_billing_*`, `google_org_policy`, `google_service_account`, or `google_*_iam_*` resources in `infra/*.tf`.
- **No Compute Metadata Fallback**: Any tool or wrapper invoking `mcp_proxy_bundle.cjs` must verify user OAuth ADC (`type: authorized_user` plus live `gcloud auth application-default print-access-token`) and export `BILLING_QUOTA_PROJECT_ID` and `GOOGLE_APPLICATION_CREDENTIALS`.
- **Withheld Evaluation Data (ADR 0001)**: Never expose live `answer_key.json` or `reveal.csv` paths to the demo workspace or agent investigation prompts; committed copies are permitted only under `fixtures/mock_withheld/` for automated tests.

### Verification guardrail

Run `uvx ruff check . && uvx ruff format --check . && make test` (or `python3 -m unittest discover -s tests`) to execute formatting, linting, glossary, syntax, and test suites.
