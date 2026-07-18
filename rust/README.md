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
| **extract** — pdf (pdfium, runtime-bound) | behind the `pdf` feature |
| **emit** — any supported format → markdown (`citenexus_to_markdown`), deterministic, byte-identical with the Python reference | ✅ implemented, parity-tested |
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

Build prerequisite: `protoc` (lance's build scripts generate protobuf code) —
`brew install protobuf` on macOS. The lid.176 real-model tests skip unless
`assets/models/lid.176.bin` exists (or `CITENEXUS_LID176_PATH` points at it);
nothing is downloaded at test time.
