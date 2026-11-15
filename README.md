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
