## Context

"Indexes are rebuildable caches" (§2) only pays off if a model/plugin swap rebuilds
the minimum. This change adds the per-artifact provenance stamp and a pure planner
that computes the stale set. No I/O, no actual rebuilding — the worker and ingest
layers consume the planner later.

## Stamp model (`src/trustrag/provenance/stamp.py`)

- `StageStamp` — `{plugin: str, plugin_version: str, endpoint_model: str | None,
  dim: int | None}`. `endpoint_model`/`dim` are populated for vision/embedding.
- `ProducedBy` — `{artifact_version: int, extractor, chunker, vision, embedding,
  graph_extractor}` where each field is an optional `StageStamp` (an artifact only
  stamps the stages that produced it). pydantic v2, frozen, full JSON round-trip.
- `ModelManifest` — the current plugin/model set for a partition: the same per-stage
  `StageStamp` map, sourced from the plugin registry's current `plugin_version`s.
  Persisted per partition as `model_manifest.json` (file I/O is out of scope here;
  this is the value type).

## Rebuild planner (`src/trustrag/provenance/rebuild_planner.py`)

- **Layers** (the rebuildable artifacts): `extract, ocr, vision, eu, embedding,
  structure, graph, community` (a `Layer` enum).
- **Dependency DAG** encoded as an adjacency map (upstream → direct downstream):
  `extract → {ocr, vision}`, `ocr → eu`, `vision → eu`, `eu → {embedding, structure,
  graph}`, `graph → community`. Closure/topological helpers derive "all downstream
  of L".
- **Stage → seed layers**: a stage change seeds the layers it directly produces —
  `chunker → eu`, `embedding → embedding`, `vision → vision`, `extractor → extract`,
  `graph_extractor → graph`. Reranker/LLM map to **no** layer (query-time only).
- `plan(current: ModelManifest, stamp: ProducedBy) -> set[Layer]`:
  1. diff `current` vs `stamp` per stage → the set of changed stages;
  2. seed layers from changed stages;
  3. take the downstream closure over the DAG;
  4. return the union. Identical inputs → empty set.
- The matrix rows in the spec are exactly the closure results: vision-swap closes
  `vision → eu → embedding` (the spec's "vision + dependent EUs + their embeddings");
  chunker-swap seeds `eu` and closes to `{eu, embedding, structure, graph, community}`;
  embedding-swap seeds the leaf `embedding` (no downstream); graph-swap seeds `graph`
  and closes to `{graph, community}`.

## Relation to other changes

- `plugin_version` comes from `plugin-protocol-registry` (the stamp records it; the
  planner diffs it).
- The answer provenance chain (§16, `core-domain-types`) embeds a `produced_by` on
  each Evidence Unit; this is the same `ProducedBy` type.

## Trade-offs

- The DAG is hardcoded to the spec's pipeline rather than derived from plugin
  declarations — simplest correct thing for L1; a plugin-declared dependency graph
  can come later if custom stages need it.
- "Vision's dependent EUs" is modelled at the layer granularity (vision → eu), not
  per-document; per-document scoping (rebuild only changed docs) is a worker concern
  layered on top, not part of this pure planner.
