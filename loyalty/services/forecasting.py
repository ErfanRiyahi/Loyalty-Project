"""Compatibility entry point; read churn_prediction.py for all seven stages."""
from . import churn_prediction
ROOT = churn_prediction.ROOT


def update(payload):
    return churn_prediction.run_prediction(payload, root=ROOT)
