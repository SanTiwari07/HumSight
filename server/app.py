"""FastAPI app for local / EC2 use. Run: uvicorn server.app:app --host 0.0.0.0 --port 8000"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sys
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from humsight import config, env
from humsight.agent.loop import job_result, run_agent
from humsight.agent.state import JobParams, JobState
from humsight.agent.trace import Trace, jsonable
from humsight.io import load_video
from humsight.pipeline import run_fixed
from server.jobs import Job, JobManager

env.load_dotenv(os.path.join(ROOT, ".env"))
OUT_ROOT = os.path.join(ROOT, "outputs")
DEMO_ROOT = os.path.join(ROOT, "demo_clips")
UPLOAD_DIR = os.path.join(OUT_ROOT, "_uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

print(env.banner(), flush=True)

app = FastAPI(title="HumSight")
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^(https://[\w-]+\.github\.io|http://(localhost|127\.0\.0\.1)(:\d+)?)$",
    allow_methods=["*"], allow_headers=["*"])
mgr = JobManager()


def _demos() -> list[dict]:
    out = []
    if not os.path.isdir(DEMO_ROOT):
        return out
    for d in sorted(os.listdir(DEMO_ROOT)):
        meta = os.path.join(DEMO_ROOT, d, "demo.json")
        if os.path.exists(meta):
            m = json.load(open(meta, encoding="utf-8"))
            m["id"] = d
            m["has_gt"] = os.path.exists(os.path.join(DEMO_ROOT, d, "gt.json"))
            out.append(m)
    return out


def _demo_clip_path(demo_id: str) -> str:
    if not re.fullmatch(r"[\w\-]+", demo_id):
        raise HTTPException(400, "bad demo id")
    for name in ("clip.npz", "clip.mp4", "clip.webm"):
        p = os.path.join(DEMO_ROOT, demo_id, name)
        if os.path.exists(p):
            return p
    raise HTTPException(404, "demo clip not found")


@app.get("/api/health")
def health():
    return {"ok": True, "mode": "server", **env.cv2_info(), "llm": env.llm_mode()}


@app.get("/api/demo-clips")
def demo_clips():
    return _demos()


def _url_map(job_id: str, outputs: dict) -> dict:
    return {k: f"/outputs/{job_id}/{v}" for k, v in outputs.items() if isinstance(v, str)}


def _run_job(job: Job, path: str, capture_fps: float | None, params: JobParams,
             demo_id: str | None) -> dict:
    out_dir = os.path.join(OUT_ROOT, job.id)
    clip = load_video(path, capture_fps)
    if params.policy == "fixed":
        from humsight.agent.trace import TraceEvent  # noqa: F401
        res = run_fixed(clip, out_dir, workers=params.workers)
        ev = {"step": 1, "kind": "tool", "tool": "fixed_pipeline", "args": {}, "source": "fixed",
              "result": {k: res[k] for k in ("verdict", "findings", "roi", "runtime_ms")},
              "rationale": "Fixed pipeline: one grid, strongest global peak, magnify at alpha=20. No shake check.",
              "t": res["runtime_ms"] / 1000, "runtime_ms": res["runtime_ms"]}
        job.emit(ev)
        result = {"job_id": job.id, "verdict": res["verdict"], "summary": "Fixed pipeline (no agent).",
                  "findings": res["findings"], "capture": {"fps": clip.fps}, "policy": "fixed",
                  "trace": [ev], "n_tool_calls": 1, "runtime_s": res["runtime_ms"] / 1000,
                  "outputs": {k: os.path.basename(v) for k, v in res["outputs"].items()
                              if k in ("magnified", "original")}}
    else:
        state = JobState(clip, params, out_dir, job_id=job.id)
        state.trace = Trace(on_event=job.emit)
        result = run_agent(state)
    result["urls"] = _url_map(job.id, result.get("outputs", {}))
    if demo_id:
        result["demo_id"] = demo_id
        result["urls"]["source"] = f"/demo/{demo_id}/" + os.path.basename(path)
    result["warnings"] = clip.warnings
    return jsonable(result)


@app.post("/api/jobs")
async def create_job(file: UploadFile | None = File(None), demo_id: str | None = Form(None),
                     capture_fps: float | None = Form(None), f_min: float | None = Form(None),
                     f_max: float | None = Form(None), expected_hz: float | None = Form(None),
                     rpm: float | None = Form(None), mm_per_px: float | None = Form(None),
                     policy: str = Form("rules")):
    if policy not in ("llm", "rules", "fixed"):
        raise HTTPException(400, "policy must be llm | rules | fixed")
    job_id = uuid.uuid4().hex[:12]
    demo_meta = None
    if demo_id:
        path = _demo_clip_path(demo_id)
        demo_meta = next((d for d in _demos() if d["id"] == demo_id), {})
        capture_fps = capture_fps or demo_meta.get("fps")
    elif file is not None:
        if capture_fps is None:
            raise HTTPException(400, "capture_fps is required for uploads (slow-motion files report a wrong container fps)")
        ext = os.path.splitext(file.filename or "")[1].lower()
        if ext not in (".mp4", ".mov", ".webm", ".avi", ".mkv", ".npz"):
            raise HTTPException(400, "unsupported file type")
        path = os.path.join(UPLOAD_DIR, job_id + ext)
        size = 0
        with open(path, "wb") as fh:
            while chunk := await file.read(1 << 20):
                size += len(chunk)
                if size > config.MAX_UPLOAD_MB * (1 << 20):
                    fh.close()
                    os.remove(path)
                    raise HTTPException(413, f"upload exceeds {config.MAX_UPLOAD_MB} MB")
                fh.write(chunk)
    else:
        raise HTTPException(400, "give a file or a demo_id")
    params = JobParams(f_min=f_min, f_max=f_max, expected_hz=expected_hz, rpm=rpm,
                       mm_per_px=mm_per_px, policy=policy, workers=max(1, (os.cpu_count() or 2)))
    mgr.submit(job_id, lambda job: _run_job(job, path, capture_fps, params, demo_id))
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = mgr.get(job_id)
    if job is None:
        raise HTTPException(404, "unknown job")
    if job.status == "error":
        return JSONResponse({"status": "error", "error": job.error}, status_code=500)
    return {"status": job.status, "result": job.result}


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str):
    job = mgr.get(job_id)
    if job is None:
        raise HTTPException(404, "unknown job")

    async def gen():
        sent = 0
        while True:
            with job.lock:
                new = job.events[sent:]
            for ev in new:
                yield f"event: trace\ndata: {json.dumps(ev)}\n\n"
            sent += len(new)
            if job.status in ("done", "error") and sent >= len(job.events):
                payload = {"status": job.status, "error": job.error}
                yield f"event: done\ndata: {json.dumps(payload)}\n\n"
                return
            await asyncio.sleep(0.1)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


os.makedirs(OUT_ROOT, exist_ok=True)
app.mount("/outputs", StaticFiles(directory=OUT_ROOT), name="outputs")
if os.path.isdir(DEMO_ROOT):
    app.mount("/demo", StaticFiles(directory=DEMO_ROOT), name="demo")
WEB = os.path.join(ROOT, "web")
if os.path.isdir(WEB):
    app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
