# PDF model contract: PdfPrepare → your models → PdfAssemble

**What this is.** This is the exact interface between the CiteNexus core and a
host that runs its own models over PDFs (ADR-0017 decisions 4, 5, 10). You can
write a harness from this page and the JSON Schema alone, without reading Rust.

- Schema: [`docs/schema/pdf-model-contract.schema.json`](schema/pdf-model-contract.schema.json)
  (draft 2020-12). `rust/tests/pdf_contract_schema_test.rs` validates the
  committed fixtures against it on every test run, so the two cannot drift.
- Worked example (synthetic, invented text): `rust/tests/data/pdf/assemble-mixed.*`.
  - `.pdf`: the input.
  - `.prepared.json`: the PdfPrepare output.
  - `.responses.json`: the answers.
  - `.golden.json`: the PdfAssemble output.
- Vectors, each with the behaviour it pins: `rust/tests/data/pdf/pdf_assemble.json`.
- Decision record: [ADR-0017](adr/0017-pdf-to-markdown-structure-not-text.md).

**The core never makes a network call.** It tells you what to ask, and it
checks what you bring back. On a page with a text layer, a model only ever
returns **structure** (a grid of word IDs). The text in every cell comes from
the PDF's own characters.

## 1. The loop

```
PdfPrepare(pdf, opts)             -> units, pages, document, requests[]
for each request: call your model -> PdfResponse (or nothing)
PdfAssemble(pdf, opts, responses) -> units, pages, document
```

- `PdfUnits(pdf, opts)` is exactly `PdfAssemble(pdf, opts, [])`, byte for byte.
- Assemble re-parses the PDF, so no state is kept between the calls. Pass the
  same `opts` to both.
- **Determinism:** the same PDF, options and responses give byte-identical
  JSON. The order of the responses does not matter.

Options (`PdfOptions`):

| field | default | meaning |
|---|---|---|
| `language` | none | `"nl"`, `"en"`, …: the hyphen rules and number reading (ADR-0015) |
| `layout_text` | false | adds `pages[].layout_text`, a `pdftotext -layout`-style rendering |
| `model_tables` | false | also asks about tables the deterministic path already accepted (review mode). Off, only **uncertain** table regions cost a call |

## 2. Requests

Every request has `id`, `page` (1-based), `kind`, `prompt`, `bbox`, `words`,
`variant` and `hint`.

- `bbox` is `[x0, y0, x1, y1]` in PDF points, **top-left origin**.
- `prompt` is a key into your prompt config. The defaults are in
  `rust/data/pdf_prompts.json`. That file is data: override it freely. The
  response **shape** is the contract, not the wording.

### 2.1 `table_structure`

**When.** For a table region the deterministic path could not settle:
- a column-tracks candidate that scored low;
- a grid the geometry gate rejected;
- a tagged table that disagrees with the page geometry;
- with `model_tables` on, also every accepted table.

**Not asked:**
- a region that is a **table of contents**: 70% or more of its lines carry a
  leader (`.....`) and end in a page number;
- a region that would have to grow to more than 2.5× its words to cover whole
  units. The base output stays.

**Id:** `p{page}:table{k}`.

**`bbox`: the region, grown to the WHOLE units it intersects.** A grid over half
a paragraph would be a certain `partial_unit`.

**`words`:** every text-layer word inside the region, plus a 12 pt margin.
Each word is `{id, text, bbox, marker}`:
- `id` is `p{page}w{n}`, stable for the same bytes and options.
- `marker: true` flags a list-marker glyph opening a line: `•`, `-`, a 1-char
  non-alphanumeric glyph, or `1.` / `1)` / `a)` / `(a)` / `iv)`.
- **Leaders** are words carrying a run of 4+ `.`, `…`, `·` or `_`, alone
  (`.......`) or glued to text (`Inleiding.......`). They are filler.

**`variant` and `hint`:** `null`.

```json
{"id": "p1:table0", "page": 1, "kind": "table_structure", "prompt": "table_structure",
 "bbox": [71.75, 99.75, 472.25, 180.25],
 "words": [{"id": "p1w8", "text": "Omschrijving", "bbox": [76.43, 106.72, 139.27, 116.09], "marker": false},
           {"id": "p1w9", "text": "Bedrag", "bbox": [226.73, 106.84, 259.81, 116.09], "marker": false}, "…"],
 "variant": null, "hint": null}
```

### 2.2 `vision_page` and `vision_region`: always TWO variants

- **When:**
  - `vision_page`: a page with no usable text layer (route `scan`).
  - `vision_region`: an image unit with fewer than 5 text-layer words inside it.
- **Ids:** `p{page}:page:v1` and `p{page}:page:v2`, or `p{page}:img{k}:v1` and
  `p{page}:img{k}:v2`.
- **`variant`:** `1` or `2`.
- **`hint`:** tells you to make the two calls **independent**: a different model,
  or the same model with a different sampling seed. Send both.
- **`words`:** empty. Render `bbox` yourself and send the image.

```json
{"id": "p2:page:v1", "page": 2, "kind": "vision_page", "prompt": "vision_page",
 "bbox": [0.0, 0.0, 595.0, 842.0], "words": [], "variant": 1,
 "hint": "variant 1 of 2: transcribe independently of the other variant, with a different model or a different sampling seed; only sentences both variants agree on become citable content"}
```

## 3. Responses

```json
{"request_id": "<the request's id>", "finish_reason": "stop",
 "tables": [ … ] | null,        // table_structure only
 "markdown": "…" | null,        // vision_page / vision_region only
 "mode": "transcription" | "description" | null}   // vision_region only
```

- **A table grid** is `{"rows": [[cell, …], …]}`, rows top to bottom and cells
  left to right. A cell is:
  - an array of word IDs, e.g. `["p1w12"]`; `[]` for an empty cell; or
  - `{"words": [...], "colspan": 2, "rowspan": 1}` for spans (HTML rules).

  Use every word that lies inside a table exactly once. **Never write text:**
  markdown on a `table_structure` request is rejected.
  - You MAY leave out `marker` words and pure leaders. They are not content,
    and they are not emitted either way.
  - **`{"tables": []}` means "there is no table here".** That is a verdict,
    not a failure (§4).
- **`finish_reason`:** send the model API's value. These count as a normal
  stop: `stop`, `end_turn`, `stop_sequence`, `eos`, `complete`, or omitted/null.
  Anything else (`length`, `content_filter`, `error`, …) fails.
  - **Budget reasoning tokens.** A reasoning model that spends its budget
    thinking ends with `length`, and the response is rejected. The consumer
    measured this: gpt-oss-120b ended `length` at 8,000 tokens on a 306-word
    region.
- **`mode`** (`vision_region` only):
  - `"transcription"` (the default): the markdown copies text visible in the
    region.
  - `"description"`: the region has no meaningful text (a logo, a photo) and
    the markdown describes it. On `vision_page`, `description` is
    `malformed_response`.

From the fixture (`assemble-mixed.responses.json`):

```json
{"request_id": "p1:table0", "finish_reason": "stop",
 "tables": [{"rows": [[["p1w8"], ["p1w9"], ["p1w10"]], [["p1w11"], ["p1w12"], ["p1w13"]], "…"]}],
 "markdown": null, "mode": null}
```

## 4. What assemble checks, and what failure looks like

**A failure never loses text.** It keeps the base output and records which
check failed in `provenance.failed_check`:
- for a table request, on the **table region's units only**: units with a word
  whose centre lies inside the request `bbox`, plus units the response's grid
  referenced. Prose in the 12 pt listing margin keeps its base provenance.
- for vision, on the region's image unit, or the page's text units.

`document.responses_applied` counts responses that passed every check.
`document.responses_rejected` counts those that failed.

| situation | send | result |
|---|---|---|
| model error, timeout, no answer | **omit the response** | base output for that region. For vision, see below |
| truncated / filtered | `finish_reason` as returned | `finish_reason` |
| "no table here" | `{"tables": []}` | **not a failure**: base output. The region's units get `provenance.model_verdict: "no_table"`. Counted as applied |
| response missing `tables` / `markdown` | — | `malformed_response` |
| two responses with one `request_id` | — | `duplicate_response` |
| unknown `request_id` | — | ignored |
| markdown on a `table_structure` request | — | `model_text_on_text_layer` |
| a word ID the request never listed | — | `unknown_word` |
| a word used twice | — | `duplicate_word` |
| a grid whose rows are all empty | — | `empty_grid` |
| rows or columns out of place (e.g. amounts swapped between rows, a word moved to another row, values swapped across columns) | — | `geometry_rows` / `geometry_columns` / `geometry_span`. Leader words are outside this test |
| a text-layer word inside the grid's box left out (a dropped cell). Markers and pure leaders excepted | — | `grid_coverage` |
| a grid taking part of a unit, leaving out a word that is not a marker or leader | — | `partial_unit` |
| vision: empty or looping output | — | `empty` / `repetition` |
| vision on a page with an OCR layer: an invented digit, a changed or dropped amount, "I.3"→"1.3", low coverage, too much new text | — | `digit_bag` / `value_novel` / `coverage` / `novelty` |

- **A model grid against a deterministic table.** This happens with
  `model_tables`, or when an uncertain region already held a tracks table. Both
  grids pass the position check, then GriTS-Con decides:
  - **≥ 0.9, they agree:** the deterministic table stays (confirmed).
  - **Below 0.9, they disagree:** a struct-tree or ruled table stays and gets
    `table_uncertain: true`. A column-tracks table loses to the model grid,
    which carries `table_uncertain: true`.
  - A deterministic table never loses to "more rows".
- **Both vision variants.** Each variant is checked on its own, and a failing
  variant is dropped.
  - The surviving **transcriptions** are compared **by sentence**: case,
    whitespace and the number spelling are normalised (`7.000,00` = `7000,00`
    under `nl`).
    - Sentences identical in both are content.
    - Everything else is **disputed**.
  - **Descriptions** are not evidence, so they are never compared.

  | surviving variants | unit |
  |---|---|
  | 2 transcriptions | agreed sentences are content, the rest disputed |
  | 1 transcription (the other missing, failed, or a description) | all disputed (single source, never silently trusted); `failed_check` names the other's failure if it had one |
  | only descriptions (`vision_region`) | kind `image_description`, never citable (§5) |
  | none | base output + `failed_check` |

## 5. What is NOT citable: disputed text and image descriptions

Disputed text stays in the unit's `markdown` inside an HTML comment, and the
unit has `provenance.vision_disputed: true`:

```text
Declaratie reiskosten 2024
<!-- vision_disputed
v1: Reiskosten 7.000,00 geen voorschot Hotel 5.100,00 per jaar
v2: Reiskosten 7.000,00 voorschot Hotel 5.100,00 geen per jaar
-->
Diner 1.250,00 vooraf betaald
Artikel I.3 is van toepassing
```

(From the fixture: variant 2 moved the "geen". No bag of words can see that,
and the sentence comparison does.)

An image description is a unit of kind `image_description`, and its markdown
is wrapped the same way:

```text
<!-- image_description
Een logo met een blauwe cirkel
-->
```

**Cite, quote-match and chunk only the citable text:** `CitableText(markdown)`
in Go, `vision::citable_text` in Rust. It removes every
`<!-- vision_disputed … -->` and `<!-- image_description … -->` block. A `--`
inside such text is written as `- -`, and `>` as `›`, so the text can never
close the comment early.

## 6. Units (output)

The output is `{units, pages, document}`. A unit is:
- `page`, `bbox`, `level`, `markdown`;
- `kind`: `heading | paragraph | list | table | furniture | image | image_description`;
- `provenance`:

| field | meaning |
|---|---|
| `route` | `plain \| formatted \| table \| image \| scan` (`ooxml` for DOCX/PPTX) |
| `table_source` | `struct_tree \| ruled \| tracks \| model_grid` |
| `vision_transcribed` | the text was written by a vision model |
| `vision_disputed` | some of it is disputed (§5) |
| `table_uncertain` | two grids disagreed, or the region scored low |
| `header_flattened` | a header spanning several columns was prefixed to each sub-header it covers ("Ervaringsjaren 0-2", "Ervaringsjaren 3-5"). Only the PDF's words; markdown cannot span |
| `model_verdict` | `"no_table"` when the model answered `{"tables": []}` |
| `failed_check` | §4 |
| `heading_source`, `joined_hyphen` | heading and hyphen provenance |

Tables are GitHub pipe tables:
- spanned slots are empty cells;
- `|` inside a cell is written `\|`;
- markers and leaders are never emitted.

The fixture's output (`assemble-mixed.golden.json`), abridged:

| page | kind | provenance | markdown |
|---|---|---|---|
| 1 | paragraph | route table | Declaraties over het jaar 2024 staan hieronder. |
| 1 | table | `table_source: ruled` (the model grid agreed) | `\| Omschrijving \| Bedrag \| Opmerking \| …` |
| 2 | image | `vision_transcribed`, `vision_disputed` | the block in §5 |
| 3 | image | `vision_transcribed` (both variants agreed) | Formulier: naam, datum, handtekening |

## 7. Go harness (behind `-tags citenexus_ffi`)

Build once: `cd rust && cargo build --release --features pdf`. Then point
`PDFIUM_DYNAMIC_LIB_PATH` at a libpdfium and build with
`go test -tags citenexus_ffi ./core/`.

The loop below is abridged from `golang/core/example_harness_test.go`, which
is compiled on every test run.

```go
opts := core.PdfOptions{Language: "nl"}
prep, err := core.PdfPrepare(pdf, opts)
if err != nil { return err }

var responses []core.PdfResponse
for _, req := range prep.Requests {
	switch req.Kind {
	case "table_structure":
		// send req.Words (id, text, bbox, marker) + a render of req.BBox; ask for word-ID grids
		raw, finish, err := tableModel(req)
		if err != nil { continue } // timeout/error: omit -> base output
		var g struct{ Tables []core.PdfGrid `json:"tables"` }
		if json.Unmarshal([]byte(raw), &g) != nil { continue }
		// g.Tables may be empty: "no table here" is a valid answer
		responses = append(responses, core.PdfResponse{RequestID: req.ID, FinishReason: finish, Tables: g.Tables})
	case "vision_page", "vision_region":
		// TWO independent calls per region: variant 1 and variant 2
		client, seed := visionA, 1
		if req.Variant != nil && *req.Variant == 2 { client, seed = visionB, 2 }
		md, mode, finish, err := client(render(pdf, req.Page, req.BBox), seed)
		if err != nil { continue } // the other variant alone -> all disputed
		// mode: "transcription" (text copied) or, vision_region only, "description"
		responses = append(responses, core.PdfResponse{RequestID: req.ID, FinishReason: finish, Markdown: &md, Mode: mode})
	}
}

res, err := core.PdfAssemble(pdf, opts, responses)
for _, u := range res.Units {
	text := core.CitableText(u.Markdown) // chunk/cite this, never the disputed or description blocks
	_ = text
}
```

- `core.PdfAssembleJSON(pdf, opts, responsesJSON)` returns the core's bytes
  untouched, which is useful for byte-level determinism checks.
- `core.PdfUnits(pdf, opts)` is the no-model path.

## 7b. Python (`citenexus.core`)

Build the core with `cd rust && cargo build --release --features pdf`. Point
`CITENEXUS_CORE_LIB` at the cdylib, unless you run from a checkout, and
`PDFIUM_DYNAMIC_LIB_PATH` at libpdfium. The binding is typed with pydantic
models, and its `*_json` variants return the core's bytes untouched. It is
covered by `python/tests/core/test_rust_pdf.py`, which checks the golden
byte for byte.

```python
from citenexus import core

opts = core.PdfOptions(language="nl")
prep = core.pdf_prepare(pdf, opts)

responses: list[core.PdfResponse] = []
for req in prep.requests:
    if req.kind == "table_structure":
        # send req.words (id, text, bbox, marker) + a render of req.bbox
        grids = table_model(req)                 # your model -> list of {"rows": [...]} or []
        if grids is None:
            continue                             # error/timeout: omit -> base output
        responses.append(core.PdfResponse(request_id=req.id, finish_reason="stop",
                                          tables=[core.PdfGrid.model_validate(g) for g in grids]))
    else:  # vision_page / vision_region, asked twice (req.variant 1 and 2)
        text, mode = vision_model(render(pdf, req.page, req.bbox), seed=req.variant)
        responses.append(core.PdfResponse(request_id=req.id, finish_reason="stop",
                                          markdown=text, mode=mode))

out = core.pdf_assemble(pdf, responses, opts)
for unit in out.units:
    chunk = core.citable_text(unit.markdown)     # never the disputed / description blocks
```

## 7c. JavaScript (`@muthuishere/citenexus/ffi`, koffi)

The build prerequisites are the same. Set `CITENEXUS_CORE_LIB` to override the
cdylib path. Covered by `js/src/core/core.test.ts`, which checks the golden
byte for byte.

```ts
import { pdfPrepare, pdfAssemble, citableText, type PdfResponse } from "@muthuishere/citenexus/ffi";

const opts = { language: "nl" };
const prep = pdfPrepare(pdf, opts);
const responses: PdfResponse[] = [];
for (const req of prep.requests) {
  if (req.kind === "table_structure") {
    const grids = await tableModel(req);        // [] = "no table here"
    if (grids) responses.push({ request_id: req.id, finish_reason: "stop", tables: grids });
  } else {
    // vision: two independent calls, req.variant 1 and 2
    const { text, mode } = await visionModel(render(pdf, req.page, req.bbox), req.variant);
    responses.push({ request_id: req.id, finish_reason: "stop", markdown: text, mode });
  }
}
const out = pdfAssemble(pdf, responses, opts);
const chunks = out.units.map((u) => citableText(u.markdown));
```

**Not changed by this contract:** the older `extract()` PDF paths, which are
separate from `pdf_units`.
- The Rust core's `citenexus_extract` for PDF
  (`rust/src/extract/pdf/mod.rs`, `page.text().all()`) still emits one
  paragraph per page and leaks U+0002. Go's `core.Extract` and JS's `extract`
  use it.
- Python's `citenexus.extract` PDF extractor uses pdfplumber, not the core.

Both outputs are pinned where they are, and moving them onto `pdf_units` is a
separate, tracked follow-up.

## 8. C ABI

```c
char* citenexus_pdf_units(const uint8_t* pdf, size_t len, const char* opts_json);
char* citenexus_pdf_prepare(const uint8_t* pdf, size_t len, const char* opts_json);
char* citenexus_pdf_assemble(const uint8_t* pdf, size_t len, const char* opts_json,
                             const char* responses_json);   /* JSON array, or NULL */
void  citenexus_free_string(char* s);
```

Every call returns JSON, or `{"error": "..."}`. An error means the core was
built without the `pdf` feature, libpdfium is missing, or the bytes are not a
PDF.

## 9. Cost and model notes on the Lex5 corpus (69 PDFs, 616 pages)

Measured at the branch head with `examples/pdf_measure.rs`, counts only:

| request kind | count | words listed |
|---|---|---|
| `table_structure` | 15 | 1,480 (mean 99, max 306); no TOC regions |
| `vision_page` | 10 (5 pages × 2) | — |
| `vision_region` | 142 (71 regions × 2) | — |

Consumer measurements with this contract (their harness, their numbers):
- **gpt-oss-120b as the table model:** every grid that landed had positional
  integrity 53/53.
- **mistral-small-3.2 as the table model:** empty on 18 of 21 table requests
  with the default prompt, so it is **not usable** for tables as is.
- **Vision descriptions of logos from two models never agree** (0.45 by line).
  That is why descriptions are `image_description`, outside dual agreement.
