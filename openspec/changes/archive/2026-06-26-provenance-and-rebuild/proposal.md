## Why

Principle 2 of the spec (§2) says all indexes are rebuildable caches — but that is
only economical if rebuilds are **partial**. When an operator swaps an embedding
model or a chunker on a million-document corpus, re-running the entire pipeline is
unaffordable. Each generated artifact must record exactly what produced it, so a
plugin/model change rebuilds **only** the layers that actually went stale, in
dependency order. This change adds that bookkeeping (the `produced_by` stamp) and
the planner that turns a model swap into a targeted rebuild instead of a full
reprocess (§4c).

## What Changes

- Add the **`produced_by` provenance stamp** (§4c) carried on every artifact:
  `artifact_version` plus the producing plugin + version (and endpoint model where
  relevant) for each stage — extractor, chunker, vision, embedding, graph_extractor.
- Add a **partition-level `model_manifest`** value type aggregating the current
  plugin/model set for a partition.
- Add the **rebuild planner**: a pure function that diffs the *current* plugin/model
  set against an artifact's stamp (or a set of stamps) and returns the set of layers
  to rebuild, respecting the dependency DAG
  `extract → OCR/vision → EU/chunk → {embedding, structure, graph} → community/summary`.
- Encode the §4c **rebuild matrix** as behaviour: embedding-swap rebuilds embeddings
  only; vision-swap rebuilds vision + dependent EUs + their embeddings; chunker-swap
  rebuilds EUs + everything downstream; graph-extractor-swap rebuilds
  entities/relations/communities/summaries; reranker/LLM swap rebuilds nothing.

No actual rebuilding or I/O — this change is the stamp model and the planner that
computes the stale set. Executing a rebuild belongs to the worker (L2) and the
ingest/graph layers (L3+).

## Capabilities

### New Capabilities
- `provenance-and-rebuild`: artifact provenance stamps + the dependency-aware
  partial-rebuild planner that makes "indexes are rebuildable caches" economical.

### Modified Capabilities
<!-- none -->

## Impact

- New modules: `src/citenexus/provenance/stamp.py`, `src/citenexus/provenance/rebuild_planner.py`.
- Depends conceptually on `plugin-protocol-registry`: the stamp records each stage's
  `{plugin, plugin_version}`, and the planner diffs against the registry's current
  plugin/model versions.
- Downstream: the worker (L2) and ingest/graph/wiki layers consume the planner's
  output to decide what to recompute; the answer provenance chain (§16) reuses the
  stamp on each Evidence Unit.
