"""Compatibility imports only; the complete prediction logic is in churn_prediction.py."""
from ..common import OUTPUT_ROOT, write_json
from .churn_prediction import (SOURCES, ACTIVITY, BASE_FEATURES as FEATURES,
    build_features as snapshot, metrics, _normalize_ids as normalize_ids)
from . import churn_prediction

# Historical callers and archived download routes keep their original root.
ROOT = OUTPUT_ROOT / "monthly"


def ingest(paths, columns=None, root=None):
    return churn_prediction.load_data(paths, columns, ROOT if root is None else root)


def aggregates(as_of, root=None):
    return churn_prediction.build_monthly_activity(as_of, ROOT if root is None else root)
