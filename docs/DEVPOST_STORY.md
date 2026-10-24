## Inspiration

You are the maintenance technician on nights at a water-treatment plant. Pump 7 sounds a little different tonight. To the eye it looks exactly as it always does: perfectly still.

Pump 7 has no vibration sensor. Wired sensors go on the few most critical machines, and Pump 7 is not one of them. A vibration specialist means a ticket and a wait, and a bearing that is going does not wait.

So you take out your phone, switch to slow motion at 240 frames per second, and film the pump for three seconds. You are holding the phone in your hand. Your arm sways about half a pixel, three and a half times a second. The fault you are looking for moves the bearing cap by a twentieth of a pixel.

A magnifying app would make your hand look like the fault. A vibration report that cannot tell the two apart is worse than none: it sends you to strip down a healthy pump, or it teaches you to stop trusting the report.

**HumSight was built for that check.** Cameras stopped being the problem years ago. Every technician carries one that records at 240 fps. What is missing is the step after the video: **a measurement that knows what it is looking at.**

The scale of the problem is not small:

- **$1.4 trillion** is what unplanned downtime costs the world's 500 largest companies each year, 11 % of their revenue (Siemens, *The True Cost of Downtime 2024*).
- **Over 40 %** of the world's electricity is used by electric motor-driven systems: the pumps, fans and compressors that run every plant (International Energy Agency, 2011).
- **6 of 12** test clips are ones on which a fixed "magnify the motion" pipeline reported camera shake as the machine fault. That is the failure we set out to remove.

![HumSight: a vibration check from any camera. A case card for a washing machine filmed handheld at 120 fps reads: Alarm, localized vibration at 22.7 Hz, 0.128 px at the drum. Camera shake at 3.9 Hz, 0.24 px, removed first.](https://raw.githubusercontent.com/SanTiwari07/HumSight/main/docs/brand/banner.jpg)

## What it does

HumSight turns every patch of a video into a virtual vibration sensor, and then reasons about what those sensors show, the way an analyst would.

1. **Measure.** OpenCV 5 phase correlation measures sub-pixel motion in every patch of every frame. An FFT turns each patch into a frequency, an amplitude and a signal-to-noise ratio.
2. **Decide.** An agent reads those numbers and chooses the next measurement. Is the whole frame moving? Remove the camera shake first. Is there a peak left in one place? Scan that region more finely. Is the frequency near the camera's limit, or is the light flickering? Stop and ask for a better recording.
3. **Show.** Magnify only the faulty region, only in the fault's frequency band, so a person can see what was measured. Add a heatmap, a spectrum, the findings and a work order.

The technician gets **a diagnosis, not a wobbling video**: a verdict in plain words (Alarm, Normal or Inconclusive), the numbers behind it, the steps that produced it, and one recommended action.

About thirty seconds after the upload, the pump clip comes back: *Alarm. Localized vibration at 58.5 Hz on the bearing cap, 0.047 px. Camera shake at 3.5 Hz was measured, removed and rejected.* On the next pump the answer is *Inconclusive*, because that pump turns faster than the camera can sample and any frequency it measured could be an alias. HumSight does not guess. It asks for a faster recording.

**Three promises**

- **It separates the camera from the machine, and shows its working.** Shake is measured on the background, removed, and named in the report. A result that hides the shake would not be believable.
- **The language model never invents a number.** OpenCV and NumPy produce every number. The model only chooses the next tool and writes the summary. A number guard checks every number in that summary against what the tools returned, and replaces the summary with a template if one does not match.
- **When it cannot tell, it says so.** Aliasing, lighting flicker, low texture, or a noise floor too high to trust a negative all end in *Inconclusive*, with what to change in the next recording. Never a forced guess.

### A walk through the app

Every screen below is a real browser capture of the public site, with the analysis running on AWS Lambda, taken on 24 October 2026.

**1. Choose a recording.** Reference clips, each with its ground truth and the outcome to expect, or upload your own slow-motion video.

![Choose a recording: reference clips with their expected outcome](https://raw.githubusercontent.com/SanTiwari07/HumSight/main/evidence/aws/live_page/01_choose_recording.jpg)

**2. Set up.** Only the capture frame rate is required. Running speed or an expected frequency lets HumSight check for aliasing.

![Setup: capture frame rate, machine details, method](https://raw.githubusercontent.com/SanTiwari07/HumSight/main/evidence/aws/live_page/02_setup.jpg)

**3. Analysis on AWS Lambda.** The whole OpenCV 5 pipeline and the agent run in one Lambda invocation. The steps are replayed when the job returns.

![Running on AWS Lambda, the stages of the analysis](https://raw.githubusercontent.com/SanTiwari07/HumSight/main/evidence/aws/live_page/03_analysis_running.jpg)

**4. A diagnosis.** The verdict in plain words, the recommended action, and the readings behind it: dominant frequency, displacement, signal to noise, and the camera shake that was removed.

![Diagnosis: Alarm, localized vibration at 58.497 Hz, camera shake removed, key readings below](https://raw.githubusercontent.com/SanTiwari07/HumSight/main/evidence/aws/live_page/04_diagnosis.jpg)

**See it.** The original next to a slowed copy in which only the fault region, in only the fault's band, is amplified.

![Original next to the magnified fault region](https://raw.githubusercontent.com/SanTiwari07/HumSight/main/evidence/aws/live_page/05_video.jpg)

**Spectrum.** The background (shake) in orange, the fault region in blue, the magnified band shaded.

![Spectrum: shake peak near 3.5 Hz, fault band at 58.5 Hz](https://raw.githubusercontent.com/SanTiwari07/HumSight/main/evidence/aws/live_page/05_spectrum.jpg)

**Heatmap.** Each cell is a virtual sensor. The box is the region the fine scan isolated.

![Heatmap of vibration amplitude per patch](https://raw.githubusercontent.com/SanTiwari07/HumSight/main/evidence/aws/live_page/05_heat.jpg)

**Activity log.** Every tool the agent called, why, and what OpenCV measured. Step 3 is where the background motion made it remove the shake.

![Activity log: seven tool calls with the reason and the measured numbers](https://raw.githubusercontent.com/SanTiwari07/HumSight/main/evidence/aws/live_page/05_log.jpg)

**Work order.** The verdict, findings, capture settings and limitations as Markdown or JSON, ready to attach to a maintenance ticket.

![Work order with downloads and limitations](https://raw.githubusercontent.com/SanTiwari07/HumSight/main/evidence/aws/live_page/05_wo.jpg)

### On real footage

The same flow on a real video: a washing machine filmed **handheld** on a phone at 120 fps ([source](https://commons.wikimedia.org/wiki/File:Washing_machine_120fps.webm), CC BY-SA 4.0). HumSight measured the hand shake at 3.9 Hz on the background, removed it, and found a localized 22.7 Hz vibration at the drum. The machine's display reads 1400 RPM, which is 23.3 Hz. That display shows the set spin speed, not a measurement, so this result is indicative, not an accuracy figure.

![Washing machine: Alarm at 22.7 Hz, shake at 3.9 Hz removed](https://raw.githubusercontent.com/SanTiwari07/HumSight/main/evidence/aws/live_page_real/04_diagnosis.jpg)

![Washing machine: original and magnified drum](https://raw.githubusercontent.com/SanTiwari07/HumSight/main/evidence/aws/live_page_real/05_video.jpg)

## How we built it

**Measurement first.** Eight tools wrap the OpenCV 5 pipeline. Each returns only measured numbers, compacted to at most 1.5 KB, so the model never sees a video frame.

- `probe_clip`: can this recording be trusted? Frame rate, Nyquist limit, frequency resolution, texture coverage, flicker.
- `scan_motion`: what moves, where, at what frequency? `cv2.phaseCorrelateIterative` on Hann-windowed patches, then an FFT per patch.
- `compensate_shake`: is the camera moving? Remove it. Median background subtraction, or `goodFeaturesToTrack` + `calcOpticalFlowPyrLK` + `findHomography(USAC_MAGSAC)` + `warpPerspective`.
- `classify_peaks`: shake, fault or noise? Peaks against the noise floor (SNR 6) and the background, alias and flicker checks, and `connectedComponentsWithStats` for the region.
- `magnify`: show it to a person. A `pyrDown`/`pyrUp` Laplacian pyramid with an FFT band-pass (Eulerian video magnification, Wu et al., SIGGRAPH 2012), region only, with an artefact check.
- `assess_severity`: how bad? Displacement and, given an image scale, velocity in mm/s. Indicative only.
- `request_review`: stop, the evidence is not good enough. Ends in *Inconclusive*.
- `file_report`: write it down. Refuses a verdict filed without a current classification.

**An agent that decides from the measurements.** Gemini (`gemini-flash-latest`, with function calling) chooses the next tool, inside a budget: at most 10 tool calls and 3 magnifications, with arguments checked against each tool's schema. The tenth call is forced to a terminal tool, and an Alarm without the evidence behind it becomes *Inconclusive*. A deterministic rules policy calls the same tools, so if Gemini fails partway through a job the rest runs on rules and the activity log says so.

**A worked example, the pump.** Every step below is real, from the live run in the screenshots above.

1. `probe_clip`: 240 fps, measurable up to 120 Hz, texture 100 %.
2. `scan_motion` (coarse): strongest patch 0.562 px at 3.509 Hz, background 0.545 px at 3.509 Hz.
3. `compensate_shake`: the background moves as much as the patch, so the whole frame moves. Shake 3.509 Hz, 0.5455 px; residual at that frequency 0.00783 px.
4. `classify_peaks`: fault 58.5 Hz, 0.0469 px, SNR 25.31; shake at 3.509 Hz rejected.
5. `scan_motion` (fine): 58.497 Hz, 0.04657 px, SNR 45.8 in a 160 x 128 px region.
6. `magnify`: only that band in that region, gain 20, slowed 8 times, artefact ratio 0.086.
7. `file_report`: the evidence is sufficient. Alarm.

The fixed pipeline on the same clip reports a fault at 3.509 Hz, 0.562 px. That is the technician's hand.

**Running on AWS.** The same `humsight/` library runs on a laptop, on Lambda and on a COOL instance; the server and the Lambda handler only wrap it.

- **AWS Lambda** (arm64, python3.12, 3008 MB) behind a Function URL runs the whole pipeline and the agent in one invocation.
- **Amazon S3** (public access blocked, presigned URLs, 7-day expiry) holds the demo clips, uploads and outputs.
- **SSM Parameter Store** holds the Gemini key as a SecureString.
- **CloudWatch Logs and AWS Budgets** cover operations and spend.
- **EC2 Spot, `c8g.large` on Graviton4,** ran the whole pipeline and web app inside Cloud-Optimized OpenCV (COOL), with stock OpenCV on the same instance as the baseline.
- The page is static HTML, CSS and JavaScript on GitHub Pages, calling the Lambda Function URL.

![AWS CLI: the Lambda function, its Function URL, the arm64 layer and the SSM parameter](https://raw.githubusercontent.com/SanTiwari07/HumSight/main/evidence/aws/01_lambda_deployment/screenshot.png)

*The function: `humsight`, arm64, python3.12, 3008 MB, Active, with its Function URL, the arm64 dependency layer and the Gemini key as an SSM SecureString.*

![curl /health on the Function URL](https://raw.githubusercontent.com/SanTiwari07/HumSight/main/evidence/aws/03_lambda_health/screenshot.png)

*The endpoint answering: OpenCV 5.0.0 on aarch64, in Lambda.*

![S3 bucket listing of the demo clips](https://raw.githubusercontent.com/SanTiwari07/HumSight/main/evidence/aws/02_s3_bucket/screenshot.png)

*S3: the demo clips the page offers, and the outputs each job writes.*

![CloudWatch REPORT lines](https://raw.githubusercontent.com/SanTiwari07/HumSight/main/evidence/aws/04_cloudwatch_invocations/screenshot.png)

*CloudWatch: one Lambda invocation per analysis, 22.9 s and 22.5 s for the pump runs, 41.3 s for the washing machine.*

During the screenshot run the page received 12 responses from AWS: `GET /health`, `GET /demo-clips` and `POST /jobs` from the Function URL, then the magnified video, heatmap, spectrum and original clip from S3.

**Built with:** OpenCV 5.0 (`opencv-python-headless`), COOL 5.1.0-dev on Graviton4, NumPy FFT, Gemini (`google-genai`), FastAPI with Server-Sent Events, AWS Lambda, S3, SSM, CloudWatch, EC2 Spot, Chart.js, GitHub Pages, pytest.

## Challenges we ran into

**Telling the camera from the machine.** The fault moves the image by 0.05 px and the hand moves it by 0.6 px. A fixed pipeline that magnifies the strongest motion reports the hand. The fix was to measure the background first, and to let that measurement decide whether to compensate for shake before anything is classified.

**Keeping the language model honest.** A model that writes the summary can write a number that no tool produced. We built a number guard that checks every number in the summary and the reasoning against what the tools returned, replaces the summary with a template when one does not match, and caps the agent at 10 tool calls with schema-checked arguments.

**Knowing when to say nothing.** Aliasing, lighting flicker, low texture and a noise floor that is too high all produce confident-looking numbers that mean nothing. Teaching the agent to stop and ask for a better recording took as much work as teaching it to find a fault. In evaluation E6, 9 of 9 aliased recordings were sent to review when the expected frequency was given.

**Compression.** Lossy re-encoding destroys sub-pixel motion and can invent low-frequency motion of its own. After re-encoding, 3 to 6 of 10 empty clips raised a false alarm (E3b). We kept this as a documented failure case, and the report tells the user to transfer the original file.

**A null result on COOL.** We ran HumSight inside Cloud-Optimized OpenCV on Graviton4 expecting a speed-up. Totals across the pipeline stages were 0.98x to 1.03x of stock OpenCV, within the run-to-run spread, because the stages are dominated by per-patch FFTs and NumPy. We reported it as a null result.

**Real footage is thin.** The accuracy numbers come from synthetic clips with exact sub-pixel ground truth (a Fourier shift). Real clips with a measured reference are hard to find, so the single real clip is labelled indicative everywhere.

**Running it in the cloud on a budget.** The public endpoint takes clips of up to 4 seconds, to keep Lambda time and cost bounded, and we set a zero-spend budget and a $1 budget with alerts before deploying anything.

## Accomplishments that we're proud of

- **12 of 12 against 5 of 12.** On 12 test clips, the agent was right 12 times and the fixed pipeline 5 times. With shake and a real fault, the agent got 3 of 3 and the fixed pipeline 0 of 3, because it magnified the shake.

![12 test clips. The agent was right 12 times, a fixed pipeline 5 times.](https://raw.githubusercontent.com/SanTiwari07/HumSight/main/docs/brand/results.png)

- **It finds motion far below what an eye can see.** On the live Lambda deployment the pump demo returned 58.497 Hz against a true 58.5 Hz, with the camera shake rejected. The smallest motion detected 90 % of the time was 0.02, 0.05 and 0.1 px at noise 0.002, 0.005 and 0.01, with no false alarm on 10 empty clips.
- **It is accurate where we can check it.** Median frequency error is 0.005 Hz at 0.05 px of motion (E1), median amplitude error is 3.2 % at 0.1 px and 6.3 % at 0.05 px (E2), and 24 of 24 faults were found in the right part of the frame (E4).
- **The model never touched a number.** With Gemini, the agent chose all 84 tool calls itself in the live evaluation, with no fallback to rules. It scored 11 of 12, then 12 of 12 on a rerun. A code change was made between the two runs, but it was never triggered in the rerun, so we report the improvement as ordinary run-to-run variation and do not credit it.
- **A real, working AWS deployment.** Lambda, S3, SSM and CloudWatch serve every analysis, and the public page has been calling them since 24 October 2026.
- **COOL, honestly measured.** The whole pipeline and web app ran inside COOL on a Graviton4 `c8g.large` (`cv2 5.1.0-dev`, KleidiCV 0.7.0, SVE and NEON), and the result is reported with its method and caveats, not rounded up. `resize` was 1.42x faster and `cvtColor` 0.83x. Compute cost was about $0.07 per 1,000 clips for both.

![verify_cool.py in the COOL environment](https://raw.githubusercontent.com/SanTiwari07/HumSight/main/evidence/01_cool_verify/screenshot.png)

*COOL loaded: `cv2 5.1.0-dev` from `/opt/cool`, KleidiCV 0.7.0, SVE and NEON.*

- **33 passing tests,** and every number in the README is generated by a script in the repository.

## What we learned

- **A measurement is only useful if it knows its own limits.** The most valuable output of HumSight is not the Alarm. It is the *Inconclusive* with a reason, and the line that says what the smallest motion it could have seen was.
- **Let the language model decide, and let the tools measure.** Giving Gemini only compact numbers, a budget, and a guard on what it may say made it useful and safe at the same time. It also meant that when the model failed, a rules policy could take over the same tools without changing the answer's meaning.
- **An agent beats a fixed pipeline because of order, not because of better math.** Both used the same OpenCV measurements. The agent was right on 12 of 12 clips because it chose to measure the background first.
- **Report the null result.** The COOL benchmark did not speed this workload up. Saying so, with the method and the per-stage tables, is more useful than a favourable figure.
- **Deployment lessons.** Building the arm64 Lambda layer without Docker, keeping secrets in SSM, expiring objects after 7 days and setting budgets first are all in `docs/DEPLOYMENT.md`, with every problem we hit and its fix.

## What's next for HumSight: See What Machines Are Humming

Today HumSight is **indicative, not certified.** Every report says *Indicative, camera-based measurement. Not a certified ISO assessment* and recommends a contact accelerometer before any shutdown decision. Next:

- **A real-footage benchmark** against a contact accelerometer or a phone's own motion sensor. The protocol is written (E8).
- **ISO 20816 zones** from a cited machine class, with an image scale from a reference object, so the report gives velocity in mm/s.
- **Phase-based magnification,** for larger amplification with fewer artefacts.
- **Fixed cameras and trends:** scheduled clips from a CCTV or Raspberry Pi camera, a trend per machine, and an alert on change.
- **A capture guide in the browser** that checks frame rate, framing and steadiness before recording.
- **Work orders sent straight to a maintenance system,** and the tools offered over MCP so any agent can call them.
- **COOL at a larger scale:** bigger Graviton instances, batch processing, and throughput per dollar against x86.

**Links**

- Live demo: https://santiwari07.github.io/HumSight/
- Video: https://youtu.be/VsnxVrgh-zU
- Code: https://github.com/SanTiwari07/HumSight
- Technical report: https://github.com/SanTiwari07/HumSight/blob/main/docs/TECHNICAL_REPORT.md
- Evaluation results: https://github.com/SanTiwari07/HumSight/blob/main/eval/results/summary.md

**HumSight. See what machines are humming.**
