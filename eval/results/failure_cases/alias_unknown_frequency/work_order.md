# HumSight work order: FAULT

_2026-10-24T05:34:08+00:00_ · policy: rules

## Summary
Localized vibration at 96.001 Hz with amplitude 0.18284 px (SNR 521.89) in ROI [64, 32, 128, 96].

## Findings

| f (Hz) | amplitude (px) | SNR | ROI [x,y,w,h] |
|---|---|---|---|
| 96.001 | 0.18284 | 521.89 | [64, 32, 128, 96] |

## Capture

- fps: 240.0
- duration: 4.0 s
- resolution: 256x192

## Limitations

- Indicative, camera-based measurement. Not a certified ISO assessment.
- Frequency is valid only up to Nyquist (fps/2); record at >= 2.5x the fault frequency.
- Amplitude is in image pixels unless a scale reference was given.
- Compression, low texture and lighting flicker can mask or fake sub-pixel motion.
