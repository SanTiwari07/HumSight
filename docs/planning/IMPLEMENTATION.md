# HumSight — Implementation Guide

> **Name:** HumSight. Tagline: "See what machines are humming."
>
> **Deadline:** Tue 27 Oct 2026, 12:15 pm IST (Mon 26 Oct, 11:45 pm PDT).
> **Internal deadline:** submit by **Mon 26 Oct, 11:00 pm IST**.
>
> **Builder:** 1 student, software only.
> **Budget:** about ₹15–50 of AWS spend (Spot EC2 for a few hours). Everything else uses always-free services or free API keys.

---

## 0. Locked decisions

| Decision | Choice | Why |
|---|---|---|
| Language | Python 3.12 | Matches COOL venv `/opt/cool/venvs/python_3.12` and Lambda `python3.12` runtime |
| Vision | OpenCV 5 (`opencv-python-headless==5.0.0.93` locally and on Lambda; COOL build on EC2) + NumPy | Mandatory OpenCV 5; headless avoids GUI deps |
| No SciPy | NumPy FFT only | Keeps Lambda zip < 250 MB unzipped |
| Agent LLM | **Gemini** via `google-genai` SDK, behind a provider interface; **rule-based fallback** always available | Free key you already have; swappable to Bedrock later |
| Local / EC2 server | FastAPI + Uvicorn, Server-Sent Events (SSE) for the live trace | Simple, async, streams the trace |
| Public endpoint (judging) | **AWS Lambda (arm64) + Function URL** | Always-free tier: 1M requests and 400,000 GB-s per month |
| COOL evidence | **EC2 c8g.large Spot** from the COOL Graviton4 AMI, used only for benchmark and demo recording | Spot was about $0.02–0.05/h recently; COOL software fee waived during the 7-day trial |
| Storage | S3 (uploads, outputs, demo clips), lifecycle delete after 7 days | Pennies |
| Frontend | Single static page (HTML + vanilla JS + Chart.js) on **GitHub Pages** | Free |
| Secrets | Gemini key in **SSM Parameter Store** (Standard, SecureString), read by Lambda at cold start | Free tier; key never in repo |

**Ground rule for the whole project:** every number shown anywhere comes from OpenCV/NumPy code in the repo. The LLM only chooses tools and writes prose, and a post-check strips any number it invents (§7.6).

---

## 1. Repository layout

```
humsight/
├── README.md                 # judge-facing: what, how to run, results, failure cases, costs
├── PRD.md
├── IMPLEMENTATION.md         # this file
├── LICENSE                   # MIT
├── requirements.txt          # pinned (local + EC2)
├── requirements-lambda.txt   # pinned, headless, no FastAPI
├── pyproject.toml            # optional; makes `humsight` importable
├── humsight/              # core library — NO web/cloud code in here
│   ├── __init__.py
│   ├── config.py             # thresholds, defaults, zone table (with source notes)
│   ├── io.py                 # video load/save, fps handling, grayscale/YCrCb
│   ├── synth.py              # synthetic ground-truth video generator
│   ├── texture.py            # patch texture scoring + optional contour mask
│   ├── motion.py             # patch grid + phase correlation → dx(t), dy(t)
│   ├── shake.py              # camera-shake estimation & compensation
│   ├── spectrum.py           # detrend, window, rFFT/Welch, peak, SNR
│   ├── detect.py             # classify peaks: shake / fault / noise; cluster patches → ROI
│   ├── magnify.py            # band-limited Eulerian magnification on ROI
│   ├── severity.py           # px → mm → velocity RMS → indicative zone
│   ├── report.py             # work order JSON/MD, heatmap PNG, spectrum JSON
│   ├── pipeline.py           # fixed (non-agent) baseline pipeline
│   └── agent/
│       ├── __init__.py
│       ├── tools.py          # tool implementations + JSON schemas
│       ├── state.py          # job state shared across tool calls
│       ├── trace.py          # trace events (step, tool, args, result, source, t)
│       ├── policy_rules.py   # deterministic fallback policy
│       ├── provider.py       # LLMProvider interface
│       ├── provider_gemini.py
│       ├── guard.py          # number guard for LLM-written text
│       └── loop.py           # run_agent(job) — the bounded loop
├── server/
│   ├── app.py                # FastAPI app (local + EC2)
│   └── jobs.py               # in-process job queue, SSE broadcaster
├── lambda_fn/
│   ├── handler.py            # Lambda entrypoint (sync job, returns trace + S3 URLs)
│   └── build_layer.sh        # builds arm64 deps zip without Docker
├── web/                      # static frontend (GitHub Pages)
│   ├── index.html
│   ├── app.js
│   ├── style.css
│   └── config.js             # API_BASE (Lambda URL or EC2 URL)
├── bench/
│   ├── bench.py              # per-stage timing, COOL vs stock
│   └── RESULTS.md            # generated
├── eval/
│   ├── make_dataset.py       # generates the synthetic eval set from a seed
│   ├── run_all.py            # E1–E6 → tables + plots
│   ├── e5_agent_vs_fixed.py
│   └── results/              # generated .md/.png/.json
├── demo_clips/               # small curated clips + gt.json (≤ 10 MB total in git)
└── scripts/
    ├── ec2_setup.sh          # run on the COOL instance
    ├── verify_cool.py        # prints cv2 path + build info (COOL proof)
    └── teardown_checklist.md
```

### Pinned requirements (starting point; pin exact versions after first install)

`requirements.txt`
```
opencv-python-headless==5.0.0.93
numpy==2.*            # pin exact after install: pip freeze | grep numpy
fastapi==0.*          # pin exact
uvicorn[standard]==0.*
python-multipart==0.*
google-genai==1.*     # pin exact
matplotlib==3.*       # eval plots only
boto3==1.*            # S3 from EC2/local (optional)
```
After the first working install, run `pip freeze > requirements.txt` and commit it. The judging rules ask for pinned dependencies.

On the COOL instance, **do not** `pip install opencv-python*` into the COOL venv. That would replace COOL's cv2. Install only the non-OpenCV deps there (§9.4).

---

## 2. Core data model

```python
# humsight/io.py
@dataclass
class Clip:
    frames_y: np.ndarray      # (T, H, W) float32 in [0,1], luma
    frames_bgr: np.ndarray | None  # (T, H, W, 3) uint8, kept only if needed for output
    fps: float                # CAPTURE fps (see §3.2), not container playback fps
    path: str
    meta: dict                # width, height, n_frames, container_fps, duration_s

@dataclass
class PatchGrid:
    boxes: np.ndarray         # (N, 4) x, y, w, h
    rows: int; cols: int
    texture: np.ndarray       # (N,) texture score
    valid: np.ndarray         # (N,) bool — textured enough to trust
    is_background: np.ndarray # (N,) bool — used for shake estimation

@dataclass
class MotionSeries:
    dx: np.ndarray            # (N, T) px, relative to reference frame
    dy: np.ndarray            # (N, T)
    response: np.ndarray      # (N, T) phaseCorrelate peak response (quality)

@dataclass
class PatchPeak:
    patch: int
    f_hz: float
    amp_px: float             # zero-to-peak displacement amplitude
    snr: float
    axis: tuple[float, float] # unit vector of dominant motion direction
```

Limits enforced everywhere, to keep Lambda safe and fast:
- `MAX_DURATION_S = 4.0` (Lambda), 10.0 (EC2/local)
- `MAX_FRAMES = 1200`
- `MAX_WIDTH = 960`. Downscale on load, **and multiply px results back by the scale factor** so amplitudes are reported in original-pixel units.
- Upload size ≤ 25 MB.

---

## 3. Module specifications

### 3.1 `synth.py`: synthetic ground-truth generator (build first; everything is tested against it)

**Purpose:** produce videos where the true vibration frequency, amplitude and location are known exactly.

**Scene:**
- background = smooth random texture: Gaussian-blurred noise, σ = 1.5 px, contrast-stretched;
- one or more rectangular "parts" (bearing cap, bracket) with their own texture and an edge outline, so they look like objects and have strong gradients.

**Motion model per frame t (time = t / fps):**
- Part k displacement: `d_k(t) = A_k · sin(2π f_k t + φ_k) · u_k`, where `u_k` is a unit direction vector.
- Optional harmonics: add `A_k/3 · sin(2π·2f_k t)`.
- Camera shake (whole frame): `s(t) = B · sin(2π f_s t + φ_s) · u_s`. Optionally add a low-frequency random walk (filtered noise, < 2 Hz) to mimic handheld drift.

**Exact sub-pixel shifting (Fourier shift theorem).** Do not use bilinear warps. They low-pass the texture and bias amplitudes.

```python
def fourier_shift(img: np.ndarray, dx: float, dy: float) -> np.ndarray:
    H, W = img.shape
    F = np.fft.fft2(img)
    ky = np.fft.fftfreq(H)[:, None]
    kx = np.fft.fftfreq(W)[None, :]
    F *= np.exp(-2j * np.pi * (kx * dx + ky * dy))
    return np.real(np.fft.ifft2(F)).astype(np.float32)
```

**Composition per frame:**
1. For each part: `part_t = fourier_shift(part_texture_full, *d_k(t))`, then blend with a feathered mask: `frame = bg*(1-m_k) + part_t*m_k`. The mask itself stays static. That is acceptable, because evaluation patches sit inside the part.
2. Whole-frame shake: `frame = fourier_shift(frame, *s(t))`.
3. Crop a margin of `ceil(max shift)+8` px on all sides to hide circular wrap.
4. Degrade:
   - Gaussian noise σ_n;
   - quantise to uint8;
   - optional JPEG round-trip at quality q (`cv2.imencode('.jpg', …, [cv2.IMWRITE_JPEG_QUALITY, q])`);
   - optional video codec round-trip through `cv2.VideoWriter`.

**Output:**
- `clip.mp4`, or a lossless `.npz` of uint8 frames for eval (avoids codec surprises);
- `gt.json`:
```json
{
  "fps": 240, "n_frames": 960, "width": 640, "height": 360,
  "parts": [{"id": "bearing_cap", "bbox": [x,y,w,h], "f_hz": 58.5, "amp_px": 0.05,
             "dir": [1,0], "phase": 0.3, "harmonics": false}],
  "shake": {"f_hz": 3.5, "amp_px": 0.6, "dir": [0.7,0.7], "drift": true},
  "noise_sigma": 0.004, "jpeg_q": 85, "seed": 42
}
```

**CLI:**
`python -m humsight.synth --f 58.5 --amp 0.05 --fps 240 --dur 4 --shake-f 3.5 --shake-amp 0.6 --noise 0.004 --jpeg 85 --seed 42 --out demo_clips/synth_pump_01`

**Unit test:** a single part, no noise, no shake, `amp = 0.05 px`. `motion.py` must recover the amplitude within ±10% and the frequency within ±1 frequency bin. If it doesn't, fix this before anything else.

### 3.2 `io.py`: loading video correctly

- `cv2.VideoCapture(path)`. Read all frames up to `MAX_FRAMES`.
  - Convert BGR → YCrCb.
  - Keep Y as float32/255 in `frames_y`.
  - Keep BGR uint8 only for the ROI output step.
- **Capture fps trap:** phone slow-motion files often record at 240 fps but store a 30 fps *playback* rate in the container. `CAP_PROP_FPS` then reports 30, which is wrong.
  - The API **requires** a `capture_fps` field.
  - If the user leaves it blank, use the container fps and add the warning `"fps taken from file metadata; slow-motion clips may be mislabelled"`.
- Downscale to `MAX_WIDTH` with `cv2.INTER_AREA`. Store `scale = orig_w / new_w` and report px in original units (`amp_px_orig = amp_px * scale`).
- `write_video(frames_bgr, path, fps_out=30)`. Try these codecs in order:
  1. `cv2.VideoWriter_fourcc(*'avc1')` → `.mp4`
  2. `*'VP80'` → `.webm`
  3. `*'mp4v'` → `.mp4`. Browsers often won't play this, so then also export an animated `.gif`, or use an ffmpeg binary if available.

  **Day-1 check:** which codec actually works in the pip wheel on your laptop, on Lambda (arm64) and on COOL. Record the result in README.

### 3.3 `texture.py`: which patches to trust

- Texture score per patch: mean gradient energy, `mean(Sobel_x² + Sobel_y²)` on the reference frame, or the minimum eigenvalue (`cv2.cornerMinEigenVal`, mean over the patch).
- `valid = score > TEXTURE_MIN`, calibrated on synthetic flat vs textured patches.
- **Background patches:**
  - by default, the outer ring of the grid (top/bottom row, left/right column);
  - or a user-drawn ROI ("this is the machine"), with everything outside treated as background.
- Optional structural mask: Canny → `cv2.findContours` (TRUCO in OpenCV 5). Keep patches overlapping large contours. This is a P2 feature; cut it if time is short.

### 3.4 `motion.py`: sub-pixel shifts with phase correlation

```python
def patch_shifts(frames_y, boxes, ref_mode="first", use_iterative=None):
    T = frames_y.shape[0]; N = len(boxes)
    dx = np.zeros((N, T), np.float32); dy = np.zeros_like(dx); resp = np.zeros_like(dx)
    w, h = boxes[0][2], boxes[0][3]
    win = cv2.createHanningWindow((w, h), cv2.CV_32F)
    ref = frames_y[0] if ref_mode == "first" else frames_y[: min(T, 30)].mean(0)
    pc = _pick_phase_correlate(use_iterative)
    for i, (x, y, w_, h_) in enumerate(boxes):
        r = np.ascontiguousarray(ref[y:y+h_, x:x+w_])
        for t in range(T):
            c = np.ascontiguousarray(frames_y[t, y:y+h_, x:x+w_])
            (sx, sy), rv = pc(r, c, win)
            dx[i, t], dy[i, t], resp[i, t] = sx, sy, rv
    return MotionSeries(dx, dy, resp)
```

- `cv2.phaseCorrelate(src1, src2, window)` returns `((dx, dy), response)`, the shift of `src2` relative to `src1`. Inputs are single-channel float32.
- **Iterative variant:** OpenCV added "Iterative Phase Correlation" in 4.13. On Day 1, run:
  ```python
  import cv2; print([n for n in dir(cv2) if 'hase' in n])
  help(cv2.<name>)
  ```
  If it is exposed, wrap it in `_pick_phase_correlate`. If not, use standard `phaseCorrelate`. Its built-in sub-pixel peak fit is already good to a few hundredths of a pixel on clean textured patches; **measure it** in E2/E3.
- **Patch size:** 64×64 by default. Use 32×32 for the fine grid. Larger patches give less noise but coarser localisation.
- **Performance budget:** `T × N` calls. For 960 frames × 60 coarse patches ≈ 58k calls. A 64×64 call is tens of microseconds, so this takes seconds. **Measure on Day 1.** If it is too slow:
  - **coarse grid first** (e.g. 8×6), then the agent refines only the candidate region (§7). This is a genuine agent decision, so it is a feature, not just an optimisation;
  - parallelise over patches with `concurrent.futures.ThreadPoolExecutor` (OpenCV releases the GIL), or rely on `cv2.setNumThreads`.
- **Reference drift:** with `ref_mode="first"`, slow drift accumulates. The detrend in `spectrum.py` handles it. For long clips, use a sliding reference every 2 s and stitch, but this is not needed for clips ≤ 4 s.

### 3.5 `shake.py`: camera shake handling (two methods; the agent chooses)

**Method A, `subtract` (default, cheap, best for translation-dominant shake):**
- `bg_dx(t) = median over valid background patches of dx[i, t]`, and the same for `bg_dy`.
- Compensated motion: `dx_c[i,t] = dx[i,t] - bg_dx(t)`, likewise `dy`.
- Residual metric: `shake_residual = median over background patches of RMS(dx_c, dy_c)`, which should be ≈ 0.

**Method B, `warp` (for rotation/zoom shake):**
1. Track features on background: `cv2.goodFeaturesToTrack` on frame 0, background mask only, max 400 corners, quality 0.01, min distance 8.
2. Per frame, `cv2.calcOpticalFlowPyrLK` from frame 0.
3. `cv2.findHomography(src, dst, cv2.USAC_MAGSAC, 1.0)`. Use `cv2.estimateAffinePartial2D(..., method=cv2.USAC_MAGSAC)` if the motion is small or the scene is planar.
4. Warp each frame back to the reference: `cv2.warpPerspective(frame, H_inv, (W,H), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP)` or equivalent.
5. Recompute patch shifts on the stabilised frames.
6. Residual: RMS of background patch motion after warp.

**Caveat:** method B interpolates, which slightly smooths sub-pixel signals. Report its residual and let the agent compare it with A.

**Metric returned to the agent:**
```json
{"method": "subtract", "bg_peak_hz": 3.5, "bg_amp_px": 0.61, "residual_px_rms": 0.004,
 "inlier_ratio": null}
```

### 3.6 `spectrum.py`: from motion to frequency

For each valid patch:

1. **Dominant direction.** PCA on `[dx_c, dy_c]` (2×T). The unit vector `u` is the first principal axis. Project: `s(t) = u · [dx_c(t), dy_c(t)]`.
2. **Detrend.** Subtract a linear fit (`np.polyfit(t, s, 1)`). This removes slow drift.
3. **Window and transform:**
   ```python
   N = len(s); w = np.hanning(N)
   X = np.fft.rfft(s * w)
   amp = 2 * np.abs(X) / w.sum()          # zero-to-peak amplitude spectrum (px)
   f = np.fft.rfftfreq(N, d=1/fps)
   ```
   - Frequency resolution `Δf = fps / N`. For example, 240 fps × 4 s gives Δf = 0.25 Hz.
   - For noisier clips, use Welch: segments of `N/4` with 50% overlap, averaging the power spectrum.
4. **Search band.** Default `[f_min, f_max] = [2 Hz, 0.45·fps]`, or a user range. Ignore anything below 2 Hz (drift and breathing of handheld cameras).
5. **Peak with parabolic interpolation** for sub-bin frequency:
   ```python
   k = band_idx[np.argmax(amp[band_idx])]
   a, b, c = amp[k-1], amp[k], amp[k+1]
   delta = 0.5 * (a - c) / (a - 2*b + c)        # in bins, |delta| <= 0.5
   f_peak = (k + delta) * fps / N
   amp_peak = b - 0.25 * (a - c) * delta          # interpolated height
   ```
   The Hann window's scalloping loss is up to about 15% between bins. Either correct it with a known Hann correction table, or report amplitude from a least-squares sine fit at `f_peak`:
   ```python
   M = np.column_stack([np.sin(2*np.pi*f_peak*t), np.cos(2*np.pi*f_peak*t), np.ones_like(t)])
   coef, *_ = np.linalg.lstsq(M, s_detrended, rcond=None)
   amp_fit = float(np.hypot(coef[0], coef[1]))
   ```
   **Use `amp_fit` as the reported amplitude.** It is unbiased and simple.
6. **SNR.** `snr = amp[k] / median(amp[band excluding k±3 bins])`. Report it in linear form and in dB.
7. **Background spectrum.** Run the same procedure on the median background signal. Return the top 3 peaks.

**Aliasing guard (`nyquist_check`):**
- `f_nyq = fps / 2`.
- If the user gave an expected frequency or RPM and `f_expected > 0.45·fps`, set `alias_risk = True`.
- Also flag when the strongest peak lies within 5% of `f_nyq`.
- Return the suggestion `record at ≥ {ceil(2.5 · f_expected)} fps`.

**Mains-flicker warning (India: 50 Hz mains → 100 Hz light flicker):**
- If a strong peak appears at 100 Hz, or its alias `|100 - k·fps|`, *and* it appears in the mean patch brightness rather than in the shift, flag `lighting_flicker`.
- Compute the brightness signal per patch, `mean(patch)` over t, and run the same FFT on it. This is cheap and catches a real-world failure.

### 3.7 `detect.py`: shake vs fault vs noise, and ROI

For each valid, non-background patch peak `(f, amp, snr)`:
- **noise:** `snr < SNR_MIN`. Default 6 (linear); calibrate on synthetic no-vibration clips so the false-positive rate is below 1%.
- **shake:** a background peak exists within `2·Δf` of f, with `bg_amp ≥ 0.5·amp`.
- **fault:** `snr ≥ SNR_MIN`, and the compensated amplitude at f exceeds `K_LOCAL × median amplitude at f across all valid patches` (default K_LOCAL = 3).

**Clustering:**
1. Build a boolean grid of `fault` patches at the same f (±2Δf).
2. Run `cv2.connectedComponentsWithStats` on that grid (uint8).
3. Take the largest component and convert it to a pixel bbox, padded by one patch. That is the ROI.

**Output:**
```json
{"faults": [{"f_hz": 58.4, "amp_px": 0.051, "snr": 23.1, "patches": [12,13,20],
             "roi": [x,y,w,h], "axis": [0.99,0.05]}],
 "shake":  [{"f_hz": 3.5, "amp_px": 0.61}],
 "noise_floor_px": 0.006, "alias_risk": false, "lighting_flicker": false}
```

### 3.8 `magnify.py`: band-limited Eulerian magnification (ROI only)

This is linear Eulerian video magnification (Wu et al., SIGGRAPH 2012), which is valid for small motions, exactly our regime.

1. **Crop the ROI** with a margin of 16 px, from luma `frames_y[:, y:y+h, x:x+w]`. Keep Cr/Cb from the original frames for colour output.
2. **Laplacian pyramid** per frame, L = 4 levels:
   ```python
   def lap_pyr(img, L):
       g = [img]
       for _ in range(L): g.append(cv2.pyrDown(g[-1]))
       lap = [g[i] - cv2.pyrUp(g[i+1], dstsize=g[i].shape[::-1]) for i in range(L)]
       return lap + [g[L]]
   ```
   Stack each level over time into `(T, h_l, w_l)` float32.
3. **Temporal ideal band-pass** on each level:
   ```python
   F = np.fft.rfft(level_stack, axis=0)
   freqs = np.fft.rfftfreq(T, 1/fps)
   F[(freqs < f1) | (freqs > f2)] = 0
   band = np.fft.irfft(F, n=T, axis=0)
   ```
   Use `[f1, f2] = [f_peak − bw/2, f_peak + bw/2]`, with bw from the agent (default 2 Hz).
4. **Amplify:**
   - level 0 (finest): `α_0 = 0`, because it is mostly noise;
   - levels 1..L−1: `α_l = min(α, λ_l/(8·δ) − 1)`, following Wu's bound, where `δ = amp_px / 2^l` is the displacement at that level and `λ_l` is the spatial wavelength of the level (≈ `2^(l+1)` px);
   - simpler acceptable version: `α_l = α` for l ≥ 1, plus a clip so `(1+α_l)·amp_px_l ≤ 0.5 px`;
   - the coarsest Gaussian level is not amplified.
5. **Reconstruct.** For each frame, `out = collapse(level + α_l·band_l)`. Clip to [0,1].
6. **Paste back** into the full frame with a feathered mask: Gaussian-blurred ROI rectangle, σ = 8 px.
7. **Overlay (optional, makes the demo pop):** colour the per-pixel energy of the band-passed signal red, semi-transparent, only inside the ROI.
8. **Output:** play the video at **30 fps**. A 240 fps capture then plays 8× slower, so 58 Hz appears as a visible ~7 Hz wobble. State this in the UI ("slowed 8×, motion ×α").
9. **Artifact metric for the agent.** Run the same band-pass on a background patch area, and compute `artifact_ratio = std(amplified background) / std(amplified ROI)`. A high ratio means amplified noise or shake, so the agent should lower α or narrow the band.

**Memory:** ROI 200×200 × 960 frames × 4 bytes ≈ 154 MB per level stack. That fits in Lambda at 3 GB. Never magnify the full frame on Lambda.

**Stretch (only if Day 2 is ahead of schedule):** phase-based magnification (Wadhwa et al. 2013) using a complex steerable pyramid. It gives better quality at large α but is significantly more work. **Default: skip.**

### 3.9 `severity.py`: indicative only

- Scale: `mm_per_px` comes from the user input (a known length L_mm spanning P px) or an ArUco marker of known size (`cv2.aruco`), which is optional.
- Displacement amplitude `A_mm = amp_px_orig × mm_per_px`.
- Velocity amplitude `V = 2π f A_mm` (mm/s, zero-to-peak). RMS `V_rms = V / √2` for a single sinusoid.
- Zones: the table lives in `config.py`, with a `source` field. **Fill thresholds only from the actual ISO 20816 part and machine class you cite.** Until then, show "zone: n/a (thresholds not configured)". Always label "indicative, camera-based, not a certified ISO assessment."

### 3.10 `report.py`

- `heatmap.png`: grid coloured by compensated amplitude at the fault frequency (matplotlib or OpenCV `applyColorMap`). Mark the ROI.
- `spectrum.json`: frequencies plus amplitudes for the ROI-median signal and the background (for Chart.js). Downsample to ≤ 1,000 points.
- `work_order.json` + `work_order.md`:
  - verdict: `FAULT` / `NO_FAULT` / `REVIEW`;
  - findings, with numbers from tools only;
  - agent summary (number-guarded);
  - capture conditions (fps, duration, resolution);
  - limitations;
  - timestamp.

### 3.11 `pipeline.py`: fixed baseline (needed for E5)

The **non-agent** pipeline, a deliberately naive approach representing what most demos do:
- one grid;
- no shake check;
- take the global strongest peak across all patches;
- magnify the whole frame (or the strongest patch's neighbourhood) at a fixed α = 20, bw = 2 Hz;
- no review or alias logic.

The agent version must beat this on E5. If it doesn't, the agent is pointless. **Find that out on Day 2 morning, not Monday.**

---

## 4. Server (local + EC2): `server/app.py`

**Endpoints:**

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/health` | — | `{ok, cv2_version, cv2_path, cool: bool, kleidicv: bool, llm: "gemini"/"rules"}` |
| GET | `/api/demo-clips` | — | list of `{id, title, fps, duration, has_gt}` |
| POST | `/api/jobs` | multipart: `file` or `demo_id`; `capture_fps`; optional `f_min`, `f_max`, `expected_hz` or `rpm`, `mm_per_px`, `policy` (`llm`/`rules`/`fixed`) | `{job_id}` |
| GET | `/api/jobs/{id}/events` | — | **SSE stream** of trace events, then `done` |
| GET | `/api/jobs/{id}` | — | final result JSON (verdict, findings, URLs) |
| GET | `/outputs/{job_id}/{file}` | — | static files (videos, PNG, JSON, MD) |

**Implementation notes:**
- Jobs run in a `ThreadPoolExecutor(max_workers=1)`. One job at a time keeps the box predictable.
- Each tool call emits a trace event onto a per-job `asyncio.Queue`, which the SSE endpoint drains.
- `cool` detection at startup (also printed to stdout, for the "proof it is genuine" demo shot):
  ```python
  info = cv2.getBuildInformation()
  cool = "/opt/cool" in cv2.__file__
  kleidicv = "kleidicv" in info.lower()
  print(f"[HumSight] cv2 {cv2.__version__} @ {cv2.__file__} | COOL={cool} | KleidiCV={kleidicv}")
  ```
- CORS: allow your GitHub Pages origin plus `http://localhost:*`.

**Run:** `uvicorn server.app:app --host 0.0.0.0 --port 8000`

---

## 5. Lambda endpoint (judging period, ₹0): `lambda_fn/`

### 5.1 Why the design differs from the server

| Constraint | Consequence |
|---|---|
| Function URL request/response payload limit is 6 MB (buffered) | Uploads go **directly to S3 via presigned PUT**; outputs are returned as **presigned GET URLs** |
| SSE streaming from Python Lambda isn't straightforward | Lambda runs the job **synchronously** and returns the full trace; the UI **replays** the recorded trace step by step, labelled "recorded trace replay" (honest) |
| 15 min max runtime; free tier is 400k GB-s/month | Cap clips at 4 s / 960 px; timeout 120 s; memory 3008 MB (≈ 133k free seconds/month at 3 GB) |
| Public URL can be abused | Reserved concurrency = 2, input caps, simple shared token header (`X-Demo-Token`) as a speed bump, Budgets alarm |

### 5.2 Handler routes (one function, route on path)

- `POST /upload-url` with `{filename, content_type}` → `{put_url, key}`. Presigned PUT to `s3://<bucket>/uploads/<uuid>.mp4`, expiry 10 min, max size enforced by checking `ContentLength` on job start.
- `POST /jobs` with `{key | demo_id, capture_fps, ...}`:
  1. download from S3 to `/tmp`;
  2. run the agent (Gemini or rules);
  3. upload outputs to `s3://<bucket>/outputs/<job_id>/`;
  4. return `{verdict, findings, trace, urls: {magnified, heatmap, spectrum, work_order}}`.
- `GET /health` returns the same fields as the server (it will show `cool: false`, which is honest).

### 5.3 Build the arm64 deployment package without Docker

Lambda zip limit: 250 MB unzipped (function + layers). Build on any OS by targeting the manylinux aarch64 wheels:

```bash
# lambda_fn/build_layer.sh
set -euo pipefail
rm -rf build && mkdir -p build/python
pip install \
  --platform manylinux2014_aarch64 --implementation cp --python-version 3.12 \
  --only-binary=:all: --target build/python \
  -r requirements-lambda.txt
# trim
find build/python -name "__pycache__" -type d -prune -exec rm -rf {} +
find build/python -name "*.dist-info" -type d -prune -exec rm -rf {} + || true   # careful: keep if a lib needs metadata
du -sh build/python
(cd build && zip -qr ../layer.zip python)
# function code
rm -f function.zip && zip -qr function.zip ../humsight handler.py
```

- `requirements-lambda.txt`: `opencv-python-headless==5.0.0.93`, `numpy==<pinned>`, `google-genai==<pinned>`. **No matplotlib.** Render the heatmap with `cv2.applyColorMap` inside Lambda instead.
- Alternative: build the zip on the c8g instance itself (it's arm64 Linux). This guarantees binary compatibility.
- If deleting `*.dist-info` breaks imports (some packages read their own metadata), keep them. Check that unzipped size stays < 250 MB.

### 5.4 Lambda configuration

| Setting | Value |
|---|---|
| Runtime | `python3.12` |
| Architecture | `arm64` |
| Memory | 3008 MB (raise later only if your account allows and you need it) |
| Timeout | 120 s |
| Ephemeral storage | 512 MB (default, free) |
| Reserved concurrency | 2 |
| Env vars | `BUCKET`, `GEMINI_PARAM=/humsight/gemini_key`, `LLM_MODEL=<current Gemini Flash/Flash-Lite id>`, `DEMO_TOKEN`, `MAX_DURATION_S=4` |
| IAM role | `s3:GetObject/PutObject` on `arn:aws:s3:::<bucket>/*`; `ssm:GetParameter` on that one parameter; `kms:Decrypt` for the AWS-managed `aws/ssm` key; basic CloudWatch Logs |
| Function URL | Auth type `NONE`; CORS allow-origin = `https://<you>.github.io`, methods `GET, POST`, headers `content-type, x-demo-token` |

### 5.5 S3 bucket

- **One bucket:** `humsight-<random>`, in the same region as Lambda (us-east-1).
- **Block all public access:** ON. Use presigned URLs only.
- **Lifecycle:** delete `uploads/` and `outputs/` after 7 days. Keep `demo/` (pre-uploaded demo clips plus precomputed outputs).
- **CORS on the bucket**, so the browser can PUT uploads and GET outputs:
  ```json
  [{"AllowedOrigins": ["https://<you>.github.io"], "AllowedMethods": ["GET","PUT"],
    "AllowedHeaders": ["*"], "MaxAgeSeconds": 3000}]
  ```

### 5.6 Gemini key

- SSM → Parameter Store → Create → `/humsight/gemini_key`, type **SecureString**, tier **Standard** (free).
- Lambda reads it once per cold start with `boto3.client("ssm").get_parameter(Name=..., WithDecryption=True)`. boto3 is already in the Lambda runtime, so don't bundle it.
- Locally and on EC2, use the `GEMINI_API_KEY` env var from a `.env` file that is **gitignored**.

---

## 6. Frontend: `web/`

**Layout (one page, responsive):**
1. **Header:** name, one-line tagline, a link to the GitHub repo and the video.
2. **Input card:**
   - demo clip dropdown, or file upload (≤ 25 MB, ≤ 4 s for the public endpoint);
   - **Capture fps** (required, prefilled for demos);
   - optional: expected RPM or Hz, frequency range, scale (mm per px or "known length");
   - policy toggle: `Agent (Gemini)` / `Agent (rules)` / `Fixed pipeline`, so judges can compare;
   - **Analyze** button.
3. **Trace panel:** a vertical list of steps (tool name, key numbers, agent rationale, source badge `LLM` or `RULES`). On EC2 it streams live via SSE. On Lambda it replays the returned trace at 400 ms per step, with the label "recorded trace".
4. **Results:**
   - original and magnified video **side by side**, with synchronised play/pause/seek (one JS handler drives both `currentTime`);
   - heatmap image with the ROI box;
   - Chart.js line chart: ROI spectrum vs background spectrum, the selected band shaded, a vertical line at the Nyquist limit;
   - verdict badge (FAULT / NO_FAULT / REVIEW) plus the findings table;
   - **Download work order** (MD/JSON).
5. **Footer:** "Indicative, camera-based measurement. Not a certified ISO assessment." Plus data credits.

`config.js`: `window.API_BASE = "https://<lambda-url>"`. Override with `?api=http://<ec2-ip>:8000` for the live COOL session.

Chart.js: pin a version from cdnjs (for example `chart.js/4.4.1`) via a `<script>` tag.

---

## 7. Agent

### 7.1 Tools (JSON-schema'd; each returns only measured values)

| Tool | Args | Returns | Notes |
|---|---|---|---|
| `probe_clip` | — | `fps, duration_s, width, height, f_nyquist, delta_f, texture_coverage, warnings[]` | Always first |
| `scan_motion` | `grid: "coarse"\|"fine"`, `roi?: [x,y,w,h]`, `f_min?`, `f_max?` | top-5 patch peaks `{patch, f, amp_px, snr}`, background top-3 peaks, `noise_floor_px`, runtime_ms | Coarse = 8×6 over the frame; fine = 32 px patches inside ROI |
| `compensate_shake` | `method: "subtract"\|"warp"` | `bg_peak_hz, bg_amp_px, residual_px_rms, inlier_ratio?` | Re-runs peaks on compensated motion |
| `classify_peaks` | — | detect.py output (faults, shake, noise floor, alias_risk, lighting_flicker) | |
| `magnify` | `f_center, bandwidth_hz, alpha, roi` | `video_url, artifact_ratio, alpha_effective` | |
| `assess_severity` | `f_hz, amp_px` (uses job's mm_per_px if any) | `amp_mm?, v_rms_mm_s?, zone?, note` | Returns `null`s if no scale |
| `request_review` | `reason, suggestion` | `{state: "REVIEW"}` | Terminal |
| `file_report` | `verdict, summary` | `{work_order_url}` | Terminal; summary passes the number guard |

**Hard limits:** ≤ 10 tool calls. `magnify` ≤ 3 times. Exactly one terminal tool must end the job. If the model doesn't end it, the loop forces `request_review("step limit reached")`.

### 7.2 Job state (`state.py`)

The state holds the clip, grids, motion series and latest peaks, so tools reuse earlier computation (no recomputing patch shifts). Tool results go into the trace in full. A **compact summary** (≤ 1.5 KB JSON) goes to the LLM, to keep tokens and cost minimal.

### 7.3 Decision rules (`policy_rules.py`). These are also the behaviour the LLM is asked to follow.

```
1. probe_clip
   - if warnings contain "fps from metadata" and no expected_hz: continue but mention in report
   - if expected_hz and expected_hz > 0.45*fps → request_review("aliasing risk", f"record at ≥{ceil(2.5*expected_hz)} fps")
2. scan_motion(grid="coarse")
3. if background top peak amp > 0.5 * top patch amp OR bg_amp_px > 0.05:
       compensate_shake("subtract")
       if residual_px_rms > 0.02: compensate_shake("warp")   # rotation/zoom suspected
4. classify_peaks
   - if lighting_flicker and fault f ≈ flicker alias → request_review("lighting flicker", "use daylight/DC lighting")
   - if no fault and noise_floor_px high → request_review("motion below noise floor", "closer shot / more texture / tripod")
   - if no fault → file_report("NO_FAULT", …)   # with noise floor shown as evidence
5. scan_motion(grid="fine", roi=fault.roi, f_min=f-3, f_max=f+3)   # coarse→fine active perception
6. magnify(f_center=f, bandwidth_hz=2, alpha=20, roi)
   - if artifact_ratio > 0.5: magnify(f, 1.0, alpha=10, roi)
7. assess_severity(f, amp_px)
8. file_report("FAULT", summary)
```

### 7.4 Provider interface

```python
class LLMProvider(Protocol):
    def next_action(self, system: str, history: list[dict], tools: list[dict]) -> dict:
        """Return {"tool": name, "args": {...}, "rationale": str}, or {"final": True, ...}."""
```

`provider_gemini.py`, using the `google-genai` SDK. **Check exact class names against the SDK version you pin.**

```python
from google import genai
from google.genai import types

client = genai.Client(api_key=KEY)
decls = [types.FunctionDeclaration(name=t["name"], description=t["description"],
                                   parameters=t["parameters"]) for t in TOOLS]
config = types.GenerateContentConfig(
    system_instruction=SYSTEM_PROMPT,
    tools=[types.Tool(function_declarations=decls)],
    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    temperature=0.2,
)
contents = [types.Content(role="user", parts=[types.Part.from_text(text=job_brief_json)])]
for step in range(MAX_STEPS):
    resp = client.models.generate_content(model=MODEL, contents=contents, config=config)
    calls = resp.function_calls or []
    if not calls:                      # model replied with text only → force a terminal tool
        break
    call = calls[0]
    result = TOOLS_IMPL[call.name](state, **dict(call.args))   # schema-validated first
    trace.add(step, call.name, dict(call.args), result, source="llm",
              rationale=(resp.text or "")[:400])
    contents.append(resp.candidates[0].content)
    contents.append(types.Content(role="user", parts=[
        types.Part.from_function_response(name=call.name, response={"result": compact(result)})]))
    if call.name in TERMINAL: break
```

- **Retries:** on 429/5xx, back off once (2 s). If it fails again, **switch to the rule policy mid-job**. The trace shows `source: rules (fallback: <error>)`.
- **Free-tier Gemini quotas are per minute and per day.** One job uses about 6–10 calls. Cache demo-clip runs: precompute and store their traces so judges' clicks on demos don't burn quota. The UI labels these "cached run from <timestamp>", with an option to "re-run live".
- **Privacy note for README:** free-tier Gemini API inputs may be used by Google to improve products. Only the compact numeric summaries are sent, never video frames.

### 7.5 System prompt (`loop.py`)

```
You are a vibration-analysis agent controlling measurement tools. You never compute or
invent numbers; every number you mention must come from a tool result in this conversation.
Goal: decide whether the clip shows a localized mechanical vibration fault, isolate its
frequency band, produce a magnified visualization, and file a report — or request human
review when evidence is insufficient.
Rules:
- Always start with probe_clip. Respect aliasing: if a frequency of interest exceeds 0.45×fps,
  request review with a recording suggestion.
- A peak that also appears in background patches is camera shake, not a fault.
- Prefer a coarse scan, then a fine scan inside the candidate region.
- If magnify returns artifact_ratio > 0.5, narrow the band or lower alpha (max 3 magnify calls).
- Severity is indicative only; never claim ISO certification.
- Finish with exactly one of: file_report or request_review. Max 10 tool calls.
Before each tool call, state in one sentence which measurement motivated it.
```

### 7.6 Number guard (`guard.py`)

- Extract all numbers in the LLM's `summary` and rationale text (regex `[-+]?\d*\.?\d+`).
- Each must match some numeric value in the tool results (relative tolerance 2%, or equal after rounding to the shown precision), or be a small integer ≤ 10 used as a count.
- On any mismatch:
  - replace the summary with a **template summary** generated from tool results;
  - add a trace event `guard: replaced summary (unverified number X)`.
- This guard is a good thing to show judges, as one line in the README and the video.

---

## 8. Evaluation (`eval/`)

All eval uses **lossless `.npz` frames** for E1–E4, so codec behaviour doesn't confound the results. E3b repeats E3 with the codec round-trip to show its real-world impact.

### 8.1 Synthetic grid (`make_dataset.py`, seed 42)

| Factor | Levels |
|---|---|
| fps | 60, 120, 240 |
| f (Hz) | 7.5, 15, 24.5, 40, 58.5 (skip any > 0.45·fps for E1; use them for E6) |
| amp (px) | 0.01, 0.02, 0.05, 0.1, 0.3, 1.0 |
| noise σ (on [0,1]) | 0.002, 0.005, 0.01 |
| shake | none; 3.5 Hz × 0.6 px; drift |
| duration | 4 s |

Full factorial is large, so run it in two passes:
- **Pass A:** fps=240, all f × amp × noise, no shake. That's 5×6×3 = 90 clips.
- **Pass B:** fixed f=24.5, amp=0.05, all fps × shake. That's 9 clips.

Resolution 320×240 keeps eval fast. Estimate runtime on Day 1. If it's too slow, cut levels, not tests.

### 8.2 Tests

| ID | What | Metric | Output |
|---|---|---|---|
| E1 | Frequency accuracy | `|f̂ − f|` in Hz and in bins (Δf) | Table by amp × noise; median and 95th percentile |
| E2 | Amplitude accuracy | `|Â − A| / A` | Plot: estimated vs true amplitude (log-log), one line per noise level |
| E3 | Detection floor | smallest A with detection rate ≥ 90% (10 seeds per cell) | Table: floor px per noise level. **Report whatever it is.** |
| E3b | Codec impact | E3 repeated after `VideoWriter` round-trip | Same table, codec column |
| E4 | Localisation | fault in 1 of 4 parts; top-1 ROI IoU ≥ 0.3 | Hit rate |
| E5 | Agent vs fixed | 12 clips: shake + hidden fault, shake only, fault only, nothing | Per clip: correct verdict? shake wrongly magnified? Agent (rules), agent (Gemini), fixed |
| E6 | Aliasing guard | f > 0.45·fps | % flagged REVIEW (target 100%) |
| E7 | COOL benchmark | §9.5 | Table |
| E8 | Real clip | fan + coin (§10) | Expected vs measured f; magnified video; caveats |

`run_all.py` writes `eval/results/summary.md` with every table, plus PNG plots. The README embeds these files. **Don't retype numbers by hand.**

**E5 must be designed honestly:** include cases where the agent *should* say NO_FAULT, and cases where it fails. Report the failures as well.

---

## 9. AWS: COOL on EC2 Spot (the only spend)

### 9.1 Guards first (5 minutes, do before anything else)

1. **Billing → Budgets:**
   - create a **Zero spend budget** (email alert at any spend);
   - create a **Monthly cost budget of $1** with alerts at 50% / 100%.
2. **Billing preferences:** enable "Receive Free Tier usage alerts" and email PDF invoices.
3. **Region:** use **us-east-1** for everything (EC2, Lambda, S3, SSM). This avoids cross-region data charges.

### 9.2 Subscribe to COOL

1. AWS Marketplace → search "Cloud Optimized OpenCV" → open the **Graviton4** listing (v3.1 on OpenCV 5.0, Ubuntu 24.04).
2. Read the pricing tab: software fee per instance type, and the **free trial** terms. Screenshot it for your records.
3. **Continue to Subscribe** → accept → wait for "subscription active."
4. If your account is on the Free plan and Marketplace blocks you, upgrade to the Paid plan. Budgets stay in place.

### 9.3 Launch as Spot

1. **Continue to Configuration** → region us-east-1 → **Launch through EC2** (not 1-click), so you can choose Spot.
2. Settings:

| Setting | Value |
|---|---|
| Instance type | `c8g.large` (2 vCPU, 4 GiB) |
| Key pair | create `humsight-key` (.pem), keep it safe |
| Network | default VPC, **auto-assign public IP: enable** (no Elastic IP) |
| Security group | inbound SSH 22 from **My IP**; TCP 8000 from **My IP** (open temporarily to 0.0.0.0/0 only during a live judge session, then close) |
| Storage | AMI default root volume, gp3, **Delete on termination: YES** |
| Advanced → Purchasing option | **Spot instances**; interruption behaviour **Stop**, *or* Terminate. "Stop" needs a persistent request; simplest is one-time + Terminate, keeping all results in git/S3 |
| IAM instance profile | optional: role with `s3:PutObject` on your bucket, to push benchmark results |

3. If Spot capacity is unavailable in one AZ, choose another subnet/AZ. If Spot still isn't available, use on-demand (about $0.08/h). That's still ₹20–40 for a few hours.

### 9.4 Setup on the instance (`scripts/ec2_setup.sh`)

```bash
ssh -i humsight-key.pem ubuntu@<public-ip>      # user may be 'ubuntu' on Ubuntu AMIs — check listing
ls /opt/cool/venvs/                                 # expect python_3.10 python_3.11 python_3.12
source /opt/cool/venvs/python_3.12/bin/activate
python scripts/verify_cool.py                       # prints cv2.__file__, version, KleidiCV lines
git clone https://github.com/<you>/humsight && cd humsight
pip install fastapi uvicorn[standard] python-multipart google-genai numpy==<same pin>   # NOT opencv
deactivate

# stock baseline env on the SAME instance
python3.12 -m venv ~/stock || (sudo apt-get update && sudo apt-get install -y python3.12-venv && python3.12 -m venv ~/stock)
source ~/stock/bin/activate
pip install opencv-python-headless==5.0.0.93 numpy==<same pin> fastapi uvicorn[standard] python-multipart google-genai
python scripts/verify_cool.py                       # must show site-packages cv2, COOL=False
deactivate
```

`scripts/verify_cool.py`:
```python
import cv2, platform, sys
info = cv2.getBuildInformation()
print("python", sys.version.split()[0], platform.machine())
print("cv2", cv2.__version__, cv2.__file__)
print("COOL path:", "/opt/cool" in cv2.__file__)
for line in info.splitlines():
    if any(k in line.lower() for k in ("kleidicv", "hal", "cpu/hw", "dispatched", "neon", "sve")):
        print("  ", line.strip())
print("threads:", cv2.getNumThreads())
```
Take a screenshot of both outputs. That's the COOL proof for the README and the video.

### 9.5 Benchmark (`bench/bench.py`)

- **Workload:** a fixed set of 3 clips (synthetic 240 fps 4 s at 640×360; synthetic with shake; the real fan clip).
- **Stages timed separately** with `time.perf_counter()`:
  `load+downscale`, `stabilise(warp)`, `patch_shifts(coarse)`, `patch_shifts(fine)`, `spectra`, `magnify(ROI)`, `encode`. Plus a **micro-benchmark** of individual OpenCV ops at the clip's sizes: `GaussianBlur`, `pyrDown`/`pyrUp`, `warpPerspective`, `phaseCorrelate`, `cvtColor`, `resize`, `Sobel`, `findContours`.
- **Protocol:**
  - 1 warm-up run, then **7 timed runs**, for `cv2.setNumThreads(n)` with n ∈ {1, 2};
  - report median and IQR;
  - fix CPU-heavy background processes (none on a fresh box);
  - record `uname -a`, instance type, AMI ID and date.
- **Run:**
  ```bash
  source /opt/cool/venvs/python_3.12/bin/activate && python bench/bench.py --label cool --out bench/cool.json
  source ~/stock/bin/activate               && python bench/bench.py --label stock --out bench/stock.json
  python bench/bench.py --compare bench/cool.json bench/stock.json --md bench/RESULTS.md
  ```
- **Cost per 1,000 clips** = `median_total_s × (spot_price_per_hour / 3600) × 1000`. Note the Spot price and the date you used.
- **Whatever the result, report it.** If COOL is not faster on some stage, say so and explain why (for example, NumPy FFT dominates and COOL doesn't accelerate NumPy). The COOL rubric rewards *measured value vs baseline*, and an honest null result on one stage beats an invented speedup.
- Push `bench/*.json` and `bench/RESULTS.md` to git **immediately** (Spot can be interrupted).

### 9.6 Live demo session on COOL (for recording, and if a judge asks)

```bash
source /opt/cool/venvs/python_3.12/bin/activate
export GEMINI_API_KEY=...        # from a local file, never committed
uvicorn server.app:app --host 0.0.0.0 --port 8000
# open http://<public-ip>:8000 (or web/index.html?api=http://<ip>:8000)
```
- Record the screen with the startup banner (`COOL=True | KleidiCV=True`) visible.
- **Stop or terminate the instance right after.**

### 9.7 Teardown checklist (`scripts/teardown_checklist.md`)

- [ ] EC2 instance **terminated** (not just stopped), unless needed for a scheduled judge session
- [ ] EBS → Volumes: none left "available"
- [ ] EBS → Snapshots: none you created
- [ ] EC2 → Elastic IPs: none allocated
- [ ] Spot requests: none open
- [ ] Marketplace subscription: cancel after judging (no instances = no software fee, but cancel anyway)
- [ ] S3: lifecycle on; delete the bucket after judging
- [ ] Lambda: delete after judging (or leave; idle Lambda costs ₹0)
- [ ] Billing → Bills: check next day; Budgets alerts silent

### 9.8 Expected cost (estimate, not a guarantee)

| Item | Usage | Estimate |
|---|---|---|
| c8g.large Spot | 3–5 h (recently ~$0.02–0.05/h; on-demand ~$0.08/h) | $0.06–0.25 |
| COOL software fee | within 7-day free trial | $0 |
| EBS gp3 root (~8–20 GB) | a few days, deleted on terminate | ~$0.01–0.10 |
| Public IPv4 | ~$0.005/h × 5 h | ~$0.03 |
| Lambda | within always-free 400k GB-s | $0 |
| S3 + requests | < 1 GB, a few thousand requests | ~$0.00–0.05 |
| SSM Standard parameter | free | $0 |
| Data transfer out | well under the free allowance | $0 |
| **Total** | | **≈ $0.10–0.45 ≈ ₹10–40** |

**The cost escapes:**
- forgetting to terminate (on-demand 24/7 ≈ $58/month);
- an Elastic IP left allocated;
- leftover volumes or snapshots;
- running a bigger instance.

The Budgets alarms catch all four within a day.

---

## 10. Real clip protocol (phone only, no hardware build)

**Setup:** table or pedestal fan. Tape a coin to one blade, near the tip, to create imbalance. That produces a vibration at the rotation frequency, `f_rot = RPM / 60`.

**Ground truth (pick one):**
1. **phyphox** app on a second phone placed on the fan base or housing: "Acceleration Spectrum" tool. Read the peak frequency.
2. Or the fan's rated RPM for that speed setting. This is less reliable because load changes RPM.

**Capture:**
- Phone on a tripod, or propped rigidly on a separate surface. **Don't** put it on the same table as the fan.
- **Slow-mo 240 fps**, 4–5 s. Frame the motor housing/guard with textured edges visible.
- **Lighting:** daylight or a DC/flicker-free lamp. Indian mains is 50 Hz, so many LED/tube lights flicker at 100 Hz, which can create false peaks. The flicker check flags it, but avoid it anyway.
- Record **coin on** and **coin off** at the same speed setting (two clips). That gives a natural positive and negative case.
- Transfer the file without re-compression: USB, or AirDrop/Quick Share "original quality". Messaging apps re-encode and destroy sub-pixel motion.

**Report:**
- expected f (phyphox) vs measured f;
- the magnified video;
- coin-off result (should be NO_FAULT or a much weaker peak);
- limits: single fan, single phone, rotation-frequency imbalance only.

---

## 11. Build timeline (from Sat 24 Oct, ~10:30 IST)

### Saturday: core works on synthetic data

| Time (IST) | Task | Done when |
|---|---|---|
| 10:30–11:00 | Repo skeleton, venv, install, pin; check `phaseCorrelate` names and VideoWriter codecs | `verify` script prints versions |
| 11:00–12:30 | `synth.py` + `io.py` | `synth_pump_01` written with gt.json |
| 12:30–14:30 | `motion.py` + `spectrum.py` | **Checkpoint 1:** recovers f within 1 bin and A within 10% at 0.05 px, no noise |
| 14:30–15:15 | Break / buffer | |
| 15:15–16:30 | `shake.py` (subtract + warp) + `detect.py` | Shake clip: background peak found, fault isolated, ROI correct |
| 16:30–18:30 | `magnify.py` | Magnified ROI video plays in browser; fault visibly moves, background still |
| 18:30–19:30 | **AWS:** budgets, COOL subscribe, Spot launch, `verify_cool.py` both envs, run `synth` + `motion` once under COOL, **terminate** | Screenshots saved; cost < ₹10 so far |
| 19:30–21:30 | `pipeline.py` (fixed baseline) + `eval/make_dataset.py` + E1/E2 | First tables in `eval/results/` |
| 21:30–22:30 | Record fan clips (coin on/off) in daylight tomorrow morning if it's dark now. Otherwise do it now with a flicker-free lamp | Clips on laptop, original quality |

**Go/No-go at Checkpoint 1 (by ~15:00):** if sub-pixel recovery doesn't work on *clean synthetic* data by then, something is wrong in the code (sign, windowing, reference). Debug for up to 1 more hour. If it's still broken at 16:00, switch to TraceHound.

### Sunday: agent, UI, cloud, benchmark

| Time (IST) | Task | Done when |
|---|---|---|
| 08:30–10:30 | `agent/tools.py`, `state.py`, `trace.py`, `policy_rules.py`, `loop.py` (rules first) | Rules agent completes all demo clips with sensible verdicts |
| 10:30–12:00 | `provider_gemini.py` + `guard.py` | Gemini agent runs end to end; fallback triggers when the key is removed |
| 12:00–13:00 | **E5 agent vs fixed** | **Checkpoint 2:** at least one clear case where the agent's decision changes the outcome. If not, fix the agent logic or the clip design honestly |
| 13:00–13:45 | Break | |
| 13:45–16:30 | `server/app.py` + `web/` (SSE trace, synced videos, Chart.js, heatmap, report download) | Full flow works locally in the browser |
| 16:30–18:00 | Lambda: S3 bucket + CORS + lifecycle, SSM key, build layer, deploy, Function URL, GitHub Pages | Public page runs a demo clip end to end on Lambda |
| 18:00–20:00 | **Spot COOL session #2:** bench (§9.5) + live UI recording on COOL; push results; **terminate** | `bench/RESULTS.md` committed; screen recording saved |
| 20:00–22:30 | E3/E3b/E4/E6 + real clip E8; `run_all.py` | `eval/results/summary.md` complete |

### Monday: write-up, video, submit

| Time (IST) | Task |
|---|---|
| 09:00–12:00 | README / technical report (§12), architecture diagram, failure cases section with images |
| 12:00–15:00 | Record and edit the ≤ 5-min video (script in PRD §12). Re-record weak segments |
| 15:00–17:00 | Fresh-clone test: follow your own README on a clean venv; fix gaps; pin deps |
| 17:00–19:00 | Devpost form, screenshots, links, testing instructions; precompute demo traces on Lambda |
| 19:00–23:00 | **Submit by 23:00 IST.** Then buffer for fixes (Devpost allows edits until the deadline) |
| Tue 00:00–12:15 | Emergency buffer only |

### Cut list (in this order, never cutting evaluation)

1. Contour-based patch mask (§3.3)
2. Severity zones (keep mm/s if scale given; drop zones)
3. Lambda upload path (keep demo-clip-only public endpoint; uploads on EC2 live session only)
4. Warp-based stabilisation (keep subtract)
5. Real clip E8 (keep synthetic; say so)
6. Gemini (keep the rules agent). **Last resort**: weakens the Agentic award

---

## 12. README / technical report skeleton

1. **What it is.** One paragraph plus a GIF of original vs magnified.
2. **Try it.** Public URL (Lambda + GitHub Pages); how to request a live COOL session.
3. **Architecture diagram:** perception (OpenCV tools on COOL) → decision (agent) → action (next tool / review / report).
4. **How it works.** Stages with the OpenCV functions used. Point out the OpenCV 5 specifics: USAC_MAGSAC, `findContours`/TRUCO, phase correlation (iterative if used), pyramids.
5. **Agentic design.** Tool table; an example trace where a measurement changes the next call; guardrails; number guard; fallback.
6. **COOL on Graviton4.** Setup, proof screenshot, benchmark table, cost per 1,000 clips, honest notes.
7. **Evaluation.** E1–E8 tables and plots (generated), method, and seeds.
8. **Failure cases.** At least 3, with images: low texture, codec damage, aliasing, lighting flicker, large motion.
9. **Limitations and responsible use.** Indicative severity; camera-based; not a replacement for certified monitoring.
10. **Cost and reproducibility.** Pinned deps, commands, AWS cost incurred.
11. **Credits.** Wu et al. 2012 (Eulerian video magnification); OpenCV; any third-party clips with licences.

---

## 13. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Recovered amplitude ~2× off | Amplitude scaling or peak-to-peak vs zero-to-peak mix-up | Use `amp_fit` from the sine fit (§3.6) |
| Frequency off by a constant factor | Wrong fps (container vs capture) | Pass `capture_fps` explicitly |
| Strong peak at fps/2 or random high f | Aliasing or codec block artifacts | Check Nyquist; inspect E3b |
| Peaks everywhere at the same f | Camera shake, or lighting flicker | `compensate_shake`; brightness-signal FFT |
| `phaseCorrelate` returns ~0 always | Patch not textured, or inputs not float32 | Texture filter; `.astype(np.float32)` |
| Sign of dx flipped | Argument order (ref, cur) | Keep consistent; sign doesn't affect spectra |
| Magnified video is a blurry mess | α too high for finest level / broad band | `α_0 = 0`, narrow band, clip `(1+α)δ` |
| Browser won't play output | `mp4v` codec | Try `avc1`/`VP80`; fallback GIF (§3.2) |
| Lambda "Unable to import cv2" | x86 wheels in an arm64 function, or missing libs | Rebuild with `--platform manylinux2014_aarch64`; check architecture = arm64 |
| Lambda timeout | Clip too long / fine grid too dense | Enforce 4 s cap; coarse→fine; 3008 MB memory |
| Gemini 429 | Free-tier rate limit | Back off; rules fallback; cached demo traces |
| COOL venv imports stock cv2 | Wrong venv activated, or pip-installed opencv into COOL venv | `which python`; reinstall nothing; recreate from AMI if needed |

---

## 14. Definition of done

- [ ] `python -m humsight.synth …` and `python eval/run_all.py` regenerate every result from a clean clone.
- [ ] Agent trace shows ≥ 1 measurement-driven change of next tool call (E5 documented).
- [ ] COOL proof screenshot + `bench/RESULTS.md` committed.
- [ ] Public demo works from GitHub Pages → Lambda; live COOL session documented.
- [ ] README has architecture, evaluation, ≥ 3 failure cases, limitations, costs, credits.
- [ ] Video ≤ 5 min uploaded; Devpost submitted **before Mon 23:00 IST**.
- [ ] AWS teardown checklist done (except anything kept deliberately for judging).
