---
name: HumSight design system
description: Industrial condition-monitoring console (dark top bar, neutral panels, one action blue, traffic-light condition colours, monospace readings) arranged as a four-step flow. Applied to web/.
colors:
  bg: "#f3f5f7"
  panel: "#ffffff"
  panel-2: "#f8fafb"
  line: "#dde3e9"
  line-strong: "#c5ced8"
  topbar: "#121a22"
  topbar-2: "#1c2731"
  ink: "#111a22"
  ink-2: "#3c4955"
  mute: "#687582"
  accent: "#1d63d8"
  accent-soft: "#e7effc"
  brand: "#f0b429"
  ok: "#1d7a3e"
  warn: "#a8640a"
  alarm: "#c0312b"
typography:
  sans: "IBM Plex Sans 400/500/600/700"
  mono: "IBM Plex Mono 400/500/600 (every measured number)"
rounded: { sm: 6px, md: 10px, lg: 14px, full: 9999px }
spacing: { 1: 4px, 2: 8px, 3: 12px, 4: 16px, 5: 24px, 6: 32px, 7: 48px }
---

## Who it is for

Maintenance and reliability engineers who already read vibration reports. The page uses their vocabulary (Alarm / Normal / Inconclusive, dominant frequency in Hz and CPM, zero-to-peak displacement, velocity RMS, work order) and keeps the methods detail one click away instead of on the first screen.

## Flow

One step per screen, routed by URL hash so the browser Back button works:

| Step | Hash | Purpose | Leaves when |
|---|---|---|---|
| 1 Recording | `#/select` | pick a reference clip (cards with expected outcome) or upload a video (drag and drop, type and size checked in the browser) | a clip is chosen, **Next: Setup** |
| 2 Setup | `#/setup` | capture fps (required, live "measurable up to" hint), optional machine details with units, analysis method as three described cards | inputs valid, **Run analysis** |
| 3 Analysis | `#/run` | stage chips, elapsed time, plain-language activity log with the numbers each tool measured | job ends; opens the diagnosis on its own |
| 4 Diagnosis | `#/report` | condition banner with recommended action, key readings, tabs: video, spectrum, heatmap, findings, activity log, work order | **New analysis** or back to Setup |

The left rail (a horizontal stepper under 900 px) shows each step's state: done (green check), current (blue), locked (dimmed, not clickable until reachable). Each step shows a one-line summary of what was chosen. A hash for a step that is not reachable yet falls back to the furthest reachable one. The Back / Next bar is sticky at the bottom of every step.

## Colour

- **Action blue** (`--accent`) is reserved for the primary button, the current step, selected cards and focus rings.
- **Condition colours** follow the familiar traffic light: `--ok` for Normal, `--warn` for Inconclusive and warnings, `--alarm` for Alarm and errors. Each has a `-soft` fill and a `-line` border for banners and tags.
- **Safety yellow** (`--brand`) appears only in the logo mark.
- Every colour is a custom property in the `:root` block of `web/style.css`; nothing outside it uses a hex value.

## Type

IBM Plex Sans for interface text, IBM Plex Mono for every measured value (KPI tiles, tables, activity-log chips, inputs) so digits line up. Page titles 28 px / 600, panel titles 16 px / 600, body 15 px, captions 12.5–13 px.

## Components

- **Clip card**: radio card with title, description, expected-outcome tag and fps / duration.
- **Input with unit**: number field with a fixed unit suffix (fps, RPM, Hz, mm/px) and help text under it.
- **Method card**: radio card with a title, tag (Recommended, Baseline, Unavailable) and one-line description.
- **Stage chip**: grey (not reached), green (done), dimmed (skipped once the job ended). Events arrive after a tool finishes, so no stage is shown as "in progress".
- **Status banner**: left rule and tint in the condition colour, icon, label, summary, recommended action.
- **KPI tile**: uppercase label, monospace value with unit, one-line context. Values that were not measured say so ("Not measured", "n/a") instead of showing a blank.
- **Tabs**: underline tabs, arrow-key navigation, dimmed when the run produced nothing for that tab; panels keep a minimum height so switching does not make the page jump.
- **Alert**: soft-tinted box for warnings and errors; errors show a plain-language message with the raw text under "Technical details".

## Honesty rules

- The disclaimer "Indicative, camera-based measurement. Not a certified ISO assessment." stays visible in the step rail and in the work-order tab.
- Every reading on the page is a number from the job result; the only arithmetic in the browser is unit conversion (Hz × 60 = CPM, RPM / 60 = Hz, fps / 2 = highest measurable frequency).
- A Fixed-pipeline result is labelled "baseline, unverified" and offers a re-run with the agent.

## Responsive

- ≤ 1080 px: method cards stack.
- ≤ 900 px: the step rail becomes a sticky four-column stepper under the top bar.
- ≤ 640 px: single-column forms, clip cards and videos; KPI tiles two per row; the back button uses a short label so the footer stays on one row; no horizontal page scroll at 375 px.
- `prefers-reduced-motion` turns off the spinner and list animations.
