"""ArchNext API."""
from __future__ import annotations

import json
import logging
import threading
from collections import OrderedDict
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .evaluation import evaluate_session
from .pipeline.preprocess import PlanImageError
from .pipeline.run import (PlanSession, apply_manual_scale, apply_user_fix, process_plan, reset_scale, session_result,
                           undo_user_fix)

log = logging.getLogger("archnext")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="ArchNext", version="1.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_sessions: "OrderedDict[str, PlanSession]" = OrderedDict()
_lock = threading.Lock()
MAX_SESSIONS = 30
UNIT_TO_M = {"m": 1.0, "cm": 0.01, "mm": 0.001, "ft": 0.3048, "in": 0.0254}
ROOT = Path(__file__).resolve().parent.parent
BENCHMARK_FILE = ROOT / "eval" / "results" / "benchmark.json"


def _get(plan_id: str) -> PlanSession:
    with _lock:
        sess = _sessions.get(plan_id)
    if sess is None:
        raise HTTPException(404, "This plan is no longer available. Please upload it again.")
    return sess


@app.get("/api/health")
def health():
    return {"ok": True}


@app.post("/api/plans")
async def upload_plan(file: UploadFile = File(...)):
    data = await file.read()
    try:
        sess = process_plan(data, file.filename or "plan")
    except PlanImageError as exc:
        raise HTTPException(400, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, f"The plan could not be reconstructed: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        log.exception("processing failed")
        raise HTTPException(500, "Something went wrong while processing this plan. Please try another image.") from exc
    with _lock:
        _sessions[sess.id] = sess
        while len(_sessions) > MAX_SESSIONS:
            _sessions.popitem(last=False)
    log.info("plan %s processed in %s", sess.id, {k: round(v, 2) for k, v in sess.timings.items()})
    return session_result(sess)


@app.get("/api/plans/{plan_id}")
def get_plan(plan_id: str):
    return session_result(_get(plan_id))


@app.get("/api/plans/{plan_id}/image")
def get_image(plan_id: str):
    return Response(_get(plan_id).png, media_type="image/png",
                    headers={"Cache-Control": "private, max-age=3600"})


class Calibration(BaseModel):
    p1: list[float] = Field(..., min_length=2, max_length=2)
    p2: list[float] = Field(..., min_length=2, max_length=2)
    distance: float = Field(..., gt=0)
    unit: str = "m"


@app.post("/api/plans/{plan_id}/calibration")
def calibrate(plan_id: str, body: Calibration):
    sess = _get(plan_id)
    if body.unit not in UNIT_TO_M:
        raise HTTPException(400, "Unsupported unit.")
    try:
        apply_manual_scale(sess, body.p1, body.p2, body.distance * UNIT_TO_M[body.unit])
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return session_result(sess)


@app.delete("/api/plans/{plan_id}/calibration")
def clear_calibration(plan_id: str):
    sess = _get(plan_id)
    reset_scale(sess)
    return session_result(sess)


class FixRequest(BaseModel):
    key: str


@app.post("/api/plans/{plan_id}/fixes")
def apply_fix(plan_id: str, body: FixRequest):
    sess = _get(plan_id)
    with _lock:
        try:
            report = apply_user_fix(sess, body.key)
        except KeyError as exc:
            raise HTTPException(409, str(exc.args[0])) from exc
    return {**session_result(sess), "last_fix": report}


@app.post("/api/plans/{plan_id}/fixes/undo")
def undo_fix(plan_id: str):
    sess = _get(plan_id)
    with _lock:
        try:
            undo_user_fix(sess)
        except KeyError as exc:
            raise HTTPException(409, str(exc.args[0])) from exc
    return session_result(sess)


@app.post("/api/plans/{plan_id}/evaluate")
async def evaluate(plan_id: str, file: UploadFile = File(...)):
    sess = _get(plan_id)
    try:
        gt = json.loads((await file.read()).decode("utf-8"))
        return evaluate_session(sess, gt)
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(400, f"The annotation file is not valid: {exc}") from exc


@app.get("/api/benchmark")
def benchmark():
    if not BENCHMARK_FILE.exists():
        return JSONResponse({"available": False})
    return {"available": True, **json.loads(BENCHMARK_FILE.read_text())}


# Serve the built frontend when present (single-process demo mode).
_dist = ROOT.parent / "frontend" / "dist"
if _dist.exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = _dist / path
        if path and f.is_file():
            return FileResponse(f)
        return FileResponse(_dist / "index.html")
