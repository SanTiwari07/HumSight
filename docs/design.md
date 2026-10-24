---
name: HumSight design system
description: Industrial paint palette (light machine grey, anthracite housing, signal yellow for position, signal green / orange / red for condition), Barlow lettering, flat ruled surfaces, arranged as a four-step flow. Applied to web/.
colors:
  ground: "#e4e6e2"
  panel: "#f5f6f3"
  rule: "#c8cdc8"
  ink: "#22272a"
  ink-2: "#4b5357"
  housing: "#2e3437"
  signal: "#f2a900"
  link: "#1f5a9e"
  ok: "#2c7a4b"
  warn: "#d0700a"
  alarm: "#a7271f"
typography:
  sans: "Barlow 400/500/600 (body, inputs, numbers with tabular figures)"
  condensed: "Barlow Semi Condensed 500/600/700 (titles, step names, readings, the annunciator word)"
  mono: "system monospace, only for tool identifiers such as probe_clip"
rounded: { sm: 3px, md: 4px }
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

The housing (the dark left rail; a band across the top under 900 px) shows each step's state: current (signal-yellow edge), done (the chosen value in full strength), locked (dimmed, not clickable until reachable). A hash for a step that is not reachable yet falls back to the furthest reachable one. The Back / Next bar is sticky at the bottom of every step.

## Colour

The palette comes from the paint on the machines being inspected (RAL): light machine grey for the ground, anthracite (RAL 7016) for the housing that holds the logo and the step route, and the signal colours used on safety signage.

- **Signal yellow** (`--signal`) means "you are here" and nothing else: the edge of the current step, the edge of the selected recording or method, the active tab.
- **Condition colours**: `--ok` Normal, `--warn` Inconclusive and warnings, `--alarm` Alarm and errors. Each has an `-ink` shade for text on its `-soft` fill, so small text keeps its contrast.
- **Ink** fills the primary button. There is no separate brand blue; `--link` is only for links and focus rings.
- Every colour is a custom property in the `:root` block of `web/style.css`; nothing outside it uses a hex value.

## Type

Barlow is a grotesk drawn after DIN-style signage, which matches machine nameplates and control panels. The condensed cut sets titles, step names and readings; the regular cut sets body text and inputs. Numbers use tabular figures in the same family instead of a monospace face. Labels are sentence case; nothing is set in all caps.

## Components

- **Housing**: the dark left rail with the logo, the four steps and the disclaimer. Each step shows its number, name and what was chosen (for example "240 fps, agent with rules"). The current step has a signal-yellow edge; steps that can't be reached yet are dimmed and not clickable. Under 900 px it becomes a band across the top.
- **Recording card / method card**: flat, ruled, 4 px radius. Selected means an ink outline plus the yellow edge. A recording's expected outcome is a small square in the condition colour with text.
- **Input with unit**: number field with a fixed unit suffix (fps, RPM, Hz, mm/px) and help text under it.
- **Stage track**: one segment per stage, filled in ink as tools finish, dotted when skipped. Events arrive after a tool finishes, so no stage is shown as "in progress".
- **Annunciator**: the diagnosis opens with a lit tile in the condition colour (Alarm, Normal, Inconclusive), like a control-room alarm panel, next to the summary and the recommended action.
- **Readings strip**: one ruled panel of cells (label, condensed value with unit, one-line context). The last row stretches so there are no empty cells. Values that were not measured say so.
- **Tabs**: plain text tabs, the active one underlined in signal yellow; dimmed when the run produced nothing for that tab. Panels keep a minimum height so switching does not make the page jump.
- **Alert**: tinted box with a 4 px condition-colour edge; errors give a plain-language message with the raw text under "Technical details".

What the page avoids on purpose: card shadows, pill-shaped tags, all-caps eyebrows, arrows in button labels, strings joined with middle dots, and a monospace face for data.

## Honesty rules

- The disclaimer "Indicative, camera-based measurement. Not a certified ISO assessment." stays visible in the step rail and in the work-order tab.
- Every reading on the page is a number from the job result; the only arithmetic in the browser is unit conversion (Hz × 60 = CPM, RPM / 60 = Hz, fps / 2 = highest measurable frequency).
- A Fixed-pipeline result is labelled "baseline, unverified" and offers a re-run with the agent.

## Responsive

- ≤ 1080 px: method cards stack.
- ≤ 900 px: the housing becomes a sticky band across the top: logo, then the four steps in a row.
- ≤ 640 px: single-column forms, recording cards and videos; the annunciator stacks above the summary; readings two per row; the back button uses a short label so the footer stays on one row; no horizontal page scroll at 375 px.
- `prefers-reduced-motion` turns off the spinner and list animations.
