from ..progress import stage, stage_call, units, stage_scope
from flask import Blueprint, request, jsonify, send_file, current_app
import pandas as pd
from ..common import OUTPUT_ROOT, json_safe, score_distributions
import json
from ..services.churn import assess_risk, DOMAIN_GROUPS

app = Blueprint("churn", __name__)


# Prefer an uploaded file over a file path and save the full downloadable result.
@app.post("/churn/assess")
def assess():
    try:
        payload = (
            request.form if request.files else (request.get_json(silent=True) or {})
        )
        method = payload.get("method", "baseline")
        if "file" in request.files:
            frame = stage_call(
                "Read data file",
                pd.read_csv,
                request.files["file"].stream,
                dtype={"MSISDN": str},
            )
            source = "Uploaded final scored CSV"
        else:
            source = payload.get("dataset_address") or str(
                OUTPUT_ROOT / "customer_segmentation_final.csv"
            )
            frame = stage_call(
                "Read data file", pd.read_csv, source, dtype={"MSISDN": str}
            )
        output, columns = assess_risk(frame, method=method)
        path = OUTPUT_ROOT / "churn_risk_assessment.csv"
        stage_call("Save output file", output.to_csv, path, index=False)
        preview = (
            output.head(100).astype(object).where(pd.notna(output.head(100)), None)
        )
        diagnostics = {
            "method": method,
            "rows": len(output),
            "score_columns": columns,
            "counts": output["risk_band"].value_counts().to_dict(),
            "accepted_band_share": (
                float(output["decision_stable"].mean())
                if method == "domain_balanced"
                else None
            ),
            "review_share": float(output["risk_band"].eq("Needs review").mean()),
            "insufficient_share": float(
                output["risk_band"].eq("Insufficient evidence").mean()
            ),
            "thresholds": {"medium": 34, "high": 67},
            "notice": "Risk indices and missing-evidence bounds are not probabilities or statistical confidence intervals.",
        }
        diagnostics["method_version"] = "score-risk-v2"
        diagnostics["created_at_utc"] = pd.Timestamp.now(tz="UTC").isoformat()
        if method == "domain_balanced":
            diagnostics["score_groups"] = DOMAIN_GROUPS
            diagnostics["ablation"] = {
                "baseline_equal_score": output["baseline_risk_band"]
                .value_counts()
                .to_dict(),
                "group_balanced_without_review": output["point_risk_band"]
                .value_counts()
                .to_dict(),
                "group_balanced_with_review": output["risk_band"]
                .value_counts()
                .to_dict(),
                "note": "Coverage and band counts only; no accuracy comparison without true outcomes.",
            }
        with open(OUTPUT_ROOT / "churn_risk_diagnostics.json", "w") as stream:
            stage_call(
                "Save report and configuration",
                json.dump,
                json_safe(diagnostics),
                stream,
                indent=2,
                allow_nan=False,
            )
        return jsonify(
            json_safe(
                {
                    "method": method,
                    "distributions": score_distributions(output),
                    "diagnostics": diagnostics,
                    "notice": "Risk index is not a churn probability or a forecast. No future outcomes were used.",
                    "source": source,
                    "rows": len(output),
                    "score_columns": columns,
                    "counts": output["risk_band"].value_counts().to_dict(),
                    "preview": preview.to_dict(orient="records"),
                    "download_url": "/churn/download",
                }
            )
        )
    except (ValueError, FileNotFoundError, pd.errors.ParserError) as exc:
        return jsonify(error=str(exc)), 400
    except Exception:
        current_app.logger.exception("Risk assessment failed")
        return jsonify(error="Risk assessment failed. Check the server log."), 500


@app.get("/churn/download")
def download():
    path = OUTPUT_ROOT / "churn_risk_assessment.csv"
    if not path.exists():
        return jsonify(error="Run the risk assessment first."), 404
    return send_file(path, as_attachment=True)


def retention_frame():
    """Read one immutable run, never interpret a legacy decline model as churn."""
    from ..services import churn_prediction
    import re
    report_path = churn_prediction.ROOT / "latest_report.json"
    if not report_path.is_file():
        raise ValueError("ابتدا پیش‌بینی ریزش را با فایل‌های کامل به‌روز کنید.")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("retention_version") != churn_prediction.MODEL_VERSION:
        raise ValueError("نتایج قبلی مربوط به تعریف قدیمی افت فعالیت است؛ پیش‌بینی ریزش را دوباره اجرا کنید.")
    run = report.get("run_id", "")
    if not re.fullmatch(r"\d{8}_\d{6}(?:_\d{6})?", run):
        raise ValueError("شناسهٔ گزارش معتبر نیست؛ پیش‌بینی ریزش را دوباره اجرا کنید.")
    frame = pd.read_csv(churn_prediction.ROOT / "runs" / run / "retention.csv", dtype={"MSISDN": "string"})
    order = {"at_risk": 0, "churned": 1, "review": 2, "low": 3}
    frame["_order"] = frame.retention_status.map(order)
    frame = frame.sort_values(["_order", "churn_probability", "consecutive_inactive_months", "MSISDN"],
                              ascending=[True, False, False, True], na_position="last").drop(columns="_order")
    frame["priority"] = frame.groupby("retention_status", sort=False).cumcount() + 1
    return frame, report


def filter_retention(frame):
    state = request.args.get("status", "at_risk")
    if state not in ["all", "at_risk", "churned", "review", "low"]:
        raise ValueError("وضعیت انتخاب‌شده معتبر نیست.")
    if state != "all":
        frame = frame.loc[frame.retention_status == state]
    level = request.args.get("risk", "all")
    if level not in ["all", "high", "medium", "low", "review", "none"]:
        raise ValueError("سطح ریسک معتبر نیست.")
    if level != "all":
        frame = frame.loc[frame.risk_level == level]
    query = request.args.get("q", "").strip()
    if query:
        frame = frame.loc[frame.MSISDN.str.contains(query, regex=False, na=False)]
    return frame


@app.get("/churn/customers")
def customers():
    try:
        frame, report = retention_frame()
        counts = frame.retention_status.value_counts().to_dict()
        selected = filter_retention(frame)
        page = int(request.args.get("page", 1))
        page_size = int(request.args.get("page_size", 25))
        if page < 1 or not 1 <= page_size <= 100:
            raise ValueError("شماره یا اندازهٔ صفحه معتبر نیست.")
        offset = (page - 1) * page_size
        return jsonify(json_safe({"rows": selected.iloc[offset:offset + page_size].to_dict(orient="records"),
            "total": len(selected), "page": page, "page_size": page_size, "counts": counts,
            "as_of_month": report["as_of_month"], "forecast_through": report["predicting_month"],
            "model_status": report["learning"]["status"],
            "evaluation_status": report["learning"].get("evaluation_status", "unavailable")}))
    except (ValueError, FileNotFoundError) as exc:
        return jsonify(error=str(exc)), 400


@app.get("/churn/customers/download")
def customer_download():
    from io import BytesIO
    try:
        frame, report = retention_frame()
        selected = filter_retention(frame)
        fields = ["priority", "MSISDN", "retention_status", "risk_level", "churn_probability",
                  "last_active_month", "consecutive_inactive_months", "forecast_through", "risk_reasons", "model_factors"]
        csv = selected[fields].to_csv(index=False).encode("utf-8-sig")
        return send_file(BytesIO(csv), mimetype="text/csv; charset=utf-8", as_attachment=True,
                         download_name=f"retention_{report['as_of_month']}.csv")
    except (ValueError, FileNotFoundError) as exc:
        return jsonify(error=str(exc)), 400


@app.post("/churn/update")
def update_forecast():
    from ..services.churn_prediction import run_prediction
    try:
        return jsonify(run_prediction(request.get_json() or {}))
    except (ValueError, FileNotFoundError) as exc:
        return jsonify(error=str(exc)), 400
