from ..common import score_distributions
from ..progress import stage, stage_call, units, stage_scope

"""Monthly batch learning from the existing source schemas.

Events are retained locally; snapshots/targets are built with explicit month cutoffs.
"""
from pathlib import Path
from collections import Counter
import hashlib
import json
import sqlite3
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment
from sklearn.cluster import KMeans
from sklearn.metrics import (
    average_precision_score,
    roc_auc_score,
    brier_score_loss,
    confusion_matrix,
    precision_score,
    recall_score,
)

from ..common import OUTPUT_ROOT, source_path, json_safe, source_read_options
from .validation import validate_clusters

ROOT = OUTPUT_ROOT / "monthly"
SOURCES = {
    "order": ("MSISDN", "PaidDateUtc", "OrderTotal"),
    "data_cdr": ("SERVED_MSISDN", "START_TIMESTAMP", "ACTUAL_USAGE"),
    "voice_cdr": ("Subscriber_MSISDN", "Call_Date", "Call_Duration"),
}
ACTIVITY = ["orders", "data", "voice"]
FEATURES = [
    f"{domain}_{part}"
    for domain in ACTIVITY
    for part in ["log_current", "log_mean3", "log_mean6", "ratio", "inactive_months"]
]
CLUSTER_FEATURES = [
    "ARPU_SCORE",
    "CLV_SCORE",
    "GROWTH_SCORE",
    "DATA_USAGE_SCORE",
    "VOICE_USAGE_SCORE",
    "Transaction_Frequency_SCORE",
]


# Write to a temporary file, then replace the destination to avoid partial files.
@stage("Save report and state")
def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(json_safe(value), indent=2, allow_nan=False))
    temporary.replace(path)


# Preserve the legacy rule that removes the first two identifier characters.
def normalize_ids(values):
    # Preserve the supplied cleaners' string-ID rule. Do not silently change it.
    result = values.astype("string").str[2:]
    if result.isna().any() or result.str.strip().eq("").any():
        raise ValueError(
            "Legacy removal of the first two ID characters produced an empty ID. Check source identifiers."
        )
    return result


# Read data in small batches and handle overlapping events in history.
@stage("Ingest, clean and deduplicate history")
def ingest(paths, columns=None):
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
    ROOT.mkdir(parents=True, exist_ok=True)
    report = {}
    with sqlite3.connect(ROOT / "history.sqlite") as database:
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
                    ids = normalize_ids(chunk[id_col])
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


# Build shared history for all three sources through the observation month only.
@stage("Build shared monthly history")
def aggregates(as_of):
    with sqlite3.connect(ROOT / "history.sqlite") as database:
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


# Build customer features using data through the selected month only.
@stage("Build six-month features")
def snapshot(panel, first_seen, month):
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
    return frame.reset_index()


# Calculate scoring-reference parameters from historical data.
@stage("Calculate scoring references")
def fit_references(frame):
    references = {}
    for feature, raw in [
        ("ARPU_SCORE", "weighted_arpu"),
        ("DATA_USAGE_SCORE", "data_mean6"),
        ("VOICE_USAGE_SCORE", "voice_mean6"),
        ("Transaction_Frequency_SCORE", "orders_mean6"),
        ("GROWTH_SCORE", "growth_pct"),
    ]:
        references[feature] = [
            float(frame[raw].quantile(0.05)),
            float(frame[raw].quantile(0.95)),
        ]
    positive = frame.loc[frame.spend_weighted6 > 0, "spend_weighted6"]
    references["BaseCLV"] = float(positive.median()) if len(positive) else 1.0
    return references


# Apply the saved reference to customers so results remain comparable across runs.
@stage("Apply scoring references")
def apply_references(frame, refs, prefix=""):
    result = frame.copy()
    for feature, raw in [
        ("ARPU_SCORE", "weighted_arpu"),
        ("DATA_USAGE_SCORE", "data_mean6"),
        ("VOICE_USAGE_SCORE", "voice_mean6"),
        ("Transaction_Frequency_SCORE", "orders_mean6"),
        ("GROWTH_SCORE", "growth_pct"),
    ]:
        lower, upper = refs[feature]
        result[prefix + feature] = (
            (1 + 9 * (frame[raw] - lower) / (upper - lower)).clip(1, 10)
            if upper > lower
            else 5.0
        )
    result[prefix + "CLV_SCORE"] = (
        5
        + 2
        * np.log10(frame.spend_weighted6.clip(lower=1e-9) / max(refs["BaseCLV"], 1e-9))
    ).clip(1, 10)
    return result


# Evaluate predictions against observed outcomes in held-out months.
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


# Run ingestion, feature building, clustering, prediction and output saving in order.
@stage("Update monthly learning")
def run_monthly(payload):
    ROOT.mkdir(parents=True, exist_ok=True)
    if payload.get("confirm_complete") is not True:
        raise ValueError(
            "Confirm that all three feeds are complete through the selected observation month. Missing feed data must not be labeled as inactivity."
        )
    try:
        as_of = pd.Period(payload["as_of_month"], freq="M")
    except Exception as exc:
        raise ValueError("as_of_month must be YYYY-MM.") from exc
    if str(as_of) != payload["as_of_month"]:
        raise ValueError("Use YYYY-MM.")
    if as_of >= pd.Timestamp.now(tz="UTC").tz_localize(None).to_period("M"):
        raise ValueError("Select a completed month before the current calendar month.")
    state_path = ROOT / "state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    if state.get("as_of_month") and str(as_of) < state["as_of_month"]:
        raise ValueError(
            "Monthly updates must not move backwards. Use a separate output folder for historical experiments."
        )
    ingestion = ingest(payload.get("sources", {}), payload.get("columns"))
    panel, first_seen, months = aggregates(as_of)
    snapshots = [snapshot(panel, first_seen, month) for month in months[5:]]
    current = snapshots[-1]
    quarter = str(as_of.asfreq("Q"))
    ref_path = ROOT / "references" / f"{quarter}.json"
    if ref_path.exists():
        references = json.loads(ref_path.read_text())
    else:
        # Build references from data before the quarter; no future-month leakage.
        prior = pd.Period(quarter, freq="Q").asfreq("M", "start") - 1
        ref_month = min(prior, as_of)
        reference_frames = [
            snapshot(panel, first_seen, ref_month - offset) for offset in [2, 1, 0]
        ]
        ref_frame = pd.concat(reference_frames, ignore_index=True)
        if ref_frame.empty:
            ref_frame = current
            ref_month = as_of
        references = {
            "quarter": quarter,
            "reference_month": str(ref_month),
            "global": fit_references(ref_frame),
            "peer": {},
            "note": "Global and peer parameters remain fixed through this quarter; unseen groups use global references.",
        }
    scored = apply_references(current, references["global"])
    X = scored[CLUSTER_FEATURES].to_numpy(dtype=float)
    if len(X) < 3 or np.unique(X, axis=0).shape[0] < 3:
        raise ValueError(
            "Monthly k=3 needs at least three customers and three distinct feature vectors."
        )
    km = stage_call(
        "Fit model", KMeans(n_clusters=3, n_init=10, random_state=42).fit, X
    )
    labels = km.labels_
    previous_path = ROOT / "latest_assignments.csv"
    mapping = {}
    if previous_path.exists():
        old = stage_call(
            "Read data file", pd.read_csv, previous_path, dtype={"MSISDN": "string"}
        )
        overlap = pd.DataFrame({"MSISDN": current.MSISDN, "raw": labels}).merge(
            old, on="MSISDN"
        )
        if len(overlap):
            matrix = (
                pd.crosstab(overlap.raw, overlap.cluster_id)
                .reindex(index=range(3), columns=range(3), fill_value=0)
                .to_numpy()
            )
            rows, cols = linear_sum_assignment(-matrix)
            mapping = dict(zip(rows.tolist(), cols.tolist()))
    if not mapping:
        order = (
            scored.assign(raw=labels)
            .groupby("raw")[CLUSTER_FEATURES]
            .mean()
            .mean(axis=1)
            .sort_values()
            .index
        )
        mapping = dict(zip(order, range(3)))
    stable = np.array([mapping[int(label)] for label in labels])
    scored["cluster_id"] = stable
    scored["cluster_label"] = [f"Cluster {number}" for number in stable]
    for number in range(3):
        key = str(number)
        if key not in references["peer"]:
            members = scored.loc[scored.cluster_id == number, "MSISDN"]
            reference = snapshot(
                panel, first_seen, pd.Period(references["reference_month"], freq="M")
            )
            subset = reference.loc[reference.MSISDN.isin(members)]
            references["peer"][key] = (
                fit_references(subset) if len(subset) >= 3 else references["global"]
            )
        positions = scored.index[scored.cluster_id == number]
        peer = apply_references(
            scored.loc[positions], references["peer"][key], prefix="PEER_"
        )
        for col in CLUSTER_FEATURES:
            scored.loc[positions, "PEER_" + col] = peer["PEER_" + col]
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    run_dir = ROOT / "runs" / run_id
    run_dir.mkdir(parents=True)
    from .retention import predict, VERSION as retention_version

    prediction, training = predict(snapshots, panel, as_of, run_dir)
    output = scored.merge(
        prediction[
            [
                "MSISDN",
                "decline_probability",
                "prediction_status",
                "predicted_next_month",
                "churn_probability", "retention_status", "risk_level", "risk_reasons",
                "model_factors", "last_active_month", "consecutive_inactive_months", "forecast_through",
            ]
        ],
        on="MSISDN",
        validate="one_to_one",
    )
    output = output.sort_values(
        ["decline_probability", "cluster_id"],
        ascending=[False, True],
        na_position="last",
    ).reset_index(drop=True)
    output["complete_inactivity_current_month"] = sum(
        output[d + "_current"] for d in ACTIVITY
    ).eq(0)
    diagnostics = validate_clusters(
        X,
        labels,
        {raw: f"Cluster {stable_id}" for raw, stable_id in mapping.items()},
        payload.get("run_stability", True),
    )
    stage_call("Save output file", prediction.to_csv, run_dir / "retention.csv", index=False)
    for file in [run_dir / "customers.csv", ROOT / "latest_customers.csv"]:
        stage_call("Save output file", output.to_csv, file, index=False)
    stage_call(
        "Save model",
        joblib.dump,
        {
            "preprocessing": "none",
            "kmeans": km,
            "cluster_id_map": mapping,
            "features": CLUSTER_FEATURES,
            "quarter": quarter,
        },
        run_dir / "cluster_model.pkl",
    )
    stage_call(
        "Save output file",
        output[["MSISDN", "cluster_id"]].to_csv,
        previous_path,
        index=False,
    )
    write_json(ref_path, references)
    report = {
        "run_id": run_id,
        "as_of_month": str(as_of),
        "predicting_month": str(as_of + 3),
        "retention_version": retention_version,
        "retention_counts": prediction.retention_status.value_counts().to_dict(),
        "quarter": quarter,
        "customers": len(output),
        "cluster_counts": output.cluster_id.value_counts().sort_index().to_dict(),
        "ingestion": ingestion,
        "clustering_validation": diagnostics,
        "learning": training,
        "references": references,
        "warnings": [
            "Identical unkeyed corrected events cannot be distinguished from genuinely new events. Exact-overlap deduplication only.",
            "Legacy ID cleaning removes the first two characters.",
        ],
        "preview": output.head(100).to_dict(orient="records"),
        "download_url": "/monthly/download",
    }
    report["distributions"] = score_distributions(output)
    report["prediction_counts"] = output["prediction_status"].value_counts().to_dict()
    report["preprocessing"] = "none"
    write_json(run_dir / "report.json", report)
    write_json(ROOT / "latest_report.json", report)
    write_json(state_path, {"as_of_month": str(as_of), "run_id": run_id})
    return json_safe(report)
