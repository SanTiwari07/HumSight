# COOL run evidence (24 Oct 2026)

Captured during the COOL benchmark session on one Spot `c8g.large` (Graviton4) in us-east-1d. The instance is terminated. For the video, use these files as on-screen evidence.

## What kind of evidence each file is

| Kind | Files | How it was made |
|---|---|---|
| **Rendered terminal evidence** (PNG and MP4) | `01_*` to `05_*` | A real `ssh` command was run against the instance; every character of its output and its real arrival times were recorded (`transcript.json`, `transcript.txt`) and re-rendered by `scripts/evidence_terminal.py`. Idle gaps over 1.5 s are shortened. **It is not a pixel capture of a screen**, and each image says so in its footer. |
| **Real browser screenshots** | `ui/*.jpg` | Genuine screenshots of the HumSight page served by the COOL instance (`http://<instance>:8000`), taken in the browser pane while a real analysis ran there. |
| **Walkthrough video** | `ui/ui_walkthrough_screenshots.mp4` | The nine screenshots above joined in order, 3 s each. It is a slideshow, not a screen recording. |

A true screen recording of your own screen can only be made by you (for example Win+Alt+R or OBS). The exact commands to repeat on a live instance are at the bottom.

## Index

| File | Shows |
|---|---|
| `01_cool_verify/` | `verify_cool.py` in the COOL venv: `cv2 5.1.0-dev` loaded from `/opt/cool/...`, `COOL path: True`, KleidiCV 0.7.0, SVE and NEON baseline |
| `02_stock_verify/` | the same script in the stock venv on the **same instance**: `cv2 5.0.0` from `site-packages`, `COOL path: False`, KleidiCV 26.03 |
| `03_instance_facts/` | EC2 metadata: `c8g.large`, instance id, AMI id, `us-east-1d`, lifecycle `spot`, Neoverse-V2, 2 vCPUs, Ubuntu 24.04.3 |
| `04_server_banner/` | the HumSight server started inside the COOL venv prints `COOL=True | KleidiCV=True | aarch64`; `/api/health` agrees |
| `05_benchmark_results/` | the head of `bench/RESULTS.md` as generated on the instance |
| `ui/10..14` | choose recording, setup, analysis running (live), analysis complete ("Alarm after 7 measurements", 9.2 s) |
| `ui/15..18` | diagnosis (Alarm at 58.497 Hz, shake rejected), video evidence, spectrum, heatmap |
| `ui/19_api_health_cool_true.jpg` | the server's `/api/health` in the browser: `cv2_version 5.1.0-dev`, `/opt/cool/...`, `"cool": true`, `"kleidicv": true` |

Each `0N_*` folder holds `screenshot.png`, `recording.mp4`, `transcript.json` and `transcript.txt`.

## Honest notes (say these in the video)

- COOL did run the whole pipeline: the analysis in `ui/` was executed by the COOL build.
- **The benchmark found no meaningful speed-up** for this workload (totals 0.98x to 1.03x; see `bench/RESULTS.md`). `resize` was faster (1.42x), `cvtColor` slower (0.83x).
- COOL here is `5.1.0-dev` and the stock baseline is `5.0.0`; the stock aarch64 wheel also ships KleidiCV.
- The page no longer shows an OpenCV/COOL badge, so `ui/19` and `04_server_banner` are what show which build served the page.

## Repeat it live (for your own screen recording)

Needs a new Spot instance from the COOL AMI; see `docs/DEPLOYMENT.md` section 6 and `docs/COOL.md`. On the instance:

```bash
source /opt/cool/venvs/python_3.12/bin/activate && cd ~/humsight && python scripts/verify_cool.py
~/stock/bin/python scripts/verify_cool.py
PYTHONPATH=$HOME/cool_extra:$PYTHONPATH python -m uvicorn server.app:app --host 0.0.0.0 --port 8000
```
