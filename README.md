# HumSight

*See what machines are humming.*

HumSight turns an ordinary video of a machine into a grid of "virtual vibration sensors":

1. **Measure.** OpenCV 5 phase correlation measures sub-pixel motion per patch; an FFT finds frequency, amplitude and SNR.
2. **Decide.** A bounded agent separates a real machine fault from camera shake and noise, escalates from a coarse to a fine scan, and asks for human review when the evidence is thin.
3. **Show.** A band-limited Eulerian magnification of the faulty region only, a heatmap, a spectrum and a work order.

Every number shown anywhere is computed by OpenCV/NumPy code in this repo. The LLM only chooses tools and writes prose, and a number guard replaces any summary containing a number that no tool produced.

> Indicative, camera-based measurement. Not a certified ISO assessment.

**Status (read this first).** The software is complete and tested locally on synthetic ground truth (see *Evaluation*). These pieces need accounts, spend or hardware that this repo cannot do for you, and are **not done yet**: the AWS COOL/Graviton4 benchmark run, the Lambda + S3 + GitHub Pages deployment, a live Gemini run (the Gemini provider is tested against a fake client only), the real fan clip (E8), and the demo video. Their scripts are in the repo and the sections below say exactly what to run. Nothing in the tables below is estimated.

## Try it locally

```bash
python -m venv .venv && .venv/Scripts/activate        # Windows; use .venv/bin/activate elsewhere
pip install -r requirements.txt
python scripts/make_demo_clips.py                      # deterministic, lossless demo clips (~50 MB each, not in git)
uvicorn server.app:app --port 8000                     # open http://localhost:8000
```

Pick a demo, leave the policy on *Agent (rules)* and press **Analyze**. The trace streams live over SSE. Switch the policy to **Fixed pipeline** on `pump_shake_fault` to see the naive approach magnify the camera shake instead of the fault.

Gemini (optional): put `GEMINI_API_KEY=...` in a git-ignored `.env`. Without a key the *Agent (Gemini)* option is disabled and the rules policy runs the same tools. If a Gemini call fails mid-job, the rest of the job runs on the rules policy and the trace says so (`source: rules (fallback: ...)`).

The UI follows the warm-paper design system in [design.md](design.md): cream canvas, Fraunces/Hanken Grotesk (open substitutes for the licensed faces), earth-tone accents for meaning, and a single action-blue button.

Tests: `python -m pytest` (units, checkpoint-1 accuracy, agent behaviour, fake-Gemini wiring, Lambda handler against a fake S3, server round trip).

## Architecture

```
video ──► decode (cv2.VideoCapture, INTER_AREA downscale, luma)
      ──► patch grid + texture score (Sobel energy)         ─┐
      ──► per-patch sub-pixel shifts (phaseCorrelateIterative)│  tools the agent calls
      ──► spectra (detrend, Hann FFT, sine-fit amplitude, SNR)│  (typed, schema-validated,
      ──► shake handling (subtract | LK + findHomography USAC_MAGSAC + warp)
      ──► classify peaks: shake / fault / noise → ROI (connectedComponentsWithStats)
      ──► Eulerian magnification in the ROI (pyrDown/pyrUp, temporal band-pass)
      ──► report: heatmap.png, spectrum.json, magnified video, work_order.json/md

agent loop (≤ 10 tool calls, ≤ 3 magnify):  perception tool → measured numbers → next tool → … → file_report | request_review
LLM = Gemini (google-genai)  ⟶  on error: deterministic rules policy (same tools, same limits)
```

`humsight/` is a pure library (no web or cloud code). `server/` (FastAPI + SSE) and `lambda_fn/` (Function URL handler) wrap it; `web/` is a static page.

## How it works (OpenCV 5 specifics)

| Stage | OpenCV / NumPy | Notes |
|---|---|---|
| sub-pixel motion | `cv2.phaseCorrelateIterative` on Hann-windowed patches, `L2size=5` | Plain `cv2.phaseCorrelate` gave gross outliers on blurred-noise textures in our tests; the iterative variant (exposed in the 5.0 Python wheel) did not. Parameters were tuned on synthetic data, see Evaluation. |
| shake, method A | median background displacement subtracted per frame | best for translation |
| shake, method B | `goodFeaturesToTrack` → `calcOpticalFlowPyrLK` → `findHomography(USAC_MAGSAC)` → `warpPerspective` | for rotation/zoom; interpolation slightly smooths sub-pixel signals |
| localisation | `connectedComponentsWithStats` on the grid of fault patches | coarse 8×6 grid, then a 32 px fine grid inside the ROI |
| magnification | `pyrDown`/`pyrUp` Laplacian pyramid + FFT band-pass (Wu et al. 2012) | finest level not amplified; α clipped so `(1+α)·δ ≤ 0.5 px` per level; ROI only |
| amplitude | least-squares sine fit at the refined peak frequency | unbiased; Hann scalloping does not matter |

Day-1 checks on the development laptop (Windows, `opencv-python-headless==5.0.0.93`): `phaseCorrelateIterative` and `USAC_MAGSAC` are exposed; `VideoWriter` codecs: `avc1` unavailable (no OpenH264), `VP80` (`.webm`) and `mp4v` work. The code tries `avc1`, `VP80`, `mp4v` in that order and transcodes `mp4v` to H.264 if an `ffmpeg` binary exists. Re-run `probe_codecs` on Lambda and COOL and record the result here.

## Agentic design

| Tool | Returns (all measured) |
|---|---|
| `probe_clip` | fps, duration, Nyquist, Δf, texture coverage, warnings (fps from metadata, low texture, flicker, aliasing) |
| `scan_motion(coarse \| fine, roi, f_min, f_max)` | top patch peaks, background peaks, noise floor; fine scan returns refined f, amplitude, ROI |
| `compensate_shake(subtract \| warp)` | background peak, residual left at the shake frequency, inlier ratio |
| `classify_peaks` | faults (f, amplitude, SNR, ROI), shake peaks, noise floor, alias and flicker flags |
| `magnify(f_center, bandwidth, alpha, roi)` | video, artifact ratio, effective alpha |
| `assess_severity` | mm, mm/s RMS, zone (only with a scale; zones stay `n/a` until real ISO 20816 thresholds are configured) |
| `request_review`, `file_report` | terminal; exactly one ends the job |

Measurements change the next call, for example: the coarse scan reports a background peak of the same size as the strongest patch, so the policy calls `compensate_shake`; `subtract` leaves a residual at the shake frequency above `WARP_RESIDUAL_PX`, so it tries `warp` and keeps whichever left less; `magnify` returns `artifact_ratio > 0.5`, so it narrows the band and lowers α. E5 below documents the cases where the agent's decisions change the outcome against the fixed pipeline.

Guardrails: tool arguments are schema-validated; at most 10 tool calls and 3 magnifications, and the 10th call is forced to a terminal tool; a `FAULT` verdict with no classified fault (or `NO_FAULT` with one) is downgraded to `REVIEW`; the number guard checks the LLM's summary and rationale against all tool results (2% tolerance, small integers allowed as counts) and substitutes a template summary when it finds an unverified number; the LLM never sees video, only compact (≤ 1.5 KB) numeric tool results.

Privacy note: free-tier Gemini API inputs may be used by Google to improve products. Only those compact numeric summaries are sent.

## Evaluation

All numbers below are generated by `python eval/run_all.py` (seeds fixed, synthetic 256×192 clips, 4 s) and copied here by `python scripts/embed_results.py`. Synthetic ground truth only; the real-clip experiment E8 is described in `IMPLEMENTATION.md` §10 and has not been run.

<!-- EMBED:eval/results/summary.md -->
HumSight evaluation summary

Generated by `python eval/run_all.py` in 1069 s. Seeds fixed (base 42). Synthetic clips: 256x192, 4 s. cv2 5.0.0. Thresholds: SNR_MIN=6.0, K_LOCAL=3.0.
## E1 Frequency accuracy (pass A: fps 240, no shake, 4 s, Δf = 0.25 Hz)

Error |f̂ − f| measured on the patches fully inside the vibrating part, median over patches.

| amp (px) | noise σ | n | median |Δf| (Hz) | p95 |Δf| (Hz) | median (bins) | p95 (bins) |
|---|---|---|---|---|---|---|
| 0.01 | 0.002 | 5 | 7.093 | 27.18 | 28.37 | 108.7 |
| 0.01 | 0.005 | 5 | 22.31 | 69.94 | 89.26 | 279.8 |
| 0.01 | 0.01 | 5 | 51.23 | 66.87 | 204.9 | 267.5 |
| 0.02 | 0.002 | 5 | 0.001605 | 0.01583 | 0.006422 | 0.06331 |
| 0.02 | 0.005 | 5 | 0.01432 | 43.28 | 0.05727 | 173.1 |
| 0.02 | 0.01 | 5 | 36.76 | 64.94 | 147 | 259.8 |
| 0.05 | 0.002 | 5 | 0.001892 | 0.003703 | 0.007568 | 0.01481 |
| 0.05 | 0.005 | 5 | 0.004798 | 0.01361 | 0.01919 | 0.05442 |
| 0.05 | 0.01 | 5 | 0.03421 | 16.97 | 0.1369 | 67.87 |
| 0.1 | 0.002 | 5 | 0.001266 | 0.003103 | 0.005065 | 0.01241 |
| 0.1 | 0.005 | 5 | 0.002261 | 0.004779 | 0.009046 | 0.01912 |
| 0.1 | 0.01 | 5 | 0.01076 | 0.01898 | 0.04306 | 0.07594 |
| 0.3 | 0.002 | 5 | 0.0006024 | 0.001323 | 0.00241 | 0.005294 |
| 0.3 | 0.005 | 5 | 0.001146 | 0.002249 | 0.004586 | 0.008997 |
| 0.3 | 0.01 | 5 | 0.001043 | 0.002066 | 0.004172 | 0.008262 |
| 1.0 | 0.002 | 5 | 5.117e-05 | 0.0002344 | 0.0002047 | 0.0009375 |
| 1.0 | 0.005 | 5 | 0.0001732 | 0.000671 | 0.0006928 | 0.002684 |
| 1.0 | 0.01 | 5 | 0.0006319 | 0.001262 | 0.002527 | 0.005047 |

### Pass B (f = 24.5 Hz, amp 0.05 px, noise 0.005)

| fps | shake | f̂ (Hz) | Â (px) | SNR | detected | ROI IoU |
|---|---|---|---|---|---|---|
| 60 | none | 24.48 | 0.04516 | 2.73 | False | n/a |
| 60 | 3.5 Hz | 20.78 | 0.03794 | 3.407 | False | n/a |
| 60 | 3.5 Hz + drift | 24.48 | 0.04349 | 3.535 | True | 0.046 |
| 120 | none | 24.49 | 0.04732 | 5.994 | True | 0.35 |
| 120 | 3.5 Hz | 24.51 | 0.04895 | 5.834 | True | 0.71 |
| 120 | 3.5 Hz + drift | 24.48 | 0.04175 | 5.976 | True | 0.35 |
| 240 | none | 24.51 | 0.04974 | 7.763 | True | 0.71 |
| 240 | 3.5 Hz | 24.48 | 0.04022 | 7.769 | True | 0.35 |
| 240 | 3.5 Hz + drift | 24.5 | 0.04873 | 8.769 | True | 0.69 |

## E2 Amplitude accuracy (pass A)

Relative error |Â − A| / A, median over patches inside the part.

| amp (px) | noise σ | n | median rel. err | p95 rel. err | median Â (px) |
|---|---|---|---|---|---|
| 0.01 | 0.002 | 5 | 0.0998 | 0.194 | 0.009076 |
| 0.01 | 0.005 | 5 | 0.48 | 0.606 | 0.0148 |
| 0.01 | 0.01 | 5 | 1.9 | 2.01 | 0.02903 |
| 0.02 | 0.002 | 5 | 0.0659 | 0.145 | 0.02035 |
| 0.02 | 0.005 | 5 | 0.147 | 0.258 | 0.01985 |
| 0.02 | 0.01 | 5 | 0.422 | 0.509 | 0.02845 |
| 0.05 | 0.002 | 5 | 0.0232 | 0.0561 | 0.05051 |
| 0.05 | 0.005 | 5 | 0.0629 | 0.123 | 0.04686 |
| 0.05 | 0.01 | 5 | 0.123 | 0.278 | 0.04387 |
| 0.1 | 0.002 | 5 | 0.027 | 0.0544 | 0.1005 |
| 0.1 | 0.005 | 5 | 0.032 | 0.0394 | 0.0968 |
| 0.1 | 0.01 | 5 | 0.0603 | 0.117 | 0.09397 |
| 0.3 | 0.002 | 5 | 0.00965 | 0.0162 | 0.2971 |
| 0.3 | 0.005 | 5 | 0.0222 | 0.0294 | 0.2933 |
| 0.3 | 0.01 | 5 | 0.0382 | 0.0472 | 0.2885 |
| 1.0 | 0.002 | 5 | 0.0943 | 0.095 | 0.9057 |
| 1.0 | 0.005 | 5 | 0.0824 | 0.0825 | 0.9176 |
| 1.0 | 0.01 | 5 | 0.0815 | 0.0855 | 0.9185 |

![E2](eval/results/e2_amplitude.png)

## E3 Detection floor

f = 24.5 Hz, fps 240, 10 seeds per cell, no shake. Detection = a classified fault within 2 bins.

| noise σ | amp (px) | detection rate |
|---|---|---|
| 0.002 | 0.01 | 0% |
| 0.002 | 0.02 | 100% |
| 0.002 | 0.05 | 100% |
| 0.002 | 0.1 | 100% |
| 0.002 | 0.3 | 100% |
| 0.002 | 1.0 | 100% |
| 0.005 | 0.01 | 0% |
| 0.005 | 0.02 | 0% |
| 0.005 | 0.05 | 100% |
| 0.005 | 0.1 | 100% |
| 0.005 | 0.3 | 100% |
| 0.005 | 1.0 | 100% |
| 0.01 | 0.01 | 0% |
| 0.01 | 0.02 | 0% |
| 0.01 | 0.05 | 20% |
| 0.01 | 0.1 | 100% |
| 0.01 | 0.3 | 100% |
| 0.01 | 1.0 | 100% |

| noise σ | detection floor (px, ≥90%) | false positives on empty clips |
|---|---|---|
| 0.002 | 0.02 | 0/10 |
| 0.005 | 0.05 | 0/10 |
| 0.01 | 0.1 | 0/10 |

## E3b Codec impact (mp4v round-trip)

f = 24.5 Hz, fps 240, 10 seeds per cell, no shake. Detection = a classified fault within 2 bins.

| noise σ | amp (px) | detection rate |
|---|---|---|
| 0.002 | 0.01 | 0% |
| 0.002 | 0.02 | 0% |
| 0.002 | 0.05 | 80% |
| 0.002 | 0.1 | 100% |
| 0.002 | 0.3 | 100% |
| 0.002 | 1.0 | 100% |
| 0.005 | 0.01 | 0% |
| 0.005 | 0.02 | 0% |
| 0.005 | 0.05 | 100% |
| 0.005 | 0.1 | 100% |
| 0.005 | 0.3 | 100% |
| 0.005 | 1.0 | 100% |
| 0.01 | 0.01 | 0% |
| 0.01 | 0.02 | 0% |
| 0.01 | 0.05 | 30% |
| 0.01 | 0.1 | 100% |
| 0.01 | 0.3 | 100% |
| 0.01 | 1.0 | 100% |

| noise σ | detection floor (px, ≥90%) | false positives on empty clips |
|---|---|---|
| 0.002 | 0.1 | 6/10 |
| 0.005 | 0.05 | 4/10 |
| 0.01 | 0.1 | 3/10 |

## E4 Localisation

Fault injected into 1 of 4 textured parts (0.1 px); the other parts are static. Hit = verdict FAULT and final ROI IoU ≥ 0.3 with the true part.

**Hit rate: 24/24 = 100%**

| true part | f (Hz) | verdict | IoU | hit |
|---|---|---|---|---|
| 0 | 58.5 | FAULT | 0.56 | yes |
| 2 | 24.5 | FAULT | 0.56 | yes |
| 1 | 58.5 | FAULT | 0.56 | yes |
| 0 | 40.0 | FAULT | 0.56 | yes |
| 0 | 15.0 | FAULT | 0.56 | yes |
| 2 | 58.5 | FAULT | 0.56 | yes |
| 2 | 58.5 | FAULT | 0.56 | yes |
| 2 | 58.5 | FAULT | 0.56 | yes |
| 2 | 15.0 | FAULT | 0.56 | yes |
| 3 | 24.5 | FAULT | 0.56 | yes |
| 2 | 24.5 | FAULT | 0.56 | yes |
| 0 | 58.5 | FAULT | 0.56 | yes |
| 3 | 40.0 | FAULT | 0.56 | yes |
| 1 | 58.5 | FAULT | 0.56 | yes |
| 2 | 24.5 | FAULT | 0.56 | yes |
| 1 | 15.0 | FAULT | 0.56 | yes |
| 0 | 40.0 | FAULT | 0.56 | yes |
| 3 | 15.0 | FAULT | 0.56 | yes |
| 3 | 58.5 | FAULT | 0.56 | yes |
| 1 | 40.0 | FAULT | 0.56 | yes |
| 0 | 58.5 | FAULT | 0.56 | yes |
| 2 | 24.5 | FAULT | 0.56 | yes |
| 0 | 58.5 | FAULT | 0.56 | yes |
| 1 | 58.5 | FAULT | 0.56 | yes |

## E5 Agent vs fixed pipeline

12 clips (4 groups x 3): shake + hidden fault, shake only, fault only, nothing. ✓ = correct verdict (and for FAULT, the right frequency). 'shake magnified' = the reported fault frequency is the camera-shake frequency.

| clip | truth | agent (rules) | agent (Gemini) | fixed pipeline |
|---|---|---|---|---|
| shake+fault #1 | FAULT | FAULT ✓ | not run (no key) | FAULT ✗ · shake magnified |
| shake+fault #2 | FAULT | FAULT ✓ | not run (no key) | FAULT ✗ · shake magnified |
| shake+fault #3 | FAULT | FAULT ✓ | not run (no key) | FAULT ✗ · shake magnified |
| shake only #1 | NO_FAULT | NO_FAULT ✓ | not run (no key) | FAULT ✗ · shake magnified |
| shake only #2 | NO_FAULT | NO_FAULT ✓ | not run (no key) | FAULT ✗ · shake magnified |
| shake only #3 | NO_FAULT | NO_FAULT ✓ | not run (no key) | FAULT ✗ · shake magnified |
| fault only #1 | FAULT | FAULT ✓ | not run (no key) | NO_FAULT ✗ |
| fault only #2 | FAULT | FAULT ✓ | not run (no key) | FAULT ✓ |
| fault only #3 | FAULT | FAULT ✓ | not run (no key) | FAULT ✓ |
| nothing #1 | NO_FAULT | NO_FAULT ✓ | not run (no key) | NO_FAULT ✓ |
| nothing #2 | NO_FAULT | NO_FAULT ✓ | not run (no key) | NO_FAULT ✓ |
| nothing #3 | NO_FAULT | NO_FAULT ✓ | not run (no key) | NO_FAULT ✓ |

| policy | correct | shake wrongly magnified |
|---|---|---|
| agent (rules) | 12/12 | 0 |
| agent (Gemini) | not run | - |
| fixed | 5/12 | 6 |

## E6 Aliasing guard

**9/9 = 100% flagged REVIEW** when the expected frequency is given (target 100%). Last column: what happens when the user gives no expected frequency (the guard cannot know, the search band stops at 0.45 x fps).

| fps | f (Hz) | verdict (expected_hz given) | verdict (not given) |
|---|---|---|---|
| 60 | 28.8 | REVIEW | NO_FAULT |
| 60 | 36.0 | REVIEW | FAULT |
| 60 | 48.0 | REVIEW | FAULT |
| 120 | 57.6 | REVIEW | REVIEW |
| 120 | 72.0 | REVIEW | FAULT |
| 120 | 96.0 | REVIEW | FAULT |
| 240 | 115.2 | REVIEW | REVIEW |
| 240 | 144.0 | REVIEW | FAULT |
| 240 | 192.0 | REVIEW | FAULT |

## E8 Real clip (fan + coin)

Not run: no real clip present at `demo_clips/real_fan/`. Record one with the protocol in IMPLEMENTATION.md §10 and run `python eval/e8_real.py <clip> --capture-fps 240 --expected-hz <phyphox Hz>`. Synthetic results above are labelled synthetic.
<!-- /EMBED -->

## Failure cases

Generated by `python eval/failure_cases.py`; reported as found, including where the tool is wrong.

<!-- EMBED:eval/results/failure_cases.md -->
Failure cases

Built to break the tool; results are reported as found.

| case | scene | ideal outcome | actual verdict | findings | probe warnings |
|---|---|---|---|---|---|
| Codec damage | 58.5 Hz, 0.05 px fault + shake, after mp4v round-trip | FAULT at 58.5 Hz | NO_FAULT | [] | - |
| Aliasing, frequency not given | 144 Hz fault recorded at 240 fps (Nyquist 120 Hz) | REVIEW (aliasing) | FAULT | [[96.001, 0.18284]] | - |
| Low texture | 24.5 Hz, 0.1 px fault on a nearly flat surface (6% contrast) | FAULT at 24.5 Hz or REVIEW | REVIEW | [] | low texture: only 0% of patches are usable |
| Large motion | 15 Hz, 6 px fault (far outside the sub-pixel regime) | one FAULT at 15 Hz, amplitude 6 px | FAULT | [[15.0, 5.63568], [104.978, 0.08597], [59.979, 0.06831]] | - |
| Lighting flicker | no motion; 100 Hz mains-light brightness modulation (8%) | NO_FAULT or REVIEW | REVIEW | [] | lighting flicker suspected near 100.0 Hz |

## Codec damage

- scene: 58.5 Hz, 0.05 px fault + shake, after mp4v round-trip
- ideal: FAULT at 58.5 Hz
- actual: **NO_FAULT** - No localized vibration above SNR 6.0. Noise floor 0.003089 px; minimum detectable amplitude about 0.018533 px.
- texture coverage: 1.0; noise floor: 0.003089 px; lighting_flicker: False
- why: The encoder's motion compensation and quantisation smooth sub-pixel motion away; the noise floor looks normal, so the clip looks quiet. Use a high-bitrate / lossless original, never a messaging-app copy.

![Codec damage: amplitude per patch](eval/results/failure_cases/codec_damage/heatmap.png)

## Aliasing, frequency not given

- scene: 144 Hz fault recorded at 240 fps (Nyquist 120 Hz)
- ideal: REVIEW (aliasing)
- actual: **FAULT** - Localized vibration at 96.001 Hz with amplitude 0.18284 px (SNR 521.89) in ROI [64, 32, 128, 96].
- texture coverage: 1.0; noise floor: 0.005396 px; lighting_flicker: False
- why: Without expected_hz the guard cannot know. The 144 Hz motion folds to 96 Hz and is reported there as a confident FAULT. Give an expected Hz/RPM whenever possible.

![Aliasing, frequency not given: amplitude per patch](eval/results/failure_cases/alias_unknown_frequency/heatmap.png)

## Low texture

- scene: 24.5 Hz, 0.1 px fault on a nearly flat surface (6% contrast)
- ideal: FAULT at 24.5 Hz or REVIEW
- actual: **REVIEW** - low texture: only 0% of patches have enough gradient energy for sub-pixel tracking
- texture coverage: 0.0; noise floor: None px; lighting_flicker: None
- why: Phase correlation needs gradient energy. Patches below TEXTURE_MIN are dropped; with almost none left the agent must ask for review rather than report a negative (an earlier version filed NO_FAULT here: fixed).

![Low texture: amplitude per patch](eval/results/failure_cases/low_texture/heatmap.png)

## Large motion

- scene: 15 Hz, 6 px fault (far outside the sub-pixel regime)
- ideal: one FAULT at 15 Hz, amplitude 6 px
- actual: **FAULT** - Localized vibration at 15.0 Hz with amplitude 5.63568 px (SNR 7505.15) in ROI [96, 32, 96, 96].
- texture coverage: 1.0; noise floor: 0.005586 px; lighting_flicker: False
- why: Magnification and the sub-pixel estimator assume small motion. The main peak is found (amplitude within a few percent) but the estimator's nonlinearity adds spurious harmonic peaks that are also classified as faults; do not trust secondary findings or magnification for motion of several pixels.

![Large motion: amplitude per patch](eval/results/failure_cases/large_motion/heatmap.png)

## Lighting flicker

- scene: no motion; 100 Hz mains-light brightness modulation (8%)
- ideal: NO_FAULT or REVIEW
- actual: **REVIEW** - lighting flicker coincides with the detected peak (mean frame brightness oscillates)
- texture coverage: 1.0; noise floor: 0.005375 px; lighting_flicker: True
- why: Guard case: brightness oscillation is flagged from the mean-frame signal instead of being read as motion.

![Lighting flicker: amplitude per patch](eval/results/failure_cases/lighting_flicker/heatmap.png)
<!-- /EMBED -->

## COOL (Cloud-Optimized OpenCV) on Graviton4

**Not run yet.** The procedure is scripted: `scripts/ec2_setup.sh` (COOL venv and a stock venv on the same `c8g.large` Spot instance), `scripts/verify_cool.py` (prints `cv2.__file__`, COOL path and KleidiCV lines: the proof screenshot), `scripts/run_bench_ec2.sh` (7 timed runs after a warm-up, threads 1 and 2, per-stage medians and IQR, micro-benchmarks) and `python bench/bench.py --compare ... --spot-price <$/h>` for cost per 1,000 clips. The server prints `[HumSight] cv2 … | COOL=… | KleidiCV=…` at start-up.

The benchmark harness was smoke-tested on this laptop by comparing two identical stock environments: it reported about 1.00× on each stage, so differences smaller than a few percent are noise. If COOL is not faster on a stage (NumPy FFT and Python loops dominate several stages), that is what will be reported.

<!-- EMBED:bench/RESULTS.md -->
_bench/RESULTS.md has not been generated yet._
<!-- /EMBED -->

## Public deployment (Lambda + GitHub Pages)

Not deployed from here (needs your AWS account). Design and code are in `lambda_fn/`: arm64 `python3.12`, 3008 MB, 120 s timeout, reserved concurrency 2, Function URL with CORS for your GitHub Pages origin, presigned S3 PUT for uploads, clips capped at 4 s, `X-Demo-Token` speed bump, Gemini key from SSM Parameter Store. `bash lambda_fn/build_layer.sh` builds `layer.zip` and `function.zip` without Docker. The job runs synchronously and returns the whole trace; the page replays it at 400 ms per step and labels it "recorded trace". Set `web/config.js` → `API_BASE` to the Function URL; `?api=http://<ec2-ip>:8000` overrides it for a live COOL session.

## Limitations and responsible use

- Severity is indicative. Zones are not reported until real ISO 20816 thresholds for a stated part and machine class are configured in `humsight/config.py`.
- Frequency is only valid below Nyquist (fps/2). Record at ≥ 2.5× the frequency of interest and give the expected Hz/RPM so the aliasing guard can work.
- `capture_fps` is mandatory for uploads: slow-motion files often store a 30 fps playback rate.
- Lossy re-compression (messaging apps, many encoders) removes or fakes sub-pixel motion. Transfer originals.
- A machine that fills the frame and vibrates as a whole is indistinguishable from camera shake by this method.
- It is not a replacement for certified condition monitoring.

## Cost and reproducibility

Dependencies are pinned in `requirements.txt` / `requirements-lambda.txt`. Local runs cost nothing. The planned AWS spend (Spot `c8g.large` for a few hours, S3, Lambda inside the free tier) is estimated in `IMPLEMENTATION.md` §9.8; **no AWS resources have been created by this repo**, so the actual cost so far is zero. `scripts/teardown_checklist.md` lists what to delete afterwards.

## Credits

Wu, Rubinstein, Shih, Guttag, Durand, Freeman, *Eulerian Video Magnification for Revealing Subtle Changes in the World*, SIGGRAPH 2012. Hrazdira et al., iterative phase correlation (as implemented in OpenCV). OpenCV and Cloud-Optimized OpenCV (COOL). All clips in this repo are synthetic and generated by `humsight/synth.py`.

MIT licence.
