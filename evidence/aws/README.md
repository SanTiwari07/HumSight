# AWS deployment evidence (24 Oct 2026)

Proof that the public HumSight endpoint runs on AWS: Lambda (arm64) for the analysis, S3 for clips and outputs, SSM for the Gemini key, CloudWatch for logs. Captured on 2026-10-24 between 09:47 and 09:52 UTC, against the live deployment. The COOL / EC2 Graviton4 evidence is in [../README.md](../README.md).

## What kind of evidence each file is

| Kind | Files | How it was made |
|---|---|---|
| **Real browser screenshots** (pixel captures) | `live_page/*.jpg`, `live_page_real/*.jpg` | Real Chrome (headless, driven by Playwright) opened https://santiwari07.github.io/HumSight/, picked a demo and ran it. The page called the Lambda Function URL and loaded results from S3. In the tab close-ups (`05_*`) the sticky bottom action bar was set to `position: static` so it does not cover the panel; nothing else on the page was changed. |
| **Network log** | `live_page/network_log.json`, `live_page_real/network_log.json` | Every response the page received from an AWS host during that run (method, URL without query string, status). |
| **Rendered terminal evidence** (PNG) | `01_*` to `04_*` | A real AWS CLI or `curl` command was run from the deployer's machine; its real output was recorded (`transcript.json`, `transcript.txt`) and rendered by `scripts/evidence_terminal.py`. Not a pixel capture of a screen; each image says so in its footer. The AWS account id is masked with `sed` in the command itself. |

## Index

| File | Shows |
|---|---|
| `live_page/01_choose_recording.jpg` | the hosted page listing the demo clips (the list comes from Lambda `GET /demo-clips`) |
| `live_page/02_setup.jpg` | setup for `pump_shake_fault`: 240 fps, method *Agent with rules* |
| `live_page/03_analysis_running.jpg` | **"Running on AWS Lambda…"** while the job runs |
| `live_page/03b_activity_log_replay.jpg` | the agent trace returned by Lambda, replayed step by step |
| `live_page/04_diagnosis.jpg` | Alarm: 58.497 Hz, 0.04657 px, SNR 45.81, camera shake at 3.509 Hz removed; done in 26.0 s |
| `live_page/05_*.jpg` | video evidence (magnified video from S3), spectrum, heatmap, findings, activity log, work order |
| `live_page_real/*.jpg` | the same flow on **real footage** (a washing machine filmed handheld at 120 fps, CC BY-SA 4.0): 22.715 Hz, handheld shake at 3.875 Hz removed |
| `01_lambda_deployment/` | `humsight` function: arm64, python3.12, 3008 MB, 120 s, Active; its Function URL and CORS origin; the arm64 layer; the SSM SecureString parameter (name and type only) |
| `02_s3_bucket/` | the demo clips in `s3://humsight-f308f2bbf0/demo/` and the bucket totals |
| `03_lambda_health/` | `GET /health` on the Function URL: `cv2_version 5.0.0`, `machine aarch64`, `mode lambda` |
| `04_cloudwatch_invocations/` | Lambda `REPORT` lines from CloudWatch Logs: the three page runs above are the 22.9 s, 22.5 s and 41.3 s invocations (labelled `/jobs` by duration in the command) |
