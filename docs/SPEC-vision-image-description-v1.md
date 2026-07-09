# SPEC — vision image description at ingest (v1)

**Status:** proposal only — owner GO gates the build. No code changes made
for this spec.

**Owner ask:** at ingest, the vision model should generate a full description
of *every aspect* of an image and store it, so that a later user question
about that image can be answered from the stored description. Today this
doesn't happen on any real document — see
[`docs/CONTENT-COVERAGE-2026-07-08.md`](CONTENT-COVERAGE-2026-07-08.md) row 5.

## 1. Root cause (grounded in current code)

Two independent gaps stack to make `vision=` inert on real documents:

1. **No extractor persists image bytes.** `extract/types.py:ImageRef` has a
   `blob_key: str | None = None` field with the comment `# Where the bytes
   live (a backend key) or None if not persisted yet.` `extract/pdf.py:
   PdfExtractor.extract` builds `ImageRef(image_id=..., page=..., bbox=...)`
   purely from `page.images` metadata (position/size) — it never reads or
   stores the actual raster. `docx.py`/`pptx.py` similarly only build
   `ImageRef(image_id=rel_id)` from relationship IDs, no bytes.
2. **The pipeline can't describe what it never loaded.**
   `ingest/pipeline.py:_image_bytes()`:
   ```python
   def _image_bytes(self, image: Any) -> bytes | None:
       blob_key = getattr(image, "blob_key", None)
       if not blob_key:
           return None
       ...
   ```
   and `_vision_units()`:
   ```python
   data = self._image_bytes(image)
   if data is None:
       continue
   ```
   Since `blob_key` is always `None` for real documents, every image is
   skipped before `describe_image()` is ever called. (A third, related gap —
   `vision/prefilter.py::decide()` is never invoked by the pipeline at all —
   is noted but out of scope for *this* spec; see §6.)

## 2. What has to change (minimal, code-grounded)

### 2a. Persist image bytes during extraction

Each PDF/DOCX/PPTX extractor needs to read the actual image bytes it already
has a handle to, and the ingest pipeline needs to store them and stamp
`blob_key`.

- **PDF** (`extract/pdf.py`): `pdfplumber`'s `page.images` entries carry a
  `"stream"` key (a `pdfminer` `PDFStream` object); its `.get_data()` decodes
  the raster bytes for most filters (FlateDecode etc.). Some encodings
  (DCTDecode/JPEG, JPXDecode/JPEG2000) return the raw (still-valid,
  already-compressed) stream — needs a short validation pass during
  implementation to confirm the bytes decode cleanly with e.g. Pillow before
  being handed to a vision endpoint. Confirmed via
  `python/.venv (pdfplumber 0.11.10)` that `page.images` exists; the
  `.get_data()` path is the standard approach, not yet exercised in this
  codebase.
- **DOCX** (`extract/docx.py`): image bytes are already reachable —
  `document.part.rels.items()` (used today to build `ImageRef(image_id=rel_id)`
  at line ~78) exposes `rel.target_part.blob` for any image relationship.
  This is the smallest lift of the three.
- **PPTX** (`extract/pptx.py`): `python-pptx` shapes expose `shape.image.blob`
  for picture shapes — same pattern as DOCX.

Extraction produces bytes; **persistence** belongs in the ingest pipeline
(extractors stay pure/no I/O, per the existing architecture note in
`extract/types.py`'s module docstring). Concretely, `extract/types.py`'s
`ExtractedBlock`/`ImageRef` types would carry the raw bytes back up (a new
transient field, not persisted itself), and `ingest/pipeline.py:ingest()`
(right after `doc = extract(...)`, before the existing
`units.extend(self._vision_units(...))` call at line ~174) would call
`self._backend.put_bytes(blob_key, image_bytes)` for each image — using the
**same `StorageBackend.put_bytes`/`get_bytes` seam already used for raw
document blobs** (`storage/backend.py:22` `StorageBackend` ABC, both
`LocalFsBackend` and `S3Backend` implement it — no new storage primitive
needed) — then set `image.blob_key` before `_vision_units()` runs. This
turns `_image_bytes()`'s existing `blob_key` check from "always None" into
"always set", with zero change to `_image_bytes()`/`_vision_units()`
themselves.

### 2b. The "describe every aspect" prompt

`vision/client.py:OpenAICompatibleVision`'s current `_VISION_PROMPT` asks for
`short_caption`, `detailed_description`, `objects`, `relationships`,
`ocr_text` — already a reasonably complete schema. To satisfy "every aspect"
concretely and make the description answer arbitrary later questions, extend
it (still one JSON object, one model call, `vision/describe.py`'s
`VisionRecord` gains the new fields):

```
short_caption          (existing)
detailed_description   (existing — expand prompt to explicitly ask for:
                         layout/structure if it's a chart/table image,
                         all visible numbers/labels/axis values,
                         colors and what they encode if a legend exists,
                         spatial relationships between elements)
objects                (existing)
relationships          (existing)
ocr_text               (existing — all visible text, verbatim)
data_values             NEW — extracted numeric/tabular values as an array
                         of {label, value} for charts/graphs/tables-as-image
image_type              NEW — photo | chart | diagram | screenshot | table |
                         handwriting | logo | other (routing/filter hint)
```
`_record_text()` in `vision/units.py` already concatenates every populated
field into the unit's searchable `text` — the new fields slot in there with
no structural change, just two more `if record.X: parts.append(...)` lines
(mirroring the existing `objects`/`relationships` pattern).

### 2c. How the description becomes retrievable/citable

**No new evidence path needed — the wiring already exists and is correct.**
`vision/units.py:build_vision_units()` already turns each
`(ImageRef, VisionRecord)` pair into a real `EvidenceUnit(type=EUType.figure,
text=<composed description>, citation=Citation(passage=text, page=image.page,
bbox=image.bbox))`. Once §2a supplies real bytes (so `described` is non-empty
in `_vision_units()`), these figure EUs flow through the *exact same*
embed → index → retrieve → cite path as every other EU — confirmed in
`docs/CONTENT-COVERAGE-2026-07-08.md` row 5 ("logic sound"). A user question
about the image (e.g. "what does the chart on page 4 show?") retrieves the
figure EU via normal vector/text search and `AnswerFlow.ask()` cites it with
page+bbox like any passage — no change needed to `answer/flow.py` or
`retrieve/`.

### 2d. Files that change

| File | Change |
|---|---|
| `extract/pdf.py` | Read image bytes via `page.images[i]["stream"].get_data()`; carry bytes up (new transient field, not on the frozen `ImageRef` itself — see note below) |
| `extract/docx.py` | Read `rel.target_part.blob` for each image relationship |
| `extract/pptx.py` | Read `shape.image.blob` for picture shapes |
| `extract/types.py` | `ImageRef` stays a frozen Pydantic model (no bytes field, to avoid huge model copies) — bytes travel alongside via a small parallel structure or extractor return value, TBD at design-detail time |
| `ingest/pipeline.py` | After `extract()`, before `_vision_units()`: persist each image's bytes via `self._backend.put_bytes(...)`, set `blob_key` on the `ImageRef` used downstream |
| `vision/client.py` | Extend `_VISION_PROMPT` with the new fields (§2b) |
| `vision/describe.py` | `VisionRecord` gains `data_values`, `image_type` fields; `_as_mapping`/parsing already generic (`Mapping[str, Any]` coercion), minimal change |
| `vision/units.py` | `_record_text()` appends the two new fields when present |

No change needed to: `evidence/builder.py`, `answer/flow.py`, `retrieve/`,
`storage/*` (existing `put_bytes`/`get_bytes` reused as-is).

## 3. Effort estimate

- DOCX/PPTX byte extraction: **small** (~half day each) — the byte handle is
  already one line away from where `ImageRef` is built today.
- PDF byte extraction: **small-medium** (~1 day) — needs the encoding
  validation spike noted in §2a (confirm DCT/JPX bytes decode cleanly; a
  fallback to Pillow's `page.to_image()` page-region crop is a safe backup if
  raw stream extraction proves unreliable for some PDFs).
- Pipeline wiring (persist bytes, set `blob_key`, before `_vision_units`):
  **small** (~half day) — reuses existing `put_bytes` seam.
  supplied bytes + `describe_image` already work.
- Prompt/schema extension (`_VISION_PROMPT`, `VisionRecord`, `_record_text`):
  **small** (~half day).
- Test coverage (extractor unit tests with real sample images, one
  ingest→retrieve→cite integration test per format): **medium** (~1-2 days).

**Total: roughly 4-5 engineer-days**, python-only.

## 4. Which ports

**Python-first, and Python-only for v1.** The Python port
(`python/src/citenexus/`) is the reference implementation per `CLAUDE.md`
("python/ reference library (full RAG)") and is the only port with a
`vision/` module at all — confirmed by the earlier codebase audit that
`golang/`/`js/`/`rust/` have no vision-module hits beyond incidental string
matches. Go/JS/Rust vision parity is not in scope until this ships and
stabilizes in Python; would be a separate, later change.

## 5. Explicitly out of scope for this spec

- Wiring `vision/prefilter.py::decide()` into the ingest pipeline (the §9
  text/ocr/vision/skip router) — a real, separate gap
  (`docs/CONTENT-COVERAGE-2026-07-08.md` row 5), but orthogonal: it's a cost/
  routing optimization, not a blocker for "vision can see real images at
  all." Worth doing in the same PR if the owner wants routing correctness
  from day one, since without it every real image would go straight to a
  paid vision call, with no decoration-skip or OCR-routing savings.
- PDF/DOCX/PPTX table extraction (row 4b of the coverage matrix) — unrelated
  gap, separate spec if prioritized.
- Any change to `AnswerFlow.ask`/`Candidate` to make citations type-aware
  (e.g. label a citation as "from figure 3") — not required for the
  described-image-answers-questions behavior to work, since figure EUs are
  already citable; this would only improve the citation's presentation.

## 6. Risk / open questions for the owner

- **Cost**: every image in every ingested document would trigger one vision
  API call (since §5 leaves the pre-filter unwired) unless the owner wants
  §5's routing included in the same PR — recommend bundling it, small
  incremental effort, meaningfully caps vision spend.
- **PDF byte-extraction reliability**: needs a short implementation spike to
  confirm `pdfplumber`'s `stream.get_data()` reliably yields valid image
  bytes across common encodings before committing to the full estimate above.
