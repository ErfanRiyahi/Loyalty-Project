from ..progress import stage, stage_call, units, stage_scope

"""Activity-history helpers retained under the legacy module name.

Independent churn inference supplies its own storage root. No adaptive model lifecycle lives here.
"""
from ..identifiers import normalize_identifiers
from pathlib import Path
from collections import Counter
import hashlib
import json
import sqlite3

import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    roc_auc_score,
    brier_score_loss,
    confusion_matrix,
    precision_score,
    recall_score,
)

from ..common import OUTPUT_ROOT, source_path, json_safe, source_read_options

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



# Write to a temporary file, then replace the destination to avoid partial files.
@stage("Save report and state")
def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(json_safe(value), indent=2, allow_nan=False))
    temporary.replace(path)


# Share exactly the same identifiers as scoring and temporal stability.
def normalize_ids(values):
    result = normalize_identifiers(values)
    if result.isna().any():
        raise ValueError("Every event needs a nonempty customer identifier.")
    return result


# Read data in small batches and handle overlapping events in history.
@stage("Ingest, clean and deduplicate history")
def ingest(paths, columns=None, root=None):
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
def aggregates(as_of, root=None):
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
