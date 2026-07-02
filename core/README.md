# trustrag-core

TrustRAG's Rust engine — **one core, FFI for all languages**
([SPEC-PORTS-v1 §3.4](../docs/SPEC-PORTS-v1.md)). Ships alongside the Python
library in this repo; the Python extractors remain the behavior reference and
`tests/core/test_rust_parity.py` proves byte-identical output through the
real C ABI.

## What's in (and coming)

| Area | Status |
|---|---|
| **extract** — txt · csv · md · html · docx · pptx (OOXML-direct) | ✅ implemented, parity-tested |
| **extract** — pdf (pdfium, runtime-bound) | behind the `pdf` feature |
| **store** — Lance (`upsert/search/scan/drop`) | next |
| **detect** — fastText lid.176 (pure Rust) | next |

The core is the **engine, not the brain**: orchestration, cite-or-abstain,
hooks, and model IO stay in each host language. Boundary: JSON in/out,
no callbacks.

## C ABI

```c
char* trustrag_extract(const uint8_t* bytes, size_t len,
                       const char* source_type,   // "pdf" | "docx" | "html" | ...
                       const char* document_id);  // -> ExtractedDoc JSON or {"error": ...}
void  trustrag_free_string(char* s);
const char* trustrag_core_version(void);
```

Bindings: cgo (Go, required) · napi-rs (TS, parity path) · pyo3/ctypes (Python).

## Develop

```bash
task core:build   # cargo build (cdylib + staticlib)
task core:test    # cargo test + the Python↔Rust parity suite
cargo build --features pdf   # enable the pdfium-backed PDF extractor
```
