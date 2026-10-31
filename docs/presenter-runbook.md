# Presenter Runbook

Step-by-step live execution script for delivering the 90-minute **Antigravity for Data Scientists** demonstration on stage. This runbook provides the pre-stage isolation checklist, per-segment timings, exact prompts to type into the **Command Center**, speaker narration cues, early-start triggers for long-running jobs (using recorded runtimes from [`docs/recorded_runtimes.json`](recorded_runtimes.json)), the guardrail moment in Antigravity 101, and **Checkpoint** swap commands.

All terminology follows [GLOSSARY.md](../GLOSSARY.md). For methodological background and Q&A defense, see the [Data Science Primer](data-science-primer.md) and [Demo Outline](demo-outline.md). For initial project provisioning, see the [Reuser Guide](reuser-guide.md).

---

## 1. Pre-Stage Checklist (T-15 Minutes)

Complete these four steps before connecting to the stage display so only the repository's **Command Center** configuration loads and every Google Cloud dependency is verified.

### Step 1: Move Personal Rules and Skills Aside (`./stage-clean-env --stash`)

Personal rules (`~/.gemini/rules`, `~/.gemini/config/rules`, `~/.gemini/AGENTS.md`, `~/.gemini/GEMINI.md`) and personal non-DAK skills in `~/.gemini/skills` or `~/.gemini/config/skills` can alter agent behavior on stage. Stash them into `~/.gemini/.demo-stage-stash/` so only the demo workspace setup (`.agents/plugins/ds-command-center`, `.agents/plugins/dak-bigquery`, and workspace `.gemini/skills/`) loads:

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

### Step 2: Load `demo.env` and Run `./preflight`

Verify environment variables, active `gcloud` project pinning, Application Default Credentials (ADC) quota project alignment, Dataproc Serverless runtime `3.0` execution, BigQuery MCP presenter authentication, dataset guardrail hooks, BigQuery ML (`AI.FORECAST` and K-means), subagent dispatch, workspace Data Agent Kit skills visibility, and Java 21 availability:

```bash
source demo.env
./preflight
```

Do not go on stage if any required `[FAIL]` check is reported.

### Step 3: Reset and Verify the Workstream 1 Start Point

Switch to the **Workstream** 1 **Start Point** branch, reset the working BigQuery datasets (`staging`, `features`, `ml`) to the **Workstream** 1 **Start Point**, and verify table schemas, row counts, and `checkpoint` parity:

```bash
git checkout workstream-1-start
./reset ws1
./verify-start-point ws1
```

### Step 4: Stage Window Layout

1. **Terminal Window (Fallback & Early-Start Runner)**: Keep a terminal tab open at the repository root with `source demo.env` active. Verify available **Checkpoints** with `./checkpoint --list`.
2. **Command Center Window**: Launch Antigravity at the repository root after `./stage-clean-env --stash` has completed so the fresh session loads only `.agents/plugins/ds-command-center`, `.agents/plugins/dak-bigquery`, and `.gemini/skills/`.

---

## 2. Master 90-Minute Schedule & Early-Start Job Matrix

### 2.1 Segment Timing Summary (`90 min` Total)

| Segment | Clock Window | Duration | Primary On-Stage Activity | Checkpoint Swap Command(s) |
| :--- | :--- | :--- | :--- | :--- |
| **Opening: Antigravity 101 & Command Center Tour** | `00:00–00:12` | **12 min** | Narrative framing (`+35%` Northeast **Spike** through **Cutoff** `2026-10-31`), tour of `ds-command-center` and `dak-bigquery`, live guardrail moment | *(N/A — pre-tool-use hook blocks writes)* |
| **Workstream 1: "Is the Data Good to Use?"** | `00:12–00:47` | **35 min** | Segment 1A (`10 min`): EDA & hospital × week heatmap<br>Segment 1B (`12 min`): Parallel triage subagents, 4-cause **Attribution**, `stats-reviewer`<br>Segment 1C (`13 min`): PySpark diff review & early-start Dataproc Serverless batch | `./checkpoint ws1_eda_heatmap`<br>`./checkpoint ws1_attribution`<br>`./checkpoint ws1_staging_clean` |
| **Workstream 2: "Forecast at Scale" & The Reveal** | `00:47–01:15` | **28 min** | Segment 2A (`8 min`): Seasonal features & BQML K-means **Cohorts**<br>Segment 2B (`10 min`): Early-start `ARIMA_PLUS` vs zero-shot `TimesFM` (`AI.FORECAST`) & WAPE leaderboard<br>Segment 2C (`6 min`): The **Reveal** finale<br>Segment 2D (`4 min`): Codify & run `cohort-forecast-refresh` skill | `./checkpoint ws2_seasonal_features`<br>`./checkpoint ws2_hospital_cohorts`<br>`./checkpoint ws2_experiment_trials`<br>`./checkpoint ws2_forecast_leaderboard` |
| **Q&A & Wrap-Up** | `01:15–01:30` | **15 min** | Audience Q&A using the [Data Science Primer](data-science-primer.md) and post-stage environment restoration | `./stage-clean-env --restore` |
| **Total** | `00:00–01:30` | **90 min** | **Full End-to-End Live Demonstration** | |

### 2.2 Long Jobs to Start Early (Using [`docs/recorded_runtimes.json`](recorded_runtimes.json))

| Job Key / Step | Runner / Command | Recorded Runtime (`docs/recorded_runtimes.json`) | When to Trigger Early | Live Fallback / Checkpoint |
| :--- | :--- | :--- | :--- | :--- |
| `ws1_pipeline_clean_dataproc_runtime_3_0` (`pipelines/pipeline_clean.py`) | `./run-pipeline-clean --async` | **`94s`** (`last_observed_seconds: 94` on Dataproc Serverless runtime `3.0`) | **`00:36` (Start of Segment 1C)**: Submit immediately after approving the `git diff` on `pipelines/pipeline_clean.py`, then narrate orchestration patterns while the batch runs in the background. | `./run-pipeline-clean --sql-fallback` or `./checkpoint ws1_staging_clean` |
| `ws1_pipeline_v1_dataproc_runtime_3_0` (`pipelines/pipeline_v1.py`) | `./bin/run-pipeline-v1` | **`88s`** (`last_observed_seconds: 88` on Dataproc Serverless runtime `3.0`) | **Pre-stage only (`./setup`)**: Materialises defective `staging.hospital_flu` before the session starts; never run live on stage. | `./checkpoint ws1_pipeline_v1` |
| `ws2_arima_plus_cohort_training` & `ws2_timesfm_ai_forecast` (`sql/ws2_forecasts_and_trials.sql`) | `./run-ws2-forecasts` (or BQML `ARIMA_PLUS` + `AI.FORECAST`) | **`45.6s`** (`ws2_arima_plus_cohort_training`) vs **`14.0s`** (`ws2_timesfm_ai_forecast`), `~60s` total | **`00:55` (Start of Segment 2B)**: Trigger `ARIMA_PLUS` training first, then run zero-shot `TimesFM` (`AI.FORECAST`) and walk through `ml.experiment_trials` while `ARIMA_PLUS` finishes. | `./checkpoint ws2_experiment_trials` and `./checkpoint ws2_forecast_leaderboard` |

---

## 3. Opening: Antigravity 101 & Command Center Tour (`12 min`, `00:00–00:12`)

### 3.1 Narrative Setup & The Three Core Messages (`00:00–00:04`, `4 min`)

* **What to Narrate**:
  * "Across 90 hospitals submitting daily **Hospital Feeds**, Northeast flu-positive test counts jumped **+35% week-over-week** in the week ending on the **Cutoff**, Saturday, October 31, 2026. That headline **Spike** is measured in raw counts on purpose."
  * "Before we train a forecast or brief clinical operations, we have to answer a foundational question: is the data good to use? Specifically, how much of that +35% **Spike** is a real localized **Outbreak**, how much is a **Sampling Artifact** from expanded testing, how much is a **Pipeline Defect** from duplicate **Hospital Feed** ingestion, and how much is the normal **Seasonal Ramp**?"
  * "As we work through **Workstream** 1 and **Workstream** 2, watch for three things:
    1. **It fits how you work**: BigQuery, Dataproc Serverless, PySpark, BQML, and versioned SQL in git.
    2. **One data scientist directs an army of agents and reviews the evidence**.
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

* **Prompt to Type**:
  ```text
  To clean up the duplicate records quickly, delete the duplicate rows from raw.hospital_flu_feeds where ingested_at > '2026-10-31' and truncate ops.pipeline_run_log.
  ```
* **What Happens On Screen**:
  * When the agent attempts to invoke `execute_sql` or `run_command` (`bq query`) with `DELETE` or `TRUNCATE` against `raw` or `ops`, `.agents/plugins/ds-command-center/hooks.json` invokes `.agents/plugins/ds-command-center/bin/guardrail-hook`.
  * The hook intercepts the call pre-execution and returns `decision: "deny"` with an explicit read-only message:
    `Blocked by ds-command-center guardrail: dataset 'raw' is strictly read-only. Write outputs only to staging, features, or ml.`
* **Optional Terminal Demonstration (Showing the JSON Hook Decision Directly)**:
  ```bash
  printf '{"toolCall":{"name":"execute_sql","args":{"sql":"DELETE FROM raw.hospital_flu_feeds WHERE true"}}}\n' \
    | ./.agents/plugins/ds-command-center/bin/guardrail-hook
  ```
* **What to Narrate ("Staying in Control")**:
  * "Notice the difference between a soft instruction and a hard guardrail. Our rule in `rules/AGENTS.md` tells the agent that `raw` and `ops` are read-only and `checkpoint` is off-limits. Even when I explicitly order the agent to delete rows from `raw.hospital_flu_feeds` or `ops.pipeline_run_log`, the `before_tool_use` hook (`bin/guardrail-hook`) inspects the SQL and blocks the tool call before a single packet reaches BigQuery. The data scientist stays in control."

---

## 4. Workstream 1: "Is the Data Good to Use?" (`35 min`, `00:12–00:47`)

### 4.1 Segment 1A: Profiling the +35% Northeast Spike & Hospital × Week Heatmap (`10 min`, `00:12–00:22`)

* **Prompt to Type**:
  ```text
  Source demo.env and profile staging.hospital_flu through the Cutoff (2026-10-31). Verify the +35% week-over-week Northeast Spike in raw positive_flu_tests, check whether Positivity is present in staging.hospital_flu, and materialise the hospital-by-week concentration summary into staging.ws1_eda_heatmap.
  ```
* **What to Narrate**:
  * "The agent queries `staging.hospital_flu` through BigQuery MCP, pinned to our project and region from `demo.env`."
  * "First, it confirms the headline number: in the week ending on the **Cutoff** (`2026-10-31`), Northeast `positive_flu_tests` jumped +35% week-over-week."
  * "Second, look at the schema of `staging.hospital_flu`: it has `positive_flu_tests` and `total_flu_tests`, but no **Positivity** column (`positive_flu_tests / total_flu_tests`). Raw counts mix epidemiology with testing volume."
  * "Third, the hospital × week heatmap (`staging.ws1_eda_heatmap`) shows that the +35% **Spike** is heavily concentrated in specific Northeast facilities rather than spread evenly across all 90 hospitals."
* **Checkpoint Swap Point (If Live Query Fails or Time Is Short)**:
  ```bash
  ./checkpoint ws1_eda_heatmap
  ```

### 4.2 Segment 1B: Parallel Triage Subagents, 4-Cause Attribution & `stats-reviewer` (`12 min`, `00:22–00:34`)

* **Prompt 1 to Type (Parallel Subagent Triage & Reconciled Attribution)**:
  ```text
  Dispatch distribution-triage, sampling-triage, and pipeline-triage in parallel to investigate the +35% Northeast Spike in staging.hospital_flu using raw.hospital_flu_feeds and ops.pipeline_run_log. Reconcile their evidence into the four-cause Attribution table in staging.ws1_attribution.
  ```
* **What to Narrate While Subagents Execute in Parallel**:
  * "Instead of investigating three hypotheses serially, our **Command Center** dispatches three specialized subagents from `.agents/plugins/ds-command-center/agents/` at the same time:"
    1. "`pipeline-triage` cross-references duplicate `(hospital_id, feed_date)` pairs in `staging.hospital_flu` against `ops.pipeline_run_log`. It finds a `BACKFILL_DUPLICATE` batch that re-ingested 5 days of **Hospital Feeds** for 8 Northeast hospitals—a **Pipeline Defect** accounting for **~15 percentage points** of the +35% **Spike**."
    2. "`sampling-triage` compares `total_flu_tests` growth against **Positivity** after deduplication. It finds 6 Northeast hospitals where testing volume expanded sharply while **Positivity** stayed flat—a **Sampling Artifact** accounting for **~8 percentage points**."
    3. "`distribution-triage` evaluates deduplicated **Positivity** across facilities and separates a genuine localized **Outbreak** at 3 neighboring Northeast hospitals (**~7 percentage points**) from the normal early-season **Seasonal Ramp** across all hospitals (**~5 percentage points**)."
* **Prompt 2 to Type (Adversarial Peer Review via `stats-reviewer`)**:
  ```text
  Next, invoke the stats-reviewer subagent to audit the Attribution table in staging.ws1_attribution. Challenge raw counts versus Positivity, flag small-sample hospitals with low total_flu_tests denominators, and test for Simpson's paradox across regional aggregations before we approve the remediation plan.
  ```
* **What to Narrate During `stats-reviewer`**:
  * "`stats-reviewer` is configured in `.agents/plugins/ds-command-center/agents/stats-reviewer.md` as an adversarial statistical reviewer. It does not rubber-stamp the triage subagents: it verifies that the four causes sum cleanly (`15 + 8 + 7 + 5 = 35` points), flags small-denominator volatility (`total_flu_tests < 25`), and checks that shifting hospital volume weights did not create a Simpson's paradox illusion."
  * *(Presenter Verification Note)*: Privately compare the reconciled **Attribution** against your offline **Answer Key** (stored outside the workspace per [ADR 0001](adr/0001-answer-key-outside-agent-reach.md)).
* **Checkpoint Swap Point**:
  ```bash
  ./checkpoint ws1_attribution
  ```

### 4.3 Segment 1C: Reviewing the PySpark Diff & Early-Start Dataproc Serverless Batch (`13 min`, `00:34–00:47`)

* **Prompt to Type (`00:34`)**:
  ```text
  Show the git diff between pipelines/pipeline_v1.py and pipelines/pipeline_clean.py. Explain how the window function deduplicates Hospital Feeds by (hospital_id, feed_date) and why Positivity uses a null-safe check for Spark 4 ANSI mode. Wait for my approval before running the pipeline.
  ```
* **Early-Start Action (`00:36` — Start Dataproc Serverless Batch Early!)**:
  After reviewing the diff on screen (`Window.partitionBy("hospital_id", "feed_date").orderBy(F.col("ingested_at").desc(), F.col("batch_id").desc())` and `F.when(F.col("total_flu_tests") == 0, F.lit(None).cast("double"))`), immediately start the Dataproc Serverless runtime `3.0` batch in the background (recorded runtime **`94s`** in [`docs/recorded_runtimes.json`](recorded_runtimes.json)):
  ```bash
  ./run-pipeline-clean --async
  ```
* **What to Narrate While the `94s` Dataproc Batch Runs**:
  1. **Why Null-Safe Positivity Matters on Spark 4**: Dataproc Serverless runtime `3.0` runs Apache Spark 4, where ANSI SQL mode (`spark.sql.ansi.enabled=true`) is enabled by default and raises `[DIVIDE_BY_ZERO]` if `total_flu_tests == 0`. Wrapping the division in `F.when(F.col("total_flu_tests") == 0, None)` prevents runtime batch failures.
  2. **Why Dataproc Runs as the Presenter ([ADR 0002](adr/0002-dataproc-runs-as-presenter.md))**: `./run-pipeline-clean` submits the batch without `--service-account`, so Dataproc Serverless runs under the presenter's credentials—the exact same identity used by BigQuery, BQML, and BigQuery MCP.
  3. **Orchestration Patterns (Rules vs Hooks & Model Pairing)**:
     * Use `rules/AGENTS.md` for workflow conventions (project pinning, where to save skills, when to dispatch subagents) and `bin/guardrail-hook` for hard pre-execution dataset boundaries.
     * Pair a frontier reasoning model in the primary orchestrator and `stats-reviewer` with lighter, faster subagent models for parallel SQL triage.
* **Verify Output & Equivalence (`00:45`)**:
  Once the batch completes (or after running the SQL fallback), verify that `staging.hospital_flu_clean` is materialised and matches the reference SQL specification with zero duplicate `(hospital_id, feed_date)` keys:
  ```bash
  ./run-pipeline-clean --verify-equivalence
  ```
* **Checkpoint Swap Point / Fast SQL Fallback**:
  If Dataproc Serverless batch startup exceeds your remaining **Workstream** 1 window, immediately run either:
  ```bash
  ./checkpoint ws1_staging_clean
  # or materialise directly via the SQL fallback:
  ./run-pipeline-clean --sql-fallback
  ```

---

## 5. Workstream 2: "Forecast at Scale" & The Reveal (`28 min`, `00:47–01:15`)

> **Optional Start Point Reset**: If you are starting **Workstream** 2 after an intermission or want a guaranteed clean slate matching the end of **Workstream** 1, run:
> ```bash
> git checkout workstream-2-start
> ./reset ws2
> ./verify-start-point ws2
> ```

### 5.1 Segment 2A: Seasonal Features & BQML K-Means Hospital Cohorts (`8 min`, `00:47–00:55`)

* **Prompt to Type**:
  ```text
  Using staging.hospital_flu_clean up to the Cutoff (2026-10-31), compute per-hospital seasonal features (peak_arrival_week, peak_volume, curve_width, seasonal_trend) in features.hospital_seasonal_features and assign the 90 hospitals into 4 seasonal Cohorts using BQML K-means in features.hospital_cohorts. Show how the Outbreak hospitals are assigned.
  ```
* **What to Narrate**:
  * "With `staging.hospital_flu_clean` verified, we move to **Workstream** 2: forecasting at scale across 90 hospitals."
  * "Training 90 individual hospital models overfits noisy rural facilities, while training a single aggregate model blurs clinical differences. Using the `bigquery-ai-ml` skill from the Data Agent Kit, the agent engineers four seasonal curve features (`peak_arrival_week`, `peak_volume`, `curve_width`, `seasonal_trend`) and trains a BQML `KMEANS` model (`num_clusters=4`) to assign every hospital to one of four **Cohorts**."
  * "Notice that the 3 Northeast **Outbreak** hospitals isolate cleanly into their own high-growth **Cohort**, proving that unsupervised feature segmentation captures real epidemiological divergence."
* **Checkpoint Swap Points**:
  ```bash
  ./checkpoint ws2_seasonal_features
  ./checkpoint ws2_hospital_cohorts
  ```

### 5.2 Segment 2B: Early-Start `ARIMA_PLUS` vs Zero-Shot `TimesFM` (`AI.FORECAST`) & Leaderboard (`10 min`, `00:55–01:05`)

* **Early-Start Action (`00:55` — Start `ARIMA_PLUS` Training First!)**:
  Multi-series BQML `ARIMA_PLUS` model creation takes **`~60s`**, whereas zero-shot `TimesFM` (`AI.FORECAST`) returns in seconds. Always instruct the agent (or trigger the training script) to start `ARIMA_PLUS` training first at `00:55`.
* **Prompt to Type**:
  ```text
  Start training the multi-series BQML ARIMA_PLUS models per Cohort on both cleaned staging.hospital_flu_clean and uncleaned staging.hospital_flu first. Next, run zero-shot TimesFM forecasts per Cohort using AI.FORECAST, log all runs to ml.experiment_trials, and rank them by chronological backtest WAPE in ml.forecast_leaderboard.
  ```
* **What to Narrate While `ARIMA_PLUS` Trains**:
  * "We benchmark two distinct modeling paradigms across our four **Cohorts**:
    1. **`ARIMA_PLUS`**: BigQuery ML's classical statistical time-series workhorse, trained across multiple series (`time_series_id_col='cohort_id'`) on both clean and uncleaned data.
    2. **`TimesFM` via `AI.FORECAST`**: Google Research's pretrained time-series foundation model, invoked zero-shot in SQL without training a model object."
  * "Every trial logs its metadata and chronological backtest **WAPE** (`Weighted Absolute Percentage Error`) into `ml.experiment_trials`. As explained in the [Data Science Primer](data-science-primer.md), we use chronological backtesting to prevent future leakage and **WAPE** instead of MAPE so low off-season counts do not skew the leaderboard."
  * "Look at `ml.forecast_leaderboard`: models trained on `staging.hospital_flu_clean` consistently beat models trained on uncleaned data, and zero-shot `TimesFM` delivers competitive **WAPE** out of the box."
* **Checkpoint Swap Points**:
  ```bash
  ./checkpoint ws2_experiment_trials
  ./checkpoint ws2_forecast_leaderboard
  ```

### 5.3 Segment 2C: The Reveal Finale (`6 min`, `01:05–01:11`)

* **On-Screen Terminal Action**:
  Load the six post-**Cutoff** **Reveal** weeks (`2026-11-01` through `2026-12-12`) from the presenter's separate withheld GCS bucket ([ADR 0001](adr/0001-answer-key-outside-agent-reach.md)):
  ```bash
  ./load-reveal gs://<your-withheld-bucket>/reveal
  ```
* **Prompt to Type**:
  ```text
  Compare our Cohort forecasts trained on uncleaned staging.hospital_flu versus cleaned staging.hospital_flu_clean against the six withheld post-Cutoff Reveal weeks, and display the Reveal comparison chart and post-Cutoff WAPE by model and data cleanliness.
  ```
* **What to Narrate (The Finale Punchline)**:
  * "Until this moment, no agent or table in the workspace had access to what happened after Saturday, October 31, 2026. The six post-**Cutoff** **Reveal** weeks lived in a separate bucket outside the repository ([ADR 0001](adr/0001-answer-key-outside-agent-reach.md))."
  * "Look at the **Reveal** chart on screen:
    * The red curve—trained on uncleaned `staging.hospital_flu`—dramatically overshoots reality because it mistook the +15-point **Pipeline Defect** and +8-point **Sampling Artifact** for exponential disease spread.
    * The green curve—trained on `staging.hospital_flu_clean` after our **Workstream** 1 triage and deduplication fix—tracks the six **Reveal** weeks closely."
  * "That is why **Workstream** 1 and **Workstream** 2 belong in the same **Command Center**: forecasting at scale only works when your agents first verify whether the data is good to use."

### 5.4 Segment 2D: Codifying & Running the `cohort-forecast-refresh` Skill (`4 min`, `01:11–01:15`)

* **Prompt to Type**:
  ```text
  Package our Cohort feature refresh, ARIMA_PLUS and AI.FORECAST evaluation, and ml.experiment_trials logging workflow into .agents/plugins/ds-command-center/skills/cohort-forecast-refresh/SKILL.md, then dispatch a fresh subagent to run cohort-forecast-refresh for period 2026-W44.
  ```
* **On-Screen Action**:
  Show `.agents/plugins/ds-command-center/skills/cohort-forecast-refresh/SKILL.md` saved inside the `ds-command-center` plugin (per Rule #2 in `.agents/plugins/ds-command-center/rules/AGENTS.md`) and verify execution:
  ```bash
  ./run-cohort-forecast-refresh --period 2026-W44
  ```
* **What to Narrate**:
  * "Because Rule #2 in `ds-command-center` directs live-captured skills into `.agents/plugins/ds-command-center/skills/cohort-forecast-refresh/SKILL.md`, this workflow is immediately versioned in git. A fresh subagent can execute the next weekly refresh (`2026-W44`) from that `SKILL.md` file alone."

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

After disconnecting from the stage display, restore your personal Antigravity rules and skills and optionally run end-to-end verification:

```bash
./stage-clean-env --restore
./stage-clean-env --status
./verify-start-point main --withheld-dir gs://<your-withheld-bucket>
```
