# Data Science Primer for Presenters

This primer is designed for presenters without a formal data science background (e.g., developer relations advocates, solutions architects, platform engineers). It provides the plain-language intuition, methodological justification, and crisp, Q&A-ready answers needed to confidently address skeptical data scientists during live presentations.

---

## 1. Executive Context & Mental Model

In the live demo, a team investigates a **Spike** in Northeast flu-positive test counts (+35% week-over-week in the week ending on the **Cutoff**, Saturday, October 31, 2026) across 90 synthetic hospitals. Data scientists in the audience are naturally skeptical of automated AI findings. They expect checks for testing volume shifts, aggregated distortions, confounding factors, and proper evaluation metrics.

This primer equips the presenter to answer the critical question: **"Why is that the right check?"**

All terms strictly adhere to the project [GLOSSARY.md](../GLOSSARY.md).

---

## 2. Core Concepts & Q&A Playbook

### 2.1 Positivity

#### Plain-Language Intuition
Total positive test counts can increase simply because more tests were administered, not because more people are sick. **Positivity** is the proportion of tests that return positive:
$$\text{Positivity} = \frac{\text{Positive Tests}}{\text{Total Tests}}$$

#### Role in the Demo
In **Workstream 1**, when the initial data profiling highlights a +35% Spike in positive flu tests in the Northeast, the agent immediately computes Positivity across all 90 hospitals. This isolates actual disease spread from testing volume swings.

#### Why Is That the Right Check?
Relying on raw counts conflates epidemiology (how widely the virus is spreading) with hospital operations (how many testing kits were deployed). Positivity standardizes testing volume across hospitals of varying bed counts and testing practices.

#### Common Pitfall / Skeptic's Challenge
> *"Why not just track hospital admissions or raw positive counts?"*
> 
> Raw counts jump when asymptomatic screening programs or drive-through testing sites open. Hospital admissions lag disease transmission by one to two weeks, whereas testing Positivity is a leading indicator.

#### Q&A-Ready Answer
> **"Raw positive test counts conflate disease spread with testing capacity. Positivity—positive tests divided by total tests—normalizes for testing volume so we don't mistake increased testing for an actual epidemic."**

---

### 2.2 Sampling Artifacts

#### Plain-Language Intuition
A **Sampling Artifact** occurs when an apparent spike or drop in data is caused by how data was collected or sampled, rather than by a change in the underlying physical reality.

#### Role in the Demo
In **Workstream 1**, subagent analysis discovers that ~6 Northeast hospitals dramatically increased their testing volume leading up to the Cutoff, while their Positivity remained flat. This administrative change contributed ~8 percentage points of the +35% Spike.

#### Why Is That the Right Check?
Without isolating sampling artifacts, a health system or public health agency might trigger costly emergency containment procedures for what is merely an operational expansion of testing clinics.

#### Common Pitfall / Skeptic's Challenge
> *"Isn't an increase in positive cases always actionable, even if driven by volume?"*
> 
> Increased testing reveals previously undetected mild cases without reflecting an increased transmission rate. Treating a testing expansion as an outbreak leads to misallocated resources and skewed forecasting models.

#### Q&A-Ready Answer
> **"A Sampling Artifact occurs when testing volume increases while Positivity remains flat: the virus isn't spreading faster, we're simply casting a wider net. Checking Positivity against test volume separates operational testing shifts from real epidemiological spread."**

---

### 2.3 Simpson's Paradox

#### Plain-Language Intuition
**Simpson's Paradox** is a statistical phenomenon where a trend appears in several different groups of data but disappears or reverses when these groups are combined into an aggregate total.

#### Role in the Demo
In **Workstream 1**, the custom `stats-reviewer` subagent explicitly challenges the preliminary findings of the triage subagents. It tests whether the regional Northeast Spike is an artifact of aggregation—for example, if high-volume urban medical centers with naturally lower positivity are masking severe localized outbreaks in smaller rural community hospitals, or vice versa.

#### Why Is That the Right Check?
Aggregation weights groups by their total volume. If high-testing hospitals have low positivity, and low-testing hospitals have high positivity, shifts in which hospitals submit data can create the illusion of a rising or falling regional rate even when individual hospital rates haven't changed.

#### Common Pitfall / Skeptic's Challenge
> *"Why bother disaggregating if the regional average Positivity is already calculated?"*
> 
> Because an aggregate rate can rise even if Positivity at every single individual hospital fell, purely due to a compositional shift in patient testing volumes across facilities.

#### Q&A-Ready Answer
> **"Simpson's Paradox warns that aggregate trends can completely reverse when broken down into subgroups due to shifting volume weights. We check both hospital-level and regional distributions to ensure an aggregate Spike isn't an optical illusion caused by shifts in reporting mix."**

---

### 2.4 K-means Clustering

#### Plain-Language Intuition
**K-means** is an unsupervised machine learning algorithm that groups observations into $K$ distinct clusters (in our narrative, **Cohorts**) based on how close their feature values are to the centroid (center) of each group.

#### Role in the Demo
In **Workstream 2**, BQML K-means clusters the 90 hospitals into four distinct seasonal **Cohorts** using per-hospital historical features (peak arrival week, peak volume, curve width, and baseline trend).

#### Why Is That the Right Check?
Training 90 separate hospital models leads to high variance and overfitting on smaller facilities with noisy feeds. Conversely, training a single aggregate model obscures regional and clinical heterogeneity. Grouping hospitals into four Cohorts strikes the ideal bias-variance balance: facilities with similar seasonal dynamics share statistical strength.

#### Why These Four Seasonal Features (Peak Arrival Week, Peak Volume, Curve Width, and Trend)
Each of the four features in `features.hospital_seasonal_features` captures an orthogonal geometry of a hospital's flu curve computed from `staging.hospital_flu_clean`:
1. **Peak Arrival Week (`peak_arrival_week`) — Timing**: Measures *when* the seasonal wave crests (average weeks after MMWR Week 40). Separating early-peaking urban medical centers (~12.5 weeks) from late-peaking rural clinics (~22.0 weeks) prevents a shared forecast from averaging two distinct peaks into a flat, mistimed plateau.
2. **Peak Volume (`peak_volume`) — Scale**: Measures *how high* weekly positive flu tests climb at the crest of the season (~289 weekly positives in large urban centers vs ~62 in rural clinics), anchoring the amplitude of each **Cohort**.
3. **Curve Width (`curve_width`) — Wave Shape**: Measures *how broad or sharp* the seasonal wave is by counting the weeks per season where weekly positive tests reach at least 50% of that season's peak (full width at half maximum). Suburban hospitals sustain broad plateaus (~17 weeks above half-peak), whereas rural hospitals experience sharp, narrow spikes (~5 weeks above half-peak).
4. **Seasonal Trend (`seasonal_trend`) — Early-Season Inflection**: Measures the ratio of **Positivity** in the **Spike** week ending on the **Cutoff** (`2026-10-25`..`2026-10-31`) to the prior week (`2026-10-18`..`2026-10-24`). While facilities on the normal **Seasonal Ramp** hover near `1.01`, hospitals experiencing an active **Outbreak** surge to `2.71` (~16.3% vs ~6.0% **Positivity**).

On the mock dataset, standardized 4-means (`ml.hospital_cohort_kmeans`) isolates the three Northeast **Outbreak** hospitals (`HOSP_NE_001`, `HOSP_NE_004`, `HOSP_NE_006`) into their own dedicated three-hospital **Cohort** (`COHORT_4`), with `seasonal_trend = 2.7143` (compared to $\le 1.0353$ across all non-**Outbreak** hospitals) and a minimum inter-**Cohort** centroid distance above `3.49` standard deviations. Isolating the **Outbreak** hospitals into their own **Cohort** allows downstream forecasting models to track their steep trajectory without contaminating baseline **Cohorts**.

#### Common Pitfall / Skeptic's Challenge
> *"Why not cluster by geography or bed count instead of seasonal curve features?"*
> 
> Geographic proximity does not guarantee identical epidemiological behavior. A suburban community hospital and a major urban tertiary referral center in the same state often experience vastly different seasonal curves. Clustering directly on curve dynamics groups hospitals by operational reality.

#### Q&A-Ready Answer
> **"Rather than training 90 noisy individual hospital models or one blunt aggregate model, BQML K-means groups hospitals with shared seasonal dynamics into four Cohorts. This allows forecasting models to learn distinct seasonal trajectories without manual hospital-by-hospital segmentation."**

---

### 2.5 ARIMA_PLUS

#### Plain-Language Intuition
**ARIMA_PLUS** is BigQuery ML's production-grade statistical forecasting algorithm. It builds upon classical Auto-Regressive Integrated Moving Average (ARIMA) modeling by automating trend extraction, holiday effect adjustments, multiple seasonalities (weekly, annual), and outlier/anomaly handling.

#### Role in the Demo
In **Workstream 2**, ARIMA_PLUS is trained per Cohort across multiple time series to provide a rigorous, transparent classical baseline against which modern foundation models are evaluated.

#### Why Is That the Right Check?
Enterprise data science teams do not adopt complex or foundation models without benchmarking them against an interpretable, battle-tested classical time-series baseline. ARIMA_PLUS provides that standard benchmark directly in SQL.

#### Common Pitfall / Skeptic's Challenge
> *"Why not jump straight to deep learning or LLM-based time series models?"*
> 
> Classical statistical models frequently outperform or match deep learning models on structured seasonal data, with lower computational cost, full parameter interpretability, and complete determinism.

#### Q&A-Ready Answer
> **"ARIMA_PLUS is BigQuery's battle-tested classical time series baseline that handles trend, seasonality, and calendar effects automatically. We train it per Cohort to establish a rigorous, interpretable benchmark that any advanced or foundation model must beat."**

---

### 2.6 TimesFM

#### Plain-Language Intuition
**TimesFM** (Time Series Foundation Model) is a pretrained foundation model developed by Google Research specifically for time series forecasting. Much like large language models understand text zero-shot, TimesFM understands sequential temporal patterns without requiring task-specific fine-tuning.

#### Role in the Demo
In **Workstream 2**, TimesFM is evaluated zero-shot via BigQuery's `AI.FORECAST` function and compared side-by-side on the experiment leaderboard against ARIMA_PLUS.

#### Why Is That the Right Check?
Data science teams want to know whether pretrained foundation models can provide high-quality forecasts immediately out-of-the-box, saving weeks of bespoke feature engineering, hyperparameter tuning, and model retraining cycles.

#### Common Pitfall / Skeptic's Challenge
> *"Can a zero-shot foundation model really understand specialized hospital flu dynamics without retraining?"*
> 
> TimesFM was pretrained on hundreds of billions of real-world time points spanning diverse domains. Its architectural priors capture multi-frequency seasonal curves and trend inflections effectively without local weight updates.

#### Q&A-Ready Answer
> **"TimesFM is a zero-shot time series foundation model from Google Research invoked via BigQuery's AI.FORECAST. It lets us test whether a pre-trained foundation model can produce competitive forecasts out-of-the-box without custom model training or hyperparameter tuning."**

---

### 2.7 Backtesting

#### Plain-Language Intuition
**Backtesting** is the process of evaluating a forecasting model by strictly simulating historical time progression: training on data up to a fixed historical date, forecasting into the subsequent historical window, and comparing those predictions against what actually occurred.

#### Role in the Demo
In **Workstream 2**, all models are backtested on the historical 2025–26 flu season (trained up to the start of the seasonal peak, then tasked with forecasting eight weeks forward).

#### Why Is That the Right Check?
Standard k-fold cross-validation randomly shuffles rows, which leaks future information into past training partitions (temporal data leakage). Backtesting preserves the arrow of time and accurately reproduces the exact conditions under which the model will be deployed in production.

#### Common Pitfall / Skeptic's Challenge
> *"Why not use standard 80/20 random train/test split or k-fold cross-validation?"*
> 
> Random splitting is disastrous for time series because tomorrow's data would be used to predict yesterday's data. Backtesting strictly enforces that only past information is available at prediction time.

#### Q&A-Ready Answer
> **"Standard cross-validation leaks future information into past time steps. Backtesting strictly respects the arrow of time: we train only up to the start of the historical 2025–26 peak and forecast eight weeks forward, proving how the models would have performed live on stage."**

---

### 2.8 WAPE (Weighted Absolute Percentage Error)

#### Plain-Language Intuition
**WAPE** is an aggregate forecast error metric that sums the total absolute errors across all predictions and divides by the total actual values:
$$\text{WAPE} = \frac{\sum |y - \hat{y}|}{\sum y}$$

#### Role in the Demo
In **Workstream 2**, WAPE is the primary metric displayed on the experiment leaderboard to rank ARIMA_PLUS and TimesFM across Cohorts and data cleanliness states.

#### Why Is That the Right Check?
Unlike MAPE (Mean Absolute Percentage Error), which calculates percentage error per individual observation ($\frac{|y - \hat{y}|}{y}$), WAPE avoids division by zero or explosive percentages during low-volume periods (such as summer off-season flu testing). It naturally weights errors proportionally to hospital patient volume.

#### Common Pitfall / Skeptic's Challenge
> *"Why use WAPE instead of standard MAPE or RMSE?"*
> 
> In epidemiology, off-season weeks often have tiny actual counts (e.g., 2 cases). A forecast of 4 is an error of only 2 cases, but MAPE registers a 100% error. WAPE aggregates across the full volume, preventing low-volume noise from dominating the evaluation.

#### Q&A-Ready Answer
> **"Unlike MAPE, which divides by zero or blows up when flu cases are low, WAPE divides total absolute error by total actual cases. It weights errors proportional to volume so high-volume hospitals carry appropriate weight and small off-season counts don't distort the metric."**

---

## 3. The `stats-reviewer` Dynamic: Why Agent Peer Review Matters

A recurring theme in the Command Center is that one data scientist directs multiple agents and reviews the evidence. A common fear among technical audiences is that AI agents blindly confirm each other's hallucinations.

In **Workstream 1**, we demonstrate an adversarial peer-review architecture:
1. **Three Triage Subagents** investigate candidate causes independently:
   - *Distribution subagent*: Evaluates spatial concentration and regional variance.
   - *Sampling subagent*: Analyzes test kit volume shifts versus Positivity.
   - *Pipeline subagent*: Correlates anomaly timestamps with ingestion batch logs.
2. **`stats-reviewer` Subagent**:
   - Acts as the adversarial skeptic.
   - Pushes back against conclusions based on raw counts rather than rates.
   - Evaluates small-sample instability in low-volume rural hospitals.
   - Checks for Simpson's Paradox across regional aggregations.
3. **Presenter Takeaway for Q&A**:
   > *"The Command Center doesn't just generate answers; it stages adversarial peer reviews between subagents before presenting a reconciled Attribution table for human sign-off."*

---

## 4. Summary Q&A Cheat Sheet

| Topic | Skeptical Question | 10-Second Stage Answer |
| :--- | :--- | :--- |
| **Positivity** | *"Why not look at positive counts?"* | *"Counts conflate testing volume with disease spread; Positivity normalizes for testing capacity."* |
| **Sampling Artifact** | *"Isn't more positive tests always real spread?"* | *"If volume doubled and Positivity stayed flat, testing expanded—the disease transmission rate didn't change."* |
| **Simpson's Paradox** | *"Why not trust the regional average?"* | *"Aggregate trends can reverse when reporting volume shifts across different hospital types."* |
| **K-means** | *"Why cluster into Cohorts?"* | *"90 individual models overfit; one global model blunts variation. Four seasonal Cohorts balance stability and granularity."* |
| **ARIMA_PLUS** | *"Why train classical ARIMA?"* | *"It provides an interpretable, production-tested statistical benchmark that any foundation model must beat."* |
| **TimesFM** | *"Why use TimesFM?"* | *"It tests whether a zero-shot foundation model delivers high forecasting accuracy out-of-the-box without custom retraining."* |
| **Backtesting** | *"Why not random k-fold splits?"* | *"Time series requires strict chronological order; backtesting prevents future data leakage into training."* |
| **WAPE** | *"Why WAPE over MAPE?"* | *"MAPE blows up on low off-season counts; WAPE weights errors by patient volume for stable comparison."* |
