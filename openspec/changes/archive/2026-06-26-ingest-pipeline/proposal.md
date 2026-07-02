## Why

L3 delivered the parts — extractors, language detection, evidence-builder,
structure-index, conditional-vision — over the L2 storage substrate. The ingest
pipeline is the orchestrator that turns "a source" into indexed, cited evidence:
dispatch → extract → detect language → build Evidence Units → build structure →
embed → upsert, all idempotent and gated by the client's declared signals (§8,
§15). It generalizes the smoke-e2e walking skeleton into the real fast path.

## What Changes

- Add `IngestPipeline.ingest(source, *, document_id?, partition?)` — universal
  intake (file path / bytes / raw text), dispatched to the right extractor
  (unknown → plain), idempotent by content hash via the etag manifest.
- Resolve the document language (detector + fallback) and stamp it on every EU.
- Signal-gated: `embedding`/`text` ⇒ embed + upsert to the leaf vector store;
  `structure` ⇒ build + persist the structure index; any of
  `graph`/`community`/`wiki` ⇒ enqueue the content hash on the slow-path worker.
- Persist the raw blob (content-addressed) and update manifests.
- Add `ingest_async(...)` returning a handle backed by the durable worker.

## Capabilities

### New Capabilities
- `ingest-pipeline`: the signal-gated, idempotent fast-path orchestrator wiring
  extraction → language → evidence → structure → embedding → storage.

## Impact

- New `src/citenexus/ingest/`. Reuses storage (L2), extractors/lang/evidence/
  structure (L3), worker (L2), and the `Embedder` seam (real BGE-M3 lands at L4).
  Hermetic tests use LocalFs + local LanceDB + FakeEmbedding; a MinIO variant is
  opt-in.
