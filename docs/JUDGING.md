# For judges: how to test HumSight

Everything below works on a laptop with Python 3.12 or newer. The public endpoint and the COOL live session are listed at the end with their current status.

## 1. Run it locally (about 5 minutes)

```bash
git clone https://github.com/SanTiwari07/HumSight && cd HumSight
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt                          # pinned
python -m pytest                                         # 31 tests, about 2 minutes
python scripts/make_demo_clips.py                        # six deterministic synthetic clips (~50 MB each)
uvicorn server.app:app --port 8000                       # open http://localhost:8000
```

The page walks through four steps: **Recording** (pick a demo), **Setup** (keep **Agent · rules**), **Analysis** (the activity log streams live) and **Diagnosis**, which opens on its own when the job ends. The diagnosis shows FAULT as *Alarm*, NO_FAULT as *Normal* and REVIEW as *Inconclusive*.

| Demo clip | Truth | Expected result |
|---|---|---|
| `pump_shake_fault` | 58.5 Hz, 0.05 px fault; 3.5 Hz, 0.6 px camera shake | **FAULT** near 58.5 Hz; shake compensated and rejected |
| `fan_fault_only` | 24.5 Hz, 0.10 px, steady camera | **FAULT** near 24.5 Hz, no shake step |
| `shake_only` | camera shake only | **NO_FAULT** |
| `quiet` | nothing | **NO_FAULT** |
| `alias_130hz` | 130 Hz at 240 fps, expected Hz given | **REVIEW** (aliasing), two tool calls |
| `codec_damaged` | the pump scene after an mp4v round trip | a **wrong** result (spurious low-frequency fault): a documented failure case |

In Setup, switch the method to **Fixed pipeline** on `pump_shake_fault`: it magnifies the 3.5 Hz camera shake and misses the fault. The diagnosis then offers **Re-run with the agent** for a side-by-side check. That contrast is evaluation E5.

Gemini is optional (`GEMINI_API_KEY` in a git-ignored `.env`); without it the rules policy runs the same tools. Uploading your own clip requires the **capture fps** (slow-motion files report the wrong container fps).

## 2. Regenerate the evidence

```bash
python eval/run_all.py            # E1-E6 tables and plots, about 18 minutes on 12 cores; --quick for a smoke run
python eval/failure_cases.py      # failure cases with images
python scripts/export_trace.py    # agent traces -> docs/example_trace.md
python scripts/embed_results.py   # copy generated results into README and the report
```

## 3. Where the award evidence is

| Requirement | Where |
|---|---|
| Technical report | [TECHNICAL_REPORT.md](TECHNICAL_REPORT.md) |
| Architecture diagram (OpenCV 5, AWS, COOL, agent) | [architecture.svg](architecture.svg) |
| Agent workflow diagram | [agent_workflow.svg](agent_workflow.svg) |
| Trace where OpenCV output changes a later call | [example_trace.md](example_trace.md) (and the live trace in the page) |
| Agent task success, failure handling, human control | report §4 and §8; evaluation E5 (agent vs fixed), E6 (aliasing guard), the `REVIEW` path |
| Evaluation and failure cases | `eval/results/summary.md`, `eval/results/failure_cases.md` |
| COOL version, instance, method, results | [COOL.md](COOL.md), `bench/` |
| Pinned dependencies, build, deploy, test | `requirements*.txt`, [DEPLOYMENT.md](DEPLOYMENT.md), section 1 above |

## 4. Public endpoint and live session (status)

- **Public page:** https://santiwari07.github.io/HumSight/ (static page on GitHub Pages; it calls the Lambda endpoint below).
- **Public endpoint:** AWS Lambda Function URL `https://ce75ttmqcc5g3il7yefnupx6ee0qydmz.lambda-url.us-east-1.on.aws/` (arm64, OpenCV 5.0.0). Requests need the `X-Demo-Token` header; the page sends it. Clips are capped at 4 s; the demo clips are on S3. `GET /health` shows `cool: false` because this is the stock OpenCV wheel (COOL is the separate Graviton4 benchmark).
- **Live COOL screen-share:** available on request once the Graviton4 instance has been run; the instance is started only for the session.
- **Demo video:** pending, to be recorded after deployment.
