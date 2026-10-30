# Coding Standards

Documented standards for Command Center scripts, tooling, and tests.

## 1. CLI Scripts (`bin/*`)

- **Strict Execution**: Scripts must begin with `#!/usr/bin/env bash` and `set -uo pipefail` (or `set -euo pipefail`).
- **Symlink Portability**: Resolve real script directory through any symlinks before deriving `REPO_ROOT` (do not rely on `$PWD` or fragile relative paths).
- **Executable Bit**: All scripts in `bin/` must have executable permissions (`chmod +x`).

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
