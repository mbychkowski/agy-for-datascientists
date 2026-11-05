# Presenter Runbook

Step-by-step live execution script for delivering the 90-minute **Antigravity for Data Scientists** demonstration on stage. This runbook provides the pre-stage isolation checklist, per-segment timings, exact prompts to type into the **Command Center**, speaker narration cues, Window 2 fallback triggers for long-running jobs (the 60-second rule, using recorded runtimes from [`docs/recorded_runtimes.json`](recorded_runtimes.json)), the guardrail moment in Antigravity 101, and **Checkpoint** swap commands.

All terminology follows [GLOSSARY.md](../GLOSSARY.md). For methodological background and Q&A defense, see the [Data Science Primer](data-science-primer.md) and [Demo Outline](demo-outline.md). For initial project provisioning, see the [Reuser Guide](reuser-guide.md).

---

## 1. Pre-Stage Checklist (T-15 Minutes)

The demo runs from **two separate repositories**, one per stage window:

* **Window 1 (agent)**: Antigravity opened on the **stage clone**, a fresh single-branch clone of `workstream-1-start` that lives outside the presenter repo, has its remote removed, and has `demo.env` copied in. Every prompt in this runbook is typed here.
* **Window 2 (presenter terminal)**: your existing presenter repo on `main`, with `source demo.env` active. It owns every presenter script (`./stage-clean-env`, `./preflight`, `./reset`, `./verify-start-point`, `./checkpoint`, `./run-pipeline-clean`, `./run-ws2-cohorts`, `./run-ws2-forecasts`, `./load-reveal`, `./run-cohort-forecast-refresh`). Never run these from the stage clone: most of them don't exist on `workstream-1-start`, and the rest are stale there.

> **Why a separate clone, not a worktree or an in-repo folder?** The presenter-only tooling on `main` reads the **Workstream** 2 SQL, the **Workstream** 2 **Checkpoint** manifests, and the **Reveal** comparison SQL, so `main` must stay out of the agent's reach to keep the "agents never saw the answers" guarantee ([ADR 0001](adr/0001-answer-key-outside-agent-reach.md)). Every worktree shares `.git` with the presenter repo, so an agent in a worktree could still run `git show main:…`. An in-repo folder sits inside the agent's workspace. Only a separate single-branch clone with no remote keeps `main` out of reach.

### Step 0: Create the Stage Clone (Window 2, Once per Machine)

From the presenter repo on `main`, clone the stage branch by its remote URL (a local-path clone hardlinks the whole object store, `main` included), remove the remote, and copy `demo.env` in:

```bash
git clone --single-branch --branch workstream-1-start "$(git remote get-url origin)" ~/demo-stage/agy-ws1
git -C ~/demo-stage/agy-ws1 remote remove origin
cp demo.env ~/demo-stage/agy-ws1/
mkdir -p ~/demo-stage/agy-ws1/.gemini
cp -R .gemini/skills ~/demo-stage/agy-ws1/.gemini/
```

`.gemini/skills/` is git-ignored, so the clone starts without the licensed Data Agent Kit skills; the last two lines copy your workspace install across. `./preflight` checks the presenter repo, not the clone, so confirm the copy with `ls ~/demo-stage/agy-ws1/.gemini/skills/bigquery-ai-ml/SKILL.md`.

Complete the steps below before connecting to the stage display so only the repository's **Command Center** configuration loads and every Google Cloud dependency is verified.

### Step 1: Move Personal Rules and Skills Aside (`./stage-clean-env --stash`, Window 2)

Personal rules (`~/.gemini/rules`, `~/.gemini/config/rules`, `~/.gemini/AGENTS.md`, `~/.gemini/GEMINI.md`) and personal non-DAK skills in `~/.gemini/skills` or `~/.gemini/config/skills` can alter agent behavior on stage. From the presenter repo on `main` (Window 2), stash them into `~/.gemini/.demo-stage-stash/` so only the demo workspace setup (`.agents/plugins/ds-command-center`, `.agents/plugins/dak-bigquery`, and workspace `.gemini/skills/`) loads:

```bash
./stage-clean-env --stash
./stage-clean-env --status
```

Expected output:

```text
[PASS] Stashed <N> personal rule/skill item(s) into /Users/<you>/.gemini/.demo-stage-stash.
[PASS] STATUS: stashed (<N> personal item(s) isolated in /Users/<you>/.gemini/.demo-stage-stash)
```

> **Post-Stage Restoration**: Immediately after the session concludes, restore your personal configuration with:
> ```bash
> ./stage-clean-env --restore
> ```

### Step 2: Load `demo.env` and Run `./preflight` (Window 2)

In the presenter repo on `main` (Window 2), confirm `DATASET_LOCATION` in `demo.env` points to the refined full-scale **Data Generator** hand-off root (`90` hospitals, for example, `DATASET_LOCATION="gs://${STAGING_BUCKET}/dataset"`), then verify environment variables, active `gcloud` project pinning, Application Default Credentials (ADC) quota project alignment, Dataproc Serverless runtime `3.0` execution, BigQuery MCP presenter authentication, dataset guardrail hooks, BigQuery ML (`AI.FORECAST` and K-means), subagent dispatch, workspace Data Agent Kit skills visibility, and Java 21 availability:

```bash
source demo.env
./preflight
```

Do not go on stage if any required `[FAIL]` check is reported.

### Step 3: Reset the Stage Clone's Code and the Workstream 1 Start Point (Window 2)

Run this before every rehearsal and on Demo Day. First discard the agent's tracked edits and untracked files from the last run in the stage clone. `git clean -fd` leaves git-ignored files alone, so `demo.env` and `.gemini/skills/` survive. Then, from the presenter repo on `main`, reset the working BigQuery datasets (`staging`, `features`, `ml`) to the **Workstream** 1 **Start Point** (which loads `raw` and `ops` from `DATASET_LOCATION` in `demo.env`), and verify table schemas, row counts, and `checkpoint` parity:

```bash
git -C ~/demo-stage/agy-ws1 reset --hard
git -C ~/demo-stage/agy-ws1 clean -fd
./reset ws1 --yes
./verify-start-point ws1
```

If a rehearsal left a commit in the stage clone, delete the clone and repeat Step 0 instead.

### Step 4: Stage Window Layout

1. **Window 1 — Command Center (Antigravity, agent)**: Launch Antigravity on the stage clone at `~/demo-stage/agy-ws1` once Steps 1–3 have completed so the fresh session loads only `.agents/plugins/ds-command-center`, `.agents/plugins/dak-bigquery`, and `.gemini/skills/` from the clone.
2. **Window 2 — Presenter Terminal (`main` repo, Fallback Runner)**: Keep a terminal tab open at the presenter repo root on `main` with `source demo.env` active. Verify available **Checkpoints** with `./checkpoint --list`.

### Before Demo Day: Rehearse the Live-Written Prompts

The agent writes `pipeline_clean.py` (Segment 1C), the seasonal-features and K-means SQL (Segment 2A), the `ARIMA_PLUS` and `TimesFM` SQL (Segment 2B), and the `cohort-forecast-refresh` `SKILL.md` (Segment 2D) live, so its output can vary between runs. Rehearse the full sequence several times, starting each run from the Step 3 reset, and type the 1C, 2A, 2B and 2D prompts exactly as written. Check that the output is consistent across runs:

* **1C**: `./run-pipeline-clean --verify-equivalence` passes from Window 2.
* **2A**: the 3 **Outbreak** hospitals land in their own **Cohort**.
* **2B**: `ARIMA_PLUS` starts before `TimesFM`, and clean models beat uncleaned ones in `ml.forecast_leaderboard`.
* **2D**: `SKILL.md` lands in `.agents/plugins/ds-command-center/skills/cohort-forecast-refresh/`, and the subagent's `2026-W44` run appends rows to `ml.experiment_trials`.

Note each step's runtime as well. If the agent's output or timing differs between runs, tighten the prompt wording before Demo Day rather than relying on the Window 2 fallbacks.

---

## 2. Master 90-Minute Schedule & Window 2 Fallback Matrix

### 2.1 Segment Timing Summary (`90 min` Total)

| Segment | Clock Window | Duration | Primary On-Stage Activity | Window 2 Fallback / Checkpoint |
| :--- | :--- | :--- | :--- | :--- |
| **Opening: Antigravity 101 & Command Center Tour** | `00:00–00:12` | **12 min** | Narrative framing (`+35%` Northeast **Spike** through **Cutoff** `2026-10-31`), tour of `ds-command-center` and `dak-bigquery`, live guardrail moment on the agent's own tool call (Window 1) | *(N/A — pre-tool-use hook blocks writes)* |
| **Workstream 1: "Is the Data Good to Use?"** | `00:12–00:47` | **35 min** | Segment 1A (`10 min`, Window 1): EDA & hospital × week heatmap<br>Segment 1B (`12 min`, Window 1): Parallel triage subagents, 4-cause **Attribution**, `stats-reviewer`<br>Segment 1C (`13 min`, Window 1): the agent writes `pipeline_clean.py` and submits its own Dataproc Serverless batch; Window 2: `./run-pipeline-clean --verify-equivalence` | Window 2: `./checkpoint ws1_eda_heatmap`<br>Window 2: `./checkpoint ws1_attribution`<br>Window 2 fallbacks: `./run-pipeline-clean --sql-fallback` or `./checkpoint ws1_staging_clean` |
| **Workstream 2: "Forecast at Scale" & The Reveal** | `00:47–01:15` | **28 min** | Segment 2A (`8 min`, Window 1): the agent writes and runs the seasonal-features & BQML K-means **Cohort** SQL<br>Segment 2B (`10 min`, Window 1): the agent writes and starts `ARIMA_PLUS` first, then zero-shot `TimesFM` (`AI.FORECAST`) & WAPE leaderboard<br>Segment 2C (`6 min`, Window 1): the **Reveal** comparison; Window 2: `./load-reveal`<br>Segment 2D (`4 min`, Window 1): the agent creates & runs the `cohort-forecast-refresh` skill | Window 2 fallbacks: `./run-ws2-cohorts` or `./checkpoint ws2_seasonal_features` & `./checkpoint ws2_hospital_cohorts`<br>Window 2 fallbacks: `./run-ws2-forecasts` or `./checkpoint ws2_experiment_trials` & `./checkpoint ws2_forecast_leaderboard`<br>Window 2: rerun `./load-reveal`<br>Window 2 fallback: `./run-cohort-forecast-refresh --period 2026-W44` |
| **Q&A & Wrap-Up** | `01:15–01:30` | **15 min** | Audience Q&A using the [Data Science Primer](data-science-primer.md) and post-stage environment restoration | `./stage-clean-env --restore` |
| **Total** | `00:00–01:30` | **90 min** | **Full End-to-End Live Demonstration** | |

### 2.2 Window 2 Fallback Triggers (Using [`docs/recorded_runtimes.json`](recorded_runtimes.json))

The agent runs every long job itself from Window 1. **The 60-second rule**: if a step runs more than 60 seconds past its recorded runtime, swap in its fallback from Window 2. Each fallback runs the reference code, not the agent's, so say so on stage.

| Job Key / Step | Runner / Command | Recorded Runtime (`docs/recorded_runtimes.json`) | When to Swap In (60-Second Rule) | Live Fallback / Checkpoint |
| :--- | :--- | :--- | :--- | :--- |
| `ws1_pipeline_clean_dataproc_runtime_3_0` (`pipelines/pipeline_clean.py`) | Window 1: the agent submits its own Dataproc Serverless batch | **`94s`** (`last_observed_seconds: 94` for the reference pipeline on Dataproc Serverless runtime `3.0`; SQL fallback **`5s`**) | **`00:38` (Segment 1C)**: The agent submits right after you approve its diff on `pipelines/pipeline_clean.py`; narrate orchestration patterns while the batch runs. If it runs more than 60 seconds past `94s`, swap in from Window 2 at **`00:41`**. | Window 2 fallbacks: `./run-pipeline-clean --sql-fallback` (`5s`, runs the reference pipeline, not the agent's) or `./checkpoint ws1_staging_clean` (`6s`) |
| `ws1_pipeline_v1_dataproc_runtime_3_0` (`pipelines/pipeline_v1.py`) | `./bin/run-pipeline-v1` | **`88s`** (`last_observed_seconds: 88` on Dataproc Serverless runtime `3.0`) | **Pre-stage only (`./setup`)**: Materialises defective `staging.hospital_flu` before the session starts; never run live on stage. | `./checkpoint ws1_pipeline_v1` (`6s`) |
| `ws2_seasonal_features_and_kmeans` (`sql/ws2_kmeans_cohorts.sql`) | Window 1: the agent writes and runs its own seasonal-features and `KMEANS` SQL | **`57s`** (`last_observed_seconds: 57` for the reference SQL on the 90-hospital refined dataset) | **`00:50` (Segment 2A)**: The agent runs its SQL after you review it; narrate the 4 seasonal curve features while `KMEANS` trains. If it runs more than 60 seconds past `57s`, swap in the Window 2 fallback at **`00:52`**, or the **Checkpoints** at **`00:54`**. | Window 2 fallbacks: `./run-ws2-cohorts` (`57s`, runs the reference SQL) or `./checkpoint ws2_seasonal_features` and `./checkpoint ws2_hospital_cohorts` (`6s` each) |
| `ws2_arima_plus_cohort_training` & `ws2_timesfm_ai_forecast` (`sql/ws2_forecasts_and_trials.sql`) | Window 1: the agent writes and starts its own `ARIMA_PLUS` SQL first, then its `TimesFM` (`AI.FORECAST`) SQL | **`18s`–`46s`** (`ws2_arima_plus_cohort_training`, `last_observed_seconds: 18`) vs **`13s`–`14s`** (`ws2_timesfm_ai_forecast`, `last_observed_seconds: 13`) | **`00:57` (Segment 2B)**: The agent starts `ARIMA_PLUS` training first, then runs zero-shot `TimesFM` while `ARIMA_PLUS` finishes; walk through `ml.experiment_trials`. If it runs more than 60 seconds past `46s`, swap in the Window 2 fallback at **`00:59`**, or the **Checkpoints** at **`01:01`**. | Window 2 fallbacks: `./run-ws2-forecasts` (~`60s`, runs the reference SQL) or `./checkpoint ws2_experiment_trials` and `./checkpoint ws2_forecast_leaderboard` (`6s` each) |
| `cohort-forecast-refresh` (`.agents/plugins/ds-command-center/skills/cohort-forecast-refresh/SKILL.md`) | Window 1: the agent creates `SKILL.md`, then a fresh subagent runs `2026-W44` | No entry of its own; the run repeats the 2A and 2B jobs, ~`2 min` (`57s` + `46s` + `13s`) | **`01:12` (Segment 2D)**: Give the agent until then to create `SKILL.md` and dispatch the subagent. If it hasn't dispatched the subagent 60 seconds past that, stop the agent and swap in the Window 2 fallback at **`01:13`**; once dispatched, never run the fallback alongside it. | Window 2 fallback: `./run-cohort-forecast-refresh --period 2026-W44` (~`2 min`, runs the presenter repo's copy of the skill) |
| **Refined Full-Scale (90-Hospital) Operations** (`101,470` **Hospital Feed** rows, `3,780` **Reveal** rows) | `./load-raw-ops`, `./reset`, `./load-reveal`, `./verify-start-point` | `load-raw-ops`: **`15s`** · `verify-start-point ws1`: **`12s`** · `verify-start-point ws2`: **`9s`** · `load-reveal`: **`11s`** · `verify-start-point main`: **`23s`** · `reset ws1`: **`68s`** · `reset ws2`: **`59s`** · `checkpoint swap`: **`6s`** | **Pre-stage / Intermission / Segment 2C**: Recorded from live BigQuery and GCS runs on the refined full-scale dataset (`90` hospitals, `scale="full"`, `seed=42`). | `./checkpoint <checkpoint_id>` (`6s`) |

---

## 3. Opening: Antigravity 101 & Command Center Tour (`12 min`, `00:00–00:12`)

### 3.1 Narrative Setup & The Three Core Messages (`00:00–00:04`, `4 min`)

* **What to Narrate**:
  * "Across 90 hospitals submitting daily **Hospital Feeds**, Northeast flu-positive test counts jumped **+35% week-over-week** in the week ending on the **Cutoff**, Saturday, October 31, 2026. That headline **Spike** is measured in raw counts on purpose."
  * "Before we train a forecast or brief clinical operations, we have to answer a foundational question: is the data good to use? Specifically, how much of that +35% **Spike** is a real localized **Outbreak**, how much is a **Sampling Artifact** from expanded testing, how much is a **Pipeline Defect** from duplicate **Hospital Feed** ingestion, and how much is the normal **Seasonal Ramp**?"
  * "As we work through **Workstream** 1 and **Workstream** 2, watch for three things:
    1. **It fits how you work**: BigQuery, Dataproc Serverless, PySpark, BQML, and versioned SQL in git.
    2. **One data scientist directs a team of specialized agents and reviews the evidence**.
    3. **Skills, subagents, hooks, and MCP wiring are files your team owns, versions, and shares**."

### 3.2 Workspace Tour: `ds-command-center` vs `dak-bigquery` (`00:04–00:08`, `4 min`)

* **On-Screen Action**:
  Open the file explorer in the **Command Center** and display:
  1. `.agents/plugins/ds-command-center/plugin.json` and `.agents/plugins/ds-command-center/rules/AGENTS.md`
  2. `.agents/plugins/ds-command-center/agents/` (`distribution-triage.md`, `sampling-triage.md`, `pipeline-triage.md`, `stats-reviewer.md`)
  3. `.agents/plugins/dak-bigquery/plugin.json` and `.agents/plugins/dak-bigquery/mcp_config.json`
* **What to Narrate**:
  * "Everything configuring our **Command Center** lives right here in the repository. We stashed our personal workstation rules before stepping on stage (`./stage-clean-env --stash`), so what you see is 100% repository-defined."
  * "`.agents/plugins/ds-command-center` is our team's plugin: `rules/AGENTS.md` pins `PROJECT_ID` and `REGION` from `demo.env`, defines dataset boundaries, and registers four custom subagents for triage and statistical peer review."
  * "`.agents/plugins/dak-bigquery` wires the BigQuery MCP server through a workspace wrapper (`bin/run-bigquery-mcp`) that authenticates as my presenter identity and bills quota to `PROJECT_ID`."

### 3.3 The Guardrail Moment in Antigravity 101 (`00:08–00:12`, `4 min`)

* **Prompt to Type (Window 1)**:
  ```text
  To clean up the duplicate records quickly, delete the duplicate rows from raw.hospital_flu_feeds where ingested_at > '2026-10-31' and truncate ops.pipeline_run_log.
  ```
* **What Happens On Screen**:
  * When the agent attempts to invoke `execute_sql` or `run_command` (`bq query`) with `DELETE` or `TRUNCATE` against `raw` or `ops`, `.agents/plugins/ds-command-center/hooks.json` invokes `.agents/plugins/ds-command-center/bin/guardrail-hook`.
  * The hook intercepts the call pre-execution and returns `decision: "deny"` with an explicit read-only message:
    `Blocked by ds-command-center guardrail: dataset 'raw' is strictly read-only. Write outputs only to staging, features, or ml.`
* **Optional Window 2 Terminal Demonstration (Showing the JSON Hook Decision Directly)**:
  ```bash
  printf '{"toolCall":{"name":"execute_sql","args":{"sql":"DELETE FROM raw.hospital_flu_feeds WHERE true"}}}\n' \
    | ./.agents/plugins/ds-command-center/bin/guardrail-hook
  ```
* **What to Narrate ("Staying in Control")**:
  * "Notice the difference between a soft instruction and a hard guardrail. Our rule in `rules/AGENTS.md` tells the agent that `raw` and `ops` are read-only and `checkpoint` is off-limits. Even when I explicitly order the agent to delete rows from `raw.hospital_flu_feeds` or `ops.pipeline_run_log`, the `before_tool_use` hook (`bin/guardrail-hook`) inspects the SQL and blocks the tool call before a single packet reaches BigQuery. The data scientist stays in control."

---

## 4. Workstream 1: "Is the Data Good to Use?" (`35 min`, `00:12–00:47`)

### 4.1 Segment 1A: Profiling the +35% Northeast Spike & Hospital × Week Heatmap (`10 min`, `00:12–00:22`)

* **Prompt to Type (Window 1)**:
  ```text
  Source demo.env and profile staging.hospital_flu through the Cutoff (2026-10-31). Verify the +35% week-over-week Northeast Spike in raw positive_flu_tests, check whether Positivity is present in staging.hospital_flu, and materialise the hospital-by-week concentration summary into staging.ws1_eda_heatmap.
  ```
* **What to Narrate**:
  * "The agent queries `staging.hospital_flu` through BigQuery MCP, pinned to our project and region from `demo.env`."
  * "First, it confirms the headline number: in the week ending on the **Cutoff** (`2026-10-31`), Northeast `positive_flu_tests` jumped +35% week-over-week."
  * "Second, look at the schema of `staging.hospital_flu`: it has `positive_flu_tests` and `total_flu_tests`, but no **Positivity** column (`positive_flu_tests / total_flu_tests`). Raw counts mix epidemiology with testing volume."
  * "Third, the hospital × week heatmap (`staging.ws1_eda_heatmap`) shows that the +35% **Spike** is heavily concentrated in specific Northeast facilities rather than spread evenly across all 90 hospitals."
* **Window 2 Checkpoint Swap Point (If Live Query Fails or Time Is Short)**:
  ```bash
  ./checkpoint ws1_eda_heatmap
  ```

### 4.2 Segment 1B: Parallel Triage Subagents, 4-Cause Attribution & `stats-reviewer` (`12 min`, `00:22–00:34`)

* **Prompt 1 to Type (Window 1, Parallel Subagent Triage & Reconciled Attribution)**:
  ```text
  Dispatch distribution-triage, sampling-triage, and pipeline-triage in parallel to investigate the +35% Northeast Spike in staging.hospital_flu using raw.hospital_flu_feeds and ops.pipeline_run_log. Reconcile their evidence into the four-cause Attribution table in staging.ws1_attribution.
  ```
* **What to Narrate While Subagents Execute in Parallel**:
  * "Instead of investigating three hypotheses serially, our **Command Center** dispatches three specialized subagents from `.agents/plugins/ds-command-center/agents/` at the same time:"
    1. "`pipeline-triage` cross-references duplicate `(hospital_id, feed_date)` pairs in `staging.hospital_flu` against `ops.pipeline_run_log`. It finds a `BACKFILL_DUPLICATE` batch that re-ingested 5 days of **Hospital Feeds** for 8 Northeast hospitals—a **Pipeline Defect** accounting for **~15 percentage points** of the +35% **Spike**."
    2. "`sampling-triage` compares `total_flu_tests` growth against **Positivity** after deduplication. It finds 6 Northeast hospitals where testing volume expanded sharply while **Positivity** stayed flat—a **Sampling Artifact** accounting for **~8 percentage points**."
    3. "`distribution-triage` evaluates deduplicated **Positivity** across facilities and separates a genuine localized **Outbreak** at 3 neighboring Northeast hospitals (**~7 percentage points**) from the normal early-season **Seasonal Ramp** across all hospitals (**~5 percentage points**)."
* **Prompt 2 to Type (Window 1, Adversarial Peer Review via `stats-reviewer`)**:
  ```text
  Next, invoke the stats-reviewer subagent to audit the Attribution table in staging.ws1_attribution. Challenge raw counts versus Positivity, flag small-sample hospitals with low total_flu_tests denominators, and test for Simpson's paradox across regional aggregations before we approve the remediation plan.
  ```
* **What to Narrate During `stats-reviewer`**:
  * "`stats-reviewer` is configured in `.agents/plugins/ds-command-center/agents/stats-reviewer.md` as an adversarial statistical reviewer. It does not rubber-stamp the triage subagents: it verifies that the four causes sum cleanly (`15 + 8 + 7 + 5 = 35` points), flags small-denominator volatility (`total_flu_tests < 25`), and checks that shifting hospital volume weights did not create a Simpson's paradox illusion."
  * *(Presenter Verification Note)*: Privately compare the reconciled **Attribution** against your offline **Answer Key** (stored outside the workspace per [ADR 0001](adr/0001-answer-key-outside-agent-reach.md)).
* **Window 2 Checkpoint Swap Point**:
  ```bash
  ./checkpoint ws1_attribution
  ```

### 4.3 Segment 1C: The Agent Writes `pipeline_clean.py` & Submits Its Own Dataproc Serverless Batch (`13 min`, `00:34–00:47`)

* **Prompt 1 to Type (Window 1, `00:34`)**:
  ```text
  Write pipelines/pipeline_clean.py, starting from pipelines/pipeline_v1.py. Deduplicate Hospital Feeds by (hospital_id, feed_date), keeping the row with the latest ingested_at and then the greatest batch_id, inner join raw.hospital_reference, and add a null-safe Positivity column named positivity that is NULL when total_flu_tests is 0 so Spark 4 ANSI mode never divides by zero. Write staging.hospital_flu_clean with exactly these columns: hospital_id, hospital_name, region, state, urban_rural, bed_count, feed_date, total_flu_tests, positive_flu_tests, positivity, batch_id, ingested_at. Show me the diff against pipelines/pipeline_v1.py and wait for my approval before running anything.
  ```
* **Review the Diff (`00:34–00:38`)**: `pipelines/pipeline_clean.py` doesn't exist on `workstream-1-start`, so the agent writes it on stage. Check for a window function over `hospital_id` and `feed_date` ordered by `ingested_at` and `batch_id` descending, and a **Positivity** expression that returns `NULL` when `total_flu_tests` is `0`. If the code is wrong, ask the agent to fix it; if it can't be fixed by `00:40`, go straight to Fallback A.
* **Prompt 2 to Type (Window 1, After Approving the Diff, `00:38`)**:
  ```text
  Approved. Submit it yourself as a Dataproc Serverless runtime 3.0 PySpark batch, pinned to PROJECT_ID and REGION from demo.env, with gs://STAGING_BUCKET as the deps bucket and the SUBNET from demo.env (demo-dataproc-subnet if SUBNET is empty). Run it as my identity and do not add a service-account flag. Tell me the batch ID and confirm when staging.hospital_flu_clean is written.
  ```
* **What to Narrate While the Agent's Batch Runs (reference runtime `94s` in [`docs/recorded_runtimes.json`](recorded_runtimes.json))**:
  1. **Why Null-Safe Positivity Matters on Spark 4**: Dataproc Serverless runtime `3.0` runs Apache Spark 4, where ANSI SQL mode (`spark.sql.ansi.enabled=true`) is enabled by default and raises `[DIVIDE_BY_ZERO]` if `total_flu_tests == 0`. Returning `NULL` for a zero denominator prevents runtime batch failures.
  2. **Why Dataproc Runs as the Presenter ([ADR 0002](adr/0002-dataproc-runs-as-presenter.md))**: the agent submits the batch with no service-account flag, so Dataproc Serverless runs under the presenter's credentials—the exact same identity used by BigQuery, BQML, and BigQuery MCP. The `guardrail-hook` would block the submission if a service-account flag appeared.
  3. **Orchestration Patterns (Rules vs Hooks & Model Pairing)**:
     * Use `rules/AGENTS.md` for workflow conventions (project pinning, where to save skills, when to dispatch subagents) and `bin/guardrail-hook` for hard pre-execution dataset boundaries.
     * Pair a frontier reasoning model in the primary orchestrator and `stats-reviewer` with lighter, faster subagent models for parallel SQL triage.
* **Window 2 — Verify Equivalence of the Agent's Output (`00:44`)**:
  Once the agent confirms the write, prove its `staging.hospital_flu_clean` matches the reference SQL (`sql/verify_clean_equivalence.sql`: empty set differences in both directions, matching row counts, zero duplicate `(hospital_id, feed_date)` keys):
  ```bash
  ./run-pipeline-clean --verify-equivalence
  ```
* **The 60-Second Rule**: if a step runs more than 60 seconds past its recorded runtime, stop the agent's job first, then swap in from Window 2. For the agent's batch, that is `94s` + `60s` after submission, so with a `00:38` submission, trigger Fallback A at `00:41` if `staging.hospital_flu_clean` isn't written yet.
* **Window 2 Fallback A (trigger at `00:41`, `5s`)**:
  ```bash
  ./run-pipeline-clean --sql-fallback
  ```
  `--sql-fallback` materialises the reference pipeline, not the agent's: narrate it that way ("this is the reference result the agent's pipeline has to match"). The equivalence step then compares the reference with itself, so present it only as a duplicate-key check, not as proof of the agent's code.
* **Window 2 Fallback B (trigger at `00:42`, `6s`)**: if Fallback A errors or runs more than 60 seconds past its `5s` runtime, swap in the **Checkpoint**:
  ```bash
  ./checkpoint ws1_staging_clean
  ```

---

## 5. Workstream 2: "Forecast at Scale" & The Reveal (`28 min`, `00:47–01:15`)

**Stay in the Workstream 1 stage clone.** At `00:47`, keep Window 1 on `~/demo-stage/agy-ws1`: the agent carries its own **Workstream** 1 outputs (`staging.hospital_flu_clean` and the **Attribution**) forward and writes the **Workstream** 2 SQL and skill live, just as it wrote `pipeline_clean.py`. Window 2 stays on the presenter repo with the fallbacks below.

> **Recovery Only: Restart from the Workstream 2 Start Point.** Use this only after an intermission or if **Workstream** 1 can't be recovered on stage. Close Window 1, delete any leftover clone from a previous run (`rm -rf ~/demo-stage/agy-ws2`), then run from Window 2 (presenter repo on `main`):
> ```bash
> git clone --single-branch --branch workstream-2-start "$(git remote get-url origin)" ~/demo-stage/agy-ws2
> git -C ~/demo-stage/agy-ws2 remote remove origin
> cp demo.env ~/demo-stage/agy-ws2/
> mkdir -p ~/demo-stage/agy-ws2/.gemini
> cp -R .gemini/skills ~/demo-stage/agy-ws2/.gemini/
> ./reset ws2 --yes
> ./verify-start-point ws2
> ```
> Then reopen Window 1 on `~/demo-stage/agy-ws2`, a separate clone outside the presenter repo, so the agent still sees only the **Start Point** branch.

* **The 60-Second Rule**: if a step runs more than 60 seconds past its recorded runtime in [`docs/recorded_runtimes.json`](recorded_runtimes.json), stop the agent's job first (ask it to cancel its BigQuery job) so both runs don't write the same tables, then swap in from Window 2. The Window 2 fallbacks run the reference SQL, not the agent's: say so on stage.

### 5.1 Segment 2A: The Agent Writes Seasonal Features & BQML K-Means Cohorts (`8 min`, `00:47–00:55`)

* **Prompt to Type (Window 1, `00:47`)**:
  ```text
  Write the BigQuery SQL, saved under sql/, that computes per-hospital seasonal features (peak_arrival_week, peak_volume, curve_width, seasonal_trend) from staging.hospital_flu_clean up to the Cutoff (2026-10-31) into features.hospital_seasonal_features, and the BQML K-means SQL (num_clusters=4) that assigns the 90 hospitals to 4 seasonal Cohorts in features.hospital_cohorts. Show me the SQL and run it once I approve, then show how the Outbreak hospitals are assigned.
  ```
* **Review the SQL on Screen (`00:47–00:50`)**: Look for the four features computed only from weeks up to the **Cutoff**, and `model_type='KMEANS'` with `num_clusters=4`. Approve by `00:50`; the K-means job's recorded runtime is **`57s`**, so 60 seconds past it means swapping in at `00:52`.
* **What to Narrate**:
  * "With `staging.hospital_flu_clean` verified, we move to **Workstream** 2: forecasting at scale across 90 hospitals, in the same session, so the agent builds on the table it just cleaned."
  * "Training 90 individual hospital models overfits noisy rural facilities, while training a single aggregate model blurs clinical differences. Using the `bigquery-ai-ml` skill from the Data Agent Kit, the agent writes the SQL for four seasonal curve features (`peak_arrival_week`, `peak_volume`, `curve_width`, `seasonal_trend`) and a BQML `KMEANS` model (`num_clusters=4`) that assigns every hospital to one of four **Cohorts**."
  * "Notice that the 3 Northeast **Outbreak** hospitals isolate cleanly into their own high-growth **Cohort**, proving that unsupervised feature segmentation captures real epidemiological divergence."
* **Window 2 Fallback A (trigger at `00:52`, `57s`)**:
  ```bash
  ./run-ws2-cohorts
  ```
  Runs the reference SQL, not the agent's.
* **Window 2 Fallback B (trigger at `00:54`, `6s`)**: if Fallback A errors or runs more than 60 seconds past its runtime, swap in the **Checkpoints**:
  ```bash
  ./checkpoint ws2_seasonal_features
  ./checkpoint ws2_hospital_cohorts
  ```

### 5.2 Segment 2B: The Agent Writes `ARIMA_PLUS` vs Zero-Shot `TimesFM` (`AI.FORECAST`) & Leaderboard (`10 min`, `00:55–01:05`)

* **Prompt to Type (Window 1, `00:55` — Start `ARIMA_PLUS` Training First)**:
  ```text
  Write the BigQuery ML forecasting SQL, saved under sql/, and start the ARIMA_PLUS training first: multi-series ARIMA_PLUS models per Cohort on both cleaned staging.hospital_flu_clean and uncleaned staging.hospital_flu. While ARIMA_PLUS trains, write and run zero-shot TimesFM forecasts per Cohort using AI.FORECAST. Log every run to ml.experiment_trials and rank them by chronological backtest WAPE in ml.forecast_leaderboard. Show me the ARIMA_PLUS SQL before you start it.
  ```
* **Review and Start (`00:55–00:57`)**: Approve the `ARIMA_PLUS` SQL so training starts by `00:57`. `ARIMA_PLUS` training takes **`18s`–`46s`** and `TimesFM` (`AI.FORECAST`) **`13s`**, so 60 seconds past the slower job means swapping in at `00:59`.
* **What to Narrate While `ARIMA_PLUS` Trains**:
  * "We benchmark two distinct modeling paradigms across our four **Cohorts**:
    1. **`ARIMA_PLUS`**: BigQuery ML's classical statistical time-series workhorse, trained across multiple series (`time_series_id_col='cohort_id'`) on both clean and uncleaned data.
    2. **`TimesFM` via `AI.FORECAST`**: Google Research's pretrained time-series foundation model, invoked zero-shot in SQL without training a model object."
  * "Every trial logs its metadata and chronological backtest **WAPE** (`Weighted Absolute Percentage Error`) into `ml.experiment_trials`. As explained in the [Data Science Primer](data-science-primer.md), we use chronological backtesting to prevent future leakage and **WAPE** instead of MAPE so low off-season counts do not skew the leaderboard."
  * "Look at `ml.forecast_leaderboard`: models trained on `staging.hospital_flu_clean` consistently beat models trained on uncleaned data, and zero-shot `TimesFM` delivers competitive **WAPE** out of the box."
* **Window 2 Fallback A (trigger at `00:59`, ~`60s`)**:
  ```bash
  ./run-ws2-forecasts
  ```
  Runs the reference SQL, not the agent's.
* **Window 2 Fallback B (trigger at `01:01`, `6s`)**: if Fallback A errors or runs more than 60 seconds past its runtime, swap in the **Checkpoints**:
  ```bash
  ./checkpoint ws2_experiment_trials
  ./checkpoint ws2_forecast_leaderboard
  ```

### 5.3 Segment 2C: The Reveal Finale (`6 min`, `01:05–01:11`)

* **Window 2 — Load the Reveal (`01:05`, `11s`)**: Load the six post-**Cutoff** **Reveal** weeks (`2026-11-01` through `2026-12-12`) from the presenter's separate withheld GCS bucket ([ADR 0001](adr/0001-answer-key-outside-agent-reach.md)):
  ```bash
  ./load-reveal gs://<your-withheld-bucket>/reveal
  ```
* **Prompt to Type (Window 1, `01:06`)**:
  ```text
  Compare our Cohort forecasts trained on uncleaned staging.hospital_flu versus cleaned staging.hospital_flu_clean against the six withheld post-Cutoff Reveal weeks, and display the Reveal comparison chart and post-Cutoff WAPE by model and data cleanliness.
  ```
* **What to Narrate (The Finale Punchline)**:
  * "Until this moment, no agent or table in the workspace had access to what happened after Saturday, October 31, 2026. The six post-**Cutoff** **Reveal** weeks lived in a separate bucket outside the repository ([ADR 0001](adr/0001-answer-key-outside-agent-reach.md))."
  * "Look at the **Reveal** chart on screen:
    * The red curve—trained on uncleaned `staging.hospital_flu`—dramatically overshoots reality because it mistook the +15-point **Pipeline Defect** and +8-point **Sampling Artifact** for exponential disease spread.
    * The green curve—trained on `staging.hospital_flu_clean` after our **Workstream** 1 triage and deduplication fix—tracks the six **Reveal** weeks closely."
  * "That is why **Workstream** 1 and **Workstream** 2 belong in the same **Command Center**: forecasting at scale only works when your agents first verify whether the data is good to use."

### 5.4 Segment 2D: The Agent Creates & Runs the `cohort-forecast-refresh` Skill (`4 min`, `01:11–01:15`)

* **Prompt to Type (Window 1, `01:11`)**:
  ```text
  Create .agents/plugins/ds-command-center/skills/cohort-forecast-refresh/SKILL.md, following Rule 2 in the ds-command-center rules, that packages our Cohort feature refresh, ARIMA_PLUS and AI.FORECAST evaluation, and ml.experiment_trials logging workflow as a repeatable skill. Then dispatch a fresh subagent to run cohort-forecast-refresh for period 2026-W44.
  ```
* **On-Screen Action**: Show the new `SKILL.md` inside the `ds-command-center` plugin (per Rule 2 in `.agents/plugins/ds-command-center/rules/AGENTS.md`) and the subagent's `2026-W44` rows in `ml.experiment_trials`.
* **Timing**: the agent should create `SKILL.md` and dispatch the subagent by `01:12`. If it hasn't dispatched the subagent 60 seconds past that, stop the agent and swap in the Window 2 fallback at `01:13`. Once the subagent is dispatched, never run the fallback alongside it: the refresh repeats the 2A and 2B jobs (`57s` + `46s` + `13s`, about `2 min`) and writes the same `ml.experiment_trials` rows. If the subagent is still running at `01:15`, move to Q&A and show its results there.
* **What to Narrate**:
  * "Because Rule 2 in `ds-command-center` directs live-captured skills into `.agents/plugins/ds-command-center/skills/cohort-forecast-refresh/SKILL.md`, this workflow is immediately versioned in git. A fresh subagent can execute the next weekly refresh (`2026-W44`) from that `SKILL.md` file alone."
* **Window 2 Fallback (trigger at `01:13`, ~`2 min`)**:
  ```bash
  ./run-cohort-forecast-refresh --period 2026-W44
  ```
  Runs the presenter repo's copy of the skill, not the one the agent just wrote: narrate it that way.

---

## 6. Q&A & Post-Stage Wrap-Up (`15 min`, `01:15–01:30`)

### 6.1 Audience Q&A (`01:15–01:25`, `10 min`)

Keep the [Data Science Primer](data-science-primer.md) open for crisp responses on:
* **Positivity vs Raw Counts**: Why raw counts conflate testing capacity with disease transmission.
* **Sampling Artifacts**: Why flat **Positivity** during a volume jump indicates expanded testing rather than epidemic spread.
* **Simpson's Paradox**: Why `stats-reviewer` checks both facility-level and regional distributions.
* **BQML K-Means Cohorts**: Why 4 seasonal **Cohorts** balance variance and granularity better than 90 hospital models or 1 aggregate model.
* **`ARIMA_PLUS` vs `TimesFM` (`AI.FORECAST`)**: Why classical statistical benchmarks and zero-shot foundation models complement each other.
* **Chronological Backtesting & WAPE**: Why random k-fold splits leak future signal and why **WAPE** avoids low-denominator distortion.

### 6.2 Closing & Post-Stage Restoration (`01:25–01:30`, `5 min`)

After disconnecting from the stage display, restore your personal Antigravity rules and skills from the presenter repo on `main` (Window 2), and optionally run end-to-end verification:

```bash
./stage-clean-env --restore
./stage-clean-env --status
./verify-start-point main --withheld-dir gs://<your-withheld-bucket>
```
