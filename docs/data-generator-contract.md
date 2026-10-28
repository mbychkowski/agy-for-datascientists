# Data Generator Contract

This document defines the written contract for producing synthetic datasets for the Antigravity for Data Scientists demo. Both the external **Data Generator** tool (owned by the presenter) and the internal mock dataset (built for development and testing) conform to this contract. Adherence to this specification guarantees that data generation remains independent of the repository codebase and that the live demonstration storyline resolves predictably and verifiably.

All terminology strictly adheres to [GLOSSARY.md](../GLOSSARY.md) and respects [ADR 0001](adr/0001-answer-key-outside-agent-reach.md). This contract is company-neutral.

---

## 1. Temporal Horizons and Calendar Conventions

The dataset spans daily reporting across three full seasons plus the current season up to the **Cutoff**, followed by a withheld six-week **Reveal** period.

### 1.1 Epidemiological Week Standards
- **Calendar Standard**: CDC Morbidity and Mortality Weekly Report (MMWR) epidemiological weeks.
- **Week Boundaries**: Each MMWR week begins on Sunday at 00:00:00 UTC and ends on Saturday at 23:59:59 UTC.
- **Season Definition**: An influenza season runs from MMWR week 40 of year $Y$ through MMWR week 39 of year $Y+1$.
- **Grain**: Hospital Feeds are generated and stored at a daily grain, and analyzed and forecasted at a weekly grain (aggregating Sunday through Saturday).

### 1.2 Seasons and Horizons
1. **Historical Seasons** (3 full seasons):
   - **2023–24 Season**: 2023-10-01 (MMWR 2023 Week 40) through 2024-09-28 (MMWR 2024 Week 39) — 52 weeks (364 days).
   - **2024–25 Season**: 2024-09-29 (MMWR 2024 Week 40) through 2025-09-27 (MMWR 2025 Week 39) — 52 weeks (364 days).
   - **2025–26 Season**: 2025-09-28 (MMWR 2025 Week 40) through 2026-10-03 (MMWR 2026 Week 39) — 53 weeks (371 days).
2. **Current Season up to the Cutoff**:
   - **2026–27 Season (to Cutoff)**: 2026-10-04 (MMWR 2026 Week 40) through 2026-10-31 (MMWR 2026 Week 43) — 4 weeks (28 days).
   - **Cutoff Date**: Saturday, October 31, 2026. This is the last day of data the agents can see.
   - **Total Visible Range**: 2023-10-01 through 2026-10-31 (1,127 days per hospital under normal ingestion).
3. **The Reveal Horizon** (withheld from agents):
   - **Reveal Period**: Sunday, 2026-11-01 (MMWR 2026 Week 44) through Saturday, 2026-12-12 (MMWR 2026 Week 49) — exactly 6 weeks (42 days, extending through mid-December).

---

## 2. Table Specifications and Schemas

The contract defines three primary tables across two BigQuery datasets: `raw` (for reference data and incoming feeds) and `ops` (for pipeline operational telemetry).

### 2.1 Hospital Reference Table: `raw.hospital_reference`

A reference table containing metadata and geographic attributes for all monitored hospitals.

- **Dataset**: `raw`
- **Table Name**: `hospital_reference`
- **Grain**: One row per hospital (`hospital_id` unique primary key).
- **Volume**: Exactly 90 hospitals distributed across several geographic regions:
  - **Northeast**: 25 hospitals (contains the Spike, the Outbreak hospitals, and the duplicate backfill).
  - **Midwest**: 25 hospitals.
  - **South**: 25 hospitals.
  - **West**: 15 hospitals.
- **Labels**: Carries `demo: true`.

#### Column Specifications
| Column Name | BigQuery Type | Mode | Description | Example |
| :--- | :--- | :--- | :--- | :--- |
| `hospital_id` | `STRING` | `REQUIRED` | Unique synthetic hospital identifier. | `HOSP_NE_001` |
| `hospital_name` | `STRING` | `REQUIRED` | Synthetic facility name. | `Pine Valley Medical Center` |
| `region` | `STRING` | `REQUIRED` | Geographic region (`Northeast`, `Midwest`, `South`, `West`). | `Northeast` |
| `state` | `STRING` | `REQUIRED` | Two-letter US state postal code. | `NY` |
| `urban_rural` | `STRING` | `REQUIRED` | Demographic classification (`Urban`, `Suburban`, `Rural`). | `Urban` |
| `bed_count` | `INT64` | `REQUIRED` | Licensed bed capacity (range 50 to 1,200). | `450` |

### 2.2 Hospital Feeds Table: `raw.hospital_flu_feeds`

The daily raw submission of flu testing data from each hospital.

- **Dataset**: `raw`
- **Table Name**: `hospital_flu_feeds`
- **Grain**: Daily feed per hospital. Logically `(hospital_id, feed_date)`. When duplicate feeds occur, multiple physical rows share the same `(hospital_id, feed_date)` with different `batch_id` and `ingested_at` values.
- **Time Range**: 2023-10-01 through 2026-10-31.
- **Volume**: 90 hospitals $\times$ 1,127 days = 101,430 base rows, plus 40 planted duplicate rows in the Northeast Spike week (8 hospitals $\times$ 5 dates).
- **Labels**: Carries `demo: true`.

#### Column Specifications
| Column Name | BigQuery Type | Mode | Description | Example |
| :--- | :--- | :--- | :--- | :--- |
| `hospital_id` | `STRING` | `REQUIRED` | Foreign key referencing `hospital_reference.hospital_id`. | `HOSP_NE_008` |
| `feed_date` | `DATE` | `REQUIRED` | Observation date for the daily report (YYYY-MM-DD). | `2026-10-28` |
| `total_flu_tests` | `INT64` | `REQUIRED` | Total diagnostic flu tests administered ($\ge 0$). | `120` |
| `positive_flu_tests` | `INT64` | `REQUIRED` | Total flu tests returning positive ($0 \le \text{positive} \le \text{total}$). | `18` |
| `batch_id` | `STRING` | `REQUIRED` | Ingestion batch identifier. | `BATCH-20261028-01` |
| `ingested_at` | `TIMESTAMP` | `REQUIRED` | UTC timestamp recording when the feed record was ingested. | `2026-10-28 04:15:00 UTC` |

### 2.3 Pipeline Run Log Table: `ops.pipeline_run_log`

Operational log recording batch ingestion runs. Used by the pipeline triage subagent to identify anomalous runs and correlate duplicate feeds with re-sent backfill jobs.

- **Dataset**: `ops`
- **Table Name**: `pipeline_run_log`
- **Grain**: One row per pipeline execution run (`run_id` unique primary key).
- **Time Range**: 2023-10-01 through 2026-10-31.
- **Frequency and Volume**: Daily scheduled ingestion runs (1 run per calendar day = 1,127 scheduled runs covering daily feeds for all 90 hospitals), plus ad-hoc backfill runs, including the errant backfill run `RUN-20261031-BF01` executed on the morning of 2026-10-31.
- **Labels**: Carries `demo: true`.

#### Column Specifications
| Column Name | BigQuery Type | Mode | Description | Example |
| :--- | :--- | :--- | :--- | :--- |
| `run_id` | `STRING` | `REQUIRED` | Unique execution run identifier. | `RUN-20261031-BF01` |
| `pipeline_name` | `STRING` | `REQUIRED` | Pipeline job name (`hospital_flu_daily_ingest` or `hospital_flu_backfill`). | `hospital_flu_backfill` |
| `run_type` | `STRING` | `REQUIRED` | Execution type: `scheduled` (daily cron) or `backfill` (re-sent / correction run). | `backfill` |
| `date_range_start` | `DATE` | `REQUIRED` | Earliest observation date covered by the batch run. | `2026-10-26` |
| `date_range_end` | `DATE` | `REQUIRED` | Latest observation date covered by the batch run. | `2026-10-30` |
| `started_at` | `TIMESTAMP` | `REQUIRED` | UTC timestamp when the pipeline execution started. | `2026-10-31 06:15:00 UTC` |
| `finished_at` | `TIMESTAMP` | `REQUIRED` | UTC timestamp when the pipeline execution finished. | `2026-10-31 06:18:42 UTC` |
| `status` | `STRING` | `REQUIRED` | Run status: `SUCCESS` or `FAILED`. | `SUCCESS` |
| `rows_written` | `INT64` | `REQUIRED` | Count of feed rows appended to `raw.hospital_flu_feeds`. | `40` |

---

## 3. Duplicate Rule and Deduplication Specification

### 3.1 Duplicate Feed Characteristics
- **Count Invariance**: Duplicated feeds carry **identical counts**. When a feed for hospital $H$ and feed date $D$ is duplicated, both records share identical values for `total_flu_tests` and `positive_flu_tests`.
- **Metadata Variation**: The duplicate record differs only in its operational metadata:
  - `batch_id`: Reflects the backfill batch identifier (e.g., `BATCH-20261031-BACKFILL-01`) rather than the regular scheduled batch (e.g., `BATCH-20261026-01`).
  - `ingested_at`: Carries a later UTC ingestion timestamp (e.g. `2026-10-31 06:16:00 UTC`) than the original scheduled record (e.g. `2026-10-26 04:10:00 UTC`).

### 3.2 Deduplication Tie-Break Rule
A single Hospital Feed is logically identified by `(hospital_id, feed_date)`. When multiple records exist for the same `(hospital_id, feed_date)`:
1. **Primary Tie-Break**: Retain the record with the latest `ingested_at` timestamp.
2. **Secondary Tie-Break**: If multiple records share the identical `ingested_at` timestamp, retain the record with the lexicographically greatest `batch_id` (`ORDER BY batch_id DESC`).

### 3.3 Metric Definition
- **Positivity**: $\text{Positivity} = \frac{\text{positive\_flu\_tests}}{\text{total\_flu\_tests}}$. When `total_flu_tests = 0`, Positivity is null.

---

## 4. The Northeast Spike and Planted Causes

### 4.1 Headline Anomaly
- **Definition**: In the week ending on the Cutoff (MMWR 2026 Week 43: Sunday, 2026-10-25 through Saturday, 2026-10-31), Northeast region total flu-positive test counts are **+35.0%** over the prior week (MMWR 2026 Week 42: Sunday, 2026-10-18 through Saturday, 2026-10-24).
- **Metric Formulation**: Measured strictly in **raw counts** on purpose (not Positivity or population rates), ensuring that pipeline duplicate errors and testing volume shifts visibly inflate the headline figure.

### 4.2 Target Attribution Breakdown
The +35.0% Spike decomposes across four planted causes:

| Cause | Target Share of Spike | Affected Hospitals | Date Range | Primary Data Footprint |
| :--- | :---: | :--- | :--- | :--- |
| **Pipeline Defect** | ~15 percentage points | ~8 Northeast hospitals | 2026-10-26 to 2026-10-30 (~5 days) | Re-sent duplicate feeds in `raw.hospital_flu_feeds`; matching `backfill` run in `ops.pipeline_run_log`. |
| **Sampling Artifact** | ~8 percentage points | ~6 Northeast hospitals | 2026-10-25 to 2026-10-31 (Spike week) | ~40–50% rise in `total_flu_tests` with flat `Positivity`. |
| **Outbreak** | ~7 percentage points | 3 neighbouring NE hospitals | 2026-10-25 to 2026-10-31 (and into Reveal) | Sharp rise in `Positivity` (~6% $\to$ ~16–18%) with stable test volume. |
| **Seasonal Ramp** | ~5 percentage points | All 90 hospitals | 2026-10-25 to 2026-10-31 (ongoing in Oct) | Normal early-season rise of ~5% week-over-week across all regions. |
| **Total Spike** | **+35.0 percentage points** | — | — | **Northeast positive test count +35% WoW** |

### 4.3 Planted Cause Mechanics

#### 1. Pipeline Defect (~15 points)
- **Mechanics**: A defective upstream backfill re-ingests 5 days of Hospital Feeds (Monday, 2026-10-26 through Friday, 2026-10-30) for 8 specific Northeast hospitals.
- **Data Footprint**:
  - Exactly duplicate records appear in `raw.hospital_flu_feeds` with identical test counts, duplicate `(hospital_id, feed_date)`, distinct backfill `batch_id`, and later `ingested_at`.
  - An entry is logged in `ops.pipeline_run_log` on the morning of 2026-10-31 (`started_at: 2026-10-31 06:15:00 UTC`) with `run_type = 'backfill'`, status `SUCCESS`, `date_range_start = '2026-10-26'`, `date_range_end = '2026-10-30'`, and `rows_written = 40` (8 hospitals $\times$ 5 days).
- **Resolution**: Deduplication (retaining the latest feed per hospital and date) eliminates the duplicate rows, removing ~15 percentage points of the spike.

#### 2. Sampling Artifact (~8 points)
- **Mechanics**: ~6 Northeast hospitals (distinct from the Outbreak hospitals) sharply ramp up testing volume (e.g., implementing employee screening or walk-in testing campaigns).
- **Data Footprint**:
  - `total_flu_tests` increases by ~40% to 50% week-over-week.
  - `Positivity` remains flat and consistent with the historical baseline.
- **Resolution**: The triage subagents identify that test volume increased while Positivity was unchanged, attributing ~8 percentage points to testing expansion.

#### 3. Outbreak (~7 points)
- **Mechanics**: A localized rise in flu infections among patients at 3 neighbouring hospitals in adjacent counties within the Northeast.
- **Data Footprint**:
  - `Positivity` jumps sharply from ~6% to ~16–18% during the Spike week.
  - `total_flu_tests` remains steady or shows minor natural variation.
  - In Workstream 2, seasonal feature engineering on clean data highlights these 3 hospitals as distinct outliers, forming their own **Cohort** in BQML K-means.
- **Resolution**: Identified as true patient transmission accounting for ~7 percentage points of the Spike.

#### 4. Seasonal Ramp (~5 points)
- **Mechanics**: Normal early-season rise in flu transmission observed across all hospitals and regions.
- **Data Footprint**:
  - Positive counts across non-anomaly hospitals increase by ~5% week-over-week, tracking historical seasonal onset curves.
- **Resolution**: Accounts for the remaining ~5 percentage points of the Spike.

---

## 5. Answer Key and Reveal Data Specifications

In accordance with [ADR 0001](adr/0001-answer-key-outside-agent-reach.md), the **Answer Key** and **Reveal** data are kept outside the reach of Antigravity agents. They are written to a presenter-managed private storage location (such as a private GCS bucket created outside Terraform).

> [!IMPORTANT]
> Neither this contract nor any file in this repository names or references the private storage location. The presenter supplies the storage path only at runtime via CLI arguments during end-state verification and the finale Reveal.

### 5.1 Answer Key Format (`answer_key.json`)
The Answer Key records the planted causes and their target shares of the Spike, used by the presenter to check the agents' Attribution.

```json
{
  "contract_version": "1.0",
  "seed": 42,
  "evaluation_window": {
    "target_region": "Northeast",
    "baseline_week_start": "2026-10-18",
    "baseline_week_end": "2026-10-24",
    "spike_week_start": "2026-10-25",
    "spike_week_end": "2026-10-31",
    "headline_spike_pct": 35.0
  },
  "attribution": [
    {
      "cause": "pipeline_defect",
      "target_points": 15.0,
      "affected_hospitals": [
        "HOSP_NE_003",
        "HOSP_NE_007",
        "HOSP_NE_011",
        "HOSP_NE_014",
        "HOSP_NE_016",
        "HOSP_NE_019",
        "HOSP_NE_022",
        "HOSP_NE_025"
      ],
      "date_range": {
        "start": "2026-10-26",
        "end": "2026-10-30"
      },
      "manifestation": "Re-sent backfill duplicate feeds with identical counts and later ingested_at"
    },
    {
      "cause": "sampling_artifact",
      "target_points": 8.0,
      "affected_hospitals": [
        "HOSP_NE_002",
        "HOSP_NE_005",
        "HOSP_NE_009",
        "HOSP_NE_013",
        "HOSP_NE_018",
        "HOSP_NE_021"
      ],
      "date_range": {
        "start": "2026-10-25",
        "end": "2026-10-31"
      },
      "manifestation": "Testing volume increased ~45% with positivity remaining flat"
    },
    {
      "cause": "outbreak",
      "target_points": 7.0,
      "affected_hospitals": [
        "HOSP_NE_001",
        "HOSP_NE_004",
        "HOSP_NE_006"
      ],
      "date_range": {
        "start": "2026-10-25",
        "end": "2026-10-31"
      },
      "manifestation": "Positivity jumped from 6% to 17% with stable testing volume"
    },
    {
      "cause": "seasonal_ramp",
      "target_points": 5.0,
      "affected_hospitals": [
        "*"
      ],
      "date_range": {
        "start": "2026-10-25",
        "end": "2026-10-31"
      },
      "manifestation": "Normal early-season rise across all regions"
    }
  ]
}
```

### 5.2 Reveal Data Format

The **Reveal** dataset contains the true data of the six weeks following the Cutoff (Sunday, 2026-11-01 through Saturday, 2026-12-12), withheld from the agents during the live demo.

- **Schema**: Exact match to `raw.hospital_flu_feeds` (`hospital_id`, `feed_date`, `total_flu_tests`, `positive_flu_tests`, `batch_id`, `ingested_at`).
- **Volume**: 90 hospitals $\times$ 42 days = 3,780 rows.
- **Characteristics**:
  - Completely free of duplicate feeds or artificial pipeline defects.
  - Follows the true epidemiological trajectory: the 3 Outbreak hospitals continue their elevated curve, while other hospitals follow normal seasonal patterns.
  - In the finale, the true data is shown on screen against the forecasts built from clean and uncleaned data; the uncleaned model visibly overshoots.

---

## 6. Seed Determinism

The Data Generator must accept an integer random seed parameter (e.g., `--seed <int>`).
- **Strict Reproducibility**: Given the same seed, the generator must produce identical records across all tables, including hospital identifiers, test counts, timestamps, batch IDs, the Answer Key, and the Reveal dataset.
- **Idempotence**: Successive runs with the same seed yield identical files and checksums, ensuring rehearsals, automated tests, and live demonstrations remain completely consistent.

---

## 7. Hand-Off Format to Setup

The generated dataset is exported in a structured directory format ready for one-time loading:

```
<dataset-root>/
├── raw/
│   ├── hospital_reference.csv (or .parquet)
│   └── hospital_flu_feeds/
│       └── *.parquet (or .csv)
└── ops/
    └── pipeline_run_log.csv (or .parquet)
```

The withheld bundle (for the presenter's private storage location per ADR 0001) is produced alongside:
```
<withheld-root>/
├── answer_key.json
└── reveal/
    └── hospital_flu_feeds_reveal/
        └── *.parquet (or .csv)
```

### Hand-Off Mechanism Demarcation
The transport mechanism (e.g., whether files are staged to an ingestion GCS bucket or read from a local directory path passed to the setup command) is explicitly left to the **Refined Data Generator and hand-off** ticket (#9) and the **Workstream 1 data state** ticket (#10). The mock dataset (#8) provides in-repo test fixtures following this exact schema.

---

## 8. Glossary Vocabulary and Neutrality

In compliance with `docs/agents/domain.md`, all terminology in this contract strictly conforms to [GLOSSARY.md](../GLOSSARY.md). Explicit care is taken to avoid prohibited synonyms (such as avoiding *ground truth* for Answer Key, *actuals* or *holdout* for Reveal, *cluster* or *surge* for Outbreak, and *baseline growth* or *trend* for Seasonal Ramp). The contract is neutral and contains no client-, person-, or event-specific information.
