# Demo film

`HumSight_demo.mp4`: 4:47, 1920×1080, 30 fps, H.264 + AAC, about 42 MB, with no burned-in subtitles. `HumSight_demo.en.srt` holds the narration as optional subtitles: upload it to YouTube as a caption track so viewers can turn it on. The narration with timestamps and the source of every number are in [../docs/VIDEO_SCRIPT.md](../docs/VIDEO_SCRIPT.md).

## What is real in it

- **Demo scenes** are screen recordings of the public site https://santiwari07.github.io/HumSight/, made on 24 Oct 2026 by a headless Chrome that clicked through four runs: the pump clip with the agent, the same clip with the fixed pipeline, the 130 Hz aliasing clip, and the real washing-machine clip. Every result on screen came back from the AWS Lambda endpoint. Only the waits are sped up, and the real run times (26.7 s and 45.8 s) are labelled.
- **The cold open, the heatmap and the patch grid** use the output files that Lambda wrote to S3 for the pump run.
- **The agent scene** shows the real trace from `docs/example_trace.md`. The AWS proof scene shows `evidence/aws/03_lambda_health` and `04_cloudwatch_invocations`. The diagrams are `docs/architecture.svg` and `docs/agent_workflow.svg`.
- **The voice** is the offline Windows "Microsoft Mark" text-to-speech voice. You can record your own voice over the same picture with the timestamps in `docs/VIDEO_SCRIPT.md`.

## Rebuilding it (`source/`)

Requires Node, Python with Pillow, ffmpeg and a Playwright Chromium.

1. `npm i playwright-core@1.55.0`
2. `node capture.js rec`: records the four live runs as screencast frames.
3. `node fetch_media.js pump_shake_fault media/pump`, then extract frames with `ffmpeg -i media/pump/original.webm -vf scale=1152:648 media/pump/original/%04d.jpg` (the same for `magnified_1.webm`).
4. Copy `docs/*.svg`, the two `evidence/aws` screenshots (as `health.png` and `cloudwatch.png`) and the run's `heatmap.png` into `assets/`.
5. `powershell -File tts.ps1 -Dir . -Voice Mark -Rate 1.1`: one WAV per scene in `vo/`.
6. `python build_timing.py`: writes `timing.js` and `recindex.js`.
7. `python mix_audio.py`: writes `narration.wav`.
8. `node render.js video silent.mp4 30`, then `ffmpeg -i silent.mp4 -i narration.wav -map 0:v -map 1:a -c:v copy -c:a aac -b:a 192k -shortest -movflags +faststart HumSight_demo.mp4`.

`film.html` opened in a browser (without `?render=1`) is also an interactive player with play/pause, a seek bar and a scene list.
