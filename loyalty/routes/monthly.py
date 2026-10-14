from flask import Blueprint, request, jsonify, send_file
from ..common import json_safe
from ..services.monthly import run_monthly, ROOT
import json
import threading

app=Blueprint('monthly',__name__)
update_lock=threading.Lock()

@app.post('/monthly/update')
def update():
    if not update_lock.acquire(blocking=False):
        return jsonify(error='Another monthly update is running.'),409
    try:
        return jsonify(run_monthly(request.get_json() or {}))
    except (ValueError,FileNotFoundError) as exc:
        return jsonify(error=str(exc)),400
    except Exception:
        from flask import current_app
        current_app.logger.exception('Monthly update failed')
        return jsonify(error='Monthly update failed; check the Python console for details.'),500
    finally:
        update_lock.release()

@app.get('/monthly/status')
def status():
    path=ROOT/'latest_report.json'
    return jsonify(json_safe(json.loads(path.read_text()))) if path.exists() else jsonify(status='not_run')

@app.get('/monthly/download')
def download():
    path=ROOT/'latest_customers.csv'
    if not path.exists(): return jsonify(error='Run Monthly Learning first.'),404
    return send_file(path,as_attachment=True)

@app.get('/monthly/report')
def report():
    path=ROOT/'latest_report.json'
    if not path.exists(): return jsonify(error='Run Monthly Learning first.'),404
    return send_file(path,as_attachment=True)
