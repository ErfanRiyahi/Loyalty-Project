# Clustering validation, experimental risk screening, and adaptive learning

## Install this update

This package contains only changed and new files. Apply it to the latest restructured project after the prior Dataset Overview JSON correction. Extract it into the existing `loyalty_project` directory, preserving paths. Restart `python app.py`, then hard-refresh the browser (Ctrl+F5) to load the updated JavaScript. Keep existing datasets, outputs and model folders. No new Python dependency is required.

The common reader now uses the supplied implementation: `low_memory=True`, string dtype for requested MSISDN variants, and `sep="|"` for `.txt`. With `usecols=None`, identifier types are inferred, exactly as in the supplied code. `low_memory=True` reduces parser pressure but still returns a complete DataFrame; it is not a streaming pipeline.

The customer-ID cleaners have not been changed because the source formats are unconfirmed. They currently remove the first two characters from string IDs. Verify an anonymized example from each source before trusting customer joins: the same subscriber must resolve to the same identifier. The new clustering input checks reject empty or duplicate IDs but cannot detect different IDs that actually belong to one person. Confirm that the voice source is pipe-delimited.

## Algorithms currently used

Clustering remains KMeans with **k=3**, `n_init=10`, and `random_state=42`. It fits multi-domain customers using RobustScaler on continuous features plus weighted binary flags. Cluster names are assigned by ranking average engagement; these names are interpretations, not observed churn outcomes. Customers with fewer than two present score groups remain outside KMeans in the Limited tier. Neither silhouette nor the cluster named At-Risk/Churning proves that a customer will churn.

The original churn method is a deterministic, unsupervised rank-based screening rule. It never learned a relationship between past behavior and future churn. For each score column, present and informative values receive average ranks for ties:

`p_ij = (rank_ij - 1) / (n_j - 1)`

The original risk index is:

`baseline_i = 100 × (1 - mean_j(p_ij))`

Higher scores are assumed to mean stronger loyalty. Missing, non-finite, constant and singleton score evidence is excluded. Available `HAS_*` flags mask absent groups. At least two informative scores are required. Bands are Low <34, Medium 34–<67, High ≥67. Thresholds are heuristic. A value of 80 is not an 80% probability of churn. Ranking is relative to the submitted cohort, so it changes when that cohort changes.

## New clustering validation

Run Cluster to see the following diagnostics. These are computed in the same weighted feature space used by KMeans, on multi-domain customers only.

| Diagnostic | Reading | Population / limits |
| --- | --- | --- |
| Silhouette | Higher is better; near zero suggests overlapping groups, negative values indicate a point is closer on average to another group | All rows if ≤2,000; otherwise uniform sample of 2,000, seed 42, distances calculated within that sample |
| Davies–Bouldin | Lower is better | All clustered rows |
| Calinski–Harabasz | Higher generally indicates better separation | All clustered rows; compare runs with comparable sample sizes and feature construction |
| Cluster sizes | Very small groups merit inspection | Count/share per cluster; warning below 1% |
| Per-cluster silhouette and negative share | Identify poorly separated groups | Same silhouette sample; counts shown |
| Subsample stability ARI | Near 1 means partitions agree despite arbitrary numeric cluster IDs | Five seeded refits, 80% of rows capped at 10,000, evaluated against the main partition on the same ≤2,000 sample |

The stability refits keep preprocessing and feature weights fixed. They test sensitivity of the KMeans fit to subsampling and initialization, not the entire feature pipeline and not future churn accuracy. Evaluation rows may also be in a refit's training subset; this is deliberately an in-sample robustness test. It is not a holdout score. ARI is invariant to permutations of cluster IDs, so no misleading direct comparison of numeric IDs is needed.

Metrics are unavailable when there are only three customers in three clusters. Stability requires at least ten clustered customers. A silhouette sample that omits a cluster is reported as unavailable. Degenerate stability refits are skipped with reasons and the successful-run count is shown. The checkbox can disable refits to reduce processing time. Main KMeans still fits all eligible customers; this update does not make the full pipeline out-of-core.

Files generated:

- `outputs/cluster_validation.json`: latest validation, downloadable from the Cluster tab.
- `outputs/models/<run_id>/validation.json`: run-specific validation, parameters, seeds, feature names and input file metadata.
- `outputs/models/<run_id>/segmentation.csv`: corresponding customer assignments.
- Existing `model.pkl` and registry remain in use. Cluster IDs are now included in the latest segmentation CSV; Limited customers have a blank ID.

Source metadata records paths, row counts and modification timestamps, not input hashes. For exact thesis reproduction, archive the input score CSVs as well as the run artifacts.

A confusion matrix requires independent labels. Three loyalty clusters and binary churn are different targets. Do not use the cluster names or a risk threshold as both prediction and ground truth. When real outcomes become available, either evaluate an independently fixed cluster-to-churn mapping on held-out data, or train a supervised churn model. For independent segment labels, use ARI/NMI or a label-aligned confusion matrix.

## Implemented candidate thesis contribution

**Proposed research question:** Can balancing score groups and abstaining when evidence is incomplete or unstable improve the reliability of churn-risk screening under missing-domain data?

This is a testable framework contribution. It is not a claim that KMeans, rank scoring, missing-data bounds, or selective prediction are new algorithms. Establish novelty through a focused literature review and supervisor agreement; establish usefulness through experiments. The literature already includes selective prediction/reject options. The implementation here is a transparent rule-based extension, not an implementation of SelectiveNet and not conformal prediction.

Select **Experimental: group balance and evidence checks** in Churn Prediction. It is the dashboard default; the API defaults to the original baseline unless `method="domain_balanced"` is supplied. Both upload and server-path inputs are supported.

### Step 1: Give each score group one vote

Feature risk is `r_ij = 100 × (1 - p_ij)`.

| Group | Constituent scores |
| --- | --- |
| Financial | ARPU, CLV, Growth |
| Data | Data usage |
| Voice | Voice usage |
| Transactions | Transaction frequency |
| Temporal | Temporal stability |
| Consistency | Consistency index |

Within each group, average available informative feature risks. Then average the available group risks. ARPU/CLV/Growth jointly get one group vote. At least two informative groups are required for a point risk index. These six groups are not statistically independent; for example, the consistency and temporal scores reuse behavior from other groups. Group balancing reduces the explicit triple vote of the financial group but does not remove all correlation.

### Step 2: Bound the effect of unknown evidence

For a group g with `m_g` expected scores, use each missing feature risk's possible range [0,100]:

`L_ig = sum(known feature risks) / m_g`

`U_ig = [sum(known feature risks) + 100 × missing feature count] / m_g`

Average all six group lower bounds to obtain `risk_lower_bound` and all six upper bounds for `risk_upper_bound`. This includes partial missingness within the three-score financial group. Entirely absent groups contribute [0,100]. Constant scores are treated as uninformative for this rank-based method, not as automatically safe or risky.

These are conservative bounds for a hypothetical completed six-group index with current observed percentile values held fixed. They are not confidence intervals, calibrated uncertainties, or bounds on actual churn probability. Imputing a full dataset and reranking it would change the reference percentiles and is outside this bound calculation.

### Step 3: Check sensitivity to group removal

For customers with at least three informative groups, remove each present group once and recompute the mean of the remaining groups. The range is exported as `leave_one_domain_out_min/max`. It measures whether the result depends strongly on one group; it is not a statistical interval.

A band is reported as High/Medium/Low only if:

1. A point index is available.
2. Both missing-evidence bounds lie in the same band.
3. Every group-removal index stays in the point estimate's band.

Otherwise the final band is **Needs review**, or **Insufficient evidence** when fewer than two informative groups exist. `point_risk_band` remains visible as a provisional estimate. Conservative abstention can send many customers to review; that tradeoff is an experimental question, not an implementation error. No customer is silently discarded.

Exports include the original baseline, group risks, coverage, bounds, group-removal range, decision stability and reasons. `outputs/churn_risk_diagnostics.json` stores method version, thresholds, group definition, coverage and three ablation summaries: original baseline, group-balanced point bands, and group-balanced bands with review. These compare assignment counts, not accuracy. The latest CSV and diagnostics are overwritten by the next assessment; archive them per experiment.

## Thesis evaluation plan

With only current scores, evaluate reproducibility, clustering separation, refit stability, sensitivity to weights, customer overlap across source files, and robustness to controlled removal of groups. These can support an unsupervised segmentation thesis. They cannot establish future churn predictive accuracy.

For a predictive thesis, obtain dated feature snapshots and genuinely later outcomes. Compare at least:

1. Original equal-score heuristic.
2. Group-balanced point score without abstention.
3. Group balance with missing-evidence checks.
4. The implemented method with both evidence and group-removal checks.
5. A simple supervised baseline, such as logistic regression, once labels exist.

Split training, validation and test chronologically. Build every feature using only records available at its cutoff date. Fit preprocessing and tune weights/thresholds on training/validation only. Lock them before evaluating the later test window. Prevent overlapping outcome windows from leaking across partitions. Exclude or explicitly censor customers whose outcome window is not complete.

Measure precision/recall, average precision (PR-AUC convention must be stated), ROC-AUC, recall or lift among the top contactable customers, and calibration for methods that actually output probabilities. For methods with review, report accepted coverage and errors among accepted cases together, and compare at matched coverage/contact budgets. Report how many real churners were routed to review. A higher precision achieved by reviewing nearly everyone is not automatically an improvement. Add controlled group-missingness experiments and report customer/time dependence when constructing uncertainty estimates.

Repeat across later periods. State the churn definition, horizon, dataset dates, exclusions, available groups, k=3 constraint and intervention history. Do not claim novelty or improvement from synthetic regression tests.

## Adaptive learning: what to decide and supply

Current model snapshots and manual weight edits are manual retraining infrastructure, not adaptive learning. This update adds monitoring and reproducible outputs; it does not automatically change weights or promote models.

| Information needed | Why it is needed |
| --- | --- |
| Operational churn rule | Explicit cancellation, inactivity, or another event defines the target. An order status value alone does not define churn. |
| Prediction horizon and observation window | For example, a defined future 30/60/90-day horizon and a past feature window; choose these from the business need. |
| Historical coverage and update cadence | Dates/months available, daily/weekly/monthly arrival, row counts, and full snapshot versus incremental delivery. |
| Outcome availability and label delay | How long until churn/non-churn is known? Incomplete windows cannot be treated as non-churn. |
| Stable ID mapping | Anonymized examples from order/data/voice and a confirmed country-code/leading-zero rule. |
| Snapshot metadata | `MSISDN`, `snapshot_date`, score/feature columns, coverage flags, feature version and source cutoff dates. |
| Outcome table | `MSISDN`, event/last-activity dates, target definition, label availability date, and complete-follow-up indicator. |
| Operational objective | Cost of missed churners versus unnecessary contact; maximum customers contacted per period. |
| Interventions | Retention offer/contact date, treatment assignment and outcome; interventions change observed churn and can bias evaluation. |
| Deployment constraints | Batch or online updates, acceptable runtime, drift alert frequency, model promotion/rollback owner. |

The present scoring code anchors some windows to each source's own maximum date and normalizes relative to available data. Before a time-based predictive experiment, add an explicit shared observation cutoff and version the feature calculation/reference distribution. Otherwise changes in score scale, coverage or source freshness can look like changes in customer behavior.

Recommended implementation sequence once these inputs exist:

1. Save immutable dated snapshots and predictions with model/version identifiers.
2. Monitor input distributions, missingness, coverage and score/segment shifts separately from predictive performance.
3. Join predictions to outcomes only after the outcome window matures; track class balance and error/calibration over time.
4. Retrain a candidate on an appropriate recent labeled window. Evaluate against the current model on a later untouched window with the same contact budget.
5. Promote only when explicit performance and stability criteria pass; keep rollback artifacts. Test seasonal changes so expected cycles do not trigger unnecessary replacement.
6. Consider online updates and drift detectors if delivery cadence and mature-label volume justify them. A detector on input changes only detects distribution change; detecting changes in predictive errors requires genuine outcomes. Never train a model using its own cluster names or risk flags as if they were churn labels.

ADWIN is one possible change detector for a monitored numeric stream. Its statistical alarms still require a chosen stream, time ordering, alert policy, and an action after an alarm. Unsupervised drift alone is not proof that a model is performing worse.

## Sources and scope

- Scikit-learn, clustering performance evaluation: https://scikit-learn.org/stable/modules/clustering.html#clustering-performance-evaluation
- Geifman & El-Yaniv (2019), SelectiveNet: https://proceedings.mlr.press/v97/geifman19a.html — establishes that reject-option prediction is an existing research direction; does not validate this project's rule.
- River, ADWIN documentation: https://riverml.xyz/dev/api/drift/ADWIN/ — describes a potential future drift detector; ADWIN is not installed or activated by this update.

Validation performed: 13 synthetic regression/integration tests cover the supplied pipe reader, current routes, k=3, small-sample metric behavior, bounded silhouette sampling, repeatable subsample refits, evidence bounds, group balancing, abstention and strict JSON. JavaScript syntax is checked. No real customer dataset or churn outcomes were provided, so no real-world predictive performance has been measured.
