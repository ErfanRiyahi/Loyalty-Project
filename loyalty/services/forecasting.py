"""Independent churn inference; never trains or calls the clustering pipeline."""
from pathlib import Path
from datetime import datetime, timezone
import json
import shutil
import joblib
import pandas as pd
from ..common import OUTPUT_ROOT, json_safe
from ..progress import stage, stage_call
from . import monthly, retention

ROOT = OUTPUT_ROOT / "churn"


@stage("Update churn predictions")
def update(payload):
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
    state_file = ROOT / "latest_report.json"
    if state_file.exists() and str(month) < json.loads(state_file.read_text())["as_of_month"]:
        raise ValueError("پیش‌بینی جدید نباید به ماهی قبل از آخرین اجرا برگردد.")
    ROOT.mkdir(parents=True, exist_ok=True)
    ingestion = monthly.ingest(payload.get("sources", {}), payload.get("columns"), root=ROOT)
    panel, first_seen, months = monthly.aggregates(month, root=ROOT)
    snapshots = [monthly.snapshot(panel, first_seen, item) for item in months[5:]]
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    run_dir = ROOT / "runs" / run_id
    run_dir.mkdir(parents=True)
    active_path = ROOT / "active_model.pkl"
    active = joblib.load(active_path) if active_path.exists() else None
    predictions, model_report = retention.predict(snapshots, panel, month, run_dir, model_bundle=active)
    stage_call("Save output file", predictions.to_csv, run_dir / "retention.csv", index=False)
    report = {"run_id": run_id, "as_of_month": str(month), "predicting_month": str(month + 3),
              "retention_version": retention.VERSION, "learning": model_report,
              "customers": len(predictions), "retention_counts": predictions.retention_status.value_counts().to_dict(),
              "ingestion": ingestion, "workflow": "independent_churn",
              "download_url": f"/churn/runs/{run_id}/customers", "report_download_url": f"/churn/runs/{run_id}/report"}
    monthly.write_json(run_dir / "report.json", report)
    if not active_path.exists() and (run_dir / "retention_model.pkl").exists():
        temporary = ROOT / "active_model.tmp"
        shutil.copyfile(run_dir / "retention_model.pkl", temporary)
        temporary.replace(active_path)
    monthly.write_json(state_file, report)
    return json_safe(report)
