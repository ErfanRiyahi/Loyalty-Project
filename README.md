# Customer Loyalty Dashboard — Version 3

The dashboard interface is Persian, with English tab subtitles. Code identifiers, comments and developer documentation are English. Persian strings in templates and JavaScript are UI display text only.

## Run

```bash
pip install -r requirements.txt
python app.py
```

Open the address printed by Flask. Configure data file paths and exact column names in the interface.

## Code guide

- `app.py` starts the application.
- `loyalty/__init__.py` creates the Flask application.
- `loyalty/routes/` handles API requests.
- `loyalty/services/` contains processing and model logic.
- `loyalty/standards/` calculates scores.
- `loyalty/templates/` contains UI markup.
- `loyalty/static/js/` handles forms, charts, downloads and progress.
- `tests/` contains automated checks.

## Input defaults and churn-source columns

The **Input Defaults** tab edits initial file paths, column names and analysis options for all pages. Save and apply updates the forms immediately and stores these defaults in this browser for future visits. Reset restores the original application defaults. Saved settings are specific to the browser and site address; they do not change server configuration or other users' defaults. The observation month and completeness confirmation are always chosen separately.

**Churn Prediction** accepts exact column names for customer ID, date and value in each source, plus order status (successful value `30`) and an optional order event ID. Clear the event ID field if none is available. The API accepts a `columns` object keyed by `order`, `data_cdr` and `voice_cdr`, with ordered arrays of five, three and three names respectively; an empty final order name disables event-ID deduplication. Omitting `columns` retains the original schema. Column names are used exactly as entered.

The eight tabs preserve the existing appearance, algorithms, downloads and actual elapsed-time reporting. Clustering uses K-Means without RobustScaler. Shared form and request helpers reduce repeated code. Comments explain the main processing steps in English.


## Clustering inputs

Clustering offers the latest six score outputs, displaying server paths, availability and modification times, or a custom CSV/path for each score family. Uploads take precedence over paths. All six inputs must contain unique, nonempty `MSISDN` values and their expected score columns. Custom uploads are temporary and never overwrite the latest score outputs. The validation report records the selected input filenames/paths.

## Customer retention list

The prediction page has one workflow: load a prioritized, searchable and paginated customer list from its independent churn prediction run, filter by status/risk, and download the entire filtered selection. Already churned customers (three consecutive complete inactive calendar months) are separate from prospective risks and customers with insufficient evidence.

A fixed histogram gradient-boosting model forecasts reaching three consecutive inactive months within the next three months. Activity means at least one successful order or positive data/voice usage. Build features only through the snapshot month, and train only on outcomes whose full three-month follow-up is observed. Customers already churned at the snapshot are excluded from prospective training/prediction. Source completeness confirmation is still required for all three feeds; missing feeds cannot be assumed to mean inactivity.

The model needs at least 30 mature snapshots with at least five positive and five negative outcomes. Otherwise it emits no probability and shows a review list with observed behavioral evidence. An independent chronological evaluation is reported only when enough earlier mature data exists. Evaluation uses a fixed specification, with no final-test-based model selection. When no churn model exists, an initial model is fitted on mature outcomes and saved. Later predictions reuse that exact saved model and training-reference medians; adaptive clustering cannot replace or retrain it. Its probabilities are estimates, not a measured accuracy claim.

Displayed evidence includes the last active month, consecutive inactive months and domain-specific declines. Model factors are group-replacement sensitivities relative to training medians, not causal reasons. Default prospective risk threshold is 0.5 (high at 0.75); these operational defaults require validation on real customer history.

After installing this update, run **Update predictions** in the Churn Prediction tab. Its raw-source paths, exact column names, observation month and completeness confirmation are now in that same tab. Old monthly outputs remain archived; they do not populate or control the new independent churn workflow. Legacy risk-scoring APIs remain available for compatibility but are no longer choices in the customer-facing page.


## Adaptive clustering learning

Adaptive Learning is exclusively a clustering lifecycle. It accepts six scored files for the selected completed month (blank paths use the latest score outputs), with confirmation that their score definitions and period match. It never ingests raw churn history, calls the churn predictor, or changes the saved churn model.

A candidate KMeans model keeps k=3, feature weights and the current model's feature floors fixed. Twenty percent of the current cohort (at least ten rows) is reserved for evaluation; the exact candidate is fit only on the other rows and is not refitted on the evaluation rows before promotion. Candidate/active models are measured on the same evaluation rows in the same feature space. Bootstrap floors and engagement names use training rows only. At least 50 multi-domain customers are required. If an existing manually trained clustering model is registered, it becomes the comparison baseline; otherwise the first accepted candidate is explicitly a bootstrap, not a claimed improvement.

Current acceptance policy requires positive silhouette, three clusters each with at least 2% share in both the evaluation sample and the full multi-domain cohort, and all five training-only subsample checks with ARI >=0.8. Replacing an incumbent additionally requires silhouette improvement >=0.01 and Davies–Bouldin no worse than 1.05 times the incumbent. These configurable-in-code operational gates are internal robustness criteria, not proof of future business performance. The incumbent may have seen customers in earlier periods; the report does not claim a fully independent future-period test.

Rejected candidates are archived without overwriting active predictions or pointers. Accepted candidates record input hashes, comparison metrics, policy, period and versioned model/output artifacts. The Clustering page then uses the active model's `predict` operation instead of fitting it again; optional stability refits are diagnostic only. Rollback swaps the active/previous model pointers and restores the previous version's saved segmentation/report. Rerun clustering for predictions on newer scores after a rollback. The UI displays the active version and rollback availability.

Evaluate once new period scores are available; the application performs the comparison and promotion automatically within that run. No unattended calendar scheduler is installed. Adaptive artifacts live under `outputs/adaptive`, independent churn history/models under `outputs/churn`, and immutable clustering model versions under `outputs/models`.

API routes: `/adaptive/update`, `/adaptive/status`, `/adaptive/rollback`, `/adaptive/download`, `/adaptive/report`; `/churn/update`, `/churn/customers` and their download routes are independent. Legacy `/monthly/update` and `/monthly/status` now alias adaptive clustering and require the new scored-input payload, not raw churn feeds.


## Processing status and technical details

The header is compact and has no revision badge. While a job runs, its status shows the current useful stage and elapsed time; the generic request-wrapper stage stays internal. Completion shows a concise message and total elapsed time. Technical details are collapsed by default and contain stage durations, the operation ID, Copy ID and a link to `/jobs/<id>`. Expanded details and copy feedback survive polling updates. Copy failures leave the ID selectable for manual copying. Reconnect/reload recovery still uses the same server operation rather than starting a duplicate job.

Dataset Overview no longer displays dataframe memory usage in the main UI; the backend profile/report still retains it. Job tracking remains in-memory and is unavailable after a server restart; finished records can be pruned after roughly one hour when a new job starts.


## Consistency coverage diagnostics

Consistency still uses the intersection of customers scored in all four domains; it does not silently replace the existing formula or inner joins. A successful request can legitimately contain zero final customers. The UI now explains that outcome and shows each domain's input rows/customers, scored customers, effective months, pairwise intersections and common-month coverage. It warns for an empty cleaned domain, no common customers, non-overlapping effective months and fewer than six observed months. These warnings describe coverage; they do not certify complete six-month observation or aligned identifiers. The existing identifier-cleaning policy is stated explicitly rather than changed without confirmed source formats.

The response includes `score.diagnostics` and an immutable `score.report_download_url` for a JSON coverage report. No customer identifiers or raw sample records are included in that report. Non-overlapping periods remain visible as a comparability warning even if some customer IDs intersect. Sources should describe the same observation period; random independent row samples are insufficient to establish cross-source customer overlap in the original full datasets.


## Independent domain defaults

Consistency Index and Temporal Stability now give each source path and each identifier/date/value field its own stable ID. Their settings are grouped by domain, and independently edited values are applied both to the actual forms and to request payloads. Previously, unnamed domain-column fields shared an empty storage key and saving/reloading applied the last column value to all of them.

The v2 browser settings migrate unambiguous v1 preferences, including the legacy source-path keys and unrelated standard/churn settings. Collapsed values under the old empty key cannot reconstruct the individual custom column names: those fields return to their correct application defaults, with a visible explanation asking users to reenter any custom names once. Reset clears both storage versions so corrupt values cannot reappear.

Browser regression (development only): with Playwright/Chromium installed and the app running, execute `python tests/check_defaults_browser.py http://127.0.0.1:5000/`. It verifies independent values, saving/reload, CI/TS request payloads, migration, preserved preferences and reset.
