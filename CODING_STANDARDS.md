# Coding Standards

Documented standards for Command Center scripts, tooling, and tests.

## 1. CLI Scripts (`bin/*`)

- **Strict Execution**: Scripts must begin with `#!/usr/bin/env bash` and `set -uo pipefail` (or `set -euo pipefail`).
- **Symlink Portability**: Resolve real script directory through any symlinks before deriving `REPO_ROOT` (do not rely on `$PWD` or fragile relative paths).
- **Executable Bit**: All top-level scripts in `bin/` must have executable permissions (`chmod +x`). Sourced shell libraries in `bin/lib/` are exempt and must not be executable (`chmod -x`).
- **Pinning Module**: New `bin/*` scripts must source `bin/lib/pinning.sh` (`# shellcheck source=lib/pinning.sh`) and use the **Pinning** module (`pinned_load_env`, `pinned_bq`, `pinned_label`, `pinned_bq_json`, `pinned_storage`, `pinned_dataproc_submit`, `pinned_dataproc_describe`, `pinned_dataproc_delete`) rather than sourcing `demo.env`, repeating `your-` placeholder checks, or calling `bq`/`gcloud` directly.
- **Shellcheck**: Every shell script in `bin/`, `bin/lib/`, `.agents/plugins/*/bin/` and `.husky/pre-commit` must pass `make lint-sh` (shellcheck `--severity=warning`, plus unresolved `source` SC1090/SC1091). Files are selected by bash or sh shebang (`.husky/pre-commit` is POSIX sh because husky runs it with `sh -e`); sourced `bin/lib/` files without one must start with `# shellcheck shell=bash`. Annotate dynamic sources with `# shellcheck source=lib/<name>.sh`. Fix findings; use a targeted `# shellcheck disable=SCxxxx` with a reason only for false positives.

## 2. Preflight Checks (`bin/preflight`)

- **Modularity**: Every check is a small, self-contained function dispatched through `run_check "<Title>" <function_name>` (or `run_warn_check` for non-fatal drift checks).
- **Unconditional Reporting**: Never skip checks silently when prerequisite configuration contains placeholders or invalid values; fail the check explicitly with an actionable remediation command.
- **CLI Profile Unshadowing**: When checking active `gcloud` configuration properties, unshadow overriding environment variables (e.g. `env -u CLOUDSDK_CORE_ACCOUNT -u CLOUDSDK_CORE_PROJECT gcloud config configurations list ...`) to verify the real underlying CLI profile.
- **Fail Fast & Non-Zero**: The runner must exit with a non-zero exit code if any required check fails.

## 3. Testing (`tests/*`)

- **Framework**: Use Python standard library `unittest` (`python3 -m unittest discover -s tests`) to avoid external test runner dependencies.
- **Seams**: Test external observed behavior (stdout, exit codes, export attributes, JSON-RPC messages) at pre-agreed seams rather than internal script implementation details.
- **Fixtures**: Extract shared mock setups (such as mock CLI binaries, temporary ADC credentials, and `demo.env` builders) into `tests/helpers.py`.
- **Subprocess Cleanup**: Always wrap `subprocess.Popen` in a `with` context manager and explicitly close `stdin`/`stdout`/`stderr` pipes so Python 3.14 never emits `ResourceWarning`.

## 4. Python & Data Generation (`lib/*`, `bin/*.py`)

- **Formatting & Linting**: All Python files must pass `uvx ruff check .` and `uvx ruff format --check .`.
- **Cross-Process Determinism**: Never use Python's built-in `hash()` inside seeded RNG calculations (because `PYTHONHASHSEED` randomizes hashes across processes). Use deterministic ordinal folds or `hashlib.sha256`.

## 5. Terraform (`infra/*.tf`)

- **Validate & Format**: `infra/` must pass `make lint-tf` (`terraform init -backend=false -lockfile=readonly`, `validate`, `fmt -check -recursive`) against the committed `infra/.terraform.lock.hcl`.

## 6. Verification

- Run `uvx ruff check . && uvx ruff format --check . && make test && make lint-sh && make lint-tf` before pushing; `.husky/pre-commit` and CI (`CI / Check & Test`) run the same checks, plus pre-commit refuses commits on `main` and CI enforces branch names (AGENTS.md § Worktree execution).
