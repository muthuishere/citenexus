## Context

The graph layer already accepts an injected producer via `CiteNexus(graph_distiller=…)`
and persists a rebuildable `GraphIndex` (`nodes`, `edges`) per leaf partition
(`graph/store.py`). `GraphEdge` today carries `source`, `target`, `weight`, and an
optional `relation`. The `_refresh_incremental` path in `client.py` rebuilds the
whole graph on every `ingest()` when the `graph`/`community` signal is on.

Per SPEC-PORTS-v1 the deterministic engine — **extract / emit / store / detect** —
lives once in the **Rust core** (`rust/src/extract/*.rs`) behind a C ABI
(`citenexus_extract`); Go binds it via FFI, JS via koffi, Python via ctypes, and
the Python extractors remain a *reference implementation* used only as the byte-
parity oracle (`tests/core/test_rust_parity.py`). Orchestration, cite-or-abstain,
graph-building, and model IO stay per host language ("the engine, not the brain").
The graph layer is **not** in the core — it is already reimplemented in
`golang/graph`, `js/src/graph`, and `python/.../graph`.

Extractors are dispatched by explicit `source_type` or file extension, each
returning an `ExtractedDoc` of ordered `ExtractedBlock`s. The shared types already
anticipate code: `BlockKind.code` and `StructureType.code_ast` exist but no
extractor emits them.

The 2026-07-17 spike (`spikes/structural-distiller/NOTES.md`) proved the end-to-end
flow works but grounded only 73% of nodes because source was ingested as flat
line-window text — symbol boundaries were lost, so a producer's `file:line` node
rarely landed on citable EU text. This change makes symbols first-class citable EUs
and records edge provenance honestly.

## Goals / Non-Goals

**Goals:**
- One verbatim, `file:line`-cited Evidence Unit per top-level code symbol, so a
  structural producer grounds at ~100% by construction.
- An honest `GraphEdge.confidence` distinguishing EXTRACTED (deterministic parse)
  from INFERRED (name-resolved) edges — additive and back-compatible.
- Graph rebuild that scales: no full rebuild per document.
- Preserve navigate-not-cite: edges route retrieval; answers cite verbatim EUs only.

**Non-Goals:**
- The call-graph producer itself. The structural distiller (AST export → edges,
  including guessed `calls`) stays an *injected* plugin shipped as example/spike
  code, not core — consistent with "code-graph product is out"
  ([[citenexus-code-graph-direction]]).
- Moving the deterministic graph-build into the Rust core. The graph layer stays
  per-language for now; a "graph-to-core" change is separate and later.
- Cross-file symbol resolution / edge inference inside the extractor. The extractor
  emits nodes (symbol EUs); edges remain a separate, injected concern.
- Community detection, wiki, or retrieval-fusion changes.

## Decisions

### 1. Home: the Rust core, once, behind `citenexus_extract`

The code extractor is a deterministic `extract` operation, so it belongs where
every other extractor already is — **once in the Rust core** — not reimplemented
per language. It ships as `rust/src/extract/code.rs`, dispatched by a `code`
source type through the existing `citenexus_extract` C ABI; Go/JS/Python consume
it over FFI unchanged. A Python reference implementation is added **only** as the
byte-parity oracle (`tests/core/test_rust_code_parity.py`), mirroring how the
csv/md/html/ooxml extractors are validated.

**Alternative considered — a pure-Python extractor (as the spike had):** rejected.
It would contradict the "one core, FFI for all" contract and force a later
re-port. tree-sitter is a first-class **Rust** crate, so the core is the natural
home, not the awkward one.

### 2. Parser: tree-sitter grammars for symbol boundaries

Use tree-sitter (Rust crates) to find top-level symbol spans (verbatim byte ranges
+ line numbers). Rationale:
- The 2026-07-11 rejection of tree-sitter was specifically about **edge
  resolution** (name-based, ~3× more guessed than reliable edges). **Symbol
  boundary extraction is deterministic** from the parse tree and is exactly what
  tree-sitter is reliable at — we use only that, and emit no edges.
- `tree-sitter` + grammar crates are MIT-licensed — clears the AGPL bar
  ([[citenexus-l6-spikes-2026-07-11]]).
- The extractor stays a pure `bytes → ExtractedDoc(JSON)` function, testable
  offline with deterministic fixtures and byte-compared to the Python reference.

**Alternative considered — consume an external AST export** (e.g. `ctx-optimize
export --format json`, as the spike did): rejected for the *extractor* because it
couples core ingest to one CLI's JSON schema and shells out mid-ingest. That export
stays the right input for the *injected distiller* (edges), where guessing is
already fenced off.

**Language coverage:** start with the languages the tree-sitter wheels make cheap
(Python, Go, JS/TS, Rust, Java). Unknown/unsupported extensions fall back to
`PlainExtractor` — never an error ("no structure → plain, not failure").

### 2b. Typed intake verb `rag.code.ingest_from(folder | git)`, fail-loud

Code is ingested through its own namespaced verb, not the generic `ingest()`
firehose ("we don't want to ingest everything everywhere"). `rag.code.ingest_from`
owns source acquisition (git clone / folder walk) + code-file filtering
(skip vendored/build dirs), then drives the core extractor per file and builds the
graph. It is per-language facade/orchestration (like the future
`rag.schema.ingest_from` and any `rag.wiki.*`), so it lives in each SDK, not the
core.

It **enforces its own prerequisite**: because a code corpus is meaningless without
its structural graph, the verb raises immediately if the instance was created
without the `graph`/`community` signal — no silent partial ingest. This is the
general principle for the intake family: *a typed verb declares and enforces the
signals it needs*. Rationale: intention-revealing, fails early with a clear
message (DHH-style), and makes the "no magic firehose" stance structural rather
than advisory.

**No new constructor surface.** The verb adds nothing to `CiteNexus.__init__`: it
reads the *existing* `signals=[...]` contract (the single place that declares what
an instance can do) and the shared backend/graph store — the `rag.code` namespace
is a lazy sub-facade bound to the same instance, not a separately-constructed
object. It MUST NOT introduce per-verb config or re-declare signals. Any
private-git auth uses the `${ENV}` token-name pattern expanded at the git call —
never a token value in the signature (consistent with endpoints-not-keys,
[[citenexus-secret-handling-style]]).

### 3. Symbol granularity: one EU per top-level named symbol

Emit one `code` block per top-level function / method / class / type / const/var
declaration, `text` = the verbatim source span, `structure_path` = enclosing
symbol names (e.g. `("MyClass",)` for a method), `level` = nesting depth,
`page=None`, and line range carried so the EvidenceUnit resolves to `file:Lx-Ly`.
Nested symbols nest via `structure_path`; imports and file-level preamble become a
single leading block so nothing is silently dropped. `structure_type =
StructureType.code_ast`.

Rationale: matches how a producer's nodes are keyed (per symbol) so node↔EU
resolution is 1:1; verbatim spans satisfy the cite-or-abstain gate; keeps EUs
coherent (a whole function, not a line window).

### 4. `GraphEdge.confidence`: optional enum, default `None` (per-language)

Added in each language's graph layer (`golang/graph`, `js/src/graph`,
`python/.../graph`) since the graph layer is not in the core. The three
implementations must stay byte-stable with one another (same JSON shape, same
default), the way the co-mention graph already is.

```python
class EdgeConfidence(StrEnum):
    extracted = "extracted"   # deterministic from the parse (contains/imports)
    inferred  = "inferred"    # name-resolved, may be wrong (calls)
    ambiguous = "ambiguous"   # multiple plausible resolutions
```

`GraphEdge.confidence: EdgeConfidence | None = None`. Default `None` keeps existing
`graph.json` loading and leaves deterministic co-mention edges unmarked (same
pattern as the existing optional `relation`). No migration.

**Alternative considered — a numeric score:** rejected. The distinction we need is
categorical (how the edge was derived), not a probability; a three-value enum is
honest and byte-stable across ports.

### 5. Incremental / deferred graph rebuild (per-language)

This is ingest orchestration, which the core excludes, so it is made in each SDK's
ingest path (`client.py` / `golang/ingest` / `js` equivalent). Change the
incremental-refresh step so a single `ingest()` no longer triggers a full
`build_from_store`. Options, recommended first:

- **(a) Deferred/dirty-flag (recommended):** ingest marks the leaf graph dirty and
  returns; the graph is rebuilt lazily on first `ask()`/graph read that needs it,
  or explicitly via `refresh_slow_path()`. One rebuild amortises a batch ingest.
- (b) Incremental delta rebuild: recompute only nodes/edges touched by the changed
  document. More code, and co-mention edges are corpus-wide so a delta is only
  partial — deferred to a later change if (a) proves insufficient.

Rationale: (a) is a small, safe change that removes the 57×-rebuild pathology while
keeping the artifact identical to a full rebuild (it *is* a full rebuild, just once
per batch). Correctness invariant: any `ask()` that reads the graph must see a graph
consistent with all committed ingests — the lazy trigger guarantees this.

## Risks / Trade-offs

- **[Deferred rebuild leaves a stale graph between ingest and next read]** → the
  lazy trigger rebuilds before any graph-reading `ask()`; a dirty flag persisted
  with the artifact means a fresh process still knows to rebuild. Co-mention/graph
  answers are never served from a graph older than the latest commit.
- **[tree-sitter grammar drift / unsupported language]** → fall back to
  `PlainExtractor` (still ingested and citable as text), never fail the ingest.
- **[Inferred edges misroute retrieval]** → acceptable and pre-existing: navigate-
  not-cite means a wrong edge can only fail to surface evidence, never fabricate a
  claim. `confidence=inferred` lets consumers down-weight; the spike confirmed
  missing/incorrect INFERRED edges degrade gracefully.
- **[Adding a code extractor re-opens "code in core" scope creep]** → fenced by the
  two-gate rule: only the *extractor* (verbatim citable symbol EUs) and the
  *confidence* field land in core; the edge producer stays injected. Documented in
  the proposal so archive review can hold the line.

## Migration Plan

Purely additive. `confidence` defaults `None` → old `graph.json` loads unchanged;
no vector-row or manifest schema change. New `SourceType` for code is additive;
existing corpora are unaffected until code files are ingested. No rollback steps
beyond reverting the change.

## Open Questions

- Exact initial language set for the code extractor (Python + Go are the spike's
  corpus; confirm which others ship in v1 vs. follow-on).
- Whether the deferred-rebuild dirty flag lives in the graph artifact or a small
  sibling marker file under the graph layer prefix (resolve in `apply`).
- Whether `code-extractor` needs its own `SourceType` per language or a single
  `SourceType.code` with a language tag on the block/metadata (lean: single
  `code` type + detected language in metadata).
