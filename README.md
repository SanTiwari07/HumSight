<div align="center">

# 〰 HumSight

### See what machines are humming.

**Turn a slow-motion phone video into a grid of virtual vibration sensors.**<br>
OpenCV 5 measures motion a twentieth of a pixel small, an agent decides whether it is a real machine fault or just a shaky hand, and AWS Lambda serves it to anyone with a browser.

[![OpenCV 5](https://img.shields.io/badge/OpenCV-5.0-5C3EE8?logo=opencv&logoColor=white)](https://opencv.org/)
[![AWS Lambda arm64](https://img.shields.io/badge/AWS_Lambda-arm64-FF9900?logo=awslambda&logoColor=white)](evidence/aws/README.md)
[![COOL on Graviton4](https://img.shields.io/badge/COOL-Graviton4-232F3E?logo=amazonwebservices&logoColor=white)](docs/COOL.md)
[![Agentic Vision](https://img.shields.io/badge/Agentic_Vision-Gemini_%2B_rules-4285F4?logo=googlegemini&logoColor=white)](docs/example_trace.md)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](requirements.txt)
[![License MIT](https://img.shields.io/badge/License-MIT-green)](LICENSE)

**[▶ Live demo](https://santiwari07.github.io/HumSight/)** · **[Technical report](docs/TECHNICAL_REPORT.md)** · **[AWS proof](#-proof-it-runs-on-aws)** · **[Judging guide](docs/JUDGING.md)** · **[Evaluation](eval/results/summary.md)**

<sub>Built for the <a href="https://opencv26.devpost.com/">OpenCV AI Competition 2026, powered by AWS</a>, on both featured paths: <b>Agentic Vision with OpenCV 5</b> and <b>Best Use of COOL</b>.</sub>

<br>

<img src="evidence/aws/live_page/04_diagnosis.jpg" alt="HumSight diagnosis on the live AWS deployment: Alarm, localized vibration at 58.5 Hz, camera shake removed" width="900">

<sub>A real run on the public site, served by AWS Lambda (24 Oct 2026), on the synthetic pump demo: a 0.047-pixel fault at 58.5 Hz found under 0.55 px of simulated handheld camera shake.</sub>

</div>

---

## Contents

- [The story](#-the-story)
- [Why it matters](#-why-it-matters)
- [See it work](#-see-it-work-live-on-aws)
- [What makes HumSight different](#-what-makes-humsight-different)
- [How it works](#-how-it-works)
- [Proof it runs on AWS](#-proof-it-runs-on-aws)
- [Competition coverage](#-how-humsight-covers-the-competition)
- [Results](#-results)
- [Tech stack](#-tech-stack)
- [Limitations and responsible use](#-limitations-and-responsible-use)
- [Future scope](#-future-scope)
- [Run it yourself](#-run-it-yourself)
- [Repository layout](#-repository-layout)

---

## 📖 The story

> *It is the night shift at a water-treatment plant. A maintenance technician walks the pump hall. Pump 7 sounds a little different tonight, but it looks exactly like it always does: perfectly still.*
>
> *Pump 7 has no vibration sensor. Wired sensors are fitted to the few most critical machines, and Pump 7 is not one of them. Calling in a vibration specialist means a ticket and a wait.*
>
> *So the technician takes out a phone, switches to slow motion (240 fps), and films the pump for three seconds. The phone is handheld. Their arm sways a little, about half a pixel at 3.5 times a second.*
>
> *They open HumSight in the browser and upload the clip. About thirty seconds later:*
>
> **Alarm: localized vibration at 58.5 Hz on the bearing cap, 0.047 px. Camera shake at 3.5 Hz was measured, removed and rejected.**
>
> *Next to the original video, HumSight plays a slowed, magnified copy in which only the bearing cap visibly shakes. A heatmap shows which part of the pump moved. A work order is ready to attach to the maintenance ticket, with the recommended next step: confirm with a contact accelerometer at the next planned stop.*
>
> *On the next pump, the result is different: **Inconclusive.** The pump turns faster than the camera can sample, so the frequency could be aliased. HumSight does not guess. It asks for a recording at a higher frame rate.*

That is HumSight: **a vibration check from any camera, which separates a real fault from a shaky hand and says when it cannot tell.**

The pump scene is the `pump_shake_fault` demo, a synthetic clip with exact ground truth (a 58.5 Hz, 0.05 px fault under 3.5 Hz, 0.6 px shake). Every number in the story is what the live AWS deployment returned for it. The second pump is the `alias_130hz` demo. A run on real footage is [below](#on-real-footage).

---

## 💡 Why it matters

**The problem.** Pumps, motors, fans and pipes vibrate abnormally before they fail. Contact sensors measure this well, but they have to be fitted machine by machine, so many machines are never monitored. To the eye, a video of a vibrating machine looks still. The textbook trick, magnifying all motion in the video ([Eulerian Video Magnification](https://people.csail.mit.edu/mrub/evm/)), also magnifies camera shake and compression noise, so a handheld clip makes a healthy machine look broken.

**Who it is for.**

| User | What HumSight gives them |
|---|---|
| Maintenance and reliability technicians | A quick non-contact check of an unmonitored machine with the phone they already carry, and a work order for the ticket |
| Plant and facility managers | A first screen of which machines need a proper sensor or a specialist visit |
| Field-service engineers | Visual evidence (magnified video, spectrum, heatmap) to show a customer which part is moving |
| Students and teaching labs | A hands-on way to see frequency, amplitude, Nyquist and aliasing on real video |

**What it changes.** Each camera patch becomes a virtual vibration sensor. One phone video gives frequency, amplitude, signal-to-noise and location for every patch at once, with no wiring and nothing touching the machine. The answer is *indicative*, not a certified ISO measurement, and HumSight says so on every report.

---

## 🎬 See it work (live on AWS)

All screenshots below are real browser captures of the public site [santiwari07.github.io/HumSight](https://santiwari07.github.io/HumSight/), whose analysis runs on **AWS Lambda (arm64)**, taken on 24 Oct 2026. How they were made: [evidence/aws/](evidence/aws/README.md).

<table>
<tr>
<td width="50%" valign="top"><b>1 · Choose a recording</b><br><img src="evidence/aws/live_page/01_choose_recording.jpg" alt="Step 1: choose a demo recording or upload a clip"></td>
<td width="50%" valign="top"><b>2 · Set up the capture</b><br><img src="evidence/aws/live_page/02_setup.jpg" alt="Step 2: capture fps, expected frequency and method"></td>
</tr>
<tr>
<td valign="top"><b>3 · Analysis running on AWS Lambda</b><br><img src="evidence/aws/live_page/03_analysis_running.jpg" alt="Step 3: Running on AWS Lambda"></td>
<td valign="top"><b>4 · Diagnosis</b><br><img src="evidence/aws/live_page/04_diagnosis.jpg" alt="Step 4: Alarm diagnosis with key readings"></td>
</tr>
<tr>
<td valign="top"><b>Magnified video: only the faulty region moves</b><br><img src="evidence/aws/live_page/05_video.jpg" alt="Original next to magnified fault region"></td>
<td valign="top"><b>Spectrum: shake at 3.5 Hz (orange) vs fault at 58.5 Hz (blue)</b><br><img src="evidence/aws/live_page/05_spectrum.jpg" alt="Spectrum with the shake peak and the fault band"></td>
</tr>
<tr>
<td valign="top"><b>Heatmap: every cell is a virtual sensor</b><br><img src="evidence/aws/live_page/05_heat.jpg" alt="Heatmap of vibration amplitude per patch"></td>
<td valign="top"><b>Activity log: what the agent measured and why it acted</b><br><img src="evidence/aws/live_page/05_log.jpg" alt="Agent activity log with seven tool calls"></td>
</tr>
</table>

### On real footage

The same flow on a real video: a washing machine filmed **handheld** on a phone at 120 fps ([source](https://commons.wikimedia.org/wiki/File:Washing_machine_120fps.webm), CC BY-SA 4.0). HumSight removed the 3.9 Hz hand shake and found a localized 22.7 Hz vibration at the drum. The machine's display reads 1400 RPM, which is 23.3 Hz. That is a set speed, not a measured reference, so this result is indicative, not a validated accuracy figure.

<table>
<tr>
<td width="50%" valign="top"><img src="evidence/aws/live_page_real/04_diagnosis.jpg" alt="Real washing machine diagnosis: 22.7 Hz, shake removed"></td>
<td width="50%" valign="top"><img src="evidence/aws/live_page_real/05_video.jpg" alt="Real washing machine original and magnified"></td>
</tr>
</table>

---

## ✨ What makes HumSight different

**1. It separates camera shake from a real fault, and proves it.** A fixed "magnify everything" pipeline gets the handheld clips wrong. On the 12 clips of evaluation E5, the fixed pipeline was right on **5 of 12** and magnified camera shake as a "fault" **6 times**. HumSight's agent was right on **12 of 12** with zero shake mistakes.

**2. The vision output drives the decisions.** This is not a chatbot that explains a fixed result. The agent reads each OpenCV measurement and picks the next tool. In the trace on the live site, the coarse scan shows the background moving 0.545 px against 0.562 px for the strongest patch, so the agent decides *"the whole frame moves, so remove camera shake first"*. After compensation, a 58.5 Hz peak appears, so it zooms in with a fine scan of that region, then magnifies only that band. On a steady clip the same agent skips the shake step entirely. ([full trace](docs/example_trace.md))

**3. It knows when to say "I can't tell".** Aliasing, lighting flicker, low texture or a noise floor too high to trust a negative all return **Inconclusive (`REVIEW`)** with a re-recording hint. When the user gives the expected frequency, all 9 aliasing cases in evaluation E6 were sent to review.

**4. The model can never invent a number.** Every number comes from OpenCV or NumPy code. The LLM only chooses tools and writes prose. A *number guard* rejects any summary containing a number no tool produced, and only compact numbers (≤ 1.5 KB) reach the LLM, never video frames.

**5. It measures, and it publishes its failures.** Synthetic clips with exact ground truth measure frequency, amplitude, detection floor and localization. Failure cases (codec damage, aliasing, low texture, large motion, flicker) are documented with images in [failure_cases.md](eval/results/failure_cases.md). The COOL benchmark found no speed-up, and that null result is reported as measured.

| | Contact accelerometer | "Magnify all motion" (EVM) | LLM looking at video | **HumSight** |
|---|---|---|---|---|
| Needs hardware on the machine | yes, per point | no | no | **no** |
| Many measurement points at once | one per sensor | visual only | no | **one per image patch** |
| Handles a handheld camera | n/a | no, shake is magnified | unreliable | **yes, measured and rejected** |
| Gives numbers (Hz, px, SNR) | yes | no | can make them up | **yes, every one traceable to code** |
| Says when it cannot tell | n/a | no | rarely | **yes (`REVIEW`)** |
| Certified (ISO 20816) | yes | no | no | no (indicative only) |

---

## 🔧 How it works

![Architecture](docs/architecture.svg)

**Measure → Decide → Show**

1. **Measure (OpenCV 5).** `cv2.phaseCorrelateIterative` measures sub-pixel motion in every patch of every frame. An FFT turns each patch's motion into frequency, amplitude and SNR. Camera shake is removed by subtracting the background motion, or for rotation and zoom with `goodFeaturesToTrack` + `calcOpticalFlowPyrLK` + `findHomography(USAC_MAGSAC)` + `warpPerspective`.
2. **Decide (agent).** Gemini (or a deterministic rules policy with the same tools) runs a bounded loop of at most 10 tool calls. It classifies peaks as fault, shake or noise, refines with a fine scan, checks for aliasing and flicker, and files a verdict: FAULT, NO_FAULT or REVIEW.
3. **Show.** Band-limited Eulerian magnification (`pyrDown`/`pyrUp` Laplacian pyramid + FFT band-pass) of the fault region only, plus a heatmap, a spectrum, findings and a work order (Markdown and JSON).

![Agent workflow](docs/agent_workflow.svg)

| Stage | OpenCV / NumPy | Note |
|---|---|---|
| Sub-pixel motion | `cv2.phaseCorrelateIterative` on Hann-windowed patches, `L2size=5` | plain `cv2.phaseCorrelate` gave gross outliers on our textures |
| Shake, method A | median background displacement subtracted | best for translation |
| Shake, method B | `goodFeaturesToTrack`, `calcOpticalFlowPyrLK`, `findHomography(USAC_MAGSAC)`, `warpPerspective` | rotation and zoom |
| Localization | `connectedComponentsWithStats` on the fault-patch grid | coarse 8×6 grid, then a 32 px fine grid in the region |
| Magnification | `pyrDown`/`pyrUp` Laplacian pyramid + FFT band-pass (Wu et al. 2012) | region only; α clipped to the small-motion bound |
| Amplitude | least-squares sine fit at the refined peak frequency | unbiased |

**Agent guardrails:** schema-validated arguments · at most 10 tool calls and 3 magnifications · the 10th call is forced to a terminal tool · number guard on summary and rationale · FAULT without evidence becomes REVIEW · a Gemini failure mid-job falls back to rules, and the trace says so.

---

## 🧾 Proof it runs on AWS

HumSight uses AWS in two places, both run on 24 Oct 2026:

| Component | AWS services | Status |
|---|---|---|
| **Public endpoint**: the whole OpenCV 5 pipeline and the agent | **Lambda** (arm64 / Graviton, python3.12, 3008 MB) behind a **Function URL**, **S3** (demo clips, uploads, outputs, presigned URLs, public access blocked, 7-day expiry), **SSM Parameter Store** (Gemini key as SecureString), **CloudWatch Logs**, **Budgets** | **live** at [santiwari07.github.io/HumSight](https://santiwari07.github.io/HumSight/) |
| **COOL benchmark and live session** | **EC2** `c8g.large` **Spot** (Graviton4) from the **AWS Marketplace COOL AMI**, COOL `cv2 5.1.0-dev` vs stock `cv2 5.0.0` on the same instance | run, benchmarked, instance terminated |

### Lambda, S3 and CloudWatch (the live endpoint)

<table>
<tr>
<td width="50%" valign="top"><b>Deployed Lambda: arm64, Function URL, layer, SSM</b><br><img src="evidence/aws/01_lambda_deployment/screenshot.png" alt="AWS CLI output of the Lambda configuration"></td>
<td width="50%" valign="top"><b>The public endpoint answering: OpenCV 5.0.0 on aarch64</b><br><img src="evidence/aws/03_lambda_health/screenshot.png" alt="curl /health on the Lambda Function URL"></td>
</tr>
<tr>
<td valign="top"><b>Demo clips and job outputs in S3</b><br><img src="evidence/aws/02_s3_bucket/screenshot.png" alt="S3 bucket listing"></td>
<td valign="top"><b>CloudWatch: one Lambda invocation per analysis (22.9 s, 22.5 s, 41.3 s)</b><br><img src="evidence/aws/04_cloudwatch_invocations/screenshot.png" alt="CloudWatch REPORT lines for the analysis runs"></td>
</tr>
</table>

During the screenshot run above, the browser received 12 responses from AWS: `GET /health`, `GET /demo-clips`, `POST /jobs` from the Lambda Function URL, and the magnified video, heatmap, spectrum and original clip from S3 ([network log](evidence/aws/live_page/network_log.json)).

### COOL on EC2 Graviton4

<table>
<tr>
<td width="50%" valign="top"><b>EC2 instance facts: c8g.large, Spot, Neoverse-V2</b><br><img src="evidence/03_instance_facts/screenshot.png" alt="EC2 instance metadata"></td>
<td width="50%" valign="top"><b>COOL build loaded: cv2 5.1.0-dev from /opt/cool, KleidiCV</b><br><img src="evidence/01_cool_verify/screenshot.png" alt="verify_cool.py in the COOL venv"></td>
</tr>
<tr>
<td valign="top"><b>HumSight server started inside COOL: <code>COOL=True</code></b><br><img src="evidence/04_server_banner/screenshot.png" alt="Server banner showing COOL=True"></td>
<td valign="top"><b>A full analysis served and computed by the COOL instance</b><br><img src="evidence/ui/15_step4_diagnosis_alarm.jpg" alt="HumSight diagnosis served by the COOL instance"><br><sub>Its <code>/api/health</code> reports <code>"cool": true</code> (<a href="evidence/ui/19_api_health_cool_true.jpg">screenshot</a>).</sub></td>
</tr>
</table>

> **How the evidence was made.** The page screenshots are real pixel captures in Chrome. The terminal images are real command output (AWS CLI, `curl`, `ssh`) recorded with timings and rendered by [`scripts/evidence_terminal.py`](scripts/evidence_terminal.py). They are not pixel captures, and each image says so in its footer. The account id is masked. Full indexes: [evidence/aws/](evidence/aws/README.md) (Lambda, S3, CloudWatch) and [evidence/](evidence/README.md) (COOL on EC2).

---

## 🏆 How HumSight covers the competition

### Core requirements

| Requirement | Where | Status |
|---|---|---|
| OpenCV 5 for substantive video analysis | [`humsight/`](humsight/), [How it works](#-how-it-works) | ✅ `phaseCorrelateIterative`, LK optical flow, MAGSAC homography, pyramids, connected components |
| A meaningful component on AWS | Lambda + S3 + SSM + CloudWatch; EC2 Graviton4 for COOL | ✅ live, [proof above](#-proof-it-runs-on-aws) |
| Technical report (problem, users, architecture, OpenCV 5, AWS, evaluation, limitations, responsible use) | [docs/TECHNICAL_REPORT.md](docs/TECHNICAL_REPORT.md) | ✅ |
| Code repository with pinned dependencies | this repo, [`requirements.txt`](requirements.txt), [`requirements-lambda.txt`](requirements-lambda.txt) | ✅ |
| Build, deployment and test instructions | [docs/JUDGING.md](docs/JUDGING.md), [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | ✅ deployment executed and verified |
| Architecture diagram with OpenCV 5, AWS, COOL and agent | [architecture.svg](docs/architecture.svg), [agent_workflow.svg](docs/agent_workflow.svg) | ✅ |
| Working web endpoint | [santiwari07.github.io/HumSight](https://santiwari07.github.io/HumSight/) → Lambda Function URL | ✅ live |
| Evaluation with failure cases | [eval/results/summary.md](eval/results/summary.md), [failure_cases.md](eval/results/failure_cases.md) | ✅ E1–E6 on synthetic ground truth, one real clip shown above |
| Video of 5 minutes or less | | ⏳ to be recorded |

### Agentic Vision with OpenCV 5

| The rules ask for | HumSight |
|---|---|
| Image or video results influence a later plan, tool call, action or human approval | The coarse scan's background motion triggers `compensate_shake`; a fault peak triggers a fine scan of that region; an alias or flicker flag ends in `REVIEW` for a human |
| Agent workflow diagram (perception, decision, action) | [agent_workflow.svg](docs/agent_workflow.svg) |
| Trace showing OpenCV output changing a later decision | [example_trace.md](docs/example_trace.md), and the live activity log on every run |
| Task success | E5: agent (rules) **12/12**, live Gemini **11/12** then **12/12** on a rerun, fixed pipeline **5/12** |
| Failure handling | number guard, call budget, forced terminal tool, rules fallback when Gemini fails, documented failure cases |
| Observability | per-step trace with tool, arguments, reason, measured result and timing; CloudWatch logs on Lambda |
| Human control | the agent cannot act on the machine; its strongest action is a work order, and ambiguous cases go to `REVIEW` |

### Best Use of COOL

| The rules ask for | HumSight |
|---|---|
| COOL executes the core workload on Graviton | the whole HumSight pipeline and the web app ran inside the COOL venv on a `c8g.large` (Graviton4) ([banner](evidence/04_server_banner/screenshot.png), [health](evidence/ui/19_api_health_cool_true.jpg)) |
| COOL version and instance configuration | COOL `cv2 5.1.0-dev`, KleidiCV 0.7.0, AMI `ami-033e481a24f94c8cb`, us-east-1d, Spot ([COOL.md](docs/COOL.md)) |
| Reproducible method, inputs, baseline, results | [`bench/bench.py`](bench/bench.py): per-stage timings, 1 warm-up + 7 runs, 1 and 2 threads, stock OpenCV on the same instance ([RESULTS.md](bench/RESULTS.md)) |
| Honest result | **no meaningful speed-up** on this workload (0.98× to 1.03× total); `resize` 1.42× faster, `cvtColor` 0.83×; cost about $0.07 per 1,000 clips for both |

### Judging criteria

| Criterion | Weight | Where HumSight answers it |
|---|---|---|
| Technical execution | 30% | sub-pixel phase correlation, shake compensation, band-limited magnification; accuracy measured in E1–E4 |
| Innovation | 20% | camera as a sensor grid, agent that separates shake from fault, number guard, a `REVIEW` path |
| Real-world impact | 20% | vibration checks on unmonitored machines with a phone; a work order ready for the maintenance ticket |
| User experience | 10% | four-step guided flow, plain-language verdicts (Alarm / Normal / Inconclusive), side-by-side video, re-recording hints |
| Documentation and presentation | 10% | this README, [technical report](docs/TECHNICAL_REPORT.md), [judging guide](docs/JUDGING.md), diagrams |
| Cloud delivery, reproducibility, responsible operation | 10% | live Lambda deployment, [step-by-step deploy guide](docs/DEPLOYMENT.md) with every fix, budgets, input caps, SSM secrets, 7-day expiry, [teardown checklist](scripts/teardown_checklist.md) |

---

## 📊 Results

All numbers are generated by scripts in this repo ([summary.md](eval/results/summary.md)); E1–E6 use synthetic clips with exact ground truth.

| Evaluation | Result |
|---|---|
| **E1** Frequency accuracy | median error **0.005 Hz** at 0.05 px amplitude (noise σ 0.005); 0.002 Hz at 0.1 px |
| **E2** Amplitude accuracy | median error **3.2%** at 0.1 px, 6.3% at 0.05 px (noise σ 0.005) |
| **E3** Detection floor (≥ 90% detected) | **0.02 / 0.05 / 0.1 px** at noise σ 0.002 / 0.005 / 0.01, with **0/10** false positives on empty clips |
| **E3b** After lossy mp4v re-encoding | false positives rise to 3–6 of 10, so original files must be used |
| **E4** Localization | **24/24** faults found in the right part |
| **E5** Agent vs fixed pipeline (12 clips) | agent (rules) **12/12** · Gemini **11/12** (first run), **12/12** (rerun) · fixed pipeline **5/12**, magnified shake 6 times |
| **E6** Aliasing guard | **9/9** sent to `REVIEW` when the expected frequency is given |
| **Live AWS run** (`pump_shake_fault`) | 58.497 Hz found (truth 58.5 Hz), shake at 3.509 Hz rejected; 22.5 to 22.9 s per run on Lambda, under 1 GB of memory |
| **Real footage** (washing machine, handheld) | 22.7 Hz with shake removed; the display's set speed implies 23.3 Hz (indicative, not a validated reference) |
| **COOL vs stock** on Graviton4 | 0.98× to 1.03× total, a null result ([COOL.md](docs/COOL.md)) |

The Gemini rerun went from 11/12 to 12/12. The code change between the runs was never triggered in the rerun, so the improvement is consistent with run-to-run variation and is not credited to the change ([E5.md](eval/results/E5.md)).

---

## 🧰 Tech stack

| Layer | Technology |
|---|---|
| Computer vision | **OpenCV 5.0** (`opencv-python-headless`), COOL `5.1.0-dev` on Graviton4 |
| Signal processing | NumPy FFT, least-squares sine fit, Laplacian pyramids |
| Agent | Gemini (`google-genai`, `gemini-flash-latest`) with function calling; deterministic rules policy; number guard |
| Backend | Python 3.12, FastAPI + Server-Sent Events (local and EC2), AWS Lambda handler |
| Frontend | Static HTML/CSS/JavaScript, Chart.js, hosted on GitHub Pages |
| Cloud | AWS Lambda (arm64), Lambda Function URL, Amazon S3, SSM Parameter Store, CloudWatch Logs, AWS Budgets, EC2 Spot (Graviton4 `c8g.large`), AWS Marketplace (COOL AMI) |
| CI / hosting | GitHub Actions (Pages deploy) |
| Testing and evaluation | pytest (33 tests), seeded synthetic generator with Fourier-shift sub-pixel ground truth, E1–E8 scripts |

---

## 🔒 Limitations and responsible use

- **Indicative, not certified.** No ISO 20816 zone is reported. Every report and the UI say "Indicative, camera-based measurement. Not a certified ISO assessment", and recommend confirming with a contact accelerometer.
- **A negative result is evidence, not a guarantee.** Reports state the noise floor and the minimum detectable amplitude, and return `REVIEW` when that floor is too high.
- **Frame rate limits frequency.** Only frequencies below half the capture fps are measurable. Give the expected Hz or RPM so the aliasing guard can work. Uploads require the true capture fps.
- **Compression destroys sub-pixel motion.** Transfer original files, not re-encoded ones.
- **A machine that fills the frame** and vibrates as a whole looks like camera shake to this method.
- **Evaluation is mostly synthetic.** One real clip is shown, without a measured reference.
- **Privacy.** Only compact numbers go to the LLM, never frames. The Gemini key is in SSM, not in the repo.
- **Abuse and cost controls.** Input caps, a 4 s clip limit, presigned URLs, 7-day object expiry, AWS budgets.

More in the [technical report](docs/TECHNICAL_REPORT.md) §8 and §9.

---

## 🔭 Future scope

| Next step | Why |
|---|---|
| **Real-footage benchmark** with a reference accelerometer or phone-IMU reading (E8 protocol is written) | turn "indicative" into measured accuracy on real machines |
| **ISO 20816 zones** from a cited machine class, with a mm/px scale from a reference object | report velocity in mm/s and a severity zone, not only pixels |
| **Phase-based magnification** (Wadhwa et al.) | larger amplification with fewer artefacts than linear Eulerian magnification |
| **Fixed cameras and trend monitoring** | scheduled clips from a CCTV or Raspberry Pi camera, trend charts per machine, alerts on change |
| **Mobile capture app** | guide the user to the right fps, framing and steadiness before recording |
| **CMMS integration** | send the work order straight to maintenance systems (for example SAP PM, Maximo, UpKeep) |
| **MCP server** for the vision tools | let any agent call `scan_motion`, `classify_peaks` and `magnify` |
| **COOL at scale** | larger Graviton instances, batch processing and a container deployment, measuring throughput per dollar against x86 |
| **Multi-camera and 3D** | combine two views for direction of motion and mode shapes |

---

## 🚀 Run it yourself

**Use the live site:** [santiwari07.github.io/HumSight](https://santiwari07.github.io/HumSight/). Pick a recording, keep *Agent with rules*, click **Run analysis**. Try **Fixed pipeline** on the pump clip to watch the naive approach magnify the camera shake instead of the fault.

**Run locally** (Python 3.12+):

```bash
git clone https://github.com/SanTiwari07/HumSight && cd HumSight
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python scripts/make_demo_clips.py                        # deterministic demo clips (~50 MB each, not in git)
uvicorn server.app:app --port 8000                       # open http://localhost:8000
python -m pytest                                         # 33 tests
```

Gemini is optional: put `GEMINI_API_KEY=...` in a git-ignored `.env`. Without it, the rules policy runs the same tools.

| Guide | What it covers |
|---|---|
| [docs/JUDGING.md](docs/JUDGING.md) | the expected result for every demo clip and how to regenerate all evidence |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | the AWS deployment step by step (S3, SSM, Lambda, Pages, COOL on EC2) and every problem we hit |
| [docs/COOL.md](docs/COOL.md) | the COOL configuration, method, results and caveats |
| [scripts/teardown_checklist.md](scripts/teardown_checklist.md) | deleting every AWS resource afterwards |

---

## 📁 Repository layout

<details>
<summary>Show the tree</summary>

```
humsight/              core library (no web or cloud code): synth, io, texture, motion, spectrum,
                       shake, detect, magnify, severity, report, pipeline (fixed baseline)
humsight/agent/        tools, state, trace, rules policy, Gemini provider, number guard, loop
server/                FastAPI + SSE (local and EC2)
lambda_fn/             Lambda handler + Docker-free arm64 build script
web/                   static page (GitHub Pages)
deploy/                S3 / Lambda / CORS / IAM templates
bench/                 COOL vs stock benchmark harness and results
eval/                  E1–E8 scripts, failure cases, generated results
evidence/              COOL-on-EC2 evidence; evidence/aws/ for Lambda, S3 and CloudWatch
scripts/               demo clips, EC2 setup, COOL check, trace export, S3 upload, evidence rendering
tests/                 accuracy checkpoint, units, agent behaviour, Gemini wiring, Lambda, server
docs/                  technical report, diagrams, example trace, deployment, COOL, judging guide
demo_clips/            demo metadata and ground truth (clips are generated, not committed)
```

</details>

---

## 🙏 Credits

Wu, Rubinstein, Shih, Guttag, Durand, Freeman, *Eulerian Video Magnification for Revealing Subtle Changes in the World*, SIGGRAPH 2012. Iterative phase correlation as implemented in OpenCV. OpenCV and Cloud-Optimized OpenCV (COOL) on AWS Graviton. Real demo clip: "Washing machine 120fps" by Golha, CC BY-SA 4.0, via Wikimedia Commons. All other clips are synthetic.

Released under the [MIT licence](LICENSE).
