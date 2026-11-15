"""Attach downloadable result files without changing version 3 processing APIs."""

from flask import Blueprint, current_app, request, jsonify, send_file
from pathlib import Path
from uuid import uuid4
import json
import re
import shutil
from .. import common
from ..progress import stage_scope

app = Blueprint("downloads", __name__)


# Snapshot the output so later runs do not change earlier download links.
def export_copy(path):
    path = Path(path).resolve()
    if not path.is_relative_to(common.OUTPUT_ROOT.resolve()) or not path.is_file():
        raise FileNotFoundError("The generated output file is unavailable.")
    directory = common.OUTPUT_ROOT / "exports"
    directory.mkdir(parents=True, exist_ok=True)
    exported = directory / f"{uuid4().hex}_{path.name}"
    with stage_scope("Prepare downloadable output"):
        shutil.copyfile(path, exported)
    return "/outputs/download/" + exported.name


# Allow only known output filenames instead of arbitrary download paths.
@app.get("/outputs/download/<name>")
def download_export(name):
    if not re.fullmatch(r"[0-9a-f]{32}_[A-Za-z0-9_]+\.(csv|json)", name):
        return jsonify(error="Unknown output file."), 404
    path = common.OUTPUT_ROOT / "exports" / name
    if not path.is_file():
        return jsonify(error="Output file not found."), 404
    return send_file(path, as_attachment=True, download_name=name[33:])


# Read monthly files from their own run directory, independent of later runs.
@app.get("/monthly/runs/<run_id>/<kind>")
def download_monthly_run(run_id, kind):
    from ..services import monthly

    if not re.fullmatch(r"\d{8}_\d{6}(?:_\d{6})?", run_id) or kind not in [
        "customers",
        "report",
    ]:
        return jsonify(error="Unknown monthly output."), 404
    name = "customers.csv" if kind == "customers" else "report.json"
    path = monthly.ROOT / "runs" / run_id / name
    if not path.is_file():
        return jsonify(error="Monthly output file not found."), 404
    return send_file(path, as_attachment=True, download_name=name)


def install(application):
    # Add the generated file's download link after a successful API response.
    @application.after_request
    def attach_output_links(response):
        if (
            not response.is_json
            or response.direct_passthrough
            or response.status_code >= 400
        ):
            return response
        eligible = {
            "/analyze",
            "/consistency_index",
            "/temporal_stability",
            "/cluster",
            "/churn/assess",
            "/monthly/update",
            "/monthly/status",
            "/dataset_overview",
        }
        if request.path not in eligible:
            return response
        data = response.get_json()
        if not isinstance(data, dict) or "error" in data:
            return response
        if request.path in ["/monthly/update", "/monthly/status"] and data.get(
            "run_id"
        ):
            data["download_url"] = "/monthly/runs/" + data["run_id"] + "/customers"
            data["report_download_url"] = "/monthly/runs/" + data["run_id"] + "/report"
        elif request.method == "POST":
            if request.path in [
                "/analyze",
                "/consistency_index",
                "/temporal_stability",
            ]:
                data["score"]["download_url"] = export_copy(
                    data["score"]["output_file"]
                )
            elif request.path == "/cluster":
                data["download_url"] = export_copy(data["output_file"])
                report = common.OUTPUT_ROOT / "cluster_validation.json"
                if report.exists():
                    data["report_download_url"] = export_copy(report)
            elif request.path == "/churn/assess":
                data["download_url"] = export_copy(
                    common.OUTPUT_ROOT / "churn_risk_assessment.csv"
                )
                data["report_download_url"] = export_copy(
                    common.OUTPUT_ROOT / "churn_risk_diagnostics.json"
                )
            elif request.path == "/dataset_overview" and "dataset_overview" in data:
                directory = common.OUTPUT_ROOT / "exports"
                directory.mkdir(parents=True, exist_ok=True)
                exported = directory / f"{uuid4().hex}_dataset_profile.json"
                with stage_scope("Save dataset report"):
                    exported.write_text(
                        json.dumps(common.json_safe(data), allow_nan=False, indent=2),
                        encoding="utf-8",
                    )
                data["download_url"] = "/outputs/download/" + exported.name
        response.set_data(json.dumps(common.json_safe(data), allow_nan=False))
        return response
