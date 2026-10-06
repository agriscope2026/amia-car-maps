"""Render worker HTTP API (FastAPI). Private: only the Next.js server calls it, with ``WORKER_TOKEN``.

Endpoints
  GET  /health
  GET  /reference/gazetteer
  GET  /templates/{kind}?period_start=YYYY-MM&period_end=YYYY-MM
  POST /preview/{type}            multipart: file (or drought/damage/crops for ENVI) + settings JSON
  POST /reference/{crops|irrigation}
  POST /jobs/{type}               same as preview + version_id → export job (queued, with progress)
  GET  /jobs/{id}                 status, progress, manifest, uploaded object paths
  GET  /jobs/{id}/files/{path}    download an export (local mode)
  POST /droughtcaster/fetch       fetch + build a draft (never publishes)
  GET  /droughtcaster/status
  POST /feeds/rainfall_dekad/fetch  10-day rainfall from the Cordillera weather API → draft payload
  POST /feeds/rainfall_seasonal/fetch  seasonal rainfall read from PAGASA's seasonal forecast page → draft
  GET  /feeds/rainfall_dekad/status
Run:  uvicorn agriclimate.api:app --port 8001
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response

from . import droughtcaster, exports, pagasa_seasonal, rainfall_feed, reference, storage, templates
from .envi import config
from .products import (crop_advice, drought, envi_product, rainfall_dekad, rainfall_seasonal, recommend,
                       reference_layers)

log = logging.getLogger("agriclimate.api")
WORKER_TOKEN = os.environ.get("WORKER_TOKEN", "")
OUTPUT_DIR = config.OUTPUTS
JOBS_DIR = OUTPUT_DIR / "jobs"
MAX_UPLOAD = 20 * 1024 * 1024

PRODUCT_TYPES = {"envi", "rainfall_dekad", "rainfall_seasonal", "drought"}
BUILDERS = {"rainfall_dekad": rainfall_dekad.build, "rainfall_seasonal": rainfall_seasonal.build,
            "drought": drought.build}

app = FastAPI(title="CAR AgriClimate render worker", version="1.0")
_executor = ThreadPoolExecutor(max_workers=1)     # matplotlib is not thread-safe: one render at a time
_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def auth(authorization: str = Header(default="")):
    if not WORKER_TOKEN:
        if os.environ.get("ENV", "development") == "production":
            raise HTTPException(500, "WORKER_TOKEN is not set")
        return
    if not secrets.compare_digest(authorization, f"Bearer {WORKER_TOKEN}"):
        raise HTTPException(401, "Invalid worker token")


async def _read(f: UploadFile | None) -> tuple[bytes, str] | None:
    if f is None:
        return None
    data = await f.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, f"{f.filename} is larger than {MAX_UPLOAD // 2**20} MB")
    return data, f.filename or "upload"


def _settings(raw: str | None) -> dict:
    try:
        return json.loads(raw) if raw else {}
    except ValueError as e:
        raise HTTPException(400, f"settings is not valid JSON: {e}") from e


def build_payload(ptype: str, files: dict, settings: dict) -> dict:
    """Validate inputs and build the payload; fill the recommendation draft and text overrides."""
    if ptype == "envi":
        missing = [k for k in ("drought", "damage", "crops") if k not in files]
        if missing:
            return {"type": ptype, "ok": False, "report": {k: {"errors": [f"Upload the {k} file."], "warnings": []}
                                                           for k in missing}}
        payload = envi_product.build(files, settings)
    else:
        if "file" not in files:
            return {"type": ptype, "ok": False, "report": {"errors": ["Upload a CSV or XLSX file."], "warnings": []}}
        payload = BUILDERS[ptype](*files["file"], settings)
    if payload.get("ok"):
        texts = payload["texts"]
        if ptype != "envi":
            draft = recommend.DRAFTERS[ptype](payload)
            payload["recommendations_draft"] = draft
            if not texts.get("recommendations"):
                texts["recommendations"] = draft
            advice = crop_advice.draft(payload)              # farm recommendations: rice, corn, HVC
            if advice:
                payload["crop_advice_draft"] = advice
                for crop, text in advice.items():
                    texts.setdefault(crop_advice.TEXT_KEYS[crop], text)
        for k, v in (settings.get("texts") or {}).items():
            if v not in (None, ""):
                texts[k] = v
    return payload


@app.get("/health")
def health():
    return {"ok": True, "municipalities": len(reference.gazetteer_table()), "storage": storage.enabled(),
            "qgis": bool(config.find_qgis_python())}


@app.get("/reference/gazetteer", dependencies=[Depends(auth)])
def gazetteer():
    return {"municipalities": reference.gazetteer_records()}


@app.get("/templates/{kind}")
def template(kind: str, period_start: str = "2026-10", period_end: str = "2027-03"):
    try:
        name, data = templates.template(kind, period_start, period_end)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    media = "text/csv" if name.endswith(".csv") else \
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.post("/preview/{ptype}", dependencies=[Depends(auth)])
async def preview(ptype: str, settings: str = Form("{}"), file: UploadFile | None = File(None),
                  drought_file: UploadFile | None = File(None, alias="drought"),
                  damage: UploadFile | None = File(None), crops: UploadFile | None = File(None)):
    if ptype not in PRODUCT_TYPES:
        raise HTTPException(404, f"Unknown product type '{ptype}'")
    files = {k: v for k, v in {"file": await _read(file), "drought": await _read(drought_file),
                               "damage": await _read(damage), "crops": await _read(crops)}.items() if v}
    return build_payload(ptype, files, _settings(settings))


@app.post("/reference/{kind}", dependencies=[Depends(auth)])
async def reference_upload(kind: str, file: UploadFile = File(...), settings: str = Form("{}")):
    data, name = await _read(file)
    if kind == "crops":
        return reference_layers.build_crops(data, name, _settings(settings))
    if kind == "irrigation":
        return reference_layers.build_irrigation(data, name, _settings(settings))
    raise HTTPException(404, f"Unknown reference layer '{kind}'")


# --------------------------------------------------------------------- jobs ---

def _save_job(job: dict) -> None:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    (JOBS_DIR / f"{job['id']}.json").write_text(json.dumps(job, ensure_ascii=False, default=str), encoding="utf-8")


def _get_job(job_id: str) -> dict:
    with _lock:
        if job_id in _jobs:
            return _jobs[job_id]
    p = JOBS_DIR / f"{job_id}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    raise HTTPException(404, "Job not found")


def _apply_texts(payload: dict, settings: dict) -> dict:
    for k, v in (settings.get("texts") or {}).items():
        if v not in (None, ""):
            payload.setdefault("texts", {})[k] = v
    return payload


def _run_job(job: dict, ptype: str, files: dict, settings: dict, given: dict | None = None) -> None:
    def progress(step, state, message=""):
        with _lock:
            job["progress"].append({"step": step, "state": state, "message": message, "at": exports.now_manila()})
            job["status"] = "running"
        _save_job(job)

    try:
        progress("validate", "running", "Validating inputs")
        payload = _apply_texts(given, settings) if given else build_payload(ptype, files, settings)
        if not payload.get("ok"):
            raise ValueError("Validation failed – fix the errors in the upload wizard first.")
        progress("validate", "done", "Inputs valid")
        out = OUTPUT_DIR / "exports" / job["id"]
        manifest = exports.export_product(payload, out, settings, files if ptype == "envi" else None, progress)
        uploaded = {}
        if storage.enabled():
            progress("upload", "running", "Uploading exports to storage")
            uploaded = storage.upload_dir(out, f"{settings.get('version_id') or job['id']}")
            progress("upload", "done", f"{len(uploaded)} files uploaded")
        with _lock:
            job.update(status="done", manifest=manifest, uploaded=uploaded, payload=payload, folder=str(out))
    except Exception as e:  # noqa: BLE001
        log.exception("job %s failed", job["id"])
        with _lock:
            job.update(status="error", error=str(e), trace=traceback.format_exc()[-3000:])
    _save_job(job)


@app.post("/jobs/{ptype}", dependencies=[Depends(auth)])
async def create_job(ptype: str, settings: str = Form("{}"), file: UploadFile | None = File(None),
                     drought_file: UploadFile | None = File(None, alias="drought"),
                     damage: UploadFile | None = File(None), crops: UploadFile | None = File(None),
                     payload: str | None = Form(None)):
    """Export job from uploaded files, or (rainfall/drought) from an already validated draft payload."""
    if ptype not in PRODUCT_TYPES:
        raise HTTPException(404, f"Unknown product type '{ptype}'")
    files = {k: v for k, v in {"file": await _read(file), "drought": await _read(drought_file),
                               "damage": await _read(damage), "crops": await _read(crops)}.items() if v}
    s = _settings(settings)
    given = None
    if payload:
        if ptype == "envi":
            raise HTTPException(400, "ENVI exports need the three input files.")
        given = _settings(payload)
        if given.get("type") != ptype or not given.get("ok") or not given.get("layers"):
            raise HTTPException(400, "payload is not a valid draft of this product type")
    job = {"id": uuid.uuid4().hex, "type": ptype, "status": "queued", "progress": [], "created": exports.now_manila(),
           "version_id": s.get("version_id")}
    with _lock:
        _jobs[job["id"]] = job
    _save_job(job)
    _executor.submit(_run_job, job, ptype, files, s, given)
    return {"id": job["id"], "status": job["status"]}


@app.get("/jobs/{job_id}", dependencies=[Depends(auth)])
def job_status(job_id: str, include_payload: bool = False):
    job = dict(_get_job(job_id))
    if not include_payload:
        job.pop("payload", None)
    job.pop("trace", None)
    return job


@app.get("/jobs/{job_id}/files/{path:path}", dependencies=[Depends(auth)])
def job_file(job_id: str, path: str):
    base = (OUTPUT_DIR / "exports" / job_id).resolve()
    p = (base / path).resolve()
    if base not in p.parents or not p.is_file():
        raise HTTPException(404, "File not found")
    return FileResponse(p, filename=p.name)


@app.post("/droughtcaster/fetch", dependencies=[Depends(auth)])
def droughtcaster_fetch(settings: dict | None = None):
    return droughtcaster.run_once(settings or {})


@app.get("/droughtcaster/status", dependencies=[Depends(auth)])
def droughtcaster_status():
    return {"configured": bool(os.environ.get("DROUGHTCASTER_URL")), **droughtcaster.last_state()}


def _with_drafts(p: dict | None) -> None:
    """Recommendation and farm-advice drafts for a payload built by a feed."""
    if p and p.get("ok"):
        draft = recommend.DRAFTERS[p["type"]](p)
        p["recommendations_draft"] = draft
        p["texts"]["recommendations"] = p["texts"].get("recommendations") or draft
        p["crop_advice_draft"] = crop_advice.draft(p)
        for crop, text in p["crop_advice_draft"].items():
            p["texts"].setdefault(crop_advice.TEXT_KEYS[crop], text)


@app.post("/feeds/rainfall_dekad/fetch", dependencies=[Depends(auth)])
def rainfall_feed_fetch(settings: dict | None = None):
    res = rainfall_feed.run_once(settings or {})
    _with_drafts(res.get("payload"))
    return res


@app.post("/feeds/rainfall_seasonal/fetch", dependencies=[Depends(auth)])
def pagasa_seasonal_fetch(settings: dict | None = None):
    """Seasonal rainfall forecast read from PAGASA's seasonal forecast page (CAR only) → draft payload."""
    res = pagasa_seasonal.run_once(settings or {})
    _with_drafts(res.get("payload"))
    return res


@app.get("/feeds/rainfall_dekad/status", dependencies=[Depends(auth)])
def rainfall_feed_status():
    return {"url": os.environ.get("RAINFALL_FEED_URL") or rainfall_feed.DEFAULT_URL, **rainfall_feed.last_state()}


__all__ = ["app", "build_payload"]
_ = Path
