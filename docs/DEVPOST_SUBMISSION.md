# Devpost submission text (draft)

Copy into the Devpost form. Fields marked **TODO** depend on the deployment and the video, which are not finished; fill them in before submitting (deadline: 26 Oct 2026, 11:59 p.m. Pacific Time). Do not paste any number that is not in a generated file.

**Project name:** HumSight

**Tagline:** See what machines are humming.

**Paths entered:** Agentic Vision with OpenCV 5; Best Use of COOL (only if the Graviton4 benchmark is completed, otherwise leave this one out).

## Inspiration

Machines vibrate abnormally before they fail, but a video of one looks perfectly still, and naively magnifying "all motion" also magnifies camera shake and compression noise. We wanted a phone video to become a grid of virtual vibration sensors that can tell a real fault from shake, and say when it cannot tell.

## What it does

OpenCV 5 phase correlation measures sub-pixel motion on every patch of every frame; an FFT gives frequency, amplitude and SNR. A bounded agent decides what to do from those measurements: it compensates camera shake, rejects shake peaks, refines a fault candidate with a fine scan, magnifies only the faulty region in the chosen band, and files a work order, or asks for human review (aliasing, lighting flicker, low texture, a noise floor too high to trust a negative). The model never invents a number: tools return only measured values and a number guard replaces any summary containing an unverified number.

## How we built it

Python, OpenCV 5.0 (`phaseCorrelateIterative`, `calcOpticalFlowPyrLK`, `findHomography(USAC_MAGSAC)`, `warpPerspective`, pyramids, `connectedComponentsWithStats`), NumPy FFT, FastAPI with Server-Sent Events, a static web page, Gemini through `google-genai` with a deterministic rules fallback, and an AWS Lambda arm64 handler with S3 and SSM. A synthetic generator with exact ground truth (Fourier-shift sub-pixel motion) drives the whole evaluation. Diagrams: `docs/architecture.svg`, `docs/agent_workflow.svg`.

## Challenges

Plain `cv2.phaseCorrelate` gave gross outliers on our test textures; the iterative variant with a Hann pre-window and a tuned `L2size` fixed it. Deterministic uint8 rounding biases phase correlation on noise-free clips. Lossy codecs destroy sub-pixel motion and can fake low-frequency "faults". Aliasing cannot be detected unless the user supplies the expected frequency. All four are documented with data.

## Accomplishments

Numbers to quote come from `eval/results/summary.md` (generated): frequency and amplitude accuracy, detection floor per noise level, 24/24 localisation hits, 12/12 correct verdicts for the agent against 5/12 for a fixed pipeline that magnifies shake, and 9/9 aliasing cases sent to review. All on synthetic ground truth; E8 (a real fan clip) is **TODO**.

## What we learned

Honest uncertainty is a feature: the most useful agent decisions were the refusals (`REVIEW`), and the most informative results were the failure cases.

## What's next

A real-footage evaluation, a live Gemini evaluation, ISO 20816 thresholds from a cited machine class, phase-based magnification.

## Built with

`opencv`, `python`, `numpy`, `fastapi`, `aws-lambda`, `amazon-s3`, `aws-systems-manager`, `amazon-ec2`, `aws-graviton`, `cool-opencv`, `gemini`, `javascript`, `chart.js`, `github-pages`  (list only what is deployed when you submit).

## Links (TODO)

- Code repository: https://github.com/SanTiwari07/HumSight
- Public endpoint or live screen-share arrangement: **TODO**
- Video (≤ 5 minutes, public or unlisted): **TODO, to be recorded after deployment**
- Technical report: `docs/TECHNICAL_REPORT.md`

## Team (TODO)

Names, roles and the team bio required by the form.
