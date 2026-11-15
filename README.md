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

The seven tabs, appearance, algorithms, downloads and actual elapsed-time reporting are preserved. Clustering uses K-Means without RobustScaler. Shared form and request helpers reduce repeated code. Comments explain the main processing steps in English.
