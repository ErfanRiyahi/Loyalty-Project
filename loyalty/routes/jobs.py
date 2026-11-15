"""Single-process worker for this local dashboard; original POST APIs remain valid."""

from flask import Blueprint, request, jsonify, current_app, g
from threading import Lock, RLock, Thread
from uuid import uuid4
import time
from ..progress import current_job, stage_scope

app = Blueprint("jobs", __name__)
PATHS = {
    "/analyze",
    "/consistency_index",
    "/temporal_stability",
    "/dataset_overview",
    "/cluster",
    "/churn/assess",
    "/monthly/update",
}


def install(application):
    state = {"jobs": {}, "guard": RLock(), "work": Lock()}
    application.extensions["progress_jobs"] = state

    # Allow only one writer because the primary output filenames are shared.
    @application.before_request
    def protect_outputs():
        if (
            request.method == "POST"
            and request.path in PATHS | {"/cluster/config"}
            and not getattr(g, "job_worker", False)
        ):
            if not state["work"].acquire(False):
                return (
                    jsonify(
                        error="Another operation is running. Please wait until it finishes."
                    ),
                    409,
                )
            g.holds_work_lock = True

    # Release the lock even after an error so later jobs can run.
    @application.teardown_request
    def release_outputs(error):
        if getattr(g, "holds_work_lock", False):
            g.holds_work_lock = False
            state["work"].release()


# Read a consistent snapshot of job state while holding the lock.
def snapshot(job):
    with job["lock"]:
        now = time.monotonic()
        events = [
            {
                **{k: v for k, v in e.items() if k != "started"},
                "elapsed_seconds": round(
                    e.get("duration_seconds", now - e["started"]), 2
                ),
            }
            for e in job["events"]
        ]
        active = job["stack"][-1] if job["stack"] else None
        return {
            "operation_id": job["id"],
            "path": job["path"],
            "status": job["status"],
            "stage": active["label"] if active else None,
            "elapsed_seconds": round(job.get("finished", now) - job["started"], 2),
            "percentage": 100 if job["status"] == "succeeded" else None,
            "events": events,
            "result": job.get("result"),
            "http_status": job.get("http_status"),
        }


# Reuse an existing job for a repeated request key instead of running it twice.
@app.post("/jobs")
def start():
    application = current_app._get_current_object()
    state = application.extensions["progress_jobs"]
    if request.is_json:
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error="Operation input must be a JSON object."), 400
        path, body, upload = payload.get("path"), payload.get("body", {}), None
    else:
        path = request.form.get("path")
        body = {"method": request.form.get("method", "baseline")}
        file = request.files.get("file")
        upload = (file.read(), file.filename) if file else None
    if path not in PATHS or not isinstance(body, dict):
        return jsonify(error="Invalid operation path or input."), 400
    key = request.headers.get("Idempotency-Key", "")[:128]
    with state["guard"]:
        # Retries of the same request return the existing operation, never rerun it.
        if key:
            for job in state["jobs"].values():
                if job["key"] == key:
                    if job["path"] != path:
                        return jsonify(error="Duplicate request key."), 409
                    return jsonify(operation_id=job["id"]), 202
        now = time.monotonic()
        for ident, job in list(state["jobs"].items()):
            if job.get("finished", now) < now - 3600:
                del state["jobs"][ident]
        if len(state["jobs"]) >= 64:
            return (
                jsonify(
                    error="The report limit has been reached. Please try again later."
                ),
                503,
            )
        if not state["work"].acquire(False):
            return (
                jsonify(
                    error="Another operation is running. Please wait until it finishes."
                ),
                409,
            )
        ident = uuid4().hex
        job = dict(
            id=ident,
            key=key,
            path=path,
            status="running",
            started=now,
            lock=RLock(),
            events=[],
            stack=[],
        )
        state["jobs"][ident] = job

        # Run the existing API handler in a background thread without rewriting its formulas.
        def work():
            token = current_job.set(job)
            try:
                kwargs = {"json": body}
                if upload is not None:
                    from io import BytesIO

                    kwargs = {
                        "data": {**body, "file": (BytesIO(upload[0]), upload[1])},
                        "content_type": "multipart/form-data",
                    }
                with application.test_request_context(path, method="POST", **kwargs):
                    g.job_worker = True
                    with stage_scope("Validate input and execute operation"):
                        response = application.full_dispatch_request()
                        result = response.get_json()
                        if result is None:
                            result = {
                                "error": "The processing response could not be read."
                            }
                    with job["lock"]:
                        job["result"], job["http_status"] = result, response.status_code
                        job["status"] = (
                            "failed"
                            if response.status_code >= 400 or "error" in result
                            else "succeeded"
                        )
            except Exception:
                application.logger.exception("Background operation failed")
                with job["lock"]:
                    job.update(
                        status="failed",
                        result={"error": "Processing failed. Check the server log."},
                        http_status=500,
                    )
            finally:
                with job["lock"]:
                    job["finished"] = time.monotonic()
                current_job.reset(token)
                state["work"].release()

        try:
            Thread(target=work, daemon=True, name="loyalty-" + ident[:8]).start()
        except Exception:
            del state["jobs"][ident]
            state["work"].release()
            raise
    return jsonify(operation_id=ident), 202


# Expose the actual stage and elapsed time for the browser to display.
@app.get("/jobs/<ident>")
def status(ident):
    job = current_app.extensions["progress_jobs"]["jobs"].get(ident)
    if not job:
        return (
            jsonify(error="Operation report not found. The server may have restarted."),
            404,
        )
    response = jsonify(snapshot(job))
    response.headers["Cache-Control"] = "no-store"
    return response


# Recover the previous job by its request key if the start response was lost.
@app.get("/jobs/request/<key>")
def find_request(key):
    state = current_app.extensions["progress_jobs"]
    with state["guard"]:
        for job in state["jobs"].values():
            if job["key"] == key:
                return jsonify(operation_id=job["id"])
    return (
        jsonify(
            error="Request not found. It may not have reached the server, or the server may have restarted."
        ),
        404,
    )
