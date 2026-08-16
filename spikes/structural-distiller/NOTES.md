# Spike: structural GraphDistiller (ctx-optimize AST graph → CiteNexus) — 2026-07-17

**Verdict: works end-to-end with ZERO core changes.** The existing
`CiteNexus(graph_distiller=...)` seam accepts a structural producer; the graph
layer, `graph_neighbors` tool, and grounding invariant all hold unchanged.

## Setup

- Corpus: this repo's `golang/` (57 `.go` files) ingested as plain text
  (FakeEmbedding, offline).
- Producer: `ctx-optimize add . && ctx-optimize export --format json` →
  406 nodes (symbols w/ signature, doc, `file` + `L..-L..`), 729 edges
  (`contains`/`imports`/`declares` = EXTRACTED, all 237 `calls` = INFERRED).
- `StructuralDistiller` (spike.py) converts the export to a `GraphIndex`,
  grounding every node in real `eu_refs` (text-containment anchor); ungrounded
  nodes and their edges are DROPPED — same invariant as `LLMGraphDistiller`.

## What worked

1. `graph_neighbors("Ask")` → the Go `Ask` node, grounded in a verbatim EU, with
   its real callees (`IsSupported`, `HasRelevanceOverlap`, `Refused`) — semantic
   edges co-mention can never produce.
2. Reverse traversal "who calls Tokenize" → `bm25.Rank`,
   `FakeEmbedding.Embed`, `gate.ContentTokens`, `gate.IsSupported`, its test —
   all correct, each resolving to cited EUs. **Unanswerable over co-mention.**
3. Hybrid `search_evidence` still works over the same corpus; navigate-not-cite
   holds throughout (edges route; only verbatim EU text is quotable).
4. The safety argument held in practice: ctx-optimize has ZERO `calls` edges into
   `Ask` (missed package-qualified call sites) — incomplete INFERRED edges just
   fail to route; they cannot create an ungrounded claim.

## Gaps found (= the Step B change)

1. **Grounding rate 73%** (296/406 nodes; 490/729 edges dropped on ungrounded
   endpoints). Cause: line-window text chunks + naive anchor matching. Fix is the
   **symbol-aware code extractor** — one EU per symbol (verbatim span +
   file:line) makes grounding 100% by construction.
2. **`GraphEdge` has no `confidence` field** — spike marks INFERRED as a
   `calls?` relation suffix. Real change: `confidence: extracted|inferred|
   ambiguous` (optional, default None → old artifacts keep loading).
3. **Full graph rebuild on every `ingest()` call** (57 rebuilds for 57 docs) —
   `build_from_store` runs per ingest. Needs deferred/incremental rebuild for
   real corpora.
4. File-level nodes mostly failed grounding, taking most EXTRACTED
   `contains`/`imports` edges with them (only 5 survived) — the extractor fix
   (1) resolves this too (file → document EU).

## Run it

    cd python && uv run python ../spikes/structural-distiller/spike.py \
        <corpus_dir> <ctx-optimize-export.json> <store_dir>
