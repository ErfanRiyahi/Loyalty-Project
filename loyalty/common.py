from flask import request, jsonify
from .standards.arpu_clv_growth import arpu_clv_growth
from .standards.data_usage import data_usage
from .standards.voice_usage import voice_usage
from .standards.TranFreq import tranFreq
from .standards.consistency_index import consistency_index
from .standards.temporal_stability import temporal_stability
import pandas as pd
import numpy as np
import traceback
import csv
import io
import os
import json
import joblib
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = Path(os.environ.get("LOYALTY_OUTPUT_ROOT", str(PROJECT_ROOT / "outputs")))
OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)



# ---------------------------------------------------------------------------
# DATA ROOT — the three raw source files, reused across standards/domains
# ---------------------------------------------------------------------------
DATA_ROOT = os.environ.get("LOYALTY_DATA_ROOT", r"D:\Loyality Project")

SOURCE_FILES = {
    "order":     "customer order.csv",
    "data_cdr":  os.path.join("DataCDR", "DataCDR.csv"),
    "voice_cdr": os.path.join("voicesmsCDR", "voicesmsCDR.txt"),
}

STANDARD_SOURCE_KEY = {
    "ARPU_CLV_GROWTH":        "order",
    "Transaction_Frequency":  "order",
    "DATA_USAGE":             "data_cdr",
    "VOICE_USAGE":            "voice_cdr",
}
CI_DOMAIN_SOURCE_KEY = {"data": "data_cdr", "voice": "voice_cdr", "spend": "order", "txn": "order"}
TS_DOMAIN_SOURCE_KEY = {"order": "order", "data": "data_cdr", "voice": "voice_cdr"}

# where each standard's/domain's score is written, so /cluster can read them back
SCORE_FILES = {
    "ARPU_CLV_GROWTH":       "ARPU_CLV_GROWTH_SCORE.csv",
    "DATA_USAGE":            "DATA_USAGE_SCORE.csv",
    "VOICE_USAGE":           "VOICE_USAGE_SCORE.csv",
    "Transaction_Frequency": "Transaction_Frequency_SCORE.csv",
    "CONSISTENCY_INDEX":     "CONSISTENCY_INDEX_SCORE.csv",
    "TEMPORAL_STABILITY":    "TEMPORAL_STABILITY_SCORE.csv",
}


def source_path(key):
    return os.path.join(DATA_ROOT, SOURCE_FILES[key])


def source_read_options(path, required_columns=None):
    """Detect a supported delimiter from a bounded header sample; keep the fast C reader."""
    with open(path, 'rb') as stream:
        sample_bytes = stream.read(65536)
    encoding = 'utf-16' if sample_bytes.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig'
    sample = sample_bytes.decode(encoding, errors='replace')
    expected = set(required_columns or [])
    candidates = []
    for delimiter in [',', '\t', '|', ';']:
        try:
            rows = csv.reader(io.StringIO(sample), delimiter=delimiter)
            columns = next((row for row in rows if row and any(cell.strip() for cell in row)), [])
            candidates.append((len(expected.intersection(columns)), len(columns), delimiter, columns))
        except csv.Error:
            continue
    if not candidates:
        raise ValueError(f'Cannot read the header of {path}.')
    _, _, delimiter, columns = max(candidates, key=lambda item: (item[0], item[1]))
    if not columns:
        raise ValueError(f'The source file is empty: {path}')
    # Let pandas read the original header. Never trim, rename, or inject names.
    return {'sep': delimiter, 'encoding': encoding, 'engine': 'c'}


def read_source(path, usecols=None):
    """Memory-efficient reader with header-based comma/tab/pipe/semicolon detection."""
    columns = list(usecols) if usecols is not None else None
    dtype_map = {column: 'string' for column in ['MSISDN', 'SERVED_MSISDN', 'Subscriber_MSISDN'] if columns and column in columns}
    kwargs = {'usecols': columns, 'low_memory': True, **source_read_options(path, columns)}
    if dtype_map:
        kwargs['dtype'] = dtype_map
    return pd.read_csv(path, **kwargs)


def build_error_response(exc, status=500):
    """Turn any exception into a JSON body the frontend can pinpoint exactly."""
    tb = traceback.extract_tb(exc.__traceback__)
    last_frame = tb[-1] if tb else None  # the innermost frame = where it actually broke
    return jsonify({
        "error": str(exc),
        "error_type": type(exc).__name__,
        "file": last_frame.filename.split("/")[-1] if last_frame else None,
        "line": last_frame.lineno if last_frame else None,
        "function": last_frame.name if last_frame else None,
        "traceback": traceback.format_exc(),
    }), status

def compute_score_stats(result_df, score_col=None, bins=10):
    """Summary stats + histogram for the score column of a result CSV.
    Auto-detects the score column (first one containing 'SCORE', 'INDEX', or
    'CI') if score_col isn't given. Returns None if no numeric column found."""
    if score_col is None:
        candidates = [c for c in result_df.columns
                      if any(k in c.upper() for k in ("SCORE", "INDEX", "CI"))]
        numeric_candidates = [c for c in candidates if pd.api.types.is_numeric_dtype(result_df[c])]
        if numeric_candidates:
            score_col = numeric_candidates[0]
        else:
            numeric_cols = result_df.select_dtypes(include="number").columns.tolist()
            score_col = numeric_cols[0] if numeric_cols else None

    if score_col is None:
        return None

    # Histograms require finite values; missing/infinite cells are not observations.
    series = result_df[score_col].replace([np.inf, -np.inf], np.nan).dropna()
    if series.empty:
        return None

    hist_counts, hist_edges = np.histogram(series, bins=bins)

    return {
        "column": score_col,
        "count": int(series.count()),
        "mean": round(float(series.mean()), 4),
        "median": round(float(series.median()), 4),
        "std": round(float(series.std()), 4) if series.count() > 1 else 0,
        "min": round(float(series.min()), 4),
        "max": round(float(series.max()), 4),
        "histogram": {
            "counts": [int(c) for c in hist_counts],
            "bin_edges": [round(float(e), 4) for e in hist_edges],
        },
    }


SCORE_FILES = {key: str(OUTPUT_ROOT / name) for key, name in SCORE_FILES.items()}

# Source schema defaults, shared by the API and rendered dashboard.
STANDARD_COLUMNS = {
    "ARPU_CLV_GROWTH": ["MSISDN", "PaidDateUtc", "OrderTotal"],
    "DATA_USAGE": ["SERVED_MSISDN", "START_TIMESTAMP", "ACTUAL_USAGE"],
    "VOICE_USAGE": ["Subscriber_MSISDN", "Call_Date", "Call_Duration"],
    "Transaction_Frequency": ["MSISDN", "PaidDateUtc", "OrderStatusId"],
}
CI_DOMAIN_STANDARD = {"data": "DATA_USAGE", "voice": "VOICE_USAGE", "spend": "ARPU_CLV_GROWTH", "txn": "Transaction_Frequency"}
TS_DOMAIN_STANDARD = {"order": "Transaction_Frequency", "data": "DATA_USAGE", "voice": "VOICE_USAGE"}

def dashboard_defaults():
    standards = {key: {"path": source_path(STANDARD_SOURCE_KEY[key]), "columns": columns} for key, columns in STANDARD_COLUMNS.items()}
    return {"standards": standards,
            "ci": {domain: standards[key] for domain, key in CI_DOMAIN_STANDARD.items()},
            "ts": {domain: standards[key] for domain, key in TS_DOMAIN_STANDARD.items()}}


def json_safe(value):
    """Replace non-finite numeric values with JSON null, including nested previews."""
    if value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    return value
