# Antigravity for Data Scientists Demo

A reusable live demo for data science teams: agents investigate whether a flu spike across 90 hospitals is a real outbreak, a sampling artifact, or a pipeline defect, then build cohort-level forecasts on the cleaned data.

## Language

### The harness

**Command Center**:
Antigravity as a data scientist's single place to direct day-to-day data work, together with everything connected to it (skills, subagents, MCP servers, hooks, Data Agent Kit).
_Avoid_: IDE, chatbot, copilot

### Data

**Hospital Feed**:
The daily raw submission of flu testing data from one hospital.
_Avoid_: Feed file, upload, hospital data

**Positivity**:
The share of flu tests that come back positive (positive tests ÷ total tests) for a hospital over a period.
_Avoid_: Positive rate, hit rate

**Spike**:
The headline anomaly: Northeast flu-positive test counts in the latest week are up 35% over the prior week. Measured in raw counts on purpose, not rates.
_Avoid_: Surge, outbreak (an outbreak is only one possible cause of the Spike)

**Cutoff**:
The last day of data the agents can see: Saturday, October 31, 2026. The Spike is measured in the week ending on the Cutoff.
_Avoid_: Today, as-of date, now

**Data Generator**:
The external tool that produces the synthetic Hospital Feeds and the Answer Key. It lives outside this repo; this repo only defines what it must produce.
_Avoid_: Simulator, faker

### Causes of the Spike

**Pipeline Defect**:
Inflation of the numbers caused by data processing rather than by patients, specifically Hospital Feeds that were ingested twice.
_Avoid_: Data bug, ETL issue

**Sampling Artifact**:
A rise in positive counts caused by more testing, with Positivity unchanged.
_Avoid_: Testing bias, volume effect

**Outbreak**:
A real rise in flu among patients, visible as rising Positivity at a localized set of hospitals.
_Avoid_: Spike, surge, cluster

**Seasonal Ramp**:
The normal early-season rise in flu that every hospital experiences.
_Avoid_: Trend, baseline growth

**Attribution**:
The breakdown of the Spike into the share caused by each cause above.
_Avoid_: Root cause, decomposition

**Answer Key**:
The record of which causes the Data Generator planted behind the Spike, and how large each one is. The agents never see it; the presenter uses it to check the agents' Attribution.
_Avoid_: Ground truth, solution

### Modeling

**Cohort**:
A group of hospitals with similar seasonal flu behavior, found by K-means clustering of per-hospital seasonal features.
_Avoid_: Cluster (in narration), segment, group

**Reveal**:
The finale: the six weeks of true data after the Cutoff, withheld from the agents, shown on screen against the forecasts built from clean and uncleaned data.
_Avoid_: Holdout, actuals, validation set

### Demo structure

**Workstream**:
One of the two acts of the demo: Workstream 1 asks "is the data good to use?" and Workstream 2 is "forecast at scale".
_Avoid_: Section, part, module

**Start Point**:
The clean state (code and data) a Workstream begins from, which the presenter can return to at any time. Workstream 2's Start Point is exactly where Workstream 1 ends.
_Avoid_: Snapshot, baseline

**Checkpoint**:
A pre-built result of one live step, swapped in if that step fails on stage. A Checkpoint covers one step; a Start Point covers a whole Workstream.
_Avoid_: Backup, cache
