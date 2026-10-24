# HumSight demo film: narration and shots

This is the script of the rendered film `video/HumSight_demo.mp4` (4:46, 1920×1080, 30 fps). The timestamps are where each line starts in the film, so you can record your own voice over the same picture. Every number comes from this repo or from the live AWS runs recorded on 24 Oct 2026.

The demo scenes are real screen recordings of https://santiwari07.github.io/HumSight/ calling the AWS Lambda endpoint. The waits are sped up, and the real run times are shown on screen (26.7 s for the pump, 45.8 s for the washing machine).

| Starts | Scene | On screen | Narration |
|---|---|---|---|
| 0:00 | cold | Real output from the live AWS run: original pump clip next to the magnified one (slowed 8×). Chips: 58.5 Hz, 0.047 px. | This pump looks perfectly still. It isn't. One part of it is vibrating fifty-eight and a half times a second, by less than a twentieth of a pixel. Nothing touched it. A handheld camera found it. |
| 0:14 | title | HumSight wordmark, animated waveform, three steps: phone video → grid of virtual sensors → real fault or shaky hand? | This is HumSight. It turns a slow-motion phone video into a grid of virtual vibration sensors, and tells you whether a machine has a real fault, or whether it was just your hand shaking. |
| 0:25 | 01 · The problem | Row of machines, only two with sensors. Then a shaking phone → “FALSE ALARM: a healthy machine looks broken”. | Machines vibrate abnormally before they fail. Contact sensors catch that, but they are fitted one machine at a time, so many machines are never monitored. Video should help. But the classic trick, magnifying all motion in the video, also magnifies camera shake. Film handheld, and a healthy machine looks broken. |
| 0:44 | 02 · Who it's for | Four cards: maintenance technicians, plant managers, field-service engineers, students and labs. | It's for maintenance technicians checking an unmonitored machine with the phone they already carry. Plant managers deciding which machines need a real sensor. Field engineers who need visual proof for a customer. And students learning frequency and aliasing on real video. |
| 0:59 | 03 · Our idea | Pump frame with the 8×6 patch grid drawing in; one patch → motion wave → FFT; the real heatmap from the AWS run fades in. “48 virtual sensors · 0 wires”. | Here's the idea. We split the frame into patches, and every patch becomes a sensor. For each one, OpenCV 5 measures motion smaller than a twentieth of a pixel, frame by frame, and turns it into a frequency, an amplitude and a signal-to-noise ratio. One video, forty-eight sensors, nothing wired to the machine. |
| 1:19 | 04 · How we solve it | The real 7-step trace (docs/example_trace.md) step by step with measured chips, then the repo's agent_workflow.svg and the guardrail badges. | Then an agent decides what to measure next, based on what it just measured. On this clip, the whole frame moves about half a pixel at three and a half hertz. That's the hand, not the machine, so it removes the shake first. Underneath, a fifty-eight and a half hertz peak appears in one region only. It zooms in with a finer scan, magnifies just that band, and files a work order. Every number comes from OpenCV. The language model only picks the next step, and a guard rejects any number that no tool produced. |
| 1:48 | 05 · How it runs on AWS | Animated AWS architecture: Browser → Function URL → Lambda (arm64) ↔ S3, SSM, CloudWatch, Budgets, Gemini (numbers only, never frames). Ends on the repo's architecture.svg. | Here's how it runs on AWS. The web page is static, on GitHub Pages. When you press run, it calls a Lambda Function URL. Lambda, on arm64 Graviton, pulls the clip from S3, runs the OpenCV pipeline and the agent, writes the magnified video, heatmap and spectrum back to S3, and returns short-lived presigned links. The browser loads the results straight from S3, and uploads go straight to S3 too. The Gemini key sits in SSM Parameter Store, CloudWatch logs every run, and a budget caps the cost. Only compact numbers ever reach Gemini. Never video frames. |
| 2:29 | 05 · How it runs on AWS | evidence/aws/03_lambda_health (cv2 5.0.0, aarch64), then evidence/aws/04_cloudwatch_invocations with the /jobs rows ringed. | And it's live. This is the public endpoint answering: OpenCV 5 on aarch64. These are real Lambda invocations in CloudWatch, one per analysis. |
| 2:40 | 06 · Live demo | Screen recording of the live site (24 Oct 2026): pick the pump clip, setup 240 fps, Agent with rules, Run. | So let's run it. This is the live site, recorded for real. We pick the pump test clip. It's synthetic, so we know the exact truth: a fifty-eight and a half hertz fault, hidden under handheld shake. Two hundred forty frames per second, agent with rules, run. |
| 2:57 | 06 · Live demo | Same recording sped up while Lambda runs; a clock shows the real elapsed seconds. | It's on Lambda now. We've sped up the wait. The real run took about twenty-seven seconds. |
| 3:04 | 06 · Live demo | Alarm card (zoomed), then Video evidence, Spectrum, Heatmap, Activity log and Work order tabs. | Alarm. Localized vibration at fifty-eight and a half hertz, zero point zero four seven pixels, with the camera shake removed. In the magnified video, only the faulty region moves. The spectrum separates shake from fault, the heatmap shows where, and the activity log shows every decision with the measurement behind it. The work order is ready for a maintenance ticket. |
| 3:26 | 07 · Why the agent matters | Live re-run with the Fixed pipeline: it reports 3.509 Hz, 0.5621 px. Callout: “3.5 Hz = the camera shake”. | Now the same clip through a fixed, magnify-everything pipeline. It reports a fault at three and a half hertz. That's the camera shake. Exactly the mistake HumSight is built to avoid. |
| 3:38 | 08 · When it can't tell | Live run of the 130 Hz / 240 fps clip: Inconclusive, “Record at >= 325 fps”. | Next, a one hundred thirty hertz fault filmed at two hundred forty frames per second. The camera is too slow to measure it honestly, so HumSight says Inconclusive, and asks for at least three hundred twenty-five frames per second. |
| 3:52 | 09 · Real footage | Live run on the real washing-machine clip (CC BY-SA 4.0): 22.715 Hz, shake 3.875 Hz removed; run took 45.8 s. | And real footage: a washing machine, filmed handheld at one hundred twenty frames per second. The hand shake at three point nine hertz is removed, and a vibration at twenty-two point seven hertz is found. The display's fourteen hundred R P M implies twenty-three point three. Indicative, not a validated benchmark. |
| 4:10 | 10 · Results | Animated E5 bars (12/12, 11→12/12, 5/12), tiles for E1, E4, E6, and the COOL null result 0.98×–1.03×. | We measured it. On twelve test clips, the agent was right twelve times out of twelve. The fixed pipeline, five, and six times it magnified the shake. Median frequency error: five thousandths of a hertz. We also ran the pipeline under COOL on a Graviton4 instance. It gave no meaningful speed-up, and we report that as measured. |
| 4:31 | close | Limitations, then end card with the live URL and the GitHub repo. | HumSight is indicative, not a certified ISO measurement, and it says so on every report. It's a first screen that tells you which machine deserves a real sensor. See what your machines are humming. |

## What not to say

| Don't say | Why |
|---|---|
| "We use YOLO" or "object detection" | There is no YOLO or detection model anywhere in the code |
| "Deployed at a plant" or "Pump 7" as a real event | The pump clip is synthetic. The README story is a scenario |
| "ISO certified" or "accurate on real machines" | Indicative only. The one real clip has no measured reference |
| "COOL made it faster" | The benchmark measured 0.98× to 1.03× total, a null result |
| "Gemini improved after our fix" | The fix never fired in the rerun. E5.md says the change is not credited |
| Any market size or failure-cost statistic | None is in the repo. Add one only with a cited source |

## Fact sheet

| Number in the VO | Value in the repo | Source |
|---|---|---|
| fault frequency / amplitude (truth) | 58.5 Hz, 0.05 px; shake 3.5 Hz, 0.6 px | `demo_clips/pump_shake_fault/demo.json` |
| "less than a twentieth of a pixel" | 0.04657 px found | `evidence/aws/live_page/04_diagnosis.jpg` |
| background vs strongest patch | 0.545 px vs 0.562 px | `evidence/aws/live_page/05_log.jpg`, `docs/example_trace.md` |
| diagnosis | 58.497 Hz, 0.04657 px, SNR 45.81, shake 3.509 Hz removed | `evidence/aws/live_page/04_diagnosis.jpg`, and the film's own live recording |
| run times shown in the film | pump 26.7 s, washing machine 45.8 s on Lambda | the sidebar of the live site in the film's recordings (24 Oct 2026) |
| fixed pipeline on the pump clip | FAULT at 3.509 Hz (0.5621 px) | `docs/example_trace.md`, and the film's live recording |
| aliasing clip | REVIEW, "record at >= 325 fps" | `docs/example_trace.md` |
| real washing machine | 22.715 Hz, shake 3.875 Hz, 120 fps; 1400 RPM = 23.33 Hz | `evidence/aws/live_page_real/04_diagnosis.jpg`, `demo_clips/real_washer/demo.json` |
| ≤ 10 tool calls, number guard | as stated | `README.md` (How it works, agent guardrails) |
| Lambda arm64, Function URL, S3, SSM, CloudWatch | as stated | `evidence/aws/README.md` |
| OpenCV on Lambda | `cv2_version 5.0.0`, `aarch64` | `evidence/aws/03_lambda_health/` |
| E5 | rules 12/12; Gemini 11/12, then 12/12; fixed 5/12, shake magnified 6 times | `eval/results/E5.md` |
| E1 median frequency error | 0.0048 Hz at 0.05 px, noise σ 0.005 (said as 0.005 Hz) | `eval/results/summary.md` |
| COOL vs stock | 0.98× to 1.03× total on c8g.large (Graviton4) | `bench/RESULTS.md`, `docs/COOL.md` |
