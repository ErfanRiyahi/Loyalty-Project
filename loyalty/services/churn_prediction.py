"""Churn prediction in one place: read the seven numbered stages in order.

Public flow:
    load_data -> build_monthly_activity -> build_features -> build_labels
    -> load_or_train_model -> predict_customers -> run_prediction

The HTTP route only calls run_prediction. Each run reads complete CSV snapshots
and passes DataFrames directly; it never reads or writes a history database.
"""
from datetime import datetime, timezone
from pathlib import Path
import json
import shutil

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import (average_precision_score, roc_auc_score, brier_score_loss,
                             confusion_matrix, precision_score, recall_score)

from ..common import OUTPUT_ROOT, source_path, source_read_options, json_safe, write_json
from ..identifiers import normalize_identifiers, VERSION as IDENTIFIER_VERSION
from ..progress import stage, stage_call, units, stage_scope

ROOT = OUTPUT_ROOT / "churn" / IDENTIFIER_VERSION
MODEL_VERSION = "three-month-inactivity-v1"
SOURCES = {
    "order": ("MSISDN", "PaidDateUtc", "OrderTotal"),
    "data_cdr": ("SERVED_MSISDN", "START_TIMESTAMP", "ACTUAL_USAGE"),
    "voice_cdr": ("Subscriber_MSISDN", "Call_Date", "Call_Duration"),
}
DOMAINS = {"orders": "خرید", "data": "مصرف اینترنت", "voice": "مکالمه"}
ACTIVITY = list(DOMAINS)
BASE_FEATURES = [f"{domain}_{part}" for domain in ACTIVITY
                 for part in ["log_current", "log_mean3", "log_mean6", "ratio", "inactive_months"]]
FEATURES = BASE_FEATURES + ["consecutive_inactive_months", "history_months"]

# 1. CSV files -> three ordinary DataFrames. No database or saved history.
@stage("Read churn CSV files")
def load_data(paths, columns=None):
    """Return (orders, internet, calls), with the original selected column names."""
    tables = []
    for source, schema in _source_schemas(columns).items():
        with stage_scope(f"Read CSV source {source}"):
            required = schema[:4] if source == "order" else schema
            path = paths.get(source) or source_path(source)
            selected = set(schema) - {""}
            frame = stage_call("Read data file", pd.read_csv, path,
                **source_read_options(path, required), usecols=lambda name: name in selected,
                dtype={schema[0]: "string", **({schema[4]: "string"} if source == "order" and schema[4] else {})},
                low_memory=True)
            missing = [name for name in required if name not in frame.columns]
            if missing:
                raise ValueError(f"{source}: missing columns {missing}")
            tables.append(frame)
            units(len(frame), description=f"{source}: rows read")
    return tuple(tables)


# 2. Three DataFrames -> one customer-month activity table.
@stage("Build monthly activity from CSV")
def build_monthly_activity(orders, internet, calls, as_of, columns=None):
    """Clean the supplied tables and return (panel, first_seen, months).

    Every run uses only these complete CSV snapshots. Orders count successful
    events; data/voice sum usage. Missing months assume confirmed source coverage.
    """
    as_of = pd.Period(as_of, freq="M")
    summaries = {}
    for (source, schema), raw in zip(_source_schemas(columns).items(), [orders, internet, calls]):
        id_col, date_col, value_col = schema[:3]
        frame = raw.copy()
        if source == "order" and schema[4] and schema[4] in frame.columns:
            frame = frame.dropna(subset=[schema[4]]).drop_duplicates(schema[4], keep="last")
        customer = normalize_identifiers(frame[id_col])
        dates = pd.to_datetime(frame[date_col], errors="coerce", utc=True, format="mixed")
        values = pd.to_numeric(frame[value_col], errors="coerce")
        valid = customer.notna() & dates.notna() & values.notna() & np.isfinite(values) & values.ge(0)
        if source == "order":
            valid &= pd.to_numeric(frame[schema[3]], errors="coerce").eq(30)
        events = pd.DataFrame({"MSISDN": customer.loc[valid],
                               "month": dates.loc[valid].dt.strftime("%Y-%m"),
                               "value": values.loc[valid]})
        events = events.loc[events.month <= str(as_of)]
        if events.empty:
            raise ValueError(f"{source}: no usable events through the selected month.")
        summaries[source] = events.groupby(["MSISDN", "month"]).agg(
            volume=("value", "sum"), frequency=("value", "size"))
    all_events = pd.concat([table.reset_index()[["MSISDN", "month"]] for table in summaries.values()], ignore_index=True)
    first_seen = all_events.groupby("MSISDN").month.min()
    start = max(pd.Period(table.index.get_level_values("month").min(), freq="M") for table in summaries.values())
    if as_of.ordinal - start.ordinal < 6:
        raise ValueError("At least seven complete common-history months are needed. Provide the historical files for initial setup.")
    months = pd.period_range(start, as_of, freq="M")
    index = pd.MultiIndex.from_product([sorted(first_seen.index), months.astype(str)], names=["MSISDN", "month"])
    panel = pd.DataFrame(index=index)
    for source, domain in [("order", "orders"), ("data_cdr", "data"), ("voice_cdr", "voice")]:
        table = summaries[source]
        panel[domain] = table["frequency" if source == "order" else "volume"].reindex(index).fillna(0)
    return panel.reset_index(), first_seen, months

# 3. Build model inputs at a particular cutoff.
@stage("Build six-month features")
def build_features(panel, first_seen, month):
    """3. Summarize six months of behavior available at the observation cutoff.

    FEATURES selects the 17 actual model inputs; raw activity summaries
    support the behavioral explanations. No later-month records enter these features.
    """
    month = pd.Period(month, freq="M")
    ids = first_seen.loc[first_seen <= str(month)].index
    recent = pd.period_range(month - 5, month, freq="M").astype(str)
    frame = pd.DataFrame(index=ids)
    frame.index.name = "MSISDN"
    frame["snapshot_month"] = str(month)
    frame["history_months"] = [
        month.ordinal - pd.Period(first_seen.loc[item], freq="M").ordinal + 1
        for item in ids
    ]
    for domain in ACTIVITY:
        values = (
            panel.loc[panel.month.isin(recent)]
            .pivot(index="MSISDN", columns="month", values=domain)
            .reindex(index=ids, columns=recent)
            .fillna(0)
        )
        mean3 = values.iloc[:, -3:].mean(axis=1)
        frame[domain + "_current"] = values.iloc[:, -1]
        frame[domain + "_mean3"] = mean3
        frame[domain + "_mean6"] = values.mean(axis=1)
        frame[domain + "_previous3"] = values.iloc[:, :3].mean(axis=1)
        frame[domain + "_log_current"] = np.log1p(frame[domain + "_current"])
        frame[domain + "_log_mean3"] = np.log1p(mean3)
        frame[domain + "_log_mean6"] = np.log1p(frame[domain + "_mean6"])
        frame[domain + "_ratio"] = (
            (
                frame[domain + "_current"]
                / frame[domain + "_previous3"].replace(0, np.nan)
            )
            .clip(0, 10)
            .fillna(1)
        )
        frame[domain + "_inactive_months"] = (values == 0).sum(axis=1)
    return _add_activity_history(frame.reset_index(), panel, month)

# 4. Build historical outcomes for supervised learning.
def build_labels(frame, panel, month, observed_through):
    """4. Mark entry into three inactive months within the next three months.

    1 = churn reached, 0 = not reached, NaN = not eligible/not yet observed.
    Full follow-up is required; already-churned customers are excluded.
    """
    month = pd.Period(month, freq="M")
    labels = pd.Series(np.nan, index=frame.index, dtype=float)
    if month + 3 > pd.Period(observed_through, freq="M"):
        return labels
    periods = pd.period_range(month - 1, month + 3, freq="M").astype(str)
    block = panel.loc[panel.month.isin(periods)].copy()
    block["active"] = block[list(DOMAINS)].gt(0).any(axis=1)
    activity = block.pivot(index="MSISDN", columns="month", values="active").reindex(index=frame.MSISDN, columns=periods)
    complete = activity.notna().all(axis=1).to_numpy()
    inactive = ~activity.astype("boolean").fillna(True).astype(bool)
    outcome = np.zeros(len(frame), dtype=bool)
    for end in [2, 3, 4]:
        outcome |= inactive.iloc[:, end-2:end+1].all(axis=1).to_numpy()
    eligible = (frame.history_months >= 3) & (frame.consecutive_inactive_months < 3) & complete
    labels.loc[eligible] = outcome[eligible.to_numpy()].astype(float)
    return labels

# 5. Read the current model, or train an initial one from mature outcomes.
def load_or_train_model(snapshots, panel, latest, model_bundle=None, model_path=None):
    """Return (saved-model bundle or None, training/evaluation report).

    Existing models are reused unchanged. Initial training needs at least
    30 labeled customer-months, with at least five of each outcome.
    """
    report = {"target": "Reach three consecutive complete months without purchases, positive data usage or positive voice usage within the next three months",
              "version": MODEL_VERSION, "horizon_months": 3, "threshold": 0.5,
              "status": "insufficient_training_data", "algorithm": "HistGradientBoostingClassifier"}
    if model_bundle is None and model_path is not None and Path(model_path).is_file():
        model_bundle = joblib.load(model_path)
    if model_bundle is not None:
        if model_bundle.get("version") != MODEL_VERSION or model_bundle.get("features") != FEATURES:
            raise ValueError("Saved churn model is incompatible with this feature version.")
        report.update(model_bundle.get("evaluation", {}))
        report.update(model_source="existing", status="trained")
        return model_bundle, report

    labeled = []
    for features in snapshots:
        frame = features.copy()
        frame["target"] = build_labels(frame, panel, frame.snapshot_month.iloc[0], latest)
        labeled.append(frame.loc[frame.target.notna()])
    history = pd.concat(labeled, ignore_index=True)
    if not _enough_examples(history):
        report["reason"] = "Need at least 30 mature customer snapshots and five examples of each outcome. No probability is fabricated."
        return None, report

    # Evaluation models only see labels matured by their prediction cutoff.
    test_month = pd.Period(history.snapshot_month.max(), freq="M")
    validation_month = test_month - 3
    training = history.loc[history.snapshot_month <= str(validation_month - 3)]
    validation = history.loc[history.snapshot_month == str(validation_month)]
    test = history.loc[history.snapshot_month == str(test_month)]
    if _enough_examples(training) and not validation.empty and not test.empty:
        evaluator = stage_call("Fit model", new_model().fit, training[FEATURES], training.target.astype(int))
        report.update(training_months=sorted(training.snapshot_month.unique()),
            training_labels_observed_through=str(pd.Period(training.snapshot_month.max(), freq="M") + 3),
            validation_month=str(validation_month), test_month=str(test_month),
            validation=metrics(validation.target.astype(int), evaluator.predict_proba(validation[FEATURES])[:, 1]),
            candidate_test=metrics(test.target.astype(int), evaluator.predict_proba(test[FEATURES])[:, 1]))

    # Fixed model specification: the final test does not select a model.
    model = stage_call("Fit model", new_model().fit, history[FEATURES], history.target.astype(int))
    report.update(model_source="initial_training", status="trained", mature_training_rows=len(history),
                  evaluation_status="held_out" if "candidate_test" in report else "insufficient_history_for_independent_evaluation")
    bundle = {"pipeline": model, "features": FEATURES, "version": MODEL_VERSION,
              "trained_through": str(latest), "latest_training_snapshot": history.snapshot_month.max(),
              "reference_medians": history[FEATURES].median().to_dict(), "evaluation": dict(report)}
    return bundle, report

# 6. Produce probabilities, observed evidence and model-sensitivity factors.
@stage("Predict three-month inactivity risk")
def predict_customers(features, model_bundle=None):
    """Return one customer row with status, risk, reasons and forecast horizon.

    >=0.5 is at risk; >=0.75 is high risk. Already-churned customers are
    separate. Without a model/eligible history, probabilities stay missing.
    """
    current = features.copy()
    latest = pd.Period(current.snapshot_month.iloc[0], freq="M")
    current["churn_probability"] = np.nan
    current["model_factors"] = ""
    if model_bundle is not None:
        model = model_bundle["pipeline"]
        eligible = (current.history_months >= 3) & (current.consecutive_inactive_months < 3)
        if eligible.any():
            inputs = current.loc[eligible, FEATURES]
            probability = model.predict_proba(inputs)[:, 1]
            current.loc[eligible, "churn_probability"] = probability
            # Group replacement sensitivity is a model explanation, not a causal claim.
            medians = pd.Series(model_bundle["reference_medians"])
            contributions = {}
            for domain, title in DOMAINS.items():
                altered = inputs.copy()
                fields = [column for column in FEATURES if column.startswith(domain + "_")]
                altered[fields] = medians[fields].to_numpy()
                contributions[title] = probability - model.predict_proba(altered)[:, 1]
            altered = inputs.copy()
            altered["consecutive_inactive_months"] = medians["consecutive_inactive_months"]
            contributions["طول بی‌فعالیتی"] = probability - model.predict_proba(altered)[:, 1]
            effects = pd.DataFrame(contributions, index=inputs.index)
            for index, row in effects.iterrows():
                factors = row[row > 0.005].nlargest(2).index.tolist()
                current.loc[index, "model_factors"] = "، ".join(factors)
    statuses, levels, reasons = [], [], []
    for _, row in current.iterrows():
        inactive = int(row.consecutive_inactive_months)
        evidence = []
        if inactive:
            evidence.append(f"{inactive} ماه متوالی بدون فعالیت در منابع ثبت‌شده")
        for domain, title in DOMAINS.items():
            baseline = row[domain + "_previous3"]
            value = row[domain + "_current"]
            if baseline > 0 and value <= baseline * 0.5:
                percent = round((1 - value / baseline) * 100)
                evidence.append(f"کاهش {percent}٪ {title} نسبت به میانگین سه ماه پیش از دورهٔ اخیر")
        probability = row.churn_probability
        if inactive >= 3:
            state, level = "churned", "none"
        elif pd.notna(probability):
            state = "at_risk" if probability >= 0.5 else "low"
            level = "high" if probability >= 0.75 else "medium" if probability >= 0.5 else "low"
        else:
            state, level = "review", "review"
        statuses.append(state); levels.append(level)
        reasons.append("؛ ".join(evidence) if evidence else "نشانهٔ افت شدید در مقایسهٔ رفتار اخیر مشاهده نشد")
    current["retention_status"] = statuses
    current["risk_level"] = levels
    current["risk_reasons"] = reasons
    current["forecast_through"] = str(latest + 3)
    # Compatibility aliases for existing monthly exports, now explicitly using the new target.
    current["decline_probability"] = current.churn_probability
    current["prediction_status"] = current.retention_status
    current["predicted_next_month"] = str(latest + 3)
    return current

# 7. The orchestration function: start here when presenting the code.
@stage("Update churn predictions")
def run_prediction(payload, root=None):
    """7. Execute all stages, persist immutable outputs and return the API report."""
    root = ROOT if root is None else Path(root)
    if payload.get("confirm_complete") is not True:
        raise ValueError("کامل بودن هر سه منبع تا پایان ماه انتخاب‌شده را تأیید کنید.")
    try:
        month = pd.Period(payload["as_of_month"], freq="M")
        if str(month) != payload["as_of_month"]:
            raise ValueError()
    except Exception as exc:
        raise ValueError("ماه را با قالب YYYY-MM وارد کنید.") from exc
    if month >= pd.Timestamp.now(tz="UTC").tz_localize(None).to_period("M"):
        raise ValueError("یک ماه کامل پیش از ماه جاری انتخاب کنید.")
    state_file = root / "latest_report.json"
    if state_file.exists() and str(month) < json.loads(state_file.read_text())["as_of_month"]:
        raise ValueError("پیش‌بینی جدید نباید به ماهی قبل از آخرین اجرا برگردد.")
    root.mkdir(parents=True, exist_ok=True)
    orders, internet, calls = load_data(payload.get("sources", {}), payload.get("columns"))
    panel, first_seen, months = build_monthly_activity(orders, internet, calls, month, payload.get("columns"))
    snapshots = [build_features(panel, first_seen, item) for item in months[5:]]
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    run_dir = root / "runs" / run_id
    run_dir.mkdir(parents=True)
    active_path = root / "active_model.pkl"
    model_bundle, model_report = load_or_train_model(snapshots, panel, month, model_path=active_path)
    predictions = predict_customers(snapshots[-1], model_bundle)
    if model_bundle is not None:
        stage_call("Save model", joblib.dump, model_bundle, run_dir / "retention_model.pkl")
    stage_call("Save output file", predictions.to_csv, run_dir / "retention.csv", index=False)
    report = {"run_id": run_id, "as_of_month": str(month), "predicting_month": str(month + 3),
              "retention_version": MODEL_VERSION, "learning": model_report,
              "customers": len(predictions), "retention_counts": predictions.retention_status.value_counts().to_dict(),
              "input_mode": "complete_csv_snapshot",
              "input_rows": dict(zip(SOURCES, [len(orders), len(internet), len(calls)])), "workflow": "independent_churn", "identifier_version": IDENTIFIER_VERSION,
              "download_url": f"/churn/runs/{run_id}/customers", "report_download_url": f"/churn/runs/{run_id}/report"}
    write_json(run_dir / "report.json", report)
    if not active_path.exists() and (run_dir / "retention_model.pkl").exists():
        temporary = root / "active_model.tmp"
        shutil.copyfile(run_dir / "retention_model.pkl", temporary)
        temporary.replace(active_path)
    write_json(state_file, report)
    return json_safe(report)

# Small shared calculations used by the seven stages above.
def _enough_examples(frame):
    return len(frame) >= 30 and frame.target.nunique() == 2 and frame.target.value_counts().min() >= 5

def _normalize_ids(values):
    result = normalize_identifiers(values)
    if result.isna().any():
        raise ValueError("Every event needs a nonempty customer identifier.")
    return result

def _add_activity_history(frame, panel, month):
    result = frame.copy()
    prior = panel.loc[panel.month <= str(month)].copy()
    prior["active"] = prior[list(DOMAINS)].gt(0).any(axis=1)
    last = prior.loc[prior.active].groupby("MSISDN").month.max()
    result["last_active_month"] = result.MSISDN.map(last)
    result["consecutive_inactive_months"] = [
        pd.Period(month, freq="M").ordinal - pd.Period(value, freq="M").ordinal
        if pd.notna(value) else 0 for value in result.last_active_month
    ]
    return result

def new_model():
    return HistGradientBoostingClassifier(max_iter=150, max_leaf_nodes=7,
        min_samples_leaf=10, l2_regularization=5, learning_rate=0.06,
        early_stopping=False, random_state=42)

def metrics(y, probabilities):
    predicted = (probabilities >= 0.5).astype(int)
    return {
        "rows": len(y),
        "positive_rate": float(np.mean(y)),
        "confusion_matrix": confusion_matrix(y, predicted, labels=[0, 1]).tolist(),
        "matrix_labels": ["No churn within horizon", "Three consecutive inactive months reached"],
        "precision": float(precision_score(y, predicted, zero_division=0)),
        "recall": float(recall_score(y, predicted, zero_division=0)),
        "average_precision": (
            float(average_precision_score(y, probabilities)) if np.sum(y) > 0 else None
        ),
        "roc_auc": (
            float(roc_auc_score(y, probabilities)) if len(np.unique(y)) == 2 else None
        ),
        "brier": float(brier_score_loss(y, probabilities)),
    }


def _source_schemas(columns):
    columns = columns or {}
    if not isinstance(columns, dict):
        raise ValueError("columns must be an object keyed by source.")
    schemas = {}
    for source, defaults in SOURCES.items():
        schema = columns.get(source, list(defaults) + (["OrderStatusId", "Id"] if source == "order" else []))
        count = 5 if source == "order" else 3
        required = schema[:4] if source == "order" and isinstance(schema, (list, tuple)) else schema
        if (not isinstance(schema, (list, tuple)) or len(schema) != count
                or any(not isinstance(name, str) for name in schema)
                or any(not name.strip() for name in required)
                or len(set(filter(None, schema))) != len(list(filter(None, schema)))):
            raise ValueError(f"{source}: provide distinct identifier, date, value columns" +
                             (", status and optional event ID columns." if source == "order" else "."))
        schemas[source] = list(schema)
    return schemas
