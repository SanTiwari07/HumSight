"""AWS Lambda (arm64, python3.12) entrypoint behind a Function URL.

Routes (payload format 2.0):
    GET  /health        same fields as the server (cool will be false: honest)
    GET  /demo-clips    demos found under s3://BUCKET/demo/<id>/demo.json
    POST /upload-url    {filename, content_type} -> presigned PUT for uploads/<uuid>.<ext>
    POST /jobs          {key | demo_id, capture_fps, ...} -> runs the agent synchronously and
                        returns the verdict, findings, the full trace (replayed by the UI) and
                        presigned URLs for the outputs

CORS is configured on the Function URL itself. Clips are capped at MAX_DURATION_S (4 s).
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from humsight import config, env  # noqa: E402

config.MAX_DURATION_S = float(os.environ.get("MAX_DURATION_S", "4"))
config.MAX_WIDTH = int(os.environ.get("MAX_WIDTH", "960"))
BUCKET = os.environ.get("BUCKET", "")
TOKEN = os.environ.get("DEMO_TOKEN", "")
URL_TTL = 3600
MAX_UPLOAD_BYTES = config.MAX_UPLOAD_MB * (1 << 20)

_s3_client = None
_key_loaded = False


def _s3():
    global _s3_client
    if _s3_client is None:
        import boto3
        _s3_client = boto3.client("s3")
    return _s3_client


def _load_gemini_key() -> None:
    """Read the key once per cold start from SSM Parameter Store (SecureString)."""
    global _key_loaded
    if _key_loaded:
        return
    _key_loaded = True
    name = os.environ.get("GEMINI_PARAM")
    if name and not os.environ.get("GEMINI_API_KEY"):
        try:
            import boto3
            r = boto3.client("ssm").get_parameter(Name=name, WithDecryption=True)
            os.environ["GEMINI_API_KEY"] = r["Parameter"]["Value"]
        except Exception as e:  # LLM is optional: the rules policy still works
            print(f"[HumSight] could not read {name}: {type(e).__name__}", flush=True)


def _resp(code: int, body) -> dict:
    return {"statusCode": code, "headers": {"content-type": "application/json"},
            "body": json.dumps(body)}


def _presign_get(key: str) -> str:
    return _s3().generate_presigned_url("get_object", Params={"Bucket": BUCKET, "Key": key},
                                        ExpiresIn=URL_TTL)


def _exists(key: str) -> bool:
    try:
        _s3().head_object(Bucket=BUCKET, Key=key)
        return True
    except Exception:
        return False


def route_health() -> dict:
    return _resp(200, {"ok": True, "mode": "lambda", **env.cv2_info(), "llm": env.llm_mode(),
                       "max_duration_s": config.MAX_DURATION_S})


def route_demos() -> dict:
    out = []
    r = _s3().list_objects_v2(Bucket=BUCKET, Prefix="demo/", Delimiter="/")
    for p in r.get("CommonPrefixes", []):
        did = p["Prefix"].split("/")[1]
        try:
            m = json.loads(_s3().get_object(Bucket=BUCKET, Key=f"demo/{did}/demo.json")["Body"].read())
            m["id"] = did
            out.append(m)
        except Exception:
            continue
    return _resp(200, out)


def route_upload_url(body: dict) -> dict:
    ext = os.path.splitext(body.get("filename", ""))[1].lower()
    if ext not in (".mp4", ".mov", ".webm", ".avi", ".mkv"):
        return _resp(400, {"error": "unsupported file type"})
    key = f"uploads/{uuid.uuid4().hex}{ext}"
    ctype = body.get("content_type") or "video/mp4"
    url = _s3().generate_presigned_url(
        "put_object", Params={"Bucket": BUCKET, "Key": key, "ContentType": ctype}, ExpiresIn=600)
    return _resp(200, {"put_url": url, "key": key})


def _float(body: dict, k: str):
    v = body.get(k)
    return None if v in (None, "") else float(v)


def route_job(body: dict) -> dict:
    from humsight.agent.loop import run_agent
    from humsight.agent.state import JobParams, JobState
    from humsight.agent.trace import jsonable
    from humsight.io import load_video
    from humsight.pipeline import run_fixed

    _load_gemini_key()
    job_id = uuid.uuid4().hex[:12]
    work = f"/tmp/{job_id}"
    os.makedirs(work, exist_ok=True)
    demo_id, key = body.get("demo_id"), body.get("key")
    if demo_id:
        if not re.fullmatch(r"[\w\-]+", demo_id):
            return _resp(400, {"error": "bad demo id"})
        key = f"demo/{demo_id}/clip.npz"
    elif key:
        if not re.fullmatch(r"uploads/[0-9a-f]{32}\.\w+", key):
            return _resp(400, {"error": "bad key"})
        size = _s3().head_object(Bucket=BUCKET, Key=key)["ContentLength"]
        if size > MAX_UPLOAD_BYTES:
            return _resp(413, {"error": f"upload exceeds {config.MAX_UPLOAD_MB} MB"})
    else:
        return _resp(400, {"error": "give demo_id or key"})
    capture_fps = _float(body, "capture_fps")
    if not demo_id and capture_fps is None:
        return _resp(400, {"error": "capture_fps is required for uploads"})
    local = os.path.join(work, "in" + os.path.splitext(key)[1])
    _s3().download_file(BUCKET, key, local)

    policy = body.get("policy", "rules")
    if policy not in ("llm", "rules", "fixed"):
        return _resp(400, {"error": "bad policy"})
    params = JobParams(f_min=_float(body, "f_min"), f_max=_float(body, "f_max"),
                       expected_hz=_float(body, "expected_hz"), rpm=_float(body, "rpm"),
                       mm_per_px=_float(body, "mm_per_px"), policy=policy,
                       write_original=False, workers=2)
    clip = load_video(local, capture_fps)
    out_dir = os.path.join(work, "out")
    if policy == "fixed":
        res = run_fixed(clip, out_dir, workers=2, write_original=False)
        ev = {"step": 1, "kind": "tool", "tool": "fixed_pipeline", "args": {}, "source": "fixed",
              "result": {k: res[k] for k in ("verdict", "findings", "roi", "runtime_ms")},
              "rationale": "Fixed pipeline: one grid, strongest global peak, magnify at alpha=20. No shake check.",
              "t": res["runtime_ms"] / 1000, "runtime_ms": res["runtime_ms"]}
        result = {"job_id": job_id, "verdict": res["verdict"], "summary": "Fixed pipeline (no agent).",
                  "findings": res["findings"], "capture": {"fps": clip.fps}, "policy": "fixed",
                  "trace": [ev], "n_tool_calls": 1, "runtime_s": res["runtime_ms"] / 1000,
                  "outputs": {k: os.path.basename(v) for k, v in res["outputs"].items()
                              if k in ("magnified", "original")}}
    else:
        state = JobState(clip, params, out_dir, job_id=job_id)
        result = run_agent(state)

    urls = {}
    for name in sorted(os.listdir(out_dir)):
        k = f"outputs/{job_id}/{name}"
        _s3().upload_file(os.path.join(out_dir, name), BUCKET, k)
    for logical, fname in result.get("outputs", {}).items():
        if isinstance(fname, str):
            urls[logical] = _presign_get(f"outputs/{job_id}/{fname}")
    if demo_id and _exists(f"demo/{demo_id}/original.webm"):
        urls["original"] = _presign_get(f"demo/{demo_id}/original.webm")
    elif not demo_id:
        urls["original"] = _presign_get(key)
    result["urls"] = urls
    result["warnings"] = clip.warnings
    result["demo_id"] = demo_id
    return _resp(200, jsonable(result))


def handler(event, context=None):
    http = event.get("requestContext", {}).get("http", {})
    method, path = http.get("method", "GET"), event.get("rawPath", "/")
    if method == "OPTIONS":
        return {"statusCode": 204, "body": ""}
    hdr = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    if TOKEN and hdr.get("x-demo-token") != TOKEN:
        return _resp(401, {"error": "missing or wrong X-Demo-Token"})
    body = {}
    if event.get("body"):
        raw = base64.b64decode(event["body"]) if event.get("isBase64Encoded") else event["body"]
        try:
            body = json.loads(raw)
        except Exception:
            return _resp(400, {"error": "body must be JSON"})
    t0 = time.time()
    try:
        if method == "GET" and path == "/health":
            return route_health()
        if method == "GET" and path == "/demo-clips":
            return route_demos()
        if method == "POST" and path == "/upload-url":
            return route_upload_url(body)
        if method == "POST" and path == "/jobs":
            return route_job(body)
        return _resp(404, {"error": "not found"})
    except Exception as e:
        print(f"[HumSight] {type(e).__name__}: {e} after {time.time() - t0:.1f}s", flush=True)
        return _resp(500, {"error": f"{type(e).__name__}: {e}"})
