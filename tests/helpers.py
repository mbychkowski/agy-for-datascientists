"""Shared test fixtures and environment builders for preflight, CLI, and plugin tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

WORKTREE_ROOT = Path(__file__).resolve().parent.parent
PREFLIGHT_BIN = WORKTREE_ROOT / "bin" / "preflight"
PREFLIGHT_SYMLINK = WORKTREE_ROOT / "preflight"
VENDORED_DAK_DIR = WORKTREE_ROOT / ".agents" / "plugins" / "dak-bigquery"


def create_demo_env_file(
    tmpdir: str | Path,
    project_id: str = "demo-proj-123",
    region: str = "us-central1",
    staging_bucket: str = "demo-staging-bucket",
    state_bucket: str = "demo-state-bucket",
    subnet: str = "",
    exported: bool = True,
) -> Path:
    """Write a temporary demo.env file with optional export directives."""
    if exported:
        export_lines = """
export PROJECT_ID
export REGION
export STAGING_BUCKET
export STATE_BUCKET
export SUBNET

export CLOUDSDK_CORE_PROJECT="${PROJECT_ID}"
export CLOUDSDK_COMPUTE_REGION="${REGION}"
export GOOGLE_CLOUD_PROJECT="${PROJECT_ID}"
export GOOGLE_CLOUD_QUOTA_PROJECT="${PROJECT_ID}"
export TF_VAR_project_id="${PROJECT_ID}"
export TF_VAR_region="${REGION}"
export TF_VAR_staging_bucket="${STAGING_BUCKET}"
export TF_VAR_state_bucket="${STATE_BUCKET}"
export TF_VAR_subnet="${SUBNET}"
"""
    else:
        export_lines = """
CLOUDSDK_CORE_PROJECT="${PROJECT_ID}"
CLOUDSDK_COMPUTE_REGION="${REGION}"
GOOGLE_CLOUD_PROJECT="${PROJECT_ID}"
GOOGLE_CLOUD_QUOTA_PROJECT="${PROJECT_ID}"
TF_VAR_project_id="${PROJECT_ID}"
TF_VAR_region="${REGION}"
TF_VAR_staging_bucket="${STAGING_BUCKET}"
TF_VAR_state_bucket="${STATE_BUCKET}"
TF_VAR_subnet="${SUBNET}"
"""
    env_content = f"""
PROJECT_ID="{project_id}"
REGION="{region}"
STAGING_BUCKET="{staging_bucket}"
STATE_BUCKET="{state_bucket}"
SUBNET="{subnet}"
{export_lines}
"""
    env_file = Path(tmpdir) / "demo.env"
    env_file.write_text(env_content, encoding="utf-8")
    return env_file


def setup_preflight_test_env(
    tmpdir: str | Path,
    *,
    project_id: str = "demo-proj-123",
    region: str = "us-central1",
    subnet: str = "",
    exported: bool = True,
    active_project: str | None = None,
    active_region: str = "us-central1",
    active_account: str = "presenter@example.com",
    quota_project: str | None = None,
    describe_state: str = "ACTIVE",
    describe_fails: bool = False,
    token_fails: bool = False,
    batch_fails: bool = False,
    bq_show_fails: bool = False,
    adc_dict: dict[str, Any] | None = None,
    dak_proxy_bytes: bytes | None = None,
    missing_dak_proxy: bool = False,
) -> tuple[Path, dict[str, str], Path]:
    """Build a complete mock CLI and ADC environment for testing bin/preflight and CLIs."""
    tmp_path = Path(tmpdir)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    log_file = tmp_path / "calls.log"

    resolved_active_project = project_id if active_project is None else active_project
    resolved_quota_project = project_id if quota_project is None else quota_project

    describe_script = (
        'echo "ERROR: project not found or deleted" >&2; exit 1'
        if describe_fails
        else f'echo "{describe_state}"; exit 0'
    )
    token_script = (
        'echo "ERROR: Reauthentication required" >&2; exit 1'
        if token_fails
        else 'echo "ya29.mock-presenter-access-token"; exit 0'
    )
    batch_script = (
        "echo 'ERROR: batch execution failed' >&2; exit 1" if batch_fails else "exit 0"
    )

    fake_gcloud = bin_dir / "gcloud"
    fake_gcloud.write_text(
        f"""#!/usr/bin/env bash
echo "gcloud $*" >> "{log_file}"
if [[ "$*" == *"configurations list"* ]]; then
    if [[ "$*" == *"properties.compute.region"* ]]; then
        echo "{active_region}"
    elif [[ "$*" == *"properties.core.account"* ]]; then
        echo "{active_account}"
    else
        echo "{resolved_active_project}"
    fi
    exit 0
fi
if [[ "$*" == *"projects describe"* ]]; then
    {describe_script}
fi
if [[ "$*" == *"print-access-token"* ]]; then
    {token_script}
fi
if [[ "$*" == *"dataproc batches submit"* ]]; then
    {batch_script}
fi
exit 0
""",
        encoding="utf-8",
    )
    fake_gcloud.chmod(0o755)

    bq_show_script = (
        "echo 'Not found: Table' >&2; exit 1" if bq_show_fails else "exit 0"
    )
    fake_bq = bin_dir / "bq"
    fake_bq.write_text(
        f"""#!/usr/bin/env bash
echo "bq $*" >> "{log_file}"
if [[ "$*" == *"show"* ]]; then
    {bq_show_script}
fi
exit 0
""",
        encoding="utf-8",
    )
    fake_bq.chmod(0o755)

    if adc_dict is None:
        adc_dict = {
            "type": "authorized_user",
            "client_id": "test-client",
            "client_secret": "test-secret",
            "refresh_token": "test-refresh",
            "quota_project_id": resolved_quota_project,
        }
    adc_file = tmp_path / "adc.json"
    adc_file.write_text(json.dumps(adc_dict), encoding="utf-8")

    env_file = create_demo_env_file(
        tmp_path,
        project_id=project_id,
        region=region,
        subnet=subnet,
        exported=exported,
    )

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["GOOGLE_APPLICATION_CREDENTIALS"] = str(adc_file)
    env["PREFLIGHT_BATCH_ID"] = "preflight-hello-test"
    env["PREFLIGHT_HELLO_TABLE"] = "_preflight_hello_test"

    if missing_dak_proxy:
        empty_dak = tmp_path / "missing-dak-plugin"
        empty_dak.mkdir(exist_ok=True)
        env["DAK_PLUGIN_DIR"] = str(empty_dak)
    elif dak_proxy_bytes is not None:
        dak_dir = tmp_path / "dak-plugin"
        (dak_dir / "mcp" / "bin").mkdir(parents=True, exist_ok=True)
        (dak_dir / "mcp" / "bin" / "mcp_proxy_bundle.cjs").write_bytes(dak_proxy_bytes)
        env["DAK_PLUGIN_DIR"] = str(dak_dir)
    else:
        env["DAK_PLUGIN_DIR"] = str(VENDORED_DAK_DIR)

    return env_file, env, log_file
