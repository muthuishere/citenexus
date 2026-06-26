## Why

Foundation-first (ADR-0002) risks building horizontal layers that never compose.
`smoke-e2e` is the mitigation: the thinnest real vertical path that proves the
core guarantee end-to-end and is kept green by every later layer. It is also the
first thing a user can actually *use*.

## What Changes

- Add deterministic fakes (`FakeEmbedding` hashing vectorizer, extractive
  `FakeLLM`, identity `FakeReranker`) under `trustrag.testing` so the guarantee is
  provable offline and the example needs no model server.
- Add `SmokePipeline`: `ingest(text, document_id)` → one Evidence Unit, embed,
  content-addressed raw blob, per-leaf vector upsert, etag manifest; and
  `ask(question)` → vector retrieve, a faithfulness gate, then **cite-or-abstain**
  returning a `Result` with a full provenance chain.

## Capabilities

### New Capabilities
- `smoke-e2e`: a thin ingest→retrieve→cite-or-abstain pipeline over the L2 storage
  layer, plus the deterministic fakes it runs on.

## Impact

- New `src/trustrag/testing/` and `src/trustrag/smoke/`. Hermetic tests on
  LocalFs + local LanceDB; an opt-in MinIO variant. The public shape (`ingest`/
  `ask`) and the "no ungrounded claim" guarantee are what L3-L5 grow into.
