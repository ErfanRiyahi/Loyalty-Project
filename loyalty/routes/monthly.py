"""Adaptive learning updates the clustering model only."""
import json
from flask import Blueprint, request, jsonify, send_file
from ..services import adaptive

app = Blueprint("monthly", __name__)


@app.post("/adaptive/update")
@app.post("/monthly/update")
def update():
    try:
        return jsonify(adaptive.update(request.get_json() or {}))
    except (ValueError, FileNotFoundError) as exc:
        return jsonify(error=str(exc)), 400


@app.get("/adaptive/status")
@app.get("/monthly/status")
def status():
    latest = adaptive.ROOT / "latest_report.json"
    result = json.loads(latest.read_text()) if latest.exists() else {"status": "not_run"}
    active = adaptive.ROOT / "active.json"
    result["active_run_id"] = json.loads(active.read_text())["run_id"] if active.exists() else None
    result["can_rollback"] = (adaptive.ROOT / "previous.json").exists()
    return jsonify(result)


@app.post("/adaptive/rollback")
def rollback():
    try:
        return jsonify(adaptive.rollback())
    except (ValueError, FileNotFoundError) as exc:
        return jsonify(error=str(exc)), 400


@app.get("/adaptive/download")
@app.get("/monthly/download")
def download():
    active = adaptive.ROOT / "active.json"
    if not active.exists():
        return jsonify(error="هنوز مدل فعال پذیرفته نشده است."), 404
    return send_file(json.loads(active.read_text())["output_file"], as_attachment=True)


@app.get("/adaptive/report")
@app.get("/monthly/report")
def report():
    path = adaptive.ROOT / "latest_report.json"
    if not path.exists():
        return jsonify(error="هنوز ارزیابی تطبیقی انجام نشده است."), 404
    return send_file(path, as_attachment=True)
