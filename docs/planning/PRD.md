# HumSight — Product Requirements Document

*"See what machines are humming."*

**Event:** OpenCV AI Competition 2026 (powered by AWS)
**Deadline:** Mon 26 Oct 2026, 11:45 pm PDT = **Tue 27 Oct 2026, 12:15 pm IST**
**Team:** 1 student, software only
**Build window:** ~2 days
**AWS budget target:** ₹0 out of pocket (free-tier credits only)
**Status:** v1.0, 24 Oct 2026

---

## 1. One-liner

HumSight turns an ordinary video of a machine into a grid of "virtual vibration sensors." It does three things:

- **Measure:** OpenCV 5 measures sub-pixel motion with phase correlation and finds the vibration frequency with an FFT.
- **Decide:** an agent separates real machine faults from camera shake and noise, and picks the frequency band to amplify.
- **Show:** a motion-magnified video lets an engineer *see* the fault.

The heavy vision work runs on **COOL (Cloud-Optimized OpenCV) on AWS Graviton4**.

## 2. Problem

- Machines (pumps, motors, fans, pipes) vibrate abnormally before they fail.
- The usual tools are contact accelerometers on every machine or proprietary motion-amplification camera systems. Both are expensive and slow to deploy across a whole plant.
- Small vibrations are invisible to the eye and to standard object detectors.
- Naively magnifying *all* motion in a video also amplifies camera shake and compression noise. The result is unusable.

> Price figures for accelerometers and commercial camera systems must be sourced before they appear in the report. Do not quote unsourced numbers.

## 3. Target user

- **Primary:** reliability or maintenance engineer at a small or mid-size plant who wants a quick, non-contact vibration check from a phone or a fixed camera.
- **Secondary:** engineering students and labs teaching vibration analysis.

## 4. Goals and non-goals

### Goals (must ship)

1. Recover vibration **frequency** and **sub-pixel amplitude** per region from video, validated on synthetic ground truth.
2. Reject global camera shake, and localise the vibrating region.
3. Produce a **band-limited motion-magnified video** of the faulty region only.
4. Run an **agent loop** in which OpenCV measurements change the agent's next tool call.
5. Run the core vision workload on **COOL on Graviton4**, with a measured **COOL vs stock OpenCV** benchmark.
6. Show results in a simple web UI: original vs magnified video, spectrum chart, agent trace, report.
7. Publish an evaluation with numbers **and failure cases**.

### Non-goals

- Certified ISO 20816 assessment. Zones are shown as **indicative only**.
- Real-time streaming or live cameras. The input is uploaded clips.
- Building hardware or test rigs.
- Training any deep model.
- Multi-user accounts or authentication beyond basic rate-limiting.

## 5. Core user journey

1. User opens the web page and picks a demo clip, or uploads one: MP4, ≤ 10 s, ≤ 1080p, known fps.
2. Optional inputs:
   - expected machine speed (RPM), or a frequency range to search;
   - a scale reference (a known length in the frame, in mm) so velocity can be shown in mm/s.
3. User clicks **Analyze**.
4. The page streams the agent trace live:
   stabilise → patch grid → spectrum → "background peak at X Hz = camera shake, rejected" → "patch (r, c) peak at Y Hz, SNR Z" → band chosen → magnify.
5. Results:
   - original and magnified videos side by side;
   - heatmap of vibration amplitude per patch;
   - spectrum chart;
   - severity (indicative);
   - downloadable JSON/Markdown work order.
6. If evidence is ambiguous (low SNR, possible aliasing), the result is **REVIEW**, with a reason and a suggested fix (for example "record at 240 fps").

## 6. Functional requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| F1 | Synthetic video generator. Inputs: frequency, amplitude (px), region, fps, duration, noise, camera shake, JPEG/H.264 compression. Writes a ground-truth JSON alongside each video. | P0 |
| F2 | Stabilisation: feature tracking on background, then homography (USAC/MAGSAC) and warp. Reports the residual. | P0 |
| F3 | Patch grid: N×M patches. Optionally use contours (`findContours`, which uses TRUCO in OpenCV 5) to keep only textured, structural patches. | P0 |
| F4 | Per-patch sub-pixel shift per frame with `cv2.phaseCorrelate` (Hanning window). Use the iterative variant if it is exposed in the Python build. **Verify with `hasattr` first.** | P0 |
| F5 | Spectrum per patch (Welch/FFT): peak frequency, amplitude, SNR. Global (background) spectrum computed separately. | P0 |
| F6 | **Aliasing guard:** if the expected fault frequency exceeds fps/2, flag it and return REVIEW. | P0 |
| F7 | Band-pass motion magnification on the selected band only: Laplacian pyramid plus temporal band-pass, with α chosen by the agent. Restricted to the ROI. | P0 |
| F8 | Agent with typed tools (§8), a hard step cap, and a rule-based fallback if Bedrock is unavailable. | P0 |
| F9 | Severity: displacement → velocity (mm/s RMS) using the scale reference. Mapped to indicative zones, labelled "not certified." | P1 |
| F10 | Web UI: upload, live trace, side-by-side videos, heatmap, spectrum, report download. | P0 |
| F11 | Benchmark script: same pipeline on the COOL venv vs stock `opencv-python` on the same instance. Reports per-stage timings over repeated runs. | P0 |
| F12 | Evaluation scripts producing all tables in §11 from one command. | P0 |
| F13 | Real-clip demo: at least one public clip (licence checked) or one phone slow-mo clip (for example a fan with a coin taped to a blade). | P1 |

## 7. Pipeline (all numbers come from OpenCV and NumPy, never from the LLM)

```
video ─► decode (cv2.VideoCapture)
      ─► stabilise   [ORB/GFTT + LK flow on background → findHomography(USAC_MAGSAC) → warpPerspective]
      ─► patch grid  [optional findContours mask; keep textured patches]
      ─► shifts      [phaseCorrelate per patch per frame → dx(t), dy(t)]
      ─► spectra     [detrend → window → FFT/Welch → peak f, amplitude, SNR per patch + background]
      ─► AGENT decides  (reject shake / pick band / ask for review)
      ─► magnify     [buildPyramid/pyrDown/pyrUp + temporal band-pass on band, α, ROI]
      ─► report      [heatmap, spectrum PNG/JSON, magnified MP4, work order]
```

## 8. Agent design

**Framework:** Strands Agents SDK. **Model:** a low-cost Amazon Bedrock model (for example Amazon Nova Lite or Micro). **Cap:** ≤ 10 tool calls per job. **Outputs:** JSON-typed.

| Tool | Input | Output (measured) |
|------|-------|-------------------|
| `analyze_motion` | clip id, grid size, freq range | per-patch peaks (f, amp_px, SNR), background spectrum, stabilisation residual |
| `check_global_motion` | clip id | dominant background frequencies and amplitude |
| `restabilise` | clip id, method (`homography` or `affine`), stronger features | new residual |
| `isolate_peak` | patch ids, f | refined f, bandwidth, SNR, neighbouring patches with the same peak |
| `magnify` | band [f1, f2], α, ROI | output video path, noise metric |
| `assess_severity` | amp_px, f, mm_per_px | velocity mm/s RMS, indicative zone |
| `request_review` | reason, suggestion | REVIEW state |
| `file_report` | findings | work order JSON/MD |

**Decisions the agent makes from measurements (each logged in the trace):**

- A background peak that matches a patch peak means camera shake. The agent restabilises or excludes that frequency.
- SNR below threshold means no confident fault. The agent files REVIEW, or a PASS with evidence shown.
- If the expected frequency is above fps/2, the agent files REVIEW with "aliasing: record at ≥ 2.5× fault frequency."
- If magnification noise is too high, the agent reduces α and narrows the band.

**Guardrails:**

- The model cannot change numbers.
- Tool arguments are schema-validated.
- If Bedrock fails, a deterministic rule policy runs the same tool types, and the trace flags it.

## 9. Tech stack

| Layer | Choice | Cost |
|-------|--------|------|
| Language | Python 3.12 | free |
| Vision | OpenCV 5 (`opencv-python==5.0.0.93` locally; COOL venv `/opt/cool/venvs/python_3.12` on AWS), NumPy, SciPy (`signal.welch`, filters) | free |
| Video I/O | OpenCV + ffmpeg (H.264 output for browsers) | free |
| Backend | FastAPI + Uvicorn; Server-Sent Events for the trace | free |
| Frontend | One static HTML page + vanilla JS + Chart.js (spectrum) | free |
| Agent | Strands Agents SDK + Amazon Bedrock (cheap model) + rule fallback | cents, from credits |
| Compute | EC2 **c8g.large** (Graviton4) from the **COOL Graviton4 AMI** (7-day free trial of the software fee) | from credits |
| Storage | S3 bucket (results, videos), lifecycle delete after 30 days | cents, from credits |
| Logs | CloudWatch Logs (basic) | from credits |
| Repo | Public GitHub, pinned `requirements.txt`, MIT licence | free |

## 10. ₹0 AWS plan

1. **Do everything locally first.** The pipeline, generator, agent (rule fallback) and UI are all built and tested on the laptop with stock OpenCV 5. AWS time is used only for the COOL runs, the benchmark and the demo.
2. **New AWS account → free-tier credits.** New accounts get $100 at sign-up and can earn up to $100 more by completing activities that include EC2 and Bedrock.
   - The Free plan limits some services and Marketplace products. If the COOL AMI or c8g is blocked, upgrading to the Paid plan is a one-click change.
   - **Unverified:** whether credits carry over after the upgrade, and whether Indian (AISPL) accounts get the same credits. Check in the console before launching.
3. **Set guards before launching anything:**
   - AWS Budgets **zero-spend budget**, plus an alert at $1;
   - billing alerts to email.
4. **Smallest instance:** c8g.large, us-east-1, on-demand. **Stop it whenever you are not using it.**
   - Expect roughly 10–15 instance-hours in total for setup, benchmark and recording.
   - Check the hourly price in the console. Region prices differ.
5. **Avoid silent charges:**
   - no Elastic IP left allocated;
   - delete unused EBS snapshots;
   - an 8–20 GB gp3 root volume;
   - no NAT gateway, load balancer or ECS.
6. **Bedrock:** cheapest model, short prompts, ≤ 10 calls per job. The rule fallback keeps the demo working at zero cost if needed.
7. **Judging period:**
   - keep the instance **stopped**;
   - host a static results page (S3 or GitHub Pages) with the precomputed demo outputs and the recorded video;
   - offer an **arranged live screen-share** (the rules allow an endpoint *or* an arranged live screen-share), starting the instance only for that session.
8. **Cleanup after judging:** terminate the instance, cancel the AMI subscription, empty and delete the bucket.

## 11. Evaluation plan (set before building; report only measured values)

| Test | Method | Metric | Pass criterion |
|------|--------|--------|----------------|
| E1 Frequency accuracy | Synthetic grid: f ∈ {5…100 Hz}, fps ∈ {60, 120, 240}, amp ∈ {0.01…1 px}, noise and compression levels | abs and % frequency error | Table generated by script |
| E2 Amplitude accuracy | Same grid | amp error (px) vs ground truth | Table + plot |
| E3 Detection floor | Lower amplitude until SNR < threshold, per noise/compression level | minimum detectable amplitude (px) | Reported honestly, whatever it is |
| E4 Localisation | Vibration injected in 1 of N regions | top-1 patch hit rate | Script output |
| E5 Agent vs fixed pipeline | Clips with injected camera shake + fault | fault found (Y/N), shake wrongly magnified (Y/N) | At least one documented case where the agent's decision changes the outcome |
| E6 Aliasing guard | Fault frequency > fps/2 | REVIEW triggered | 100% of such cases flagged |
| E7 COOL benchmark | Same clip, COOL venv vs stock `opencv-python`, same c8g, ≥ 5 runs | per-stage ms, total, $/1,000 clips | Median and spread reported, whichever wins |
| E8 Real clip | Public clip or phone 240 fps fan + coin | qualitative + frequency vs expected (RPM or phone accelerometer app) | Shown with caveats |
| Failure cases | Low texture, heavy compression, aliasing, large motion | — | ≥ 3 documented with examples |

## 12. Demo script (≤ 5 min video)

1. **0:00–0:20** Problem in one line, on face-cam.
2. **0:20–0:45** Architecture slide (three boxes: OpenCV on COOL → agent → UI).
3. **0:45–2:00** Synthetic clip with camera shake plus a hidden fault. The trace shows the shake rejected and the fault peak found. Magnified video shows only the faulty region moving. Then show the fixed-pipeline result, where everything wobbles.
4. **2:00–2:45** Real clip (fan with coin): spectrum peak vs expected frequency.
5. **2:45–3:30** Evaluation tables, E1–E6, plus the failure cases.
6. **3:30–4:15** COOL vs stock benchmark, with proof that COOL ran: library path and build info printed at startup.
7. **4:15–4:45** Limits (indicative severity, fps requirement) and what's next.

## 13. Build plan (~2 days)

### Day 1 (Sat): core + proof

| Slot | Task |
|------|------|
| 2 h | Repo skeleton, pinned deps, synthetic generator (F1) |
| 3 h | Stabilise + patch grid + phaseCorrelate + spectra (F2–F5). **Check: recovers the injected frequency.** |
| 2 h | Magnification (F7) on the selected band |
| 1 h | AWS account, budgets, COOL AMI subscribe, launch c8g.large, run the pipeline in the COOL venv, then **stop the instance** |
| 2 h | Eval scripts E1–E4, E6 (F12) |

### Day 2 (Sun): agent + UI + AWS + submission

| Slot | Task |
|------|------|
| 3 h | Agent tools + Strands/Bedrock + rule fallback (F8); E5 |
| 3 h | FastAPI + SSE + single-page UI (F10) |
| 2 h | COOL benchmark E7 on c8g (F11); S3 results page |
| 1 h | Real clip E8 |
| 3 h | README / technical report, architecture diagram, record ≤ 5 min video, submit on Devpost |

**Mon / Tue morning:** buffer only. Submit by Mon night IST at the latest.

### Cut list if behind (drop in this order)

1. Contour-based patch masking (F3 optional)
2. Severity in mm/s (F9)
3. Real clip (F13)
4. Bedrock: ship rule-based agent only. This **weakens the Agentic award**, so keep it if at all possible.

## 14. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| Sub-pixel motion swamped by compression/noise on real clips | High | Medium | Report the measured detection floor; use synthetic as the main evidence |
| COOL AMI or c8g blocked on Free plan | Medium | High (COOL award) | Upgrade to Paid plan with budgets set; fallback: stock OpenCV on Graviton, drop COOL award |
| Bedrock model access delayed | Medium | Medium | Request access first thing; rule fallback |
| COOL shows no speedup on this workload | Medium | Low–medium | Report honestly; the COOL rubric rewards measured value, not a positive result |
| Iterative phase correlation not exposed in Python | Medium | Low | Use standard `phaseCorrelate` + windowing |
| Judges ask "why an agent?" | High | Medium | E5: show cases where the measurement-driven decision changes the result vs a fixed pipeline |

## 15. Honesty rules for the submission

- Every number in the README, video and slides comes from a script in the repo.
- No invented speedups, accuracies or market figures. A number that isn't measured gets deleted.
- Synthetic results are labelled synthetic. Real-clip results are labelled with their limits.
- ISO 20816 mapping is described as indicative, not a certified assessment.
- Third-party clips are used only if their licence allows it, and they are credited.

## 16. Acceptance criteria

- [ ] `python eval/run_all.py` regenerates every table and plot.
- [ ] At least one trace in which a measurement changes the agent's next tool call.
- [ ] COOL run proven by printed library path and build info, plus benchmark table.
- [ ] Demo works from the static results page **and** live on the instance.
- [ ] README has setup, architecture diagram, evaluation, failure cases, and cost notes.
- [ ] Video ≤ 5 min, submitted before Tue 27 Oct 12:15 pm IST.
