"""Churn prediction in one place: read the seven numbered stages in order.

Public flow:
    load_data -> build_monthly_activity -> build_features -> build_labels
    -> load_or_train_model -> predict_customers -> run_prediction

The HTTP route only calls run_prediction. Saved models, feature names, history,
three-month labels and API outputs remain compatible with earlier versions.
"""
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import shutil
import sqlite3

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

# 1. Read sources and maintain event history.
@stage("Ingest, clean and deduplicate history")
def load_data(paths, columns=None, root=None):
    """1. Read/clean the three sources and deduplicate their persistent event history.

    Returns per-source read/skip/deduplication counts; writes history.sqlite.
    """
    root = ROOT if root is None else Path(root)
    columns = columns or {}
    if not isinstance(columns, dict):
        raise ValueError("columns must be an object keyed by source.")
    schemas = {}
    for source, defaults in SOURCES.items():
        schema = columns.get(source, list(defaults) + (["OrderStatusId", "Id"] if source == "order" else []))
        expected = 5 if source == "order" else 3
        if (not isinstance(schema, (list, tuple)) or len(schema) != expected
                or any(not isinstance(col, str) or not col.strip() for col in schema[:4 if source == "order" else 3])
                or any(not isinstance(col, str) for col in schema)
                or len(set(filter(None, schema))) != len(list(filter(None, schema)))):
            raise ValueError(f"{source}: provide distinct identifier, date, value columns"
                             + (", status and optional event ID columns." if source == "order" else "."))
        schemas[source] = schema
    root.mkdir(parents=True, exist_ok=True)
    report = {}
    with sqlite3.connect(root / "history.sqlite") as database:
        database.execute(
            "CREATE TABLE IF NOT EXISTS events (source TEXT, event_key TEXT, customer TEXT, month TEXT, value REAL, successful INTEGER, occurrences INTEGER, PRIMARY KEY(source,event_key))"
        )
        for source, schema in schemas.items():
            id_col, date_col, value_col = schema[:3]
            with stage_scope(f"Ingest and clean source {source}"):
                path = str(paths.get(source) or source_path(source))
                required = [id_col, date_col, value_col]
                if source == "order":
                    required.append(schema[3])
                read_options = source_read_options(path, required)
                header = stage_call(
                    "Read data file", pd.read_csv, path, **read_options, nrows=0
                ).columns.tolist()
                absent = [col for col in required if col not in header]
                if absent:
                    raise ValueError(f"{source}: missing columns {absent}")
                # Orders can be corrected reliably if their event Id is supplied.
                event_id = schema[4] if source == "order" and schema[4] in header else None
                selected = required + ([event_id] if event_id else [])
                database.execute(
                    "CREATE TEMP TABLE IF NOT EXISTS incoming (event_key TEXT PRIMARY KEY, customer TEXT, month TEXT, value REAL, successful INTEGER, occurrences INTEGER)"
                )
                database.execute("DELETE FROM incoming")
                read_rows = dropped = 0
                for chunk in stage_call(
                    "Read data file",
                    pd.read_csv,
                    path,
                    **read_options,
                    usecols=selected,
                    dtype={
                        id_col: "string",
                        **({event_id: "string"} if event_id else {}),
                    },
                    low_memory=True,
                    chunksize=100000,
                ):
                    incoming = Counter()
                    payloads = {}
                    read_rows += len(chunk)
                    dates = pd.to_datetime(chunk[date_col], errors="coerce", utc=True)
                    values = pd.to_numeric(chunk[value_col], errors="coerce")
                    valid = (
                        dates.notna()
                        & chunk[id_col].notna()
                        & values.notna()
                        & np.isfinite(values)
                        & (values >= 0)
                    )
                    if event_id:
                        valid &= chunk[event_id].notna()
                    dropped += int((~valid).sum())
                    chunk = chunk.loc[valid].copy()
                    ids = _normalize_ids(chunk[id_col])
                    months = dates.loc[valid].dt.strftime("%Y-%m")
                    status = (
                        pd.to_numeric(chunk[schema[3]], errors="coerce").eq(30)
                        if source == "order"
                        else pd.Series(True, index=chunk.index)
                    )
                    for index in chunk.index:
                        if event_id:
                            key = "id:" + str(chunk.loc[index, event_id])
                        else:
                            # Preserve within-delivery multiplicity; repeat/overlap feeds do not add it again.
                            raw = [str(chunk.loc[index, col]) for col in required]
                            key = hashlib.sha256(
                                json.dumps(raw, ensure_ascii=False).encode()
                            ).hexdigest()
                        incoming[key] += 1
                        payloads[key] = (
                            str(ids.loc[index]),
                            str(months.loc[index]),
                            float(values.loc[index]),
                            int(status.loc[index]),
                        )
                    records = [
                        (key, *payloads[key], 1 if event_id else count)
                        for key, count in incoming.items()
                    ]
                    database.executemany(
                        "INSERT INTO incoming VALUES (?,?,?,?,?,?) ON CONFLICT(event_key) DO UPDATE SET customer=excluded.customer,month=excluded.month,value=excluded.value,successful=excluded.successful,occurrences=incoming.occurrences+excluded.occurrences",
                        records,
                    )
                    units(read_rows, description=f"{source}: rows read and processed")
                if event_id:
                    database.execute(
                        "INSERT INTO events SELECT ?,event_key,customer,month,value,successful,1 FROM incoming WHERE 1 ON CONFLICT(source,event_key) DO UPDATE SET customer=excluded.customer,month=excluded.month,value=excluded.value,successful=excluded.successful,occurrences=1",
                        (source,),
                    )
                else:
                    database.execute(
                        "INSERT INTO events SELECT ?,event_key,customer,month,value,successful,occurrences FROM incoming WHERE 1 ON CONFLICT(source,event_key) DO UPDATE SET occurrences=MAX(events.occurrences,excluded.occurrences)",
                        (source,),
                    )
                report[source] = {
                    "path": path,
                    "input_rows": read_rows,
                    "invalid_rows_skipped": dropped,
                    "deduplication": (
                        "Id upsert"
                        if event_id
                        else "Exact selected-field fingerprint, maximum multiplicity across deliveries"
                    ),
                    "stored_events": database.execute(
                        "SELECT COALESCE(SUM(occurrences),0) FROM events WHERE source=?",
                        (source,),
                    ).fetchone()[0],
                }
        database.commit()
    return report

# 2. Build the monthly activity table.
@stage("Build shared monthly history")
def build_monthly_activity(as_of, root=None):
    """2. Return customer-month activity, first-seen dates and observed months.

    Orders are successful-event counts; data/voice are positive-volume activity.
    Zero-filled months assume the user confirmed complete source coverage.
    """
    as_of = pd.Period(as_of, freq="M")
    root = ROOT if root is None else Path(root)
    with sqlite3.connect(root / "history.sqlite") as database:
        all_data = pd.read_sql_query(
            "SELECT source,customer,month,SUM(value*occurrences) AS volume,SUM(occurrences) AS frequency FROM events WHERE successful=1 AND month<=? GROUP BY source,customer,month",
            database,
            params=[str(as_of)],
        )
    if all_data.empty:
        raise ValueError("No usable historical events through this month.")
    first_by_source = all_data.groupby("source")["month"].min()
    if set(first_by_source.index) != set(SOURCES):
        raise ValueError("All three sources need usable historical events.")
    start = pd.Period(max(first_by_source), freq="M")
    if as_of.ordinal - start.ordinal < 6:
        raise ValueError(
            "At least seven complete common-history months are needed. Provide the historical files for initial setup."
        )
    months = pd.period_range(start, as_of, freq="M")
    ids = sorted(all_data["customer"].unique())
    index = pd.MultiIndex.from_product(
        [ids, months.astype(str)], names=["MSISDN", "month"]
    )
    panel = pd.DataFrame(index=index)
    for source, name in [
        ("order", "orders"),
        ("data_cdr", "data"),
        ("voice_cdr", "voice"),
    ]:
        data = all_data.loc[all_data.source == source].set_index(["customer", "month"])
        panel[name] = (
            data["frequency" if source == "order" else "volume"]
            .reindex(index)
            .fillna(0)
        )
        if source == "order":
            panel["spend"] = data["volume"].reindex(index).fillna(0)
    first_seen = all_data.groupby("customer")["month"].min()
    return panel.reset_index(), first_seen, months

# 3. Build model inputs at a particular cutoff.
@stage("Build six-month features")
def build_features(panel, first_seen, month):
    """3. Summarize six months of behavior available at the observation cutoff.

    FEATURES selects the 17 actual model inputs; other exported summaries are
    retained for compatibility. No later-month records enter these features.
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
    for domain in ACTIVITY + ["spend"]:
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
        frame[domain + "_weighted6"] = values.dot(
            np.array([0.05, 0.10, 0.15, 0.20, 0.25, 0.25])
        )
        frame[domain + "_recent3_median"] = values.iloc[:, -3:].median(axis=1)
        frame[domain + "_previous3_median"] = values.iloc[:, :3].median(axis=1)
        if domain == "spend":
            frame["weighted_arpu"] = values.dot(np.array([1, 1, 1, 2, 2, 2])) / 9
        if domain in ACTIVITY:
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
    previous = frame.spend_previous3_median
    frame["growth_pct"] = (
        ((frame.spend_recent3_median / previous.replace(0, np.nan) - 1) * 100)
        .replace([np.inf, -np.inf], np.nan)
        .fillna(0)
    )
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
    ingestion = load_data(payload.get("sources", {}), payload.get("columns"), root=root)
    panel, first_seen, months = build_monthly_activity(month, root=root)
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
              "ingestion": ingestion, "workflow": "independent_churn", "identifier_version": IDENTIFIER_VERSION,
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
