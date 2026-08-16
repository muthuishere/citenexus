## Why

The 2026-07-17 spike (`spikes/structural-distiller/`) proved a structural code
graph lands in CiteNexus through the existing `graph_distiller=` seam with zero
core changes: ingest source as text, inject a producer that turns an AST export
into a `GraphIndex`, and "who calls Tokenize" answers correctly with EU-grounded
results — a question co-mention can never answer. But the spike exposed three
gaps that block real use, and one honesty gap in the graph model:

1. **Grounding rate was only 73%** (296/406 nodes, 490/729 edges dropped). Cause:
   line-window text chunks + naive anchor matching. Source ingested as flat text
   has no symbol boundaries, so a node's `file:line` rarely lands on citable EU
   text and the node — plus every edge touching it — is dropped.
2. **`GraphEdge` cannot say how it knows an edge.** The spike smuggled provenance
   into the relation name (a `calls?` suffix). Structural producers emit both
   EXTRACTED edges (`contains`/`imports` — deterministic from the parse) and
   INFERRED edges (`calls` — name-resolved, may be wrong). The model must record
   which, so retrieval and downstream consumers can weight inferred edges lower.
3. **The single-document `ingest()` path full-rebuilds the graph every call.**
   (The batch path already amortizes to one rebuild via `refresh_slow_path()` — so
   the real gap is only per-`ingest()`, not the whole pipeline.) This does not scale
   for one-at-a-time ingest.

This also settles the standing tension with the "no code-graph in core" decision
([[citenexus-code-graph-direction]], 2026-07-11): the call-graph **product**
stays out. What lands here is a code **extractor** that emits verbatim,
`file:line`-citable symbol EUs (passes both core gates — artifact + citable,
exactly like any other new extractor), plus the `confidence` field that keeps
inferred edges honest. The guessing — the `calls` edges — stays in an *injected*
distiller (like `LLMGraphDistiller`), never in core.

**Architecture placement (SPEC-PORTS-v1 "one core, FFI for all languages"):** the
code extractor is a **deterministic extract** operation, so — like every existing
extractor (csv/md/html/ooxml) — it lands **once in the Rust core**
(`citenexus_extract`) and every SDK (Go/JS/Python) consumes it over the C ABI;
Python keeps a reference implementation only as the parity oracle. The graph layer
is **not in the core today**, and — important — it is **only wired in Python**:
`python/.../graph` has the `graph_distiller=` seam, `GraphRetriever`, and the
ingest→rebuild path. In Go (`golang/graph`) and JS (`js/src/graph`) the graph is an
**unwired stub** (`BuildComentionGraph` has zero callers; JS has no ask/ingest
facade at all). So **this change scopes the graph work to Python** (`confidence` +
`code.ingest_from` + rebuild) plus the Rust-core extractor for all SDKs; adding the
`confidence` *field* to Go/JS `Edge` structs is trivial and included, but building
the Go/JS graph *seam* (distiller injection, retriever wiring, ingest→rebuild) is a
**separate later change**, not smuggled in here as if it were symmetric.

## What Changes

- **New: symbol-aware code extractor in the Rust core.** A new `extract` format
  emits one Evidence Unit per top-level symbol (function / method / class / type /
  const), carrying the **verbatim source span** plus `file` and line range,
  `BlockKind.code`, and `StructureType.code_ast`. Exposed through
  `citenexus_extract` and dispatched by code file extension; consumed by all SDKs
  via FFI. This is the fix for gap 1: symbols become citable EUs by construction,
  so a structural producer's nodes for **internally-defined** symbols resolve at
  ~100% (up from 73%). Note: nodes that target external/stdlib symbols the corpus
  never defines (e.g. `fmt.Println`) still have no EU — the headline is "~100% of
  in-corpus symbols," not all edge endpoints. A Python reference implementation
  exists solely as the byte-parity oracle (`test_rust_parity.py`).
- **New: a dedicated `rag.code.ingest_from(folder | git)` intake verb.** Code gets
  its own namespaced entry (not an overload of `ingest()`): it accepts a local
  folder **or** a git URL, acquires the source (git clone / folder walk), filters
  to code files (skips vendored/build dirs), drives the core code extractor per
  file, and builds the structural graph. This is per-language facade/orchestration
  (like the future `rag.schema.ingest_from(...)`); the git-URL path mirrors the
  existing URL-intake precedent.
- **New: `rag.code.ingest_from` requires the graph signal — fail loud.** Code is
  meaningless without its structural graph, so the verb MUST raise a clear error
  immediately when the instance was not created with the `graph` (or `community`)
  signal declared. No silent partial ingest. This is the "don't ingest everything
  everywhere" rule made concrete: a typed intake verb enforces its own
  prerequisites.
- **New: `GraphEdge.confidence`** — an optional field taking
  `extracted | inferred | ambiguous`, defaulting to `None` so existing
  `graph.json` artifacts keep loading (same back-compat pattern as the existing
  optional `relation` field). The on-disk form is pinned: **absent when `None`**
  (never `"confidence":null`), byte-stable across ports. Added to the `Edge`
  structs in all three languages; the Python graph layer uses it; deterministic
  co-mention edges leave it `None`.
- **New: deferred graph rebuild (Python).** Only the single-document `ingest()`
  path full-rebuilds today; the batch path already amortizes to one rebuild via the
  existing `refresh_slow_path()`. This change fixes just that single-`ingest()` gap
  (mark dirty → rebuild lazily), in Python where the rebuild is wired.
- The dispatch table (per language) routes recognised code file extensions to the
  code extractor; unknown extensions keep falling back to plain-text extraction.
- Not in this change: the structural (call-graph) distiller itself stays an
  injected plugin shipped as example/spike code, consistent with "code-graph
  product is out." Moving the deterministic graph-build into the Rust core is a
  separate, later change.

## Capabilities

### New Capabilities
- `code-extractor`: A symbol-aware extractor (Rust core, exposed via
  `citenexus_extract`, available across all SDKs at parity) that turns a source
  file into one verbatim, `file:line`-cited Evidence Unit per top-level symbol,
  with `code_ast` structure — the citable producer that makes a structural graph
  ground at ~100%.

### Modified Capabilities
- `graph-retriever`: `GraphEdge` gains an optional `confidence` field
  (`extracted | inferred | ambiguous`, default `None`, back-compat, absent-when-
  None), and the single-`ingest()` path stops full-rebuilding (deferred/lazy).
  Applied in the Python graph layer (the only wired one).
- `extractors`: the dispatch table recognises code source types by extension and
  routes them to the code extractor (unknown extensions still fall back to plain).

## Impact

- **Rust core:** new `rust/src/extract/code.rs` (+ a `code` source type in
  `citenexus_extract` / dispatch), and a tree-sitter dependency for symbol
  boundaries. New parity test `tests/core/test_rust_code_parity.py` against the
  Python reference extractor.
- **SDKs:** Go/JS pick up the extractor via the existing FFI (`extract_ffi.go`,
  koffi bindings) — no reimplementation. The `confidence` *field* is added to the
  Go/JS `Edge` structs (trivial), but `code.ingest_from` + rebuild + graph wiring
  land in **Python only** (the only wired graph layer); the Go/JS graph *seam* is a
  separate later change.
- **Artifacts:** `confidence` is additive, absent-when-`None` (no `null`), so
  existing `graph.json` and vector rows keep loading — no migration.
- **Dependencies:** tree-sitter grammar crates (MIT — clears the AGPL bar per
  [[citenexus-l6-spikes-2026-07-11]]). No bundled models.
- **Safety:** navigate-not-cite protects **content** grounding — for a content
  question, a wrong inferred edge only mis-routes retrieval; the answer still cites
  verbatim EU text. It does **NOT** by itself protect **topology** questions ("who
  calls X?"), where the edge *is* the asserted fact: a wrong inferred `calls` edge
  can yield a citation whose verbatim text contains the token but attributes it to
  the wrong symbol, and the token-subset gate cannot see the misattribution.
  Therefore `confidence` MUST become **load-bearing** in the answer path for
  topology answers (surface/down-weight/abstain on `inferred`) — specified as a
  follow-on in the answer flow, not claimed as free here. This change does not
  overclaim "never creates an ungrounded claim."
