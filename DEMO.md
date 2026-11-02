# How to Demo: Antigravity for Data Scientists (`DEMO.md`)

Complete live demonstration guide for presenting **Antigravity for Data Scientists** in the **Command Center**. This guide gives you the scenario setup, the 15-minute pre-stage checklist, the master schedule with early-start triggers, exact copy-paste prompts to type on stage, speaker narration points, instant **Checkpoint** fallback commands, and shortened 45/60-minute cuts.

For initial Google Cloud project provisioning, see [README.md](README.md) and the [Reuser Setup & Operations Guide](docs/reuser-guide.md). For deep statistical Q&A preparation, see the [Data Science Primer](docs/data-science-primer.md). All terminology follows [GLOSSARY.md](GLOSSARY.md).

---

## Table of Contents

1. [The Story & What the Audience Sees](#1-the-story--what-the-audience-sees)
2. [Pre-Stage Checklist (T-15 Minutes)](#2-pre-stage-checklist-t-15-minutes)
3. [Master 90-Minute Timeline & Early-Start Matrix](#3-master-90-minute-timeline--early-start-matrix)
4. [Act-by-Act Live Demo Script](#4-act-by-act-live-demo-script)
   - [Opening: Antigravity 101 & The Guardrail Moment (00:00–00:12)](#41-opening-antigravity-101--the-guardrail-moment-12-min-00000012)
   - [Workstream 1: "Is the Data Good to Use?" (00:12–00:47)](#42-workstream-1-is-the-data-good-to-use-35-min-00120047)
   - [Workstream 2: "Forecast at Scale" & The Reveal (00:47–01:15)](#43-workstream-2-forecast-at-scale--the-reveal-28-min-00470115)
   - [Q&A & Post-Stage Restoration (01:15–01:30)](#44-qa--post-stage-restoration-15-min-01150130)
5. [Shortened Demo Cuts (45-Minute & 60-Minute Formats)](#5-shortened-demo-cuts-45-minute--60-minute-formats)
6. [Cross-Industry Narrative Translation Matrix](#6-cross-industry-narrative-translation-matrix)
7. [Presenter Q&A Quick-Reference Cheat Sheet](#7-presenter-qa-quick-reference-cheat-sheet)

---

## 1. The Story & What the Audience Sees

### The Scenario

Across 90 hospitals submitting daily **Hospital Feeds**, Northeast flu-positive test counts (`positive_flu_tests`) jump **+35.0% week-over-week** in the week ending on the **Cutoff**, Saturday, October 31, 2026.

Clinical leadership wants to know immediately: **Are we facing a regional epidemic, or is something wrong with the data?**

Behind the scenes, the external **Data Generator** planted four distinct causes inside that +35.0% Northeast **Spike**:

| Planted Cause | Share of the +35.0% Spike | What Actually Happened in the Data |
| :--- | :---: | :--- |
| **Pipeline Defect** | **`15.0` pts** | A `BACKFILL_DUPLICATE` batch in `ops.pipeline_run_log` re-ingested 5 days of **Hospital Feeds** across 8 Northeast hospitals (`40` duplicate rows). |
| **Sampling Artifact** | **`8.0` pts** | 6 Northeast hospitals expanded walk-in testing volume (`total_flu_tests` jumped) while **Positivity** (`positive_flu_tests / total_flu_tests`) stayed flat. |
| **Outbreak** | **`7.0` pts** | 3 neighboring Northeast hospitals (`HOSP_NE_001`, `HOSP_NE_004`, `HOSP_NE_006`) experienced a genuine surge in **Positivity** (`~6.0%` → `~16.3%`). |
| **Seasonal Ramp** | **`5.0` pts** | The expected autumn rise in flu activity across all hospitals entering late October. |
| **Total Reconciled Spike** | **`35.0` pts** | **100% of the headline +35.0% Northeast Spike accounted for.** |

### Three Core Takeaways to Land on Stage

1. **It fits how your team works**: BigQuery, Dataproc Serverless, PySpark, BigQuery ML (`KMEANS`, `ARIMA_PLUS`, `AI.FORECAST`), and versioned SQL in git.
2. **One data scientist directs a team of specialized agents and reviews the evidence**: Parallel triage subagents and an adversarial `stats-reviewer` investigate hypotheses concurrently, while the human data scientist approves code diffs before execution.
3. **Skills, subagents, hooks, and MCP wiring are files your team owns, versions, and shares**: Everything powering the **Command Center** lives in `.agents/plugins/` inside the repository.

---

## 2. Pre-Stage Checklist (T-15 Minutes)

Run these four steps in your terminal before connecting to the projector or starting your screen share:

### Step 1: Isolate Personal Rules & Skills (`./stage-clean-env --stash`)

Stash personal rules (`~/.gemini/rules`, `~/.gemini/config/rules`, `~/.gemini/AGENTS.md`) and personal non-DAK skills so only the repository's `.agents/plugins/ds-command-center`, `.agents/plugins/dak-bigquery`, and workspace `.gemini/skills/` load on stage:

```bash
./stage-clean-env --stash
./stage-clean-env --status
```

### Step 2: Source `demo.env` & Run the 12-Point Preflight Check

```bash
source demo.env
./preflight
```

Verify that all 12 checks report `[PASS]` (including BigQuery MCP presenter auth, `guardrail-hook` enforcement, BigQuery ML `AI.FORECAST` + `KMEANS`, subagent dispatch, and Java 21).

### Step 3: Reset & Verify the Workstream 1 Start Point

Switch to the `workstream-1-start` branch, reset the working BigQuery datasets (`staging`, `features`, `ml`) to the **Workstream** 1 **Start Point**, and verify parity against `checkpoint`:

```bash
git checkout workstream-1-start
./reset ws1 --yes
./verify-start-point ws1
```

### Step 4: Arrange Your Two Stage Windows

1. **Window 1 — Command Center (Antigravity)**: Open at the repository root after `./stage-clean-env --stash` has completed.
2. **Window 2 — Presenter Terminal**: Open at the repository root with `source demo.env` active. Run `./checkpoint --list` so you can trigger background jobs or swap a **Checkpoint** in ~6 seconds if needed.

---

## 3. Master 90-Minute Timeline & Early-Start Matrix

### 3.1 Segment Schedule (`90 min` Total)

| Segment | Clock | Duration | On-Stage Focus | Instant Checkpoint Fallback (`~6s`) |
| :--- | :---: | :---: | :--- | :--- |
| **Opening: Antigravity 101 & Guardrail Moment** | `00:00–00:12` | **12 min** | Narrative framing (`+35%` Northeast **Spike** through **Cutoff** `2026-10-31`), tour of `.agents/plugins/`, live `guardrail-hook` block | *(N/A — blocked pre-execution)* |
| **Segment 1A: EDA & Hospital × Week Heatmap** | `00:12–00:22` | **10 min** | Confirm +35% **Spike** in `staging.hospital_flu`, note missing **Positivity**, materialise `staging.ws1_eda_heatmap` | `./checkpoint ws1_eda_heatmap` |
| **Segment 1B: Parallel Triage & `stats-reviewer`** | `00:22–00:34` | **12 min** | Dispatch 3 triage subagents in parallel, build `staging.ws1_attribution`, run adversarial `stats-reviewer` audit | `./checkpoint ws1_attribution` |
| **Segment 1C: PySpark Diff & Dataproc Serverless** | `00:34–00:47` | **13 min** | Review `git diff` (`pipeline_v1.py` vs `pipeline_clean.py`), early-start Dataproc batch (`00:36`), verify SQL equivalence | `./run-pipeline-clean --sql-fallback` *(5s)* or `./checkpoint ws1_staging_clean` *(6s)* |
| **Segment 2A: Seasonal Features & K-Means Cohorts** | `00:47–00:55` | **8 min** | Engineer 4 seasonal curve features, train BQML `KMEANS` (`num_clusters=4`), isolate the 3 **Outbreak** hospitals | `./checkpoint ws2_seasonal_features`<br>`./checkpoint ws2_hospital_cohorts` |
| **Segment 2B: `ARIMA_PLUS` vs `TimesFM` (`AI.FORECAST`)** | `00:55–01:05` | **10 min** | Early-start multi-series `ARIMA_PLUS` (`00:55`), run zero-shot `TimesFM`, rank by backtest **WAPE** in `ml.forecast_leaderboard` | `./checkpoint ws2_experiment_trials`<br>`./checkpoint ws2_forecast_leaderboard` |
| **Segment 2C: The Reveal Finale** | `01:05–01:11` | **6 min** | Load 6 post-**Cutoff** **Reveal** weeks (`./load-reveal`), compare clean vs uncleaned forecasts against reality | `./load-reveal gs://<withheld-bucket>/reveal` |
| **Segment 2D: Codify `cohort-forecast-refresh` Skill** | `01:11–01:15` | **4 min** | Package workflow into `.agents/plugins/ds-command-center/skills/cohort-forecast-refresh/SKILL.md` and run `2026-W44` | `./run-cohort-forecast-refresh --period 2026-W44` |
| **Q&A & Wrap-Up** | `01:15–01:30` | **15 min** | Audience Q&A defense & `./stage-clean-env --restore` | `./stage-clean-env --restore` |

### 3.2 Early-Start Triggers for Longer Jobs ([`docs/recorded_runtimes.json`](docs/recorded_runtimes.json))

| Step | Command | Recorded Runtime | When to Trigger on Stage | Fast Fallback (`5s–6s`) |
| :--- | :--- | :---: | :--- | :--- |
| **Workstream 1C Dataproc Clean Batch** | `./run-pipeline-clean --async` | **`94s`** | Trigger at **`00:36`** right after approving the `git diff`, then narrate Spark 4 ANSI mode and [ADR 0002](docs/adr/0002-dataproc-runs-as-presenter.md) while the batch runs. | `./run-pipeline-clean --sql-fallback` (`5s`) or `./checkpoint ws1_staging_clean` (`6s`) |
| **Workstream 2A BQML K-Means Cohorts** | `./run-ws2-cohorts` | **`57s`** | Trigger at **`00:47`** at the start of Segment 2A, then explain the 4 seasonal curve features while `KMEANS` trains. | `./checkpoint ws2_seasonal_features` & `./checkpoint ws2_hospital_cohorts` (`6s`) |
| **Workstream 2B `ARIMA_PLUS` + `TimesFM`** | `./run-ws2-forecasts` | **`18s`–`46s`** (`ARIMA_PLUS`) / **`13s`** (`TimesFM`) | Trigger `ARIMA_PLUS` training first at **`00:55`**, then run zero-shot `TimesFM` (`AI.FORECAST`) while `ARIMA_PLUS` completes. | `./checkpoint ws2_experiment_trials` & `./checkpoint ws2_forecast_leaderboard` (`6s`) |

---

## 4. Act-by-Act Live Demo Script

### 4.1 Opening: Antigravity 101 & The Guardrail Moment (`12 min`, `00:00–00:12`)

#### Part A: Frame the Problem (`00:00–00:04`)
* **Say to the Audience**:
  > "Across 90 hospitals submitting daily **Hospital Feeds**, Northeast flu-positive test counts jumped **+35% week-over-week** in the week ending on the **Cutoff**, Saturday, October 31, 2026. Before we brief clinical leadership or train a forecast, we have to answer a foundational question: **is the data good to use?** How much of that +35% **Spike** is a real localized **Outbreak**, how much is a **Sampling Artifact** from expanded testing, how much is a **Pipeline Defect** from duplicate ingestion, and how much is the normal **Seasonal Ramp**?"

#### Part B: Tour the Repository-Owned Command Center (`00:04–00:08`)
* **Show on Screen**:
  1. `.agents/plugins/ds-command-center/rules/AGENTS.md` (team rules pinning `PROJECT_ID` and `REGION` from `demo.env`, enforcing read-only `raw` and `ops`, and registering subagents).
  2. `.agents/plugins/ds-command-center/agents/` (`distribution-triage.md`, `sampling-triage.md`, `pipeline-triage.md`, `stats-reviewer.md`).
  3. `.agents/plugins/dak-bigquery/mcp_config.json` and `.agents/plugins/dak-bigquery/bin/run-bigquery-mcp` (BigQuery MCP running under presenter user OAuth credentials).

#### Part C: Live Guardrail Moment (`00:08–00:12`)
* **Type This Prompt into the Command Center**:
  ```text
  To clean up the duplicate records quickly, delete the duplicate rows from raw.hospital_flu_feeds where ingested_at > '2026-10-31' and truncate ops.pipeline_run_log.
  ```
* **What Happens Live**:
  `.agents/plugins/ds-command-center/hooks.json` invokes `.agents/plugins/ds-command-center/bin/guardrail-hook` on `before_tool_use`, inspecting the SQL and returning `decision: "deny"` before any packet reaches BigQuery:
  `Blocked by ds-command-center guardrail: dataset 'raw' is strictly read-only. Write outputs only to staging, features, or ml.`
* **Optional Terminal Verification**:
  ```bash
  printf '{"toolCall":{"name":"execute_sql","args":{"sql":"DELETE FROM raw.hospital_flu_feeds WHERE true"}}}\n' \
    | ./.agents/plugins/ds-command-center/bin/guardrail-hook
  ```
* **Say to the Audience**:
  > "Notice the difference between a soft prompt instruction and a hard deterministic guardrail. Even when I explicitly instruct the agent to delete rows from `raw.hospital_flu_feeds` or truncate `ops.pipeline_run_log`, the `before_tool_use` hook blocks the call pre-execution. The data scientist stays in control."

---

### 4.2 Workstream 1: "Is the Data Good to Use?" (`35 min`, `00:12–00:47`)

#### Segment 1A: Exploratory Profiling & Hospital × Week Heatmap (`00:12–00:22`)
* **Type This Prompt into the Command Center**:
  ```text
  Source demo.env and profile staging.hospital_flu through the Cutoff (2026-10-31). Verify the +35% week-over-week Northeast Spike in raw positive_flu_tests, check whether Positivity is present in staging.hospital_flu, and materialise the hospital-by-week concentration summary into staging.ws1_eda_heatmap.
  ```
* **Key Evidence Shown**:
  1. Northeast `positive_flu_tests` rose **+35.0%** in the **Spike** week (`2026-10-25`..`2026-10-31`) vs the prior week (`2026-10-18`..`2026-10-24`).
  2. `staging.hospital_flu` lacks a **Positivity** column (`positive_flu_tests / total_flu_tests`), mixing disease prevalence with testing volume.
  3. `staging.ws1_eda_heatmap` shows the jump is concentrated in a subset of Northeast hospitals rather than uniform across all 90 facilities.
* **Checkpoint Fallback**:
  ```bash
  ./checkpoint ws1_eda_heatmap
  ```

#### Segment 1B: Parallel Triage Subagents, 4-Cause Attribution & `stats-reviewer` (`00:22–00:34`)
* **Prompt 1 — Dispatch the Three Triage Subagents in Parallel**:
  ```text
  Dispatch distribution-triage, sampling-triage, and pipeline-triage in parallel to investigate the +35% Northeast Spike in staging.hospital_flu using raw.hospital_flu_feeds and ops.pipeline_run_log. Reconcile their evidence into the four-cause Attribution table in staging.ws1_attribution.
  ```
* **What the Three Subagents Find Concurrently**:
  - **`pipeline-triage`**: Correlates `staging.hospital_flu` duplicates with `ops.pipeline_run_log` (`BACKFILL_DUPLICATE`), isolating **`15.0` percentage points** of **Pipeline Defect** across 8 Northeast hospitals (`40` duplicate rows).
  - **`sampling-triage`**: Identifies 6 Northeast hospitals where `total_flu_tests` expanded sharply while deduplicated **Positivity** remained flat, isolating **`8.0` percentage points** of **Sampling Artifact**.
  - **`distribution-triage`**: Separates a localized **Outbreak** at 3 Northeast hospitals (`HOSP_NE_001`, `HOSP_NE_004`, `HOSP_NE_006`, **`7.0` percentage points**) from the broad **Seasonal Ramp** (**`5.0` percentage points**).
* **Prompt 2 — Challenge the Attribution with `stats-reviewer`**:
  ```text
  Next, invoke the stats-reviewer subagent to audit the Attribution table in staging.ws1_attribution. Challenge raw counts versus Positivity, flag small-sample hospitals with low total_flu_tests denominators, and test for Simpson's paradox across regional aggregations before we approve the remediation plan.
  ```
* **Say to the Audience**:
  > "`stats-reviewer` is an adversarial peer reviewer. It checks that the four causes sum to the full +35.0% **Spike** (`15 + 8 + 7 + 5 = 35`), flags small-sample denominator volatility, and tests for Simpson's paradox before we sign off on pipeline changes."
* **Checkpoint Fallback**:
  ```bash
  ./checkpoint ws1_attribution
  ```

#### Segment 1C: Reviewing the PySpark Diff & Running Dataproc Serverless (`00:34–00:47`)
* **Type This Prompt into the Command Center (`00:34`)**:
  ```text
  Show the git diff between pipelines/pipeline_v1.py and pipelines/pipeline_clean.py. Explain how the window function deduplicates Hospital Feeds by (hospital_id, feed_date) and why Positivity uses a null-safe check for Spark 4 ANSI mode. Wait for my approval before running the pipeline.
  ```
* **Early-Start Action (`00:36`)**:
  Once you review the `Window.partitionBy("hospital_id", "feed_date").orderBy(F.col("ingested_at").desc(), F.col("batch_id").desc())` deduplication and `F.when(F.col("total_flu_tests") == 0, F.lit(None).cast("double"))` **Positivity** calculation on screen, kick off the Dataproc Serverless batch:
  ```bash
  ./run-pipeline-clean --async
  ```
* **Verify Equivalence (`00:45`)**:
  ```bash
  ./run-pipeline-clean --verify-equivalence
  ```
  *(Confirms `101,430` deduplicated rows in `staging.hospital_flu_clean`, `0` duplicates, and `0` row differences against `sql/ws1_pipeline_clean_equiv.sql`).*
* **Fast Fallback (`5s–6s`)**:
  ```bash
  ./run-pipeline-clean --sql-fallback
  # or:
  ./checkpoint ws1_staging_clean
  ```

---

### 4.3 Workstream 2: "Forecast at Scale" & The Reveal (`28 min`, `00:47–01:15`)

> **Starting After an Intermission?** You can jump directly to the **Workstream** 2 **Start Point** at any time with:
> ```bash
> git checkout workstream-2-start
> ./reset ws2 --yes
> ./verify-start-point ws2
> ```

#### Segment 2A: Seasonal Features & BQML K-Means Hospital Cohorts (`00:47–00:55`)
* **Type This Prompt into the Command Center**:
  ```text
  Using staging.hospital_flu_clean up to the Cutoff (2026-10-31), compute per-hospital seasonal features (peak_arrival_week, peak_volume, curve_width, seasonal_trend) in features.hospital_seasonal_features and assign the 90 hospitals into 4 seasonal Cohorts using BQML K-means in features.hospital_cohorts. Show how the Outbreak hospitals are assigned.
  ```
* **Key Evidence Shown**:
  - Rather than training 90 noisy hospital models or 1 overly broad aggregate model, BQML `KMEANS` (`ml.hospital_cohort_kmeans`) groups the 90 hospitals into 4 **Cohorts** using four orthogonal curve geometry features.
  - The 3 Northeast **Outbreak** hospitals (`HOSP_NE_001`, `HOSP_NE_004`, `HOSP_NE_006`, with `seasonal_trend = 2.7143`) isolate cleanly into their own dedicated 3-hospital **Cohort**.
* **Checkpoint Fallbacks**:
  ```bash
  ./checkpoint ws2_seasonal_features
  ./checkpoint ws2_hospital_cohorts
  ```

#### Segment 2B: `ARIMA_PLUS` vs Zero-Shot `TimesFM` (`AI.FORECAST`) & WAPE Leaderboard (`00:55–01:05`)
* **Type This Prompt into the Command Center (`00:55` — Start `ARIMA_PLUS` First!)**:
  ```text
  Start training the multi-series BQML ARIMA_PLUS models per Cohort on both cleaned staging.hospital_flu_clean and uncleaned staging.hospital_flu first. Next, run zero-shot TimesFM forecasts per Cohort using AI.FORECAST, log all runs to ml.experiment_trials, and rank them by chronological backtest WAPE in ml.forecast_leaderboard.
  ```
* **Key Evidence Shown**:
  - `ml.experiment_trials` records model family (`ARIMA_PLUS` vs `TimesFM`), training data state (`clean` vs `uncleaned`), **Cohort**, and chronological backtest **WAPE**.
  - `ml.forecast_leaderboard` proves that models trained on `staging.hospital_flu_clean` beat uncleaned models across every **Cohort**, and zero-shot `TimesFM` (`AI.FORECAST`) delivers competitive accuracy without training a model object.
* **Checkpoint Fallbacks**:
  ```bash
  ./checkpoint ws2_experiment_trials
  ./checkpoint ws2_forecast_leaderboard
  ```

#### Segment 2C: The Reveal Finale (`01:05–01:11`)
* **Run in the Presenter Terminal**:
  Supply your separate withheld Cloud Storage bucket URI (stored outside the repo per [ADR 0001](docs/adr/0001-answer-key-outside-agent-reach.md)) to load the six post-**Cutoff** **Reveal** weeks (`2026-11-01` through `2026-12-12`):
  ```bash
  ./load-reveal gs://<your-withheld-bucket>/reveal
  ```
* **Type This Prompt into the Command Center**:
  ```text
  Compare our Cohort forecasts trained on uncleaned staging.hospital_flu versus cleaned staging.hospital_flu_clean against the six withheld post-Cutoff Reveal weeks, and display the Reveal comparison chart and post-Cutoff WAPE by model and data cleanliness.
  ```
* **Say to the Audience (The Finale Punchline)**:
  > "Until this moment, no agent or table in the workspace had access to what happened after Saturday, October 31, 2026. Look at `ml.reveal_forecast_evaluation`: the forecast trained on uncleaned `staging.hospital_flu` dramatically overshoots the six **Reveal** weeks because it mistook the +15-point **Pipeline Defect** and +8-point **Sampling Artifact** for exponential disease spread. The forecast trained on `staging.hospital_flu_clean` tracks reality tightly (`WAPE ~0.075` vs `~0.165` on uncleaned data). That is why **Workstream** 1 and **Workstream** 2 belong in the same **Command Center**."

#### Segment 2D: Codify & Run the `cohort-forecast-refresh` Skill (`01:11–01:15`)
* **Type This Prompt into the Command Center**:
  ```text
  Package our Cohort feature refresh, ARIMA_PLUS and AI.FORECAST evaluation, and ml.experiment_trials logging workflow into .agents/plugins/ds-command-center/skills/cohort-forecast-refresh/SKILL.md, then dispatch a fresh subagent to run cohort-forecast-refresh for period 2026-W44.
  ```
* **Terminal Verification**:
  ```bash
  ./run-cohort-forecast-refresh --period 2026-W44
  ```

---

### 4.4 Q&A & Post-Stage Restoration (`15 min`, `01:15–01:30`)

After finishing Audience Q&A and disconnecting from the stage display, restore your personal `~/.gemini` rules and skills:

```bash
./stage-clean-env --restore
./stage-clean-env --status
```

To verify that the entire post-**Reveal** environment matches the **Answer Key** and all **Checkpoints**:

```bash
./verify-start-point main --withheld-dir gs://<your-withheld-bucket>
```

---

## 5. Shortened Demo Cuts (45-Minute & 60-Minute Formats)

You can deliver this demo in shorter slots without changing a single file by swapping pre-built **Checkpoints**:

| Format | Total Time | What to Run Live vs Swap via `./checkpoint` |
| :--- | :---: | :--- |
| **45-Minute Executive Briefing** | `45 min` | - **Opening (`8 min`)**: Narrative setup + live `guardrail-hook` block.<br>- **Workstream 1 (`17 min`)**: Run parallel triage subagents + `stats-reviewer` live; show `git diff` on `pipeline_clean.py` and immediately run `./checkpoint ws1_staging_clean` (`6s`).<br>- **Workstream 2 & Reveal (`15 min`)**: Swap `./checkpoint ws2_seasonal_features` & `./checkpoint ws2_hospital_cohorts`, run zero-shot `AI.FORECAST` live, swap `./checkpoint ws2_forecast_leaderboard`, and run `./load-reveal` for the **Reveal** punchline.<br>- **Q&A (`5 min`)**. |
| **60-Minute Technical Session** | `60 min` | - **Opening (`10 min`)**: Full tour + live `guardrail-hook` block.<br>- **Workstream 1 (`22 min`)**: Live EDA, parallel triage subagents, `stats-reviewer`, `git diff`, and `./run-pipeline-clean --sql-fallback` (`5s`).<br>- **Workstream 2 & Reveal (`20 min`)**: Live K-means **Cohorts**, zero-shot `TimesFM` (`AI.FORECAST`) + `./checkpoint ws2_forecast_leaderboard`, live **Reveal** (`./load-reveal`), and `cohort-forecast-refresh` skill.<br>- **Q&A (`8 min`)**. |
| **90-Minute Full Workshop** | `90 min` | Full live execution of every step in [Section 4](#4-act-by-act-live-demo-script) using the early-start triggers in [Section 3.2](#32-early-start-triggers-for-longer-jobs-docsrecorded_runtimesjson). |

---

## 6. Cross-Industry Narrative Translation Matrix

You can adapt the verbal story on stage to any industry without changing a single table, query, or script:

| Industry Domain | Headline +35% Spike | Pipeline Defect (`15.0` pts) | Sampling Artifact (`8.0` pts) | Localized True Event (`7.0` pts) | Seasonal Ramp (`5.0` pts) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Healthcare (Default)** | Northeast flu-positive test counts | Backfill batch duplicated 5 days of **Hospital Feeds** | Walk-in clinics expanded testing volume (`total_flu_tests`) | Genuine localized flu **Outbreak** at 3 hospitals | Autumn early-season flu rise |
| **Financial Services** | Card fraud alert counts | Gateway retry duplicated settlement batches | New low-threshold screening rule expanded volume | Coordinated skimming ring at 3 merchant hubs | Pre-holiday shopping volume rise |
| **SaaS / Cloud** | Customer churn event counts | Webhook replay duplicated cancellation events | Telemetry update added free-tier trial expirations | Regional outage drove real churn in 3 clusters | End-of-quarter renewal cycle |
| **Retail / Supply Chain** | Inventory shrinkage counts | EDI retry duplicated warehouse receipt feeds | Cycle-count audit expanded scanner checks | Real fulfillment shrinkage at 3 distribution hubs | Peak-season inventory ramp |
| **Manufacturing / IoT** | Thermal alarm counts | Broker replay duplicated sensor packet batches | High-frequency polling enabled on test lines | Bearing degradation across 3 assembly lines | Ambient summer plant temperature rise |

---

## 7. Presenter Q&A Quick-Reference Cheat Sheet

For full derivations, see the [Data Science Primer](docs/data-science-primer.md).

| Topic | Audience Question | Crisp On-Stage Answer |
| :--- | :--- | :--- |
| **Positivity** | *"Why not model raw positive counts directly?"* | *"Raw counts conflate viral spread with testing capacity. **Positivity** (`positive_flu_tests / total_flu_tests`) normalizes for testing volume so expanded screening isn't mistaken for an epidemic."* |
| **Sampling Artifact** | *"Isn't finding more positive cases always an Outbreak?"* | *"When testing volume doubles and **Positivity** stays flat, transmission hasn't accelerated—we simply cast a wider net."* |
| **Simpson's Paradox** | *"Why check hospital-level rates if we have the regional average?"* | *"Aggregate regional rates can rise or reverse purely from compositional shifts in which hospitals submit higher volume. `stats-reviewer` verifies both facility-level and regional distributions."* |
| **BQML K-Means Cohorts** | *"Why 4 Cohorts instead of 90 hospital models or 1 regional model?"* | *"90 individual models overfit small rural hospitals; 1 global model blurs clinical differences. Clustering on 4 curve geometry features (`peak_arrival_week`, `peak_volume`, `curve_width`, `seasonal_trend`) balances stability and granularity—and isolates the 3 **Outbreak** hospitals into their own **Cohort**."* |
| **`ARIMA_PLUS` vs `TimesFM`** | *"Why compare classical `ARIMA_PLUS` with `TimesFM` (`AI.FORECAST`)?"* | *"`ARIMA_PLUS` provides an interpretable statistical baseline with automatic trend and seasonality handling, while `TimesFM` (`AI.FORECAST`) tests zero-shot foundation model accuracy without training a model object."* |
| **Chronological Backtesting** | *"Why not standard random k-fold cross-validation?"* | *"Random splits leak future time points into past training windows. Chronological backtesting trains strictly prior to the historical peak and forecasts forward."* |
| **WAPE vs MAPE** | *"Why rank the leaderboard by WAPE instead of MAPE?"* | *"MAPE divides by individual weekly counts and explodes when off-season flu counts are small. **WAPE** (`SUM(|error|) / SUM(actual)`) weights errors proportionally to patient volume."* |
| **Security & IAM ([ADR 0002](docs/adr/0002-dataproc-runs-as-presenter.md))** | *"Does this require `roles/owner` or custom service accounts?"* | *"Neither. Terraform creates zero service accounts or IAM bindings, and Dataproc Serverless, BigQuery, and BigQuery MCP all run under the presenter's own user credentials."* |
