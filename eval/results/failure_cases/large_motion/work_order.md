# HumSight work order: FAULT

_2026-10-24T05:50:10+00:00_ · policy: rules

## Summary
Localized vibration at 15.0 Hz with amplitude 5.63568 px (SNR 7505.15) in ROI [96, 32, 96, 96].

## Findings

| f (Hz) | amplitude (px) | SNR | ROI [x,y,w,h] |
|---|---|---|---|
| 15.0 | 5.63568 | 7548.47 | [96, 32, 96, 96] |
| 104.978 | 0.08597 | 6.32 | [32, 32, 96, 96] |
| 59.979 | 0.06831 | 6.34 | [32, 64, 96, 96] |

## Capture

- fps: 240.0
- duration: 4.0 s
- resolution: 256x192

## Limitations

- Indicative, camera-based measurement. Not a certified ISO assessment.
- Frequency is valid only up to Nyquist (fps/2); record at >= 2.5x the fault frequency.
- Amplitude is in image pixels unless a scale reference was given.
- Compression, low texture and lighting flicker can mask or fake sub-pixel motion.
