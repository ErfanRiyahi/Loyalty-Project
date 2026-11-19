"""Compatibility API for older integrations; no prediction algorithm lives here."""
import joblib
from .churn_prediction import (MODEL_VERSION as VERSION, DOMAINS, FEATURES,
    HistGradientBoostingClassifier, new_model, build_labels as target,
    _add_activity_history as enrich, load_or_train_model, predict_customers)


def predict(snapshots, panel, latest, run_dir, model_bundle=None):
    frames = [enrich(frame, panel, frame.snapshot_month.iloc[0]) for frame in snapshots if not frame.empty]
    bundle, report = load_or_train_model(frames, panel, latest, model_bundle)
    predictions = predict_customers(frames[-1], bundle)
    if bundle is not None:
        joblib.dump(bundle, run_dir / "retention_model.pkl")
    return predictions, report
