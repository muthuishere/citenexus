# citenexus-core

CiteNexus's Rust engine — **one core, FFI for all languages**
([SPEC-PORTS-v1 §3.4](../docs/SPEC-PORTS-v1.md)). Ships alongside the Python
library in this repo; the Python extractors remain the behavior reference and
`tests/core/test_rust_parity.py` proves byte-identical output through the
real C ABI.

## What's in (and coming)

| Area | Status |
|---|---|
| **extract** — txt · csv · md · html · docx · pptx (OOXML-direct) · xlsx (calamine) | ✅ implemented, parity-tested |
| **extract** — code (tree-sitter: python · go) — one verbatim `code` EU per top-level symbol, `structure_type=code_ast`, line range carried; unknown language → plain | ✅ implemented, parity-tested (`tests/core/test_rust_code_parity.py`) |
| **extract** — pdf (pdfium, runtime-bound): `extract` keeps the one-paragraph-per-page `ExtractedDoc` | behind the `pdf` feature |
| **pdf units** — `pdf_units` / `citenexus_pdf_units`: the no-model base extractor (ADR-0017 step 2). Layout lines/columns from pdfium char boxes, U+0002 hyphen join with document witnesses, running header/footer kept once as `furniture`, reading order (struct tree → rule-based → XY-cut), headings: on a tagged document only where the struct tree tags one AND the print supports it (per heading; the per-document agreement rate is still reported), on an untagged one by the strict font rule (font-only headings need ≥1.15× body size or a bold section number, never bold alone; an "Artikel N" label merges with its title), lists, per-page route (`plain`/`formatted`/`table`/`image`/`scan`) with its signals | behind the `pdf` feature; tested on synthetic PDFs (`tests/pdf_units_test.rs`); tables: see **pdf tables** below |
| **emit** — any supported format → markdown (`citenexus_to_markdown`), deterministic, byte-identical with the Python reference | ✅ implemented, parity-tested |
| **pdf contract** — `pdf_prepare` / `pdf_assemble` (ADR-0017 step 3): the model returns table STRUCTURE as word IDs, Rust fills the cells from pdfium's characters; a geometry gate (rows/columns in disjoint ordered bands, IDs known and used once, no dropped cell, no split unit) rejects swapped, moved or duplicated values; vision text is checked against any OCR layer (digit bag, ADR-0015 values as a multiset, coverage 0.90 / novelty 0.08) and labelled `vision_transcribed`; any failure keeps the base text with `failed_check` | behind the `pdf` feature; vectors in `tests/data/pdf/pdf_assemble.json` (15 must-reject, 3 must-accept, 1 documented gap: a word MOVED inside vision text is invisible to every bag); byte-identical Go golden (`tests/data/pdf/assemble-mixed.*`, Rust-generated, so kept out of the Python-generated `conformance/`); default prompts as data in `data/pdf_prompts.json`; `model_tables: true` also sends confidently-detected tables to the model for review |
| **pdf tables** — deterministic, no model (ADR-0017 step 4, `src/extract/pdf/tables.rs`): struct tree (`Table/TR/TH/TD`, `RowSpan`/`ColSpan`) wins when complete; ruled grid from rules AND rectangle edges (a boundary drawn in under half the rows is not a column; empty strips dropped; shading-only grids are weak); column tracks from whitespace rivers, scored (accept ≥ 0.75, uncertain ≥ 0.4); validators reject one-column boxes, TOCs, key-value lists and prose in columns; every grid must pass the same geometry gate as model grids; competing grids are decided by GriTS-Con + evidence priority (struct > ruled > model grid > tracks), never "more rows wins"; cells come only from pdfium characters | behind the `pdf` feature; `tests/pdf_tables_test.rs`; `examples/pdf_tables.rs` is the acceptance measure (counts and shapes only) |
| **checks / numbers** — `checks` (geometry gate, output guards, digit bag, value/token multisets) and `numbers` (ADR-0015 locale reader) | pure, no feature; `numbers` pinned to the Python reference's 30 `number_readings` vectors (`tests/data/number_readings.json`, from `6f7cee0`) |
| **store** — Lance (`upsert/search/scan/drop`, merge-insert by `eu_id`) | ✅ implemented; `tests/core/test_rust_store_parity.py` proves Rust-written tables are read (scan + search) by Python's `LanceVectorStore` and vice versa — same URI, same bytes |
| **detect** — fastText lid.176 (pure-Rust `fasttext` crate) | ✅ implemented — **dense `lid.176.bin` only**: the crate's quantized (`.ftz`) inference diverges from upstream in 0.8.0, so quantized models are refused with an error (see `src/detect.rs`) |
| **rrf** — reciprocal-rank fusion (`citenexus_rrf`) — pure rank arithmetic over `eu_id`s, k passed in, no tokenization/Unicode/key | ✅ implemented, byte-parity-tested (`tests/rrf_test.rs` + `tests/core/test_rust_rrf_parity.py`) against the Python reference `citenexus.retrieve.fusion` (ADR-0006). Every SDK's fusion is a thin binding to this; the old per-language helpers are **deprecated, not removed** |

**Where the boundary is drawn (ADR-0006).** Only *pure, text-free* computation
moves into the core: `rrf` qualifies (rank arithmetic, no tokenizer). The
cite-or-abstain **grounding gate**, `bm25`, `chunker`, and the **tokenizer** stay
per host language — they must stay hackable without a Rust toolchain, and moving
their Unicode-sensitive case-folding into Rust would silently diverge on exactly
the non-Latin languages CiteNexus targets. Their drift is killed instead by a
shared **conformance-vector suite** (`conformance/cases/`, incl. the
`multilingual.json` Unicode-edge corpus) that Python, Go, and JS all run.

The core is the **engine, not the brain**: orchestration, cite-or-abstain,
hooks, and model IO stay in each host language. Boundary: JSON in/out,
no callbacks.

## C ABI

```c
char* citenexus_extract(const uint8_t* bytes, size_t len,
                       const char* source_type,   // "pdf" | "docx" | "html" | ...
                       const char* document_id);  // -> ExtractedDoc JSON or {"error": ...}

char* citenexus_to_markdown(const uint8_t* bytes, size_t len,
                           const char* source_type); // -> {"markdown": ...} or {"error": ...}

// pdf units (feature `pdf`) — opts_json = {"language":"nl","layout_text":false}
// or NULL. -> {"units":[DocUnit...],"pages":[...],"document":{...}} or
// {"error": ...} (also when built without `pdf` or libpdfium is missing).
char* citenexus_pdf_units(const uint8_t* bytes, size_t len, const char* opts_json);
// The model contract (ADR-0017; docs/pdf-model-contract.md): the core never
// calls a model. prepare returns the base output + requests: table_structure
// over text-layer word IDs (one per uncertain table region), and vision_page /
// vision_region TWICE each (ids ...:v1 / ...:v2, `variant` 1|2, a `hint` to use
// a different model or seed). The host fulfils them; assemble re-parses the
// PDF and applies each response that passes the checks; vision text is kept
// only where both variants agree, the rest is wrapped in
// <!-- vision_disputed ... --> (not citable). pdf_units == pdf_assemble with no
// responses, byte for byte.
char* citenexus_pdf_prepare(const uint8_t* bytes, size_t len, const char* opts_json);
char* citenexus_pdf_assemble(const uint8_t* bytes, size_t len, const char* opts_json,
                             const char* responses_json); // JSON array of PdfResponse, or NULL

// rrf — reciprocal-rank fusion. lists_json = JSON array of arrays of eu_id
// strings; k = the RRF constant (60 is standard). -> JSON array of fused
// eu_ids (descending fused score, ascending eu_id tie-break) or {"error": ...}.
char* citenexus_rrf(const char* lists_json, int64_t k);

// store — opaque handle, JSON rows, {"error": ...} on failure
void* citenexus_store_open(const char* uri, const char* storage_options_json); // NULL on failure
char* citenexus_store_upsert(void* store, const char* rows_json);              // {"ok":true}
char* citenexus_store_search(void* store, const char* vector_json, size_t limit); // rows + _distance
char* citenexus_store_scan(void* store, int64_t limit);                        // limit < 0 = all
char* citenexus_store_drop(void* store);                                       // {"ok":true}
void  citenexus_store_close(void* store);

// detect — fastText lid.176 (dense .bin; caller supplies the model path)
void* citenexus_detector_open(const char* model_path);   // NULL on failure
char* citenexus_detect(void* detector, const char* text); // {"language":"fr","confidence":0.98}
void  citenexus_detector_close(void* detector);

void  citenexus_free_string(char* s);   // releases every char* above
const char* citenexus_core_version(void);
```

Bindings: cgo (Go, required) · napi-rs (TS, parity path) · pyo3/ctypes (Python).

## Develop

```bash
task core:build   # cargo build (cdylib + staticlib)
task core:test    # cargo test + the Python↔Rust parity suite
cargo build --features pdf   # enable the pdfium-backed PDF extractor
```

### libpdfium (the `pdf` feature)

pdfium-render binds libpdfium **dynamically at runtime**; nothing is bundled.
The core looks for it in this order (`src/extract/pdf/raw.rs`, `pdfium()`):

1. `PDFIUM_DYNAMIC_LIB_PATH`, which can be the library file itself or a
   directory that holds `libpdfium.{so,dylib}` / `pdfium.dll`;
2. the current directory;
3. the system loader path.

The core binds libpdfium itself (twice: one handle for pdfium-render's
`Pdfium`, one for its raw `FPDFText_*` calls). If another pdfium-render user
in the same process creates its `Pdfium` first, every PDF call fails with
`PdfiumLoadError::InitializedElsewhere` rather than degrading: bind the core
first.

Production: ship a pinned `libpdfium.so` from bblanchon/pdfium-binaries next
to the cdylib (ADR-0017 §Runtime). Locally, any pdfium build works. For
example, the one inside a pypdfium2 wheel (the binary only, via uv's cache):

```bash
export PDFIUM_DYNAMIC_LIB_PATH=/path/to/pypdfium2_raw/libpdfium.dylib
cargo test --features pdf                       # PDF tests run
cargo build --release --features pdf            # for golang/core PdfUnits
(cd ../golang && go test -tags citenexus_ffi ./core/)
```

Without libpdfium the PDF tests print `SKIP: libpdfium unavailable …` and
pass, and Go's `TestPdfUnits` skips. pdfium is not thread-safe, so every call
holds one process-wide lock.

PDF test fixtures are **synthetic**: `tests/common/pdfgen.rs` writes PDF 1.7
by hand, with no AGPL/GPL tool involved. `conformance/fixtures/pdf/*.pdf` is
regenerated with `CITENEXUS_WRITE_PDF_FIXTURES=1 cargo test --test pdf_fixtures_test`.
Third-party attributions: [`NOTICE`](NOTICE).

**Table acceptance scoring** (`examples/pdf_tables.rs`, counts/shapes/scores
only; the GT map is parsed at run time so client file names never enter the
repo; disputed vision text is excluded):

```bash
# deterministic, no model: runs pdf_units over the originals
PDFIUM_DYNAMIC_LIB_PATH=... cargo run --profile measure --features pdf --example pdf_tables -- \
  --originals <spike185>/data/originals --manifest <spike185>/data/originals_manifest.json \
  --gt-map <spike185>/measure_tables.py --gt ~/answer-engine-local/lex-markdown --lang nl

# ALREADY-ASSEMBLED output from a host harness (PdfPrepare -> models -> PdfAssemble):
# one PdfUnitsOutput JSON per file at <dir>/<file_id>.json, file ids as in the GT map
cargo run --profile measure --features pdf --example pdf_tables -- \
  --assembled <dir> --gt-map <spike185>/measure_tables.py --gt ~/answer-engine-local/lex-markdown \
  [--originals <dir> --manifest <json>]   # adds positional integrity (needs libpdfium)
```

`--gt-map` also accepts a JSON object `{"<gt file>.md": "<file_id>"}`.
`--gt-corrections <json>` applies a GT overlay before scoring (for GT typos
confirmed against the PDF): `{"<gt file>.md": [{"table": 0, "row": r, "col": c,
"value": "…"} | {"from": "…", "to": "…"}]}`; the total line reports how many
cells it changed. The host
contract itself is [`docs/pdf-model-contract.md`](../docs/pdf-model-contract.md).

`examples/pdf_measure.rs` measures `pdf_units` over a directory of PDFs and
prints **counts only**: routes, heading agreement, hyphen markers left,
furniture. Optionally it also runs spike 185's quote-support measure in memory.
Nothing is written to disk, so it can be pointed at client documents read in
place:
`cargo run --release --features pdf --example pdf_measure -- <dir> --lang nl [--quotes <manifest.json> <run.jsonl>...]`.

Build prerequisite: `protoc` (lance's build scripts generate protobuf code) —
`brew install protobuf` on macOS. The lid.176 real-model tests skip unless
`assets/models/lid.176.bin` exists (or `CITENEXUS_LID176_PATH` points at it);
nothing is downloaded at test time.
