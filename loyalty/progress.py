"""Real execution telemetry. No stage weights or time-based percentage estimates."""

from contextvars import ContextVar
from contextlib import contextmanager
from functools import wraps
import time

current_job = ContextVar("current_job", default=None)


# Record actual stage start and end times without estimating remaining time.
@contextmanager
def stage_scope(label):
    job = current_job.get()
    if job is None:
        yield
        return
    event = {
        "label": label,
        "status": "running",
        "started": time.monotonic(),
        "completed_units": None,
        "total_units": None,
        "unit": None,
    }
    with job["lock"]:
        job["stack"].append(event)
        job["events"].append(event)
    try:
        yield
    except BaseException:
        with job["lock"]:
            event["status"] = "failed"
        raise
    else:
        with job["lock"]:
            event["status"] = "completed"
    finally:
        with job["lock"]:
            event["duration_seconds"] = time.monotonic() - event["started"]
            job["stack"].pop()
            # Bound memory while retaining the actual active stack separately.
            job["events"] = job["events"][-2000:]


# This wrapper measures time without changing the wrapped function's result.
def stage(label):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            with stage_scope(label):
                return fn(*args, **kwargs)

        return wrapped

    return decorate


# Measure an actual function call and return its original result.
def stage_call(label, fn, *args, **kwargs):
    with stage_scope(label):
        return fn(*args, **kwargs)


# Report completed rows only after actual processing is confirmed.
def units(completed, unit="rows", total=None, description=None):
    job = current_job.get()
    if job is not None:
        with job["lock"]:
            if job["stack"]:
                event = job["stack"][-1]
                event.update(
                    completed_units=int(completed), total_units=total, unit=unit
                )
                if description:
                    event["description"] = description
