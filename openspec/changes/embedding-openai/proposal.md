## Why

The §4b `EmbeddingPlugin` protocol exists but has no concrete implementation, so
nothing can actually turn evidence text into vectors. TrustRAG bundles no models
(§4b) — embeddings come from an injected, OpenAI-compatible endpoint (local
Ollama / FlagEmbedding / infinity). This change lands the first concrete
`EmbeddingPlugin` so the L4 retrieval layer has real dense vectors to index.

## What Changes

- Add `OpenAICompatibleEmbedding(EmbeddingPlugin)` — calls
  `POST {base_url}/embeddings` with `{"model": ..., "input": [texts...]}` and
  parses `data[].embedding` into dense `list[list[float]]`. `plugin_version =
  "openai-embed-v1"`.
- The HTTP call is injected via a `transport` callable so unit tests are fully
  hermetic; the default transport uses stdlib `urllib.request` (no new deps).
- The API key is read at call time from the env var named in config
  (`api_key_env`) and passed only in the `Authorization` header — never
  hardcoded or logged.
- Add `embed_query(text) -> list[float]`, the single-text convenience matching
  the ingest `Embedder` protocol.
- Add `embed_in_batches(plugin, texts, batch_size=64)` — batches a long
  sequence into endpoint calls, preserving order.

## Capabilities

### New Capabilities
- `embedding-openai`: the concrete OpenAI-compatible dense `EmbeddingPlugin`
  (injected transport, env-var API key, `embed`/`embed_query`) plus the
  order-preserving batching helper.

### Modified Capabilities
<!-- none — the EmbeddingPlugin protocol already exists (plugin-protocol-registry); this change only supplies a concrete implementation. -->

## Impact

- New module `src/trustrag/embed/` (`client.py`, `batcher.py`, `__init__.py`)
  and tests under `tests/embed/`.
- No new dependencies — stdlib `urllib` only. No `pyproject.toml` change.
- Honest scope: returns DENSE vectors only. BGE-M3 **sparse** weights need a
  sparse-capable endpoint and are handled by a separate lexical signal (see
  design.md).
