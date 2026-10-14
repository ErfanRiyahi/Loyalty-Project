# Customer Loyalty and Monthly Activity Decline

This final project runs a local Flask dashboard for monthly batch learning. When the company delivers data, use Monthly Learning to ingest history, update k=3 clusters, calculate comparisons within each cluster, and estimate qualifying activity decline in the following month.

## Install and run

Requires Python 3.10 or later. Extract this folder and open a terminal inside it:

```sh
python -m venv .venv
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

macOS/Linux:

```sh
source .venv/bin/activate
```

Then:

```sh
python -m pip install -r requirements.txt
python app.py
```

Open **http://127.0.0.1:5000**. Do not open HTML templates directly. The server runs on localhost. Input paths must be accessible to Python, on your computer.

## Monthly workflow

1. For the first run, provide historical order, data and voice files. At least seven common complete months are needed for clustering snapshots; enough labeled months and customers are also needed for prediction training. More than one year is a better starting point.
2. Select the last fully delivered month in **Monthly Learning**. All three sources must be complete through that month. Use Gregorian months based on the UTC dates read from the source files.
3. Confirm completeness and click **Run Monthly Update**. The service retains history, handles exact overlap, rebuilds chronological snapshots and targets, updates clusters and evaluates a candidate decline model.
4. Review clustering validation, the test confusion matrix, candidate promotion, and customer results. Download the full CSV.
5. Open **Churn Prediction** to view the latest trained predictions. The other two methods remain available as heuristic baselines.
6. When the next delivery arrives, repeat with the next completed month. The same month can be replayed after corrections. Updates cannot move backwards; use a separate output folder for independent historical experiments.

The service processes a batch when you click the button. It is not a scheduled/background file watcher. Large initial imports may take time; leave the page and Python server running. Multiple updates are blocked within this single server process.

## Expected input schemas

| Source | Default path | Required columns |
| --- | --- | --- |
| Orders | `D:\Loyality Project\customer order.csv` | `MSISDN`, `PaidDateUtc`, `OrderTotal`, `OrderStatusId`; optional `Id` strongly recommended |
| Data | `D:\Loyality Project\DataCDR\DataCDR.csv` | `SERVED_MSISDN`, `START_TIMESTAMP`, `ACTUAL_USAGE` |
| Voice | `D:\Loyality Project\voicesmsCDR\voicesmsCDR.txt` | `Subscriber_MSISDN`, `Call_Date`, `Call_Duration`, pipe delimiter |

Successful orders are `OrderStatusId == 30`. The monthly order activity measure is the number of successful orders; spend is their summed `OrderTotal`. Data and voice activity are summed usage and call duration. Their original units are retained. Invalid dates, missing IDs, non-finite or negative values are excluded and counted in the ingestion report; inspect those counts before interpreting prediction results.

The default data root can be changed before starting Python:

```powershell
$env:LOYALTY_DATA_ROOT = 'D:/Loyality Project'
python app.py
```

`LOYALTY_OUTPUT_ROOT` changes the output folder. The standard reader preserves your supplied `low_memory=True`, requested identifier string dtypes and `.txt` pipe separator. The new monthly importer uses the same delimiter/identifier rules with 100,000-row chunks.

**ID handling:** the monthly importer preserves the current string-ID rule: remove the first two characters. This must resolve the same subscriber consistently across all three sources. Empty results are rejected. The application cannot detect that two different IDs belong to the same person. Update this rule if source formats change.

## History and overlapping files

The local database is `outputs/monthly/history.sqlite`.

- Orders with `Id` use upserts: a repeated Id is reused; a changed row with the same Id replaces that event's stored values.
- Without an event Id, the importer fingerprints the selected ID/date/value/status fields. For each fingerprint it keeps the maximum count observed across deliveries, preserving repeated identical rows within a delivery while preventing exact replay/overlap inflation.
- Identical unkeyed events can be legitimate new events or repeated deliveries. The maximum-count policy is an explicit assumption, not a guarantee of event identity. Changed or deleted unkeyed historical records cannot be corrected reliably from the supplied schema.
- Deleted events in full extracts are not automatically removed. If an extract retracts/corrects old unkeyed data, stop Python, back up and move the entire `outputs/monthly` folder, then rebuild from authoritative full historical files. Do not delete just the database while retaining trained models and quarterly references.
- File ingestion is transactional; a failure reading a source rolls back that ingestion transaction. A later model-stage failure does not undo a successful history import; rerunning it reuses the imported events.

The confirmation means missing customer-month events are genuine zero activity, not a missing company feed. The system cannot prove feed completeness. The first common observation month is inferred conservatively from each source's first usable event; the first five common months are warm-up.

## Cluster numbers and peer comparisons

The primary monthly model uses six scores: ARPU, CLV, Growth, data usage, voice usage and successful-order frequency. RobustScaler followed by KMeans (`k=3`, `n_init=10`, seed 42) fits the latest customer snapshot. This monthly feature implementation is separate from the original exploratory standard/consistency/temporal tabs; those original formulas remain available there. CI and TS from those tabs are not silently recomputed or used by the monthly model.

Six months remain the calculation history. Customers are compared using cluster membership, not grouped by six-month tenure. Monthly snapshots include zero-activity months. Weighted ARPU uses `[1,1,1,2,2,2]/9`; weighted CLV uses `[.05,.10,.15,.20,.25,.25]`, oldest to newest. Growth compares median spend in the recent three months with median spend in the preceding three months; a zero preceding median uses growth zero as an explicit cold-start convention.

At first fit, IDs 0/1/2 follow increasing average global score. Later fits match new clusters to previous IDs using maximum customer overlap and a one-to-one assignment. IDs therefore track groups; they do not guarantee a fixed loyalty order forever. The validation report displays cluster sizes, separation and subsample stability. If there are no overlapping customers, the initial engagement ordering is used again. New groups or population changes can still alter a cluster's meaning; inspect profiles.

Global scores determine clustering. `PEER_*` scores compare customers with the reference distribution of their own cluster. Peer scores are not fed back into the same fit, avoiding circular normalization.

References remain fixed within each Gregorian quarter. Global references use trailing snapshots before that quarter when available; the initial bootstrap falls back to data available at the selected month if earlier references are unavailable. ARPU/data/voice/frequency/Growth use P5/P95 bounds and clipping to [1,10]. CLV uses `clip(5 + 2 log10(weighted CLV / BaseCLV), 1, 10)`. BaseCLV is the median positive customer weighted CLV in the reference sample. Flat distributions yield a neutral score of 5. Initial peer references use prior reference-month observations from customers assigned to that cluster, with global fallback for fewer than three reference members.

References are stored per quarter in `outputs/monthly/references`. A reference change can change score scales; retaining its version makes that change auditable, but does not by itself prove that equal numeric scores across quarters mean identical behavior. The supervised decline model uses raw activity features, independent of these quarterly score references.

## Next-month decline prediction and adaptive updates

This target is an operational proxy for reduced activity, not verified cancellation:

- At cutoff month t, calculate each customer's mean activity during t−2, t−1 and t.
- A previously active domain has a positive baseline mean.
- The label is 1 when activity during t+1 is at most 50% of that baseline in at least two previously active domains.
- Customers need at least three months since first observed activity and two active baseline domains. Others receive insufficient prior activity, not a fabricated zero probability.
- Complete current-month inactivity is recorded separately in the export. It is an observed warning, not itself a prediction.

Historical snapshots use only events through their cutoff. Targets use the following completed month. The latest snapshot has no target and is used for prediction. Every update rebuilds historical snapshots/targets from retained events, allowing keyed corrections to affect training.

The supervised model is **StandardScaler + L2 logistic regression** with a fixed 0.5 decision threshold. Inputs are current/three-month/six-month log activity, an activity ratio, and inactive-month counts for the three domains. It requires at least four labeled months, 30 training rows and at least five training examples of each class. The last two labeled months are validation and test; earlier months train the model. The threshold is not tuned on test data. Probabilities have not been calibrated or validated on actual company data here.

Every monthly run fits a candidate. The currently deployed model and candidate are evaluated on the same latest chronological test month. A candidate replaces the deployed model if its average precision and Brier score stay within 0.02 of the champion; the first adequately trained candidate is deployed. This is a configurable engineering tolerance in the code, not a statistical significance test. A one-class test month may prevent later promotion. If historical inputs change, compare the archived reports carefully because the targets/reference sample may also change.

The deployed model is the evaluated pipeline; it is not silently refitted on the test set. On the next update, older validation/test periods can enter training as new held-out months become available. This is monthly batch adaptation with versioning and candidate checks, not per-event online learning. Repeated testing/promotion on the same calendar month is not independent evidence.

The confusion matrix compares predictions with the defined later activity-decline labels. It is not a confusion matrix for k=3 clustering. Precision, recall, average precision, ROC-AUC where defined, and Brier score are reported. The UI identifies candidate metrics and whether the prior model was retained. Future work should add feed availability manifests, better event keys, calibration, retention-intervention records and a business contact budget.

## Outputs and reproducibility

| File | Purpose |
| --- | --- |
| `outputs/monthly/history.sqlite` | Retained source event history |
| `outputs/monthly/state.json` | Last completed observation month/run |
| `outputs/monthly/latest_customers.csv` | Cluster IDs, global and peer scores, forecasts and observed inactivity |
| `outputs/monthly/latest_report.json` | Ingestion, references, clustering and predictive evaluation |
| `outputs/monthly/churn_model.pkl` | Deployed decline model |
| `outputs/monthly/latest_assignments.csv` | Alignment reference for the next cluster fit |
| `outputs/monthly/references/<quarter>.json` | Frozen global and peer scoring references |
| `outputs/monthly/runs/<run_id>/` | Cluster model, churn candidate when fitted, full customer CSV and report |

Keep the entire monthly output folder between deliveries. Model files are local trusted artifacts; do not load model pickle files from third parties. For an independent thesis experiment use a different `LOYALTY_OUTPUT_ROOT`. Archive the source delivery files and installed package versions as well as run outputs for exact reproduction.

The original tabs remain available for exploratory scoring, consistency, temporal stability, dataset overview, score-file clustering and heuristic risk ablations. Their outputs are separate from the primary monthly pipeline. The previous detailed thesis notes describe those baselines; this README governs the final monthly workflow.

## Verification

Run:

```sh
python -m unittest discover -s tests -v
```

Synthetic tests cover existing routes, strict JSON, pipe reading, risk baselines, clustering validation, monthly target construction, chronological splitting, repeat-feed deduplication, cluster alignment, fixed quarterly references and invalid update guards. A full synthetic history was also replayed through three monthly updates. Those checks verify behavior; no actual company prediction accuracy is claimed. The failed latest voice attachment was not used; the existing prior voice module is included.
