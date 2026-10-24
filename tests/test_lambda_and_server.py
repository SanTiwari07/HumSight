"""Lambda handler (fake S3) and FastAPI server (TestClient) round trips."""
import io
import json
import os
import shutil
import time

import numpy as np
import pytest


class FakeS3:
    """Directory-backed stand-in for the few boto3 S3 calls the handler uses."""

    def __init__(self, root):
        self.root = root

    def _p(self, key):
        return os.path.join(self.root, *key.split("/"))

    def put(self, key, data: bytes):
        os.makedirs(os.path.dirname(self._p(key)), exist_ok=True)
        open(self._p(key), "wb").write(data)

    def generate_presigned_url(self, op, Params, ExpiresIn):
        return f"https://fake-s3/{op}/{Params['Key']}"

    def head_object(self, Bucket, Key):
        if not os.path.exists(self._p(Key)):
            raise FileNotFoundError(Key)
        return {"ContentLength": os.path.getsize(self._p(Key))}

    def download_file(self, bucket, key, local):
        shutil.copy(self._p(key), local)

    def upload_file(self, local, bucket, key, ExtraArgs=None):
        os.makedirs(os.path.dirname(self._p(key)), exist_ok=True)
        shutil.copy(local, self._p(key))

    def list_objects_v2(self, Bucket, Prefix, Delimiter):
        d = self._p(Prefix.rstrip("/"))
        subs = [f"{Prefix}{n}/" for n in sorted(os.listdir(d)) if os.path.isdir(os.path.join(d, n))]
        return {"CommonPrefixes": [{"Prefix": s} for s in subs]}

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(open(self._p(Key), "rb").read())}


def _event(method, path, body=None, headers=None):
    return {"requestContext": {"http": {"method": method}}, "rawPath": path,
            "headers": headers or {}, "body": json.dumps(body) if body is not None else None}


@pytest.fixture()
def lam(tmp_path, monkeypatch, fault_only):
    from lambda_fn import handler
    s3 = FakeS3(str(tmp_path / "bucket"))
    frames = fault_only[0]
    buf = io.BytesIO()
    np.savez(buf, frames=frames, fps=240.0)
    s3.put("demo/fault_only/clip.npz", buf.getvalue())
    s3.put("demo/fault_only/demo.json", json.dumps({"title": "Fault only", "fps": 240}).encode())
    monkeypatch.setattr(handler, "_s3", lambda: s3)
    monkeypatch.setattr(handler, "BUCKET", "b")
    monkeypatch.setattr(handler, "TOKEN", "")
    monkeypatch.setattr(handler, "_key_loaded", True)
    return handler


def test_lambda_health_and_demos(lam):
    h = json.loads(lam.handler(_event("GET", "/health"))["body"])
    assert h["mode"] == "lambda" and h["cool"] is False
    demos = json.loads(lam.handler(_event("GET", "/demo-clips"))["body"])
    assert demos[0]["id"] == "fault_only"


def test_lambda_job_runs_and_returns_trace_and_urls(lam):
    r = lam.handler(_event("POST", "/jobs", {"demo_id": "fault_only", "policy": "rules"}))
    assert r["statusCode"] == 200, r["body"]
    res = json.loads(r["body"])
    assert res["verdict"] == "FAULT" and abs(res["findings"][0]["f_hz"] - 24.5) < 1.0
    assert [e["tool"] for e in res["trace"] if e["kind"] == "tool"][0] == "probe_clip"
    assert res["urls"]["magnified"].startswith("https://fake-s3/get_object/outputs/")
    assert "work_order_md" in res["urls"]


def test_lambda_upload_url_and_validation(lam):
    r = json.loads(lam.handler(_event("POST", "/upload-url", {"filename": "clip.mp4"}))["body"])
    assert r["key"].startswith("uploads/") and r["put_url"].startswith("https://fake-s3/put_object/")
    assert lam.handler(_event("POST", "/upload-url", {"filename": "evil.exe"}))["statusCode"] == 400
    assert lam.handler(_event("POST", "/jobs", {"key": "uploads/../../etc/passwd"}))["statusCode"] == 400
    assert lam.handler(_event("POST", "/jobs", {"demo_id": "../x"}))["statusCode"] == 400
    assert lam.handler(_event("POST", "/jobs", {}))["statusCode"] == 400


def test_lambda_token_speed_bump(lam, monkeypatch):
    monkeypatch.setattr(lam, "TOKEN", "s3cret")
    assert lam.handler(_event("GET", "/health"))["statusCode"] == 401
    ok = lam.handler(_event("GET", "/health", headers={"X-Demo-Token": "s3cret"}))
    assert ok["statusCode"] == 200


def test_server_job_roundtrip(tmp_path, monkeypatch, fault_only):
    from fastapi.testclient import TestClient
    from server import app as srv

    demo = tmp_path / "demos" / "fault_only"
    demo.mkdir(parents=True)
    np.savez(demo / "clip.npz", frames=fault_only[0], fps=240.0)
    (demo / "demo.json").write_text(json.dumps({"title": "Fault only", "fps": 240.0}))
    monkeypatch.setattr(srv, "DEMO_ROOT", str(tmp_path / "demos"))

    c = TestClient(srv.app)
    h = c.get("/api/health").json()
    assert h["ok"] and h["mode"] == "server" and h["cv2_version"].startswith("5")
    assert c.get("/api/demo-clips").json()[0]["id"] == "fault_only"

    assert c.post("/api/jobs", data={"policy": "rules"}).status_code == 400            # no file / demo
    assert c.post("/api/jobs", files={"file": ("a.mp4", b"x")}).status_code == 400     # no capture_fps
    assert c.post("/api/jobs", files={"file": ("a.exe", b"x")}, data={"capture_fps": "240"}).status_code == 400

    job = c.post("/api/jobs", data={"demo_id": "fault_only", "policy": "rules"}).json()["job_id"]
    events = []
    with c.stream("GET", f"/api/jobs/{job}/events") as s:
        for line in s.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    assert events[-1]["status"] == "done"
    assert [e["tool"] for e in events[:-1]][0] == "probe_clip"
    res = c.get(f"/api/jobs/{job}").json()["result"]
    assert res["verdict"] == "FAULT" and res["urls"]["magnified"].startswith(f"/outputs/{job}/")
    assert c.get(res["urls"]["heatmap"]).status_code == 200
    shutil.rmtree(os.path.join(srv.OUT_ROOT, job), ignore_errors=True)
