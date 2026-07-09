# Live vision demo — 2026-07-08

Proves the §9 vision Q&A loop end-to-end with a **real** vision model — not
`FakeVision`. `FakeVision` proves orchestration (extraction → persistence →
shaping → retrieval → citation); this proves the vision *model call itself*
produces a usable, citable description.

## Setup

- **Model:** Google Gemini `gemini-2.5-flash`, called via its OpenAI-compatible
  endpoint (`GeminiHttpEndpoint` + `OpenAICompatibleVision`, both already in
  `citenexus.http` / `citenexus.vision` — no new client class needed).
- **Auth:** `GEMINI_API_KEY` from the environment, read once by the caller and
  passed as `HttpEndpoint.api_key` (a `SecretStr`) — never hardcoded, never
  logged, never entered the library. The library itself reads no environment.
- **PDF:** a hand-built single-page PDF (same raw-object construction as
  `tests/extract/fixtures/pdf_builder.py`) embedding one real JPEG chart
  (`docs/demo-assets/live-vision-2026-07-08/chart.jpg`) — a line chart titled
  "Quarterly Revenue vs Profit ($M)" with a Y-axis (0–100, $M), an X-axis
  (Q1–Q4), a legend, and two series: Revenue (30/45/60/90) and Profit
  (10/15/20/25). Page text is deliberately unrelated ("Q4 board report
  narrative text, unrelated to the chart contents."), so any answer about the
  chart can only be grounded in the vision description.
  Source PDF: `docs/demo-assets/live-vision-2026-07-08/report.pdf`.
- **Text side (embedding + answer generation):** `FakeEmbedding` /
  `FakeLLM` (deterministic, in-process) — only the **vision** call is real.
  This isolates what's being proven: the vision model's output quality and its
  path into a citable Evidence Unit, not embedding/generation fidelity.

## Bug found + fixed

`OpenAICompatibleVision`'s default `max_tokens` was `512`. Gemini's real JSON
description (the `_VISION_PROMPT` schema: caption, detailed description,
objects, relationships, OCR text, data values, image type) plus Gemini
2.5 Flash's internal reasoning tokens (billed against the same completion
budget in the OpenAI-compat endpoint) blew through that in every real run,
truncating the JSON mid-string. `_parse_description`'s fallback then treated
the whole truncated blob as `short_caption`, and the resulting EU passage was
garbage (`'A line chart displaying quarterly revenue and profit'`, cut off).
Raised the default to `8192` (`python/src/citenexus/vision/client.py`) — this
never showed up against `FakeVision` because the fake returns a small fixed
dict, no real model, no token budget. Confirmed fix with a fresh store: full
JSON now returns, parses, and grounds the answer in the vision passage
(not the unrelated page text).

## Real vision output (verbatim, from Gemini)

```json
{
  "short_caption": "A line chart showing quarterly revenue and profit trends from Q1 to Q4.",
  "detailed_description": "A 2D line chart titled \"Quarterly Revenue vs Profit ($M)\" displays two data series, Revenue and Profit, across four quarters. The chart has a white background with a black border for the plotting area. The Y-axis, representing monetary values in millions of dollars, ranges from 0 to 100 with major tick marks and labels at 0, 25, 50, 75, and 100. The X-axis, representing quarters, has labels Q1, Q2, Q3, and Q4. A legend is located in the top right corner of the plotting area, identifying the blue line with circular markers as \"Revenue\" and the red line with circular markers as \"Profit\".\n\nThe blue \"Revenue\" line shows an increasing trend across the quarters. Its data points are approximately: Q1 at 32, Q2 at 45, Q3 at 60, and Q4 at 90. The line is solid blue and connects blue circular markers.\n\nThe red \"Profit\" line also shows an increasing trend, consistently below the Revenue line. Its data points are approximately: Q1 at 10, Q2 at 15, Q3 at 20, and Q4 at 25. The line is solid red and connects red circular markers.\n\nBoth lines indicate a positive growth trend for both revenue and profit over the four quarters, with revenue growing at a faster rate than profit.",
  "objects": ["line chart", "X-axis", "Y-axis", "chart title", "legend", "Revenue line", "Profit line", "data markers (blue circles)", "data markers (red circles)", "axis labels", "legend labels"],
  "relationships": [
    "\"Quarterly Revenue vs Profit ($M)\" is the title of the line chart.",
    "The Y-axis represents values in millions of dollars.",
    "The X-axis represents quarters.",
    "The blue line represents Revenue.",
    "The red line represents Profit.",
    "The Revenue line is consistently above the Profit line.",
    "Both Revenue and Profit show an increasing trend over the quarters.",
    "The legend associates 'Revenue' with the blue line and 'Profit' with the red line.",
    "Blue circular markers indicate data points for Revenue.",
    "Red circular markers indicate data points for Profit.",
    "The Revenue line connects its data markers.",
    "The Profit line connects its data markers."
  ],
  "ocr_text": "Quarterly Revenue vs Profit ($M)\nRevenue\nProfit\n100\n75\n50\n25\n0\nQ1\nQ2\nQ3\nQ4",
  "data_values": [
    {"label": "Revenue Q1", "value": 32}, {"label": "Revenue Q2", "value": 45},
    {"label": "Revenue Q3", "value": 60}, {"label": "Revenue Q4", "value": 90},
    {"label": "Profit Q1", "value": 10}, {"label": "Profit Q2", "value": 15},
    {"label": "Profit Q3", "value": 20}, {"label": "Profit Q4", "value": 25}
  ],
  "image_type": "chart"
}
```

Ground truth drawn into the chart: Revenue 30/45/60/90, Profit 10/15/20/25.
Gemini read Revenue Q1 as 32 (vs actual 30) — everything else exact, including
every axis label, tick value, legend mapping, and the up/down comparison
between the two lines. Quality is strong: this is real understanding of chart
structure, not a generic caption.

## `rag.ask()` transcript

```
Q: What does the chart show — what are the axis values and which line trends upward?

decision: answered
claim supported: True
document: q4-report, page: 1
cited passage: [the detailed_description + objects + relationships + ocr_text +
                data_values block above, shaped into the figure EU's text]
```

The citation lands on the vision-generated figure passage, not the unrelated
page narrative — proving retrieval correctly grounds an image-only question in
the real vision description.

## Honest assessment

- Real vision quality **exceeded** `FakeVision`'s deterministic stand-in, as
  expected — it read every axis tick, the legend color mapping, and all 8
  data points off a synthetic PIL-drawn chart with only a ~7% error on one
  value.
- The `max_tokens=512` default was a real latent bug: it worked with
  `FakeVision` because the fake never hits a token budget, and would have
  silently produced truncated, useless figure EUs for any real chart/diagram
  with a moderately detailed description. Fixed to `8192`.
- Text-side (embedding, answer generation) still used fakes in this demo —
  only the vision leg was live. A full real-model demo (real embeddings + real
  LLM) is a separate, larger proof and out of scope for "does live vision
  work."
