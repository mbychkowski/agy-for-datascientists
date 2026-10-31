"""Shared test fixtures and environment builders for preflight, CLI, and plugin tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

WORKTREE_ROOT = Path(__file__).resolve().parent.parent
PREFLIGHT_BIN = WORKTREE_ROOT / "bin" / "preflight"
PREFLIGHT_SYMLINK = WORKTREE_ROOT / "preflight"
SETUP_BIN = WORKTREE_ROOT / "bin" / "setup"
SETUP_SYMLINK = WORKTREE_ROOT / "setup"
VERIFY_START_POINT_BIN = WORKTREE_ROOT / "bin" / "verify-start-point"
VERIFY_START_POINT_SYMLINK = WORKTREE_ROOT / "verify-start-point"
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
    ai_forecast_fails: bool = False,
    ai_forecast_empty: bool = False,
    ai_forecast_with_status_lines: bool = False,
    kmeans_fails: bool = False,
    kmeans_cleanup_fails: bool = False,
    subagent_fails: bool = False,
    subagent_bad_token: bool = False,
    missing_workspace_dak_skills: bool = False,
    fresh_agent_skills_fails: bool = False,
    ws1_missing_table: str = "",
    ws1_missing_label: str = "",
    ws1_no_duplicates: bool = False,
    ws1_wrong_spike: bool = False,
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

    bq_show_fails_flag = "true" if bq_show_fails else "false"
    dup_val = 0 if ws1_no_duplicates else 5
    spike_val = 12.5 if ws1_wrong_spike else 35.0
    ws1_query_json = (
        '[{"raw_ref_rows":6,"raw_feeds_rows":6767,"ops_log_rows":1128,'
        f'"staging_rows":6767,"duplicate_groups":{dup_val},'
        f'"w42_positives":200,"w43_positives":270,"spike_pct":{spike_val}}}]'
    )
    if ai_forecast_fails:
        ai_forecast_script = (
            'echo "ERROR: AI.FORECAST failed or Vertex AI API disabled" >&2; exit 1'
        )
    elif ai_forecast_empty:
        ai_forecast_script = 'echo "[]"; exit 0'
    elif ai_forecast_with_status_lines:
        ai_forecast_script = """echo "Waiting on bqjob_r123456_000001 ... (1s) Current status: DONE"
    echo '[{"forecast_timestamp":"2026-10-15T00:00:00","forecast_value":24.5}]'; exit 0"""
    else:
        ai_forecast_script = """echo '[{"forecast_timestamp":"2026-10-15T00:00:00","forecast_value":24.5}]'; exit 0"""

    kmeans_script = (
        'echo "ERROR: KMEANS model training failed" >&2; exit 1'
        if kmeans_fails
        else 'echo "Created model"; exit 0'
    )
    kmeans_cleanup_script = (
        'echo "ERROR: model cleanup failed" >&2; exit 1'
        if kmeans_cleanup_fails
        else "exit 0"
    )

    fake_bq = bin_dir / "bq"
    fake_bq.write_text(
        f"""#!/usr/bin/env bash
echo "bq $*" >> "{log_file}"
if [[ "$*" == *"show"* ]]; then
    if [[ -n "{ws1_missing_table}" ]] && [[ "$*" == *"{ws1_missing_table}"* ]]; then
        echo "Not found: Table {ws1_missing_table}" >&2
        exit 1
    fi
    if [[ "{bq_show_fails_flag}" == "true" ]]; then
        echo "Not found: Table" >&2
        exit 1
    fi
    if [[ -n "{ws1_missing_label}" ]] && [[ "$*" == *"{ws1_missing_label}"* ]]; then
        echo '{{"id":"mock","labels":{{}}}}'
        exit 0
    fi
    echo '{{"id":"mock","labels":{{"demo":"true"}}}}'
    exit 0
fi
if [[ "$*" == *"duplicate_groups"* ]]; then
    echo '{ws1_query_json}'
    exit 0
fi
if [[ "$*" == *"AI.FORECAST"* ]]; then
    {ai_forecast_script}
fi
if [[ "$*" == *"KMEANS"* ]]; then
    {kmeans_script}
fi
if [[ "$*" == *"rm -f -m"* ]]; then
    {kmeans_cleanup_script}
fi
exit 0
""",
        encoding="utf-8",
    )
    fake_bq.chmod(0o755)

    if subagent_fails:
        subagent_script = 'echo "ERROR: subagent dispatch timed out" >&2; exit 1'
    elif subagent_bad_token:
        subagent_script = 'echo "UNEXPECTED_RESPONSE"; exit 0'
    else:
        subagent_script = 'echo "SUBAGENT_OK"; exit 0'

    fresh_agent_skills_script = (
        'echo "bigquery-ai-ml is NOT visible in this workspace (DAK_SKILLS_MISSING)"; exit 0'
        if fresh_agent_skills_fails
        else 'echo "DAK_SKILLS_VISIBLE: bigquery-ai-ml, gcp-spark"; exit 0'
    )

    fake_agy = bin_dir / "agy"
    fake_agy.write_text(
        f"""#!/usr/bin/env bash
echo "agy $*" >> "{log_file}"
if [[ "$*" == *"SUBAGENT_OK"* ]]; then
    {subagent_script}
fi
if [[ "$*" == *"DAK_SKILLS_VISIBLE"* ]]; then
    {fresh_agent_skills_script}
fi
exit 0
""",
        encoding="utf-8",
    )
    fake_agy.chmod(0o755)

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
    env["PREFLIGHT_KMEANS_MODEL"] = "_preflight_kmeans_test"
    env["PREFLIGHT_AGY_TIMEOUT"] = "5s"
    env["PIPELINE_V1_BATCH_ID"] = "ws1-pipeline-v1-test"

    workspace_skills_dir = tmp_path / "workspace-gemini-skills"
    if not missing_workspace_dak_skills:
        for skill_name in ("bigquery-ai-ml", "gcp-spark"):
            skill_dir = workspace_skills_dir / skill_name
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(
                f"---\nname: {skill_name}\ndescription: Test skill {skill_name}\n---\n",
                encoding="utf-8",
            )
    env["WORKSPACE_DAK_SKILLS_DIR"] = str(workspace_skills_dir)

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
