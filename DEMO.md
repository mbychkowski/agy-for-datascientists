# How to Demo: Antigravity for Data Scientists (`DEMO.md`)

Complete live demonstration guide for presenting **Antigravity for Data Scientists** in the **Command Center**. This guide gives you the scenario setup, the 15-minute pre-stage checklist, the master schedule with Window 2 fallback triggers, exact copy-paste prompts to type on stage, speaker narration points, instant **Checkpoint** fallback commands, and shortened 45/60-minute cuts.

For initial Google Cloud project provisioning, see [README.md](README.md) and the [Reuser Setup & Operations Guide](docs/reuser-guide.md). For deep statistical Q&A preparation, see the [Data Science Primer](docs/data-science-primer.md). All terminology follows [GLOSSARY.md](GLOSSARY.md).

---

## Table of Contents

1. [The Story & What the Audience Sees](#1-the-story--what-the-audience-sees)
2. [Pre-Stage Checklist (T-15 Minutes)](#2-pre-stage-checklist-t-15-minutes)
3. [Master 90-Minute Timeline & Fallback Triggers](#3-master-90-minute-timeline--fallback-triggers)
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

The demo runs from **two separate repositories**, one per stage window:

* **Window 1 (agent)**: Antigravity opened on the **stage clone**, a fresh single-branch clone of `workstream-1-start` that lives outside the presenter repo, has its remote removed, and has `demo.env` copied in. The agent only ever sees this clone.
* **Window 2 (presenter terminal)**: your existing presenter repo on `main`, with `source demo.env` active. It owns every presenter script: `./stage-clean-env`, `./preflight`, `./reset`, `./verify-start-point`, `./checkpoint`, `./run-pipeline-clean`, `./run-ws2-cohorts`, `./run-ws2-forecasts`, `./load-reveal`, and `./run-cohort-forecast-refresh`. Never run these from the stage clone: most of them don't exist on `workstream-1-start`, and the rest are stale there.

> **Why a separate clone, not a worktree or an in-repo folder?** The presenter-only tooling on `main` reads the **Workstream** 2 SQL, the **Workstream** 2 **Checkpoint** manifests, and the **Reveal** comparison SQL, so `main` must stay out of the agent's reach to keep the "agents never saw the answers" guarantee ([ADR 0001](docs/adr/0001-answer-key-outside-agent-reach.md)). Every worktree shares `.git` with the presenter repo, so an agent in a worktree could still run `git show main:…`. An in-repo folder sits inside the agent's workspace. Only a separate single-branch clone with no remote keeps `main` out of reach.

### Step 0: Create the Stage Clone (Window 2, Once per Machine)

Run this from the presenter repo on `main`. Clone from the remote URL, not from a local path: a local-path clone hardlinks the whole object store, `main` included.

```bash
git clone --single-branch --branch workstream-1-start "$(git remote get-url origin)" ~/demo-stage/agy-ws1
git -C ~/demo-stage/agy-ws1 remote remove origin
cp demo.env ~/demo-stage/agy-ws1/
mkdir -p ~/demo-stage/agy-ws1/.gemini
cp -R .gemini/skills ~/demo-stage/agy-ws1/.gemini/
```

`.gemini/skills/` is git-ignored, so the clone starts without the licensed Data Agent Kit skills; the last two lines copy your workspace install across. `./preflight` checks the presenter repo, not the clone, so confirm the copy with `ls ~/demo-stage/agy-ws1/.gemini/skills/bigquery-ai-ml/SKILL.md`.

Run these steps before connecting to the projector or starting your screen share:

### Step 1: Isolate Personal Rules & Skills (`./stage-clean-env --stash`, Window 2)

From the presenter repo on `main` (Window 2), stash personal rules (`~/.gemini/rules`, `~/.gemini/config/rules`, `~/.gemini/AGENTS.md`) and personal non-DAK skills so only the repository's `.agents/plugins/ds-command-center`, `.agents/plugins/dak-bigquery`, and workspace `.gemini/skills/` load on stage:

```bash
./stage-clean-env --stash
./stage-clean-env --status
```

### Step 2: Source `demo.env` & Run the 12-Point Preflight Check (Window 2)

Run this from the presenter repo on `main` (Window 2):

```bash
source demo.env
./preflight
```

Verify that all 12 checks report `[PASS]` (including BigQuery MCP presenter auth, `guardrail-hook` enforcement, BigQuery ML `AI.FORECAST` + `KMEANS`, subagent dispatch, and Java 21).

### Step 3: Reset the Stage Clone's Code & the Workstream 1 Start Point (Window 2)

Run this before every rehearsal and on Demo Day. First discard the agent's tracked edits and untracked files from the last run in the stage clone. `git clean -fd` leaves git-ignored files alone, so `demo.env` and `.gemini/skills/` survive. Then, from the presenter repo on `main`, reset the working BigQuery datasets (`staging`, `features`, `ml`) to the **Workstream** 1 **Start Point** and verify parity against `checkpoint`:

```bash
git -C ~/demo-stage/agy-ws1 reset --hard
git -C ~/demo-stage/agy-ws1 clean -fd
./reset ws1 --yes
./verify-start-point ws1
```

If a rehearsal left a commit in the stage clone, delete the clone and repeat Step 0 instead.

### Step 4: Arrange Your Two Stage Windows

1. **Window 1 — Command Center (Antigravity, agent)**: Open Antigravity on the stage clone at `~/demo-stage/agy-ws1` once Steps 1–3 have completed. Every prompt in this guide is typed here.
2. **Window 2 — Presenter Terminal (`main` repo)**: Open at the presenter repo root on `main` with `source demo.env` active. Run `./checkpoint --list` so you can run a fallback or swap a **Checkpoint** in ~6 seconds if needed.

### Before Demo Day: Rehearse the Live-Written Prompts

The agent writes `pipeline_clean.py` (Segment 1C), the seasonal-features and K-means SQL (Segment 2A), the `ARIMA_PLUS` and `TimesFM` SQL (Segment 2B), and the `cohort-forecast-refresh` `SKILL.md` (Segment 2D) live, so its output can vary between runs. Rehearse the full sequence several times, starting each run from the Step 3 reset, and type the 1C, 2A, 2B and 2D prompts exactly as written. Check that the output is consistent across runs:

* **1C**: `./run-pipeline-clean --verify-equivalence` passes from Window 2.
* **2A**: the 3 **Outbreak** hospitals land in their own **Cohort**.
* **2B**: `ARIMA_PLUS` starts before `TimesFM`, and clean models beat uncleaned ones in `ml.forecast_leaderboard`.
* **2D**: `SKILL.md` lands in `.agents/plugins/ds-command-center/skills/cohort-forecast-refresh/`, and the subagent's `2026-W44` run appends rows to `ml.experiment_trials`.

Note each step's runtime as well. If the agent's output or timing differs between runs, tighten the prompt wording before Demo Day rather than relying on the Window 2 fallbacks.

---

## 3. Master 90-Minute Timeline & Fallback Triggers

### 3.1 Segment Schedule (`90 min` Total)

| Segment | Clock | Duration | On-Stage Focus | Instant Checkpoint Fallback (`~6s`) |
| :--- | :---: | :---: | :--- | :--- |
| **Opening: Antigravity 101 & Guardrail Moment** | `00:00–00:12` | **12 min** | Narrative framing (`+35%` Northeast **Spike** through **Cutoff** `2026-10-31`), tour of `.agents/plugins/`, live `guardrail-hook` block on the agent's own tool call (Window 1) | *(N/A — blocked pre-execution)* |
| **Segment 1A: EDA & Hospital × Week Heatmap** | `00:12–00:22` | **10 min** | Window 1: confirm +35% **Spike** in `staging.hospital_flu`, note missing **Positivity**, materialise `staging.ws1_eda_heatmap` | Window 2: `./checkpoint ws1_eda_heatmap` |
| **Segment 1B: Parallel Triage & `stats-reviewer`** | `00:22–00:34` | **12 min** | Window 1: dispatch 3 triage subagents in parallel, build `staging.ws1_attribution`, run adversarial `stats-reviewer` audit | Window 2: `./checkpoint ws1_attribution` |
| **Segment 1C: Agent-Written `pipeline_clean.py` & Dataproc Serverless** | `00:34–00:47` | **13 min** | Window 1: the agent writes `pipeline_clean.py`, shows the diff, and submits its own Dataproc batch (`00:38`); Window 2: `./run-pipeline-clean --verify-equivalence` (`00:44`) | Window 2 fallbacks: `./run-pipeline-clean --sql-fallback` *(`00:41`, 5s)* or `./checkpoint ws1_staging_clean` *(`00:42`, 6s)* |
| **Segment 2A: Seasonal Features & K-Means Cohorts** | `00:47–00:55` | **8 min** | Window 1: the agent writes and runs the 4 seasonal curve features and BQML `KMEANS` (`num_clusters=4`) SQL (`00:50`), isolating the 3 **Outbreak** hospitals | Window 2 fallbacks: `./run-ws2-cohorts` *(`00:52`, 57s)* or `./checkpoint ws2_seasonal_features` & `./checkpoint ws2_hospital_cohorts` *(`00:54`, 6s)* |
| **Segment 2B: `ARIMA_PLUS` vs `TimesFM` (`AI.FORECAST`)** | `00:55–01:05` | **10 min** | Window 1: the agent writes and starts the multi-series `ARIMA_PLUS` SQL first (`00:57`), then writes and runs zero-shot `TimesFM`, ranking by backtest **WAPE** in `ml.forecast_leaderboard` | Window 2 fallbacks: `./run-ws2-forecasts` *(`00:59`, ~60s)* or `./checkpoint ws2_experiment_trials` & `./checkpoint ws2_forecast_leaderboard` *(`01:01`, 6s)* |
| **Segment 2C: The Reveal Finale** | `01:05–01:11` | **6 min** | Window 2: load 6 post-**Cutoff** **Reveal** weeks (`./load-reveal`, `01:05`); Window 1: the agent compares clean vs uncleaned forecasts against reality | Window 2: rerun `./load-reveal gs://<withheld-bucket>/reveal` |
| **Segment 2D: Codify `cohort-forecast-refresh` Skill** | `01:11–01:15` | **4 min** | Window 1: the agent creates `.agents/plugins/ds-command-center/skills/cohort-forecast-refresh/SKILL.md` and a fresh subagent runs `2026-W44` | Window 2 fallback: `./run-cohort-forecast-refresh --period 2026-W44` *(`01:13`, ~2 min)* |
| **Q&A & Wrap-Up** | `01:15–01:30` | **15 min** | Audience Q&A defense & `./stage-clean-env --restore` | `./stage-clean-env --restore` |

### 3.2 Window 2 Fallback Triggers ([`docs/recorded_runtimes.json`](docs/recorded_runtimes.json))

The agent runs every long job itself from Window 1. **The 60-second rule**: if a step runs more than 60 seconds past its recorded runtime, swap in its fallback from Window 2. Each fallback runs the reference code, not the agent's, so say so on stage.

| Step | Who Runs It | Recorded Runtime | When to Swap In | Window 2 Fallback |
| :--- | :--- | :---: | :--- | :--- |
| **Workstream 1C Dataproc Clean Batch** | Window 1: the agent submits its own `pipeline_clean.py` batch | **`94s`** (reference pipeline) | The agent submits at **`00:38`** right after you approve its diff; narrate Spark 4 ANSI mode and [ADR 0002](docs/adr/0002-dataproc-runs-as-presenter.md) while the batch runs. If it runs more than 60 seconds past `94s`, swap in from Window 2 at **`00:41`**. | Window 2: `./run-pipeline-clean --sql-fallback` (`5s`, runs the reference pipeline) or `./checkpoint ws1_staging_clean` (`6s`) |
| **Workstream 2A BQML K-Means Cohorts** | Window 1: the agent runs its own seasonal-features and `KMEANS` SQL | **`57s`** (reference SQL) | The agent runs its SQL at **`00:50`** after you review it; explain the 4 seasonal curve features while `KMEANS` trains. If it runs more than 60 seconds past `57s`, swap in the Window 2 fallback at **`00:52`**. | Window 2: `./run-ws2-cohorts` (`57s`, runs the reference SQL) or, at **`00:54`**, `./checkpoint ws2_seasonal_features` & `./checkpoint ws2_hospital_cohorts` (`6s`) |
| **Workstream 2B `ARIMA_PLUS` + `TimesFM`** | Window 1: the agent starts its own `ARIMA_PLUS` SQL first, then runs its `TimesFM` (`AI.FORECAST`) SQL | **`18s`–`46s`** (`ARIMA_PLUS`) / **`13s`** (`TimesFM`) | The agent starts `ARIMA_PLUS` training first at **`00:57`**, then runs zero-shot `TimesFM` while `ARIMA_PLUS` completes. If `ARIMA_PLUS` runs more than 60 seconds past `46s`, swap in the Window 2 fallback at **`00:59`**. | Window 2: `./run-ws2-forecasts` (~`60s`, runs the reference SQL) or, at **`01:01`**, `./checkpoint ws2_experiment_trials` & `./checkpoint ws2_forecast_leaderboard` (`6s`) |
| **Workstream 2D `cohort-forecast-refresh` Skill** | Window 1: the agent writes `SKILL.md`, then a fresh subagent runs `2026-W44` | No entry of its own; the run repeats the 2A and 2B jobs, ~`2 min` (`57s` + `46s` + `13s`) | Give the agent until **`01:12`** to write `SKILL.md` and dispatch the subagent. If it hasn't dispatched the subagent 60 seconds past that, stop the agent and swap in the Window 2 fallback at **`01:13`**; once dispatched, never run the fallback alongside it. | Window 2: `./run-cohort-forecast-refresh --period 2026-W44` (~`2 min`, runs the presenter repo's copy of the skill) |

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
* **Type This Prompt into Window 1 (Command Center)**:
  ```text
  To clean up the duplicate records quickly, delete the duplicate rows from raw.hospital_flu_feeds where ingested_at > '2026-10-31' and truncate ops.pipeline_run_log.
  ```
* **What Happens Live**:
  `.agents/plugins/ds-command-center/hooks.json` invokes `.agents/plugins/ds-command-center/bin/guardrail-hook` on `before_tool_use`, inspecting the SQL and returning `decision: "deny"` before any packet reaches BigQuery:
  `Blocked by ds-command-center guardrail: dataset 'raw' is strictly read-only. Write outputs only to staging, features, or ml.`
* **Optional Window 2 Terminal Verification**:
  ```bash
  printf '{"toolCall":{"name":"execute_sql","args":{"sql":"DELETE FROM raw.hospital_flu_feeds WHERE true"}}}\n' \
    | ./.agents/plugins/ds-command-center/bin/guardrail-hook
  ```
* **Say to the Audience**:
  > "Notice the difference between a soft prompt instruction and a hard deterministic guardrail. Even when I explicitly instruct the agent to delete rows from `raw.hospital_flu_feeds` or truncate `ops.pipeline_run_log`, the `before_tool_use` hook blocks the call pre-execution. The data scientist stays in control."

---

### 4.2 Workstream 1: "Is the Data Good to Use?" (`35 min`, `00:12–00:47`)

#### Segment 1A: Exploratory Profiling & Hospital × Week Heatmap (`00:12–00:22`)
* **Type This Prompt into Window 1 (Command Center)**:
  ```text
  Source demo.env and profile staging.hospital_flu through the Cutoff (2026-10-31). Verify the +35% week-over-week Northeast Spike in raw positive_flu_tests, check whether Positivity is present in staging.hospital_flu, and materialise the hospital-by-week concentration summary into staging.ws1_eda_heatmap.
  ```
* **Key Evidence Shown**:
  1. Northeast `positive_flu_tests` rose **+35.0%** in the **Spike** week (`2026-10-25`..`2026-10-31`) vs the prior week (`2026-10-18`..`2026-10-24`).
  2. `staging.hospital_flu` lacks a **Positivity** column (`positive_flu_tests / total_flu_tests`), mixing disease prevalence with testing volume.
  3. `staging.ws1_eda_heatmap` shows the jump is concentrated in a subset of Northeast hospitals rather than uniform across all 90 facilities.
* **Window 2 Checkpoint Fallback**:
  ```bash
  ./checkpoint ws1_eda_heatmap
  ```

#### Segment 1B: Parallel Triage Subagents, 4-Cause Attribution & `stats-reviewer` (`00:22–00:34`)
* **Prompt 1 — Type into Window 1: Dispatch the Three Triage Subagents in Parallel**:
  ```text
  Dispatch distribution-triage, sampling-triage, and pipeline-triage in parallel to investigate the +35% Northeast Spike in staging.hospital_flu using raw.hospital_flu_feeds and ops.pipeline_run_log. Reconcile their evidence into the four-cause Attribution table in staging.ws1_attribution.
  ```
* **What the Three Subagents Find Concurrently**:
  - **`pipeline-triage`**: Correlates `staging.hospital_flu` duplicates with `ops.pipeline_run_log` (`BACKFILL_DUPLICATE`), isolating **`15.0` percentage points** of **Pipeline Defect** across 8 Northeast hospitals (`40` duplicate rows).
  - **`sampling-triage`**: Identifies 6 Northeast hospitals where `total_flu_tests` expanded sharply while deduplicated **Positivity** remained flat, isolating **`8.0` percentage points** of **Sampling Artifact**.
  - **`distribution-triage`**: Separates a localized **Outbreak** at 3 Northeast hospitals (`HOSP_NE_001`, `HOSP_NE_004`, `HOSP_NE_006`, **`7.0` percentage points**) from the broad **Seasonal Ramp** (**`5.0` percentage points**).
* **Prompt 2 — Type into Window 1: Challenge the Attribution with `stats-reviewer`**:
  ```text
  Next, invoke the stats-reviewer subagent to audit the Attribution table in staging.ws1_attribution. Challenge raw counts versus Positivity, flag small-sample hospitals with low total_flu_tests denominators, and test for Simpson's paradox across regional aggregations before we approve the remediation plan.
  ```
* **Say to the Audience**:
  > "`stats-reviewer` is an adversarial peer reviewer. It checks that the four causes sum to the full +35.0% **Spike** (`15 + 8 + 7 + 5 = 35`), flags small-sample denominator volatility, and tests for Simpson's paradox before we sign off on pipeline changes."
* **Window 2 Checkpoint Fallback**:
  ```bash
  ./checkpoint ws1_attribution
  ```

#### Segment 1C: The Agent Writes `pipeline_clean.py` & Runs Dataproc Serverless (`00:34–00:47`)
* **Prompt 1 — Type into Window 1 (Command Center, `00:34`)**:
  ```text
  Write pipelines/pipeline_clean.py, starting from pipelines/pipeline_v1.py. Deduplicate Hospital Feeds by (hospital_id, feed_date), keeping the row with the latest ingested_at and then the greatest batch_id, inner join raw.hospital_reference, and add a null-safe Positivity column named positivity that is NULL when total_flu_tests is 0 so Spark 4 ANSI mode never divides by zero. Write staging.hospital_flu_clean with exactly these columns: hospital_id, hospital_name, region, state, urban_rural, bed_count, feed_date, total_flu_tests, positive_flu_tests, positivity, batch_id, ingested_at. Show me the diff against pipelines/pipeline_v1.py and wait for my approval before running anything.
  ```
* **Review the Diff on Screen (`00:34–00:38`)**: Look for a window function over `hospital_id` and `feed_date` ordered by `ingested_at` and `batch_id` descending, and a **Positivity** expression that returns `NULL` when `total_flu_tests` is `0`. If the code is wrong, ask the agent to fix it; if it can't be fixed by `00:40`, go straight to Fallback A.
* **Prompt 2 — Type into Window 1 After Approving the Diff (`00:38`)**:
  ```text
  Approved. Submit it yourself as a Dataproc Serverless runtime 3.0 PySpark batch, pinned to PROJECT_ID and REGION from demo.env, with gs://STAGING_BUCKET as the deps bucket and the SUBNET from demo.env (demo-dataproc-subnet if SUBNET is empty). Run it as my identity and do not add a service-account flag. Tell me the batch ID and confirm when staging.hospital_flu_clean is written.
  ```
  The batch runs as the presenter identity with no service-account flag ([ADR 0002](docs/adr/0002-dataproc-runs-as-presenter.md)). Narrate Spark 4 ANSI mode while it runs; the reference pipeline's recorded runtime is **`94s`** ([`docs/recorded_runtimes.json`](docs/recorded_runtimes.json)), so expect the agent's batch to finish around `00:40`.
* **Window 2 — Verify Equivalence of the Agent's Output (`00:44`)**:
  ```bash
  ./run-pipeline-clean --verify-equivalence
  ```
  *(Compares the agent's `staging.hospital_flu_clean` against the reference SQL in `sql/verify_clean_equivalence.sql`: matching row counts (`101,430` on the full-scale dataset), `0` duplicate `(hospital_id, feed_date)` keys, and `0` row differences in both directions.)*
* **The 60-Second Rule**: if a step runs more than 60 seconds past its recorded runtime, stop the agent's job first, then swap in from Window 2. For the agent's batch, that is `94s` + `60s` after submission, so with a `00:38` submission, trigger Fallback A at `00:41` if `staging.hospital_flu_clean` isn't written yet.
* **Window 2 Fallback A (trigger at `00:41`, `5s`)**:
  ```bash
  ./run-pipeline-clean --sql-fallback
  ```
  `--sql-fallback` materialises the reference pipeline, not the agent's: say so on stage. The equivalence step then compares the reference with itself, so present it only as a duplicate-key check, not as proof of the agent's code.
* **Window 2 Fallback B (trigger at `00:42`, `6s`)**: if Fallback A errors or runs more than 60 seconds past its `5s` runtime, swap in the **Checkpoint**:
  ```bash
  ./checkpoint ws1_staging_clean
  ```

---

### 4.3 Workstream 2: "Forecast at Scale" & The Reveal (`28 min`, `00:47–01:15`)

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

* **The 60-Second Rule**: if a step runs more than 60 seconds past its recorded runtime in [`docs/recorded_runtimes.json`](docs/recorded_runtimes.json), stop the agent's job first (ask it to cancel its BigQuery job) so both runs don't write the same tables, then swap in from Window 2. The Window 2 fallbacks run the reference SQL, not the agent's: say so on stage.

#### Segment 2A: The Agent Writes Seasonal Features & BQML K-Means Cohorts (`00:47–00:55`)
* **Type This Prompt into Window 1 (Command Center, `00:47`)**:
  ```text
  Write the BigQuery SQL, saved under sql/, that computes per-hospital seasonal features (peak_arrival_week, peak_volume, curve_width, seasonal_trend) from staging.hospital_flu_clean up to the Cutoff (2026-10-31) into features.hospital_seasonal_features, and the BQML K-means SQL (num_clusters=4) that assigns the 90 hospitals to 4 seasonal Cohorts in features.hospital_cohorts. Show me the SQL and run it once I approve, then show how the Outbreak hospitals are assigned.
  ```
* **Review the SQL on Screen (`00:47–00:50`)**: Look for the four features computed only from weeks up to the **Cutoff**, and `model_type='KMEANS'` with `num_clusters=4`. Approve by `00:50`; the K-means job's recorded runtime is **`57s`**, so 60 seconds past it means swapping in at `00:52`.
* **Key Evidence Shown**:
  - Rather than training 90 noisy hospital models or 1 overly broad aggregate model, BQML `KMEANS` (`ml.hospital_cohort_kmeans`) groups the 90 hospitals into 4 **Cohorts** using four orthogonal curve geometry features.
  - The 3 Northeast **Outbreak** hospitals (`HOSP_NE_001`, `HOSP_NE_004`, `HOSP_NE_006`, with `seasonal_trend = 2.7143`) isolate cleanly into their own dedicated 3-hospital **Cohort**.
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

#### Segment 2B: The Agent Writes `ARIMA_PLUS` vs Zero-Shot `TimesFM` (`AI.FORECAST`) & the WAPE Leaderboard (`00:55–01:05`)
* **Type This Prompt into Window 1 (Command Center, `00:55` — Start `ARIMA_PLUS` Training First)**:
  ```text
  Write the BigQuery ML forecasting SQL, saved under sql/, and start the ARIMA_PLUS training first: multi-series ARIMA_PLUS models per Cohort on both cleaned staging.hospital_flu_clean and uncleaned staging.hospital_flu. While ARIMA_PLUS trains, write and run zero-shot TimesFM forecasts per Cohort using AI.FORECAST. Log every run to ml.experiment_trials and rank them by chronological backtest WAPE in ml.forecast_leaderboard. Show me the ARIMA_PLUS SQL before you start it.
  ```
* **Review and Start (`00:55–00:57`)**: Approve the `ARIMA_PLUS` SQL so training starts by `00:57`. `ARIMA_PLUS` training takes **`18s`–`46s`** and `TimesFM` (`AI.FORECAST`) **`13s`**, so 60 seconds past the slower job means swapping in at `00:59`.
* **Key Evidence Shown**:
  - `ml.experiment_trials` records model family (`ARIMA_PLUS` vs `TimesFM`), training data state (`clean` vs `uncleaned`), **Cohort**, and chronological backtest **WAPE**.
  - `ml.forecast_leaderboard` proves that models trained on `staging.hospital_flu_clean` beat uncleaned models across every **Cohort**, and zero-shot `TimesFM` (`AI.FORECAST`) delivers competitive accuracy without training a model object.
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

#### Segment 2C: The Reveal Finale (`01:05–01:11`)
* **Window 2 — Load the Reveal (`01:05`, `11s`)**: Supply your separate withheld Cloud Storage bucket URI (stored outside the repo per [ADR 0001](docs/adr/0001-answer-key-outside-agent-reach.md)) to load the six post-**Cutoff** **Reveal** weeks (`2026-11-01` through `2026-12-12`):
  ```bash
  ./load-reveal gs://<your-withheld-bucket>/reveal
  ```
* **Type This Prompt into Window 1 (Command Center, `01:06`)**:
  ```text
  Compare our Cohort forecasts trained on uncleaned staging.hospital_flu versus cleaned staging.hospital_flu_clean against the six withheld post-Cutoff Reveal weeks, and display the Reveal comparison chart and post-Cutoff WAPE by model and data cleanliness.
  ```
* **Say to the Audience (The Finale Punchline)**:
  > "Until this moment, no agent or table in the workspace had access to what happened after Saturday, October 31, 2026. Look at `ml.reveal_forecast_evaluation`: the forecast trained on uncleaned `staging.hospital_flu` dramatically overshoots the six **Reveal** weeks because it mistook the +15-point **Pipeline Defect** and +8-point **Sampling Artifact** for exponential disease spread. The forecast trained on `staging.hospital_flu_clean` tracks reality tightly (`WAPE ~0.075` vs `~0.165` on uncleaned data). That is why **Workstream** 1 and **Workstream** 2 belong in the same **Command Center**."

#### Segment 2D: The Agent Creates & Runs the `cohort-forecast-refresh` Skill (`01:11–01:15`)
* **Type This Prompt into Window 1 (Command Center, `01:11`)**:
  ```text
  Create .agents/plugins/ds-command-center/skills/cohort-forecast-refresh/SKILL.md, following Rule 2 in the ds-command-center rules, that packages our Cohort feature refresh, ARIMA_PLUS and AI.FORECAST evaluation, and ml.experiment_trials logging workflow as a repeatable skill. Then dispatch a fresh subagent to run cohort-forecast-refresh for period 2026-W44.
  ```
* **Timing**: the agent should create `SKILL.md` and dispatch the subagent by `01:12`. If it hasn't dispatched the subagent 60 seconds past that, stop the agent and swap in the Window 2 fallback at `01:13`. Once the subagent is dispatched, never run the fallback alongside it: the refresh repeats the 2A and 2B jobs (`57s` + `46s` + `13s`, about `2 min`) and writes the same `ml.experiment_trials` rows. If the subagent is still running at `01:15`, move to Q&A and show its results there.
* **Window 2 Fallback (trigger at `01:13`, ~`2 min`)**:
  ```bash
  ./run-cohort-forecast-refresh --period 2026-W44
  ```
  Runs the presenter repo's copy of the skill, not the one the agent just wrote: say so on stage.

---

### 4.4 Q&A & Post-Stage Restoration (`15 min`, `01:15–01:30`)

After finishing Audience Q&A and disconnecting from the stage display, restore your personal `~/.gemini` rules and skills from the presenter repo on `main` (Window 2):

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
| **45-Minute Executive Briefing** | `45 min` | Prepare with the same T-15 reset ([Section 2](#2-pre-stage-checklist-t-15-minutes)).<br>- **Opening (`8 min`)**: Narrative setup + live `guardrail-hook` block (Window 1).<br>- **Workstream 1 (`17 min`)**: In Window 1, run parallel triage subagents + `stats-reviewer` live and review the agent's `pipeline_clean.py` diff; then swap in the Window 2 fallback `./checkpoint ws1_staging_clean` (`6s`) instead of waiting for the batch.<br>- **Workstream 2 & Reveal (`15 min`)**: Window 2 swaps in `./checkpoint ws2_seasonal_features` & `./checkpoint ws2_hospital_cohorts`. In Window 1, the agent writes and runs the zero-shot `AI.FORECAST` SQL live. Window 2 then swaps in the fallback `./checkpoint ws2_forecast_leaderboard` and runs `./load-reveal` for the **Reveal** punchline.<br>- **Q&A (`5 min`)**. |
| **60-Minute Technical Session** | `60 min` | Prepare with the same T-15 reset ([Section 2](#2-pre-stage-checklist-t-15-minutes)).<br>- **Opening (`10 min`)**: Full tour + live `guardrail-hook` block (Window 1).<br>- **Workstream 1 (`22 min`)**: In Window 1, live EDA, parallel triage subagents, `stats-reviewer`, and the agent's `pipeline_clean.py` diff; then the Window 2 fallback `./run-pipeline-clean --sql-fallback` (`5s`, runs the reference pipeline).<br>- **Workstream 2 & Reveal (`20 min`)**: In Window 1, the agent writes and runs the K-means **Cohort** SQL and the zero-shot `TimesFM` (`AI.FORECAST`) SQL live. Window 2 swaps in the fallback `./checkpoint ws2_forecast_leaderboard`, then loads the **Reveal** (`./load-reveal`). Back in Window 1, the agent creates the `cohort-forecast-refresh` skill.<br>- **Q&A (`8 min`)**. |
| **90-Minute Full Workshop** | `90 min` | Full live execution of every step in [Section 4](#4-act-by-act-live-demo-script), with the Window 2 fallback triggers in [Section 3.2](#32-window-2-fallback-triggers-docsrecorded_runtimesjson). |

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
