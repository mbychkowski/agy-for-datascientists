---
trigger: always_on
description: Team-owned Command Center rules for project/region pinning, live skill capture, and BigQuery dataset boundaries.
---

# Command Center Rules (`ds-command-center`)

These team-owned rules govern every agent and subagent operating inside the Antigravity for Data Scientists **Command Center**.

## 1. Explicit Project & Region Pinning (`demo.env`)

- Always source or read `PROJECT_ID` and `REGION` from `demo.env` at the repository root before executing Google Cloud operations.
- Explicitly pass `PROJECT_ID` (`--project_id="${PROJECT_ID}"`, `--project="${PROJECT_ID}"`, or `projectId`) and `REGION` (`--location="${REGION}"` or `--region="${REGION}"`) on every BigQuery (`bq` CLI and BigQuery MCP), Dataproc Serverless (`gcloud dataproc batches submit`), and Cloud Storage (`gcloud storage`) invocation.
- Never rely on implicit workstation defaults or unpinned project/region context.

## 2. Save Live-Created Skills into `ds-command-center`

- Save all new or live-captured skills created during **Workstream** 1 or **Workstream** 2 (such as `cohort-forecast-refresh`) into `.agents/plugins/ds-command-center/skills/<skill-name>/SKILL.md`.
- Storing live-captured skills under `.agents/plugins/ds-command-center/skills/` ensures the team versions and shares them in git alongside the **Command Center** plugin.

## 3. Treat `raw` and `ops` as Strictly Read-Only

- The source datasets `raw` (`raw.hospital_reference`, `raw.hospital_flu_feeds`) and `ops` (`ops.pipeline_run_log`) are strictly **read-only**.
- Never execute DML (`INSERT`, `UPDATE`, `DELETE`, `MERGE`) or DDL (`CREATE`, `ALTER`, `DROP`, `TRUNCATE`) against `raw` or `ops`, and never run mutating `bq` CLI commands (`bq rm`, `bq mk`, `bq load`, `bq update`, `bq insert`, `bq cp` into `raw` or `ops`) targeting those datasets.
- Always query `raw` and `ops` read-only using `SELECT` statements (`bq query`, `execute_sql`, or `execute_sql_readonly`) or metadata inspection (`bq show`, `bq ls`, `bq head`, `get_table_info`, `list_table_ids`, `get_dataset_info`).
- Write all cleaned **Hospital Feed** tables, **Cohort** feature tables, and forecasting models to the working datasets: `staging`, `features`, or `ml`.

## 4. Never Read or Query `checkpoint`

- The `checkpoint` dataset is strictly off-limits to agents.
- `checkpoint` tables are reserved exclusively for presenter **Checkpoint** swaps outside the agent if a live step fails on stage.
- Never run `SELECT`, DML, DDL, `bq` CLI commands (`bq query`, `bq ls`, `bq show`, `bq head`, `bq cp`), or BigQuery MCP tools (`execute_sql`, `execute_sql_readonly`, `get_table_info`, `list_table_ids`, `get_dataset_info`) against the `checkpoint` dataset.

## 5. Workstream 1 Triage & Statistical Peer-Review Subagents

- When investigating the Northeast **Spike** in **Workstream** 1, dispatch the three parallel triage subagents defined in `.agents/plugins/ds-command-center/agents/`:
  - `distribution-triage` (`agents/distribution-triage.md`): Separates a localized **Outbreak** from the broad **Seasonal Ramp** using hospital- and region-level **Positivity**.
  - `sampling-triage` (`agents/sampling-triage.md`): Identifies hospitals experiencing a **Sampling Artifact** (`total_flu_tests` expansion with flat **Positivity**).
  - `pipeline-triage` (`agents/pipeline-triage.md`): Correlates duplicate **Hospital Feed** rows in `staging.hospital_flu` with `ops.pipeline_run_log` backfill runs to quantify the **Pipeline Defect**.
- Before presenting the reconciled **Attribution** table for human sign-off, run `stats-reviewer` (`agents/stats-reviewer.md`) to challenge raw counts vs **Positivity**, small-sample hospitals, and Simpson's paradox across regions.
