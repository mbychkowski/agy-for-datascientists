# Reuser Setup & Operations Guide

End-to-end guide for setting up the **Antigravity for Data Scientists** **Command Center** in your own Google Cloud project, installing the licensed Data Agent Kit skills into the workspace, running local Spark 4 tests with Java 21, and avoiding common authentication pitfalls.

All terminology follows [GLOSSARY.md](../GLOSSARY.md). Once your environment passes `./preflight` and `./verify-start-point ws1`, use [DEMO.md](../DEMO.md) to rehearse or deliver the live session.

---

## 1. Environment File (`demo.env`)

Every script, Terraform command, BigQuery MCP wrapper, and agent rule in this repository reads project and region configuration from `demo.env` at the repository root.

1. Copy the template environment file:
   ```bash
   cp demo.env.example demo.env
   ```
2. Edit `demo.env` and set the core variables for your Google Cloud environment:
   ```bash
   PROJECT_ID="your-demo-project-id"
   REGION="us-central1"
   STAGING_BUCKET="your-dataproc-staging-bucket"
   STATE_BUCKET="your-terraform-state-bucket"
   SUBNET="" # Leave empty to let Terraform create demo-dataproc-vpc & demo-dataproc-subnet
   DATASET_LOCATION="gs://${STAGING_BUCKET}/dataset" # Refined full-scale Data Generator hand-off root (90 hospitals; leave empty to default to fixtures/mock_dataset for unit tests)
   ```
3. Source `demo.env` in your shell before running any CLI tool:
   ```bash
   source demo.env
   ```

### How `demo.env` Overrides Workstation Defaults

Sourcing `demo.env` exports three sets of overrides so your session never leaks queries or infrastructure into an unintended project:
* **`gcloud` CLI overrides**: `CLOUDSDK_CORE_PROJECT="${PROJECT_ID}"` and `CLOUDSDK_COMPUTE_REGION="${REGION}"` pin `gcloud` commands.
* **SDK & ADC quota overrides**: `GOOGLE_CLOUD_PROJECT="${PROJECT_ID}"` and `GOOGLE_CLOUD_QUOTA_PROJECT="${PROJECT_ID}"` pin Google Cloud client libraries and the BigQuery MCP wrapper (`.agents/plugins/dak-bigquery/bin/run-bigquery-mcp`).
* **Terraform input variables**: `TF_VAR_project_id`, `TF_VAR_region`, `TF_VAR_staging_bucket`, `TF_VAR_state_bucket`, and `TF_VAR_subnet` populate `infra/variables.tf` without hardcoded defaults.

 Also pin your underlying `gcloud` CLI profile so unshadowed checks in `./preflight` match `demo.env`:

```bash
source demo.env
gcloud config set project "${PROJECT_ID}"
gcloud config set compute/region "${REGION}"
```

---

## 2. Minimum Presenter IAM Roles ([ADR 0002](adr/0002-dataproc-runs-as-presenter.md))

Per [ADR 0002](adr/0002-dataproc-runs-as-presenter.md), the presenter does **not** need `roles/owner`, and Terraform creates **no** custom service accounts or `google_*_iam_*` policy bindings. Every component of the **Command Center**—BigQuery, BigQuery ML (`ARIMA_PLUS` and `AI.FORECAST`), BigQuery MCP, and Dataproc Serverless runtime `3.0` batches—executes under the presenter's own user credentials (the Dataproc Serverless runtime `3.0` default).

### 2.1 Minimum Project IAM Roles for the Presenter Identity

Grant the following minimum IAM roles to the presenter's user account (`user:<presenter-email>`) on `PROJECT_ID`:

| IAM Role | Why It Is Required |
| :--- | :--- |
| `roles/serviceusage.serviceUsageAdmin` | Enables the six required APIs in `infra/main.tf` (`bigquery.googleapis.com`, `bigquerystorage.googleapis.com`, `dataproc.googleapis.com`, `dataprocrm.googleapis.com`, `storage.googleapis.com`, `compute.googleapis.com`). |
| `roles/compute.networkAdmin` | Creates `demo-dataproc-vpc` and `demo-dataproc-subnet` (with Private Google Access) when `SUBNET=""`. *(Not required if using a pre-provisioned `SUBNET` with `roles/compute.networkUser`).* |
| `roles/compute.securityAdmin` | Creates the `demo-dataproc-allow-internal` ingress firewall rule for Spark executor-to-executor communication when `SUBNET=""`. |
| `roles/storage.admin` | Creates and manages `gs://${STATE_BUCKET}` (Terraform state), `gs://${STAGING_BUCKET}` (Dataproc Serverless staging), and the separate withheld bucket for the **Answer Key** and **Reveal** ([ADR 0001](adr/0001-answer-key-outside-agent-reach.md)). |
| `roles/bigquery.admin` *(or `roles/bigquery.dataEditor` + `roles/bigquery.jobUser`)* | Creates and manages the six demo datasets (`raw`, `ops`, `staging`, `features`, `ml`, `checkpoint`), runs SQL queries, and trains BigQuery ML models (`KMEANS`, `ARIMA_PLUS`, `AI.FORECAST`). |
| `roles/dataproc.editor` | Submits and monitors Dataproc Serverless runtime `3.0` PySpark batches (`bin/run-pipeline-v1`, `bin/run-pipeline-clean`, and `./preflight` Check 5). |

### 2.2 Optional Landing-Zone Service Account Roles

Dataproc Serverless runtime `3.0` runs batches as the submitting user identity by default ([ADR 0002](adr/0002-dataproc-runs-as-presenter.md)). If your organization's landing zone enforces a policy requiring worker VM provisioning or batch execution to attach the Compute Engine default service account (`<PROJECT_NUMBER>-compute@developer.gserviceaccount.com`):
* Grant the presenter `roles/iam.serviceAccountUser` on that service account.
* Ensure the service account holds `roles/dataproc.worker`, `roles/bigquery.dataEditor`, and `roles/bigquery.jobUser`.

---

## 3. Terraform Bootstrap & Apply

Terraform state is stored in a dedicated Cloud Storage bucket (`gs://${STATE_BUCKET}`) so it never collides with other workloads in a shared project.

### Step 1: Bootstrap the Dedicated State Bucket and Initialize Terraform

Run the idempotent bootstrap script from the repository root:

```bash
source demo.env
./bin/bootstrap-tf-state
```

`./bin/bootstrap-tf-state` creates `gs://${STATE_BUCKET}` in `${REGION}` (with uniform bucket-level access, public access prevention, object versioning, and label `demo=true`) and runs:

```bash
terraform -chdir=infra init -reconfigure -backend-config="bucket=${STATE_BUCKET}"
```

### Step 2: Plan and Apply the Demo Infrastructure

```bash
source demo.env
terraform -chdir=infra validate
terraform -chdir=infra plan
terraform -chdir=infra apply
```

This provisions:
* The required project APIs (`bigquery`, `bigquerystorage`, `dataproc`, `dataprocrm`, `storage`, `compute`).
* `demo-dataproc-vpc`, `demo-dataproc-subnet` (`private_ip_google_access = true`), and `demo-dataproc-allow-internal` (unless `SUBNET` is set in `demo.env`).
* The Dataproc Serverless staging bucket `gs://${STAGING_BUCKET}`.
* The six BigQuery datasets (`raw`, `ops`, `staging`, `features`, `ml`, `checkpoint`), all labeled `demo:true`.

---

## 4. Installing Data Agent Kit Skills into the Workspace (Licensed, Not Redistributed)

### Licensing Boundary

* **Not Redistributed (`.gemini/skills/`)**: The Data Agent Kit skills (`bigquery-ai-ml`, `bigquery-sql`, `gcp-spark`, `gcp-data-pipelines`, etc.) are **licensed** upstream components and are **not redistributed** in this git repository (`.gemini/skills/` is gitignored).
* **Vendored Apache-2.0 Proxy (`.agents/plugins/dak-bigquery/`)**: Only the Apache-2.0 licensed BigQuery MCP stdio proxy bundle (`mcp_proxy_bundle.cjs`) is vendored inside `.agents/plugins/dak-bigquery/mcp/bin/mcp_proxy_bundle.cjs` (with upstream notice in `.agents/plugins/dak-bigquery/NOTICE`).

### Why Workspace Installation Is Required

In Antigravity, subagents spawned inside a workspace discover skills through `.agents/skills.json`, which points to `.gemini/skills` in the repository root. Installing the Data Agent Kit skills into `.gemini/skills/` guarantees that both the primary **Command Center** agent and every freshly dispatched subagent can load `bigquery-ai-ml`, `bigquery-sql`, and `gcp-spark` even after `./stage-clean-env --stash` isolates personal global skills.

### Step-by-Step Installation into `.gemini/skills/`

1. Locate your licensed local Data Agent Kit installation (typically installed at `~/.gemini/config/plugins/data-agent-kit-plugin/skills` or `~/.gemini/skills`).
2. Copy the Data Agent Kit skill directories into the workspace's `.gemini/skills/` directory:
   ```bash
   mkdir -p .gemini/skills
   cp -R "${HOME}/.gemini/config/plugins/data-agent-kit-plugin/skills/"* .gemini/skills/
   ```
   *(If your licensed skills are stored in `~/.gemini/skills/`, copy the `bigquery-*` and `gcp-*` directories from `~/.gemini/skills/` into `./.gemini/skills/`).*
3. Verify that the core skills are present in the workspace:
   ```bash
   ls -la .gemini/skills/bigquery-ai-ml/SKILL.md \
          .gemini/skills/bigquery-sql/SKILL.md \
          .gemini/skills/gcp-spark/SKILL.md
   ```
4. `./preflight` (Check 11) validates both `.gemini/skills/` on disk and fresh-agent visibility via `agy --print`.

---

## 5. Java 21 Requirement for Local Spark 4 Tests

Dataproc Serverless runtime `3.0` executes on **Apache Spark 4**, which supports Java 17 and **Java 21** (`OpenJDK 21`) and fails on **Java 25+** due to removed JVM security manager APIs. All local PySpark / Spark 4 unit tests (`tests/test_ws1_reference_fix.py`) and `./preflight` (Check 12) require a Java 21 runtime.

### Installing OpenJDK 21 and Configuring `JAVA_HOME`

* **macOS (Homebrew)**:
  ```bash
  brew install openjdk@21
  export JAVA_HOME="/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home"
  export PATH="${JAVA_HOME}/bin:${PATH}"
  ```
  *(On Intel Macs, use `/usr/local/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home`).*
* **Ubuntu / Debian Linux**:
  ```bash
  sudo apt-get update && sudo apt-get install -y openjdk-21-jdk
  export JAVA_HOME="/usr/lib/jvm/java-21-openjdk-amd64"
  export PATH="${JAVA_HOME}/bin:${PATH}"
  ```
* **Verification**:
  ```bash
  java -version
  python3 -c "from pipelines.pipeline_clean import ensure_java_21_env; print(ensure_java_21_env())"
  ```

`pipelines/pipeline_clean.py` (`ensure_java_21_env`) automatically checks `JAVA_21_HOME`, `JAVA_HOME`, `PATH`, Homebrew `openjdk@21` paths, `~/.local/share/mise/installs/java/21*`, and `/usr/libexec/java_home -v 21`.

---

## 6. Troubleshooting the Stale ADC Quota Project Pitfall

### Symptom: Opaque `403 Forbidden` Errors in BigQuery MCP

One of the most common setup pitfalls when switching between Google Cloud projects is a **stale or deleted quota project** inside Application Default Credentials (`~/.config/gcloud/application_default_credentials.json`).

Two failure modes occur when ADC is misconfigured:
1. **Stale or Deleted `quota_project_id`**: If `~/.config/gcloud/application_default_credentials.json` references a `quota_project_id` from an older project that was deleted, disabled, or differs from `PROJECT_ID`, the BigQuery MCP server (`mcp_proxy_bundle.cjs`) fails every tool call with an opaque HTTP `403 Forbidden` error without naming the stale quota project.
2. **Missing or Expired User OAuth ADC (Compute Metadata Fallback)**: If `~/.config/gcloud/application_default_credentials.json` is missing, has `type: service_account`, or has an expired refresh token, `mcp_proxy_bundle.cjs` silently falls back to `http://metadata.google.internal/...` and authenticates as the workstation's compute service account instead of the presenter.

### Remediation Steps

Run the following commands whenever you create or switch to a new `PROJECT_ID`:

```bash
source demo.env

# 1. Authenticate gcloud CLI as the presenter's user account
gcloud auth login

# 2. Authenticate user OAuth Application Default Credentials (authorized_user)
gcloud auth application-default login

# 3. Pin the ADC quota_project_id to PROJECT_ID from demo.env
gcloud auth application-default set-quota-project "${PROJECT_ID}"
```

### How the Repository Protects You Against This Pitfall

1. **`demo.env` Exports `GOOGLE_CLOUD_QUOTA_PROJECT="${PROJECT_ID}"`**: Ensures SDK tools use the demo project for quota billing.
2. **`.agents/plugins/dak-bigquery/bin/run-bigquery-mcp` Wrapper**: Before launching `mcp_proxy_bundle.cjs`, the workspace wrapper validates that user OAuth ADC (`type: authorized_user`) is active, mints a fresh token check, and exports `BILLING_QUOTA_PROJECT_ID="${PROJECT_ID}"`.
3. **`./preflight` Checks 4 & 6**: Explicitly inspect `~/.config/gcloud/application_default_credentials.json`, verify `quota_project_id == PROJECT_ID`, run `gcloud projects describe "${adc_quota}"` to confirm `lifecycleState == ACTIVE`, and fail fast with the exact `gcloud auth application-default set-quota-project` command if a stale quota project is detected.

---

## 7. Seeding Data, Building Checkpoints & Preparing for Stage

Once Terraform, workspace Data Agent Kit skills, Java 21, and ADC are configured:

1. **Generate or Load Synthetic Data & Run Setup**:
   * For a full live environment, run the external **Data Generator** (`--scale full --seed 42`) to populate your dataset hand-off root (`DATASET_LOCATION` in `demo.env`, e.g., `gs://${STAGING_BUCKET}/dataset`) and your separate, manually created withheld bucket (`gs://<your-withheld-bucket>/answer_key.json` and `gs://<your-withheld-bucket>/reveal/`, per [ADR 0001](adr/0001-answer-key-outside-agent-reach.md)).
   * When `DATASET_LOCATION` is configured in `demo.env`, `./setup`, `./reset ws1`, `./reset ws2`, `./bin/load-raw-ops`, and `./verify-start-point main` automatically read from the refined full-scale dataset (90 hospitals, while `fixtures/mock_dataset` stays in place for unit tests). Seed `raw` and `ops`, execute Pipeline v1 (`pipelines/pipeline_v1.py`) on Dataproc Serverless, and verify the **Workstream** 1 **Start Point**:
     ```bash
     ./setup
     # Or pass an explicit dataset location override:
     ./setup gs://<your-dataset-bucket>
     # Or seed using the deterministic local mock dataset fixture:
     ./setup fixtures/mock_dataset
     ```
2. **Materialise All Checkpoints**:
   ```bash
   ./checkpoint --build all
   ./checkpoint --list
   ```
3. **Run Full Preflight & Start Point Verification**:
   ```bash
   ./preflight
   ./verify-start-point ws1
   ```
4. **Isolate Personal Rules/Skills Before Presenting**:
   ```bash
   ./stage-clean-env --stash
   ```
   Follow [DEMO.md](../DEMO.md) for the live 90-minute session, and run `./stage-clean-env --restore` when finished.

---

## 8. Two-Repository Stage Setup (Window 1 and Window 2)

The live session runs from **two separate repositories**, never from one checkout:

| Window | Repository | What runs there |
| :--- | :--- | :--- |
| **Window 1 (agent)** | A fresh single-branch clone of `workstream-1-start`, outside this repo, with its remote removed and `demo.env` copied in | Antigravity. The agent writes and runs its code here. |
| **Window 2 (presenter terminal)** | This repo on `main` | Every presenter script: `./stage-clean-env`, `./preflight`, `./reset`, `./verify-start-point`, `./checkpoint`, `./run-pipeline-clean`, `./run-ws2-cohorts`, `./run-ws2-forecasts`, `./load-reveal`, `./run-cohort-forecast-refresh`, `./install-evidence-board`, `./evidence-board`. |

The presenter scripts read the **Workstream** 2 SQL, the **Workstream** 2 **Checkpoint** manifests, and the **Reveal** comparison SQL, and the branch-boundary tests (`tests/test_ws1_reference_fix.py`, `tests/test_ws2_start_point.py`, `tests/test_reveal_and_verify_main.py`) keep those files off the stage branches ([ADR 0001](adr/0001-answer-key-outside-agent-reach.md)). That is why the presenter scripts only exist on `main`, and why `main` must stay out of the agent's reach:

* A **worktree** shares `.git` with this repo, so an agent in it could still run `git show main:…`.
* An **in-repo folder** sits inside the agent's workspace.
* A **local-path clone** hardlinks the whole object store, `main` included. Clone from the remote URL instead.

Create the stage clone once per machine, from this repo on `main`:

```bash
git clone --single-branch --branch workstream-1-start "$(git remote get-url origin)" ~/demo-stage/agy-ws1
git -C ~/demo-stage/agy-ws1 remote remove origin
cp demo.env ~/demo-stage/agy-ws1/
mkdir -p ~/demo-stage/agy-ws1/.gemini
cp -R .gemini/skills ~/demo-stage/agy-ws1/.gemini/
```

`.gemini/skills/` is git-ignored, so the clone starts without the licensed Data Agent Kit skills; the last two lines copy your workspace install across. `./preflight` checks the presenter repo, not the clone, so confirm the copy with `ls ~/demo-stage/agy-ws1/.gemini/skills/bigquery-ai-ml/SKILL.md`.

Before every rehearsal and on Demo Day, the T-15 checklist resets the clone's code (`git reset --hard`, `git clean -fd`) and then runs `./reset ws1 --yes` and `./verify-start-point ws1` from this repo. See the [DEMO.md Pre-Stage Checklist](../DEMO.md#2-pre-stage-checklist-t-15-minutes) for the full sequence.

---

## 9. The **Evidence Board** in Your Own Project

The **Evidence Board** is an Antigravity UI sidecar that shows one **Tile** per demo step beside the **Command Center** chat. A **Tile** lands when its source table has rows in `staging`, `features` or `ml`, so it works the same whether the agent, a Window 2 fallback or a **Checkpoint** swap wrote the table. The **Tile** manifest is [`tiles.json`](../.agents/plugins/ds-command-center/sidecars/evidence-board/tiles.json).

> [!WARNING]
> **Experimental Antigravity feature.** UI sidecars sit behind the `enable-ui-sidecars` experiment flag, and their web-UI layer is undocumented, so it may change between Antigravity releases. Antigravity also discovers sidecars only under the global `~/.gemini/config/` directories, never in a workspace, so the board's source lives in this repo and an installer copies it out ([ADR 0003](adr/0003-evidence-board-installed-by-copy-and-driven-by-tables.md)). Rehearse on the machine you present from, and keep the standalone launcher ready. A blank or empty **Evidence Board** pane most likely means `enable-ui-sidecars` is off or the sidecar isn't enabled in `config.json`; use the standalone `./evidence-board` fallback.

1. **Install the board's Python dependencies** into the interpreter the sidecar will run (`${PYTHON:-python3}`, which the installer records). Building the frontend also needs Node.js and `npm`:
   ```bash
   uv pip install --python "${PYTHON:-python3}" -r .agents/plugins/ds-command-center/sidecars/evidence-board/requirements.txt
   ```
2. **Copy the board into Antigravity**, pinned to the workspace whose `demo.env` it reads (for the two-repository setup, the stage clone):
   ```bash
   ./install-evidence-board --workspace ~/demo-stage/agy-ws1
   ```
   It builds the frontend, copies the sidecar to `~/.gemini/config/sidecars/evidence-board/` (replacing any earlier install), and records the Python interpreter and workspace in `install.env`. Rerun it after pulling **Evidence Board** changes, or to point the board at another workspace.
3. **Enable the sidecar** by merging `{"sidecars": {"evidence-board": {"enabled": true}}}` into `~/.gemini/config/config.json`, then restart the Antigravity App. The installer never edits `config.json`.
4. **Verify**: `./preflight` warns (it never fails) when the install is missing, out of date with the repo, unpinned or not enabled. If the side pane stays blank, check `~/.gemini/antigravity/sidecar_data/evidence-board/logs/`.

**Standalone fallback.** Without the sidecar (for example, in the Antigravity CLI), serve the same board in a browser tab:

```bash
./evidence-board --workspace ~/demo-stage/agy-ws1 --port 8765
```

Open `http://127.0.0.1:8765/`. **Tiles** land the same way, but the Ask button copies its prompt to the clipboard instead of sending it to the **Command Center**. `--fake-catalog <json>` runs it offline against a hand-written table catalog for rehearsing the layout.

**Activity lanes** (a **Tile**'s in-progress view) come from the **Command Center** event recorder hooks, which append the agent's tool calls to `<workspace>/.evidence-board/events.jsonl`, so the workspace the agent runs in (your stage clone) must carry the plugin's `hooks.json` and `bin/event-recorder*`. Landing never depends on them, and `./reset` appends a `reset` marker to that log so the board starts fresh.
