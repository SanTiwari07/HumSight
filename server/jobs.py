"""In-process job queue: one job at a time, events replayable by SSE subscribers."""
from __future__ import annotations

import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class Job:
    id: str
    status: str = "queued"            # queued | running | done | error
    events: list[dict] = field(default_factory=list)
    result: dict | None = None
    error: str | None = None
    created: float = field(default_factory=time.time)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def emit(self, ev: dict) -> None:
        with self.lock:
            self.events.append(ev)


class JobManager:
    def __init__(self):
        self.pool = ThreadPoolExecutor(max_workers=1)   # one job at a time keeps the box predictable
        self.jobs: dict[str, Job] = {}

    def submit(self, job_id: str, fn: Callable[[Job], dict]) -> Job:
        job = Job(job_id)
        self.jobs[job_id] = job

        def run():
            job.status = "running"
            try:
                job.result = fn(job)
                job.status = "done"
            except Exception as e:  # surface to the client instead of hanging the SSE stream
                job.error = f"{type(e).__name__}: {e}"
                job.status = "error"
                traceback.print_exc()

        self.pool.submit(run)
        return job

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def add_done(self, job_id: str, result: dict, events: list[dict]) -> Job:
        job = Job(job_id, "done", list(events), result)
        self.jobs[job_id] = job
        return job
