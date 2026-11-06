# Coding Standards

Documented standards for Command Center scripts, tooling, and tests.

## 1. CLI Scripts (`bin/*`)

- **Strict Execution**: Scripts must begin with `#!/usr/bin/env bash` and `set -uo pipefail` (or `set -euo pipefail`).
- **Symlink Portability**: Resolve real script directory through any symlinks before deriving `REPO_ROOT` (do not rely on `$PWD` or fragile relative paths).
- **Executable Bit**: All top-level scripts in `bin/` must have executable permissions (`chmod +x`). Sourced shell libraries in `bin/lib/` are exempt and must not be executable (`chmod -x`).
- **Pinning Module**: New `bin/*` scripts must source `bin/lib/pinning.sh` (`# shellcheck source=lib/pinning.sh`) and use the **Pinning** module (`pinned_load_env`, `pinned_require_project_region`, `pinned_require_cli`, `pinned_require_staging_bucket`, `pinned_require_state_bucket`, `pinned_bq`, `pinned_label`, `pinned_has_demo_label`, `pinned_bq_json`, `pinned_storage`, `pinned_dataproc_submit`, `pinned_dataproc_describe`, `pinned_dataproc_delete`, `pinned_gcloud_profile`, `pinned_project_lifecycle_state`, `pinned_adc_token_ok`) rather than sourcing `demo.env`, repeating `your-` placeholder checks, parsing `bq` JSON output inline, or calling `bq`/`gcloud` directly. The guard test in `tests/test_pinning.py` enforces this for every `bin/*` script and has no allowlist. A line that only matches because it holds `bq`/`gcloud` command text as data (such as a hook probe payload) may carry `# pinning-guard: allow (<reason>)`, and the reason is required. Reviewers challenge every new marker in a diff and confirm the marked line only holds command text as data and never executes it. The marker never exempts a real `bq`/`gcloud` invocation, a source of the environment file, a placeholder check or an inline JSON parser. The same test also requires every `bin/*` script that calls `pinned_bq`, `pinned_label` or `pinned_bq_json` to call `pinned_require_cli bq`, and every script that calls `pinned_storage` or `pinned_dataproc_*` to call `pinned_require_cli gcloud`, so a missing CLI fails fast instead of mid-run. The header of `bin/lib/pinning.sh` lists the globals each public function reads and writes; update it when a function starts using another global.
- **Dataset Boundaries**: Repo code (`bin/*`, `bin/lib/*`, `sql/**`, `lib/**`, `jobs/**`, `.agents/plugins/ds-command-center/sidecars/**`) never writes the read-only `raw`/`ops` datasets and never references `checkpoint` (rules 3 and 4 of `.agents/plugins/ds-command-center/rules/AGENTS.md`). Scratch and probe tables go to `staging`. `tests/test_dataset_boundaries.py` enforces this. Its per-file allowlist holds only presenter-owned provisioning scripts, each with a one-line reason. A line that holds forbidden SQL or a `checkpoint` table name as data (such as a hook probe payload) may carry `# dataset-guard: allow (<reason>)` or the Pinning marker; reviewers challenge every new marker, and it never exempts a mutating `bq` invocation or a line that runs a query.
- **Shellcheck**: Every shell script in `bin/`, `bin/lib/`, `.agents/plugins/*/bin/` and `.husky/pre-commit` must pass `make lint-sh` (shellcheck `--severity=warning`, plus unresolved `source` SC1090/SC1091). Files are selected by bash or sh shebang (`.husky/pre-commit` is POSIX sh because husky runs it with `sh -e`); sourced `bin/lib/` files without one must start with `# shellcheck shell=bash`. Annotate dynamic sources with `# shellcheck source=lib/<name>.sh`. Fix findings; use a targeted `# shellcheck disable=SCxxxx` with a reason only for false positives.

## 2. Preflight Checks (`bin/preflight`)

- **Modularity**: Every check is a small, self-contained function dispatched through `run_check "<Title>" <function_name>` (or `run_warn_check` for non-fatal drift checks).
- **Unconditional Reporting**: Never skip checks silently when prerequisite configuration contains placeholders or invalid values; fail the check explicitly with an actionable remediation command.
- **CLI Profile Unshadowing**: When checking active `gcloud` configuration properties, read them through `pinned_gcloud_profile <section/property>`, which unsets the overriding `CLOUDSDK_*` environment variables that `demo.env` (or the presenter's shell) may export, to verify the real underlying CLI profile.
- **Fail Fast & Non-Zero**: The runner must exit with a non-zero exit code if any required check fails.

## 3. Testing (`tests/*`)

- **Framework**: Use Python standard library `unittest` (`python3 -m unittest discover -s tests`) to avoid external test runner dependencies.
- **Seams**: Test external observed behavior (stdout, exit codes, export attributes, JSON-RPC messages) at pre-agreed seams rather than internal script implementation details.
- **Evidence Board dependencies**: The Evidence Board backend and event tests (`tests/test_evidence_board_backend.py`, `tests/test_evidence_board_events.py`) are the one exception to standard-library-only tests: they need the packages in `.agents/plugins/ds-command-center/sidecars/evidence-board/requirements.txt` (FastAPI, Uvicorn, httpx, google-cloud-bigquery), which CI installs before `make test`. Keep them out of every other test module.
- **Fixtures**: Extract shared mock setups (such as mock CLI binaries, temporary ADC credentials, and `demo.env` builders) into `tests/helpers.py`.
- **Subprocess Cleanup**: Always wrap `subprocess.Popen` in a `with` context manager and explicitly close `stdin`/`stdout`/`stderr` pipes so Python 3.14 never emits `ResourceWarning`.

## 4. Python & Data Generation (`lib/*`, `bin/*.py`)

- **Formatting & Linting**: All Python files must pass `uvx ruff check .` and `uvx ruff format --check .`.
- **Cross-Process Determinism**: Never use Python's built-in `hash()` inside seeded RNG calculations (because `PYTHONHASHSEED` randomizes hashes across processes). Use deterministic ordinal folds or `hashlib.sha256`.

## 5. Terraform (`infra/*.tf`)

- **Validate & Format**: `infra/` must pass `make lint-tf` (`terraform init -backend=false -lockfile=readonly`, `validate`, `fmt -check -recursive`) against the committed `infra/.terraform.lock.hcl`.
