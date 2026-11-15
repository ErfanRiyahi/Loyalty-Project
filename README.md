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

## Input defaults and monthly columns

The **Input Defaults** tab edits initial file paths, column names and analysis options for all pages. Save and apply updates the forms immediately and stores these defaults in this browser for future visits. Reset restores the original application defaults. Saved settings are specific to the browser and site address; they do not change server configuration or other users' defaults. The observation month and completeness confirmation are always chosen separately.

**Monthly Learning** accepts exact column names for customer ID, date and value in each source, plus order status (successful value `30`) and an optional order event ID. Clear the event ID field if none is available. The API accepts a `columns` object keyed by `order`, `data_cdr` and `voice_cdr`, with ordered arrays of five, three and three names respectively; an empty final order name disables event-ID deduplication. Omitting `columns` retains the original schema. Column names are used exactly as entered.

The eight tabs preserve the existing appearance, algorithms, downloads and actual elapsed-time reporting. Clustering uses K-Means without RobustScaler. Shared form and request helpers reduce repeated code. Comments explain the main processing steps in English.


## Clustering inputs

Clustering offers the latest six score outputs, displaying server paths, availability and modification times, or a custom CSV/path for each score family. Uploads take precedence over paths. All six inputs must contain unique, nonempty `MSISDN` values and their expected score columns. Custom uploads are temporary and never overwrite the latest score outputs. The validation report records the selected input filenames/paths.

## Customer retention list

The prediction page has one workflow: load a prioritized, searchable and paginated customer list from the latest monthly run, filter by status/risk, and download the entire filtered selection. Already churned customers (three consecutive complete inactive calendar months) are separate from prospective risks and customers with insufficient evidence.

A fixed histogram gradient-boosting model forecasts reaching three consecutive inactive months within the next three months. Activity means at least one successful order or positive data/voice usage. Build features only through the snapshot month, and train only on outcomes whose full three-month follow-up is observed. Customers already churned at the snapshot are excluded from prospective training/prediction. Monthly completeness confirmation is still required for all three feeds; missing feeds cannot be assumed to mean inactivity.

The model needs at least 30 mature snapshots with at least five positive and five negative outcomes. Otherwise it emits no probability and shows a review list with observed behavioral evidence. An independent chronological evaluation is reported only when enough earlier mature data exists. Evaluation uses a fixed specification, with no final-test-based model selection. The deployment model is then fitted on all currently mature outcomes. Its probabilities are estimates, not a measured accuracy claim.

Displayed evidence includes the last active month, consecutive inactive months and domain-specific declines. Model factors are group-replacement sensitivities relative to training medians, not causal reasons. Default prospective risk threshold is 0.5 (high at 0.75); these operational defaults require validation on real customer history.

After installing this update, rerun Monthly Learning: legacy next-month activity-decline outputs/models are not used as three-month churn predictions. Legacy risk-scoring APIs remain available for compatibility but are no longer choices in the customer-facing page.
