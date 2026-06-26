## Context

The §4b `EmbeddingPlugin` protocol (`embed(texts) -> list[Embedding]`, where
`Embedding` is a forward `Any` alias) needs its first concrete implementation.
Per the project stack, TrustRAG bundles no models: the embedding model is an
injected OpenAI-compatible endpoint (local Ollama `bge-m3`, or a FlagEmbedding /
infinity server). §17 already carries an `EmbeddingConfig` (`model`, `endpoint`,
`dense`, `sparse`, `batch_size`, `dimensions`). Unit tests must stay hermetic
(fakes, no network); only the opt-in integration test touches a real endpoint,
and local Ollama is currently DOWN — so the real path is integration-only.

## Goals / Non-Goals

**Goals:**
- A concrete dense `EmbeddingPlugin` over the OpenAI `/embeddings` shape.
- Hermetic unit tests via an injected `transport` seam (no network, no new deps).
- API key sourced from a named env var at call time, carried only in the
  `Authorization` header, never logged or persisted.
- An order-preserving batching helper for long sequences.

**Non-Goals:**
- Sparse / lexical vectors (see Decisions — handled separately).
- Wiring this plugin into the config loader, registry, or ingest pipeline (later
  changes). This change ships the plugin + helper and their tests only.
- Async embedding, retries, or rate limiting (the durable worker queue owns
  retry/backoff at the ingest layer).

## Decisions

- **Concrete `Embedding` shape = dense `list[float]`.** The protocol left
  `Embedding` as `Any`; the dense vector is the minimal, universally-supported
  shape an OpenAI-compatible `/embeddings` endpoint returns (`data[].embedding`).
  `embed` returns `list[list[float]]`.

- **Inject the HTTP via a `transport` callable**
  (`Callable[[str, bytes, dict[str, str]], bytes]` = url, json body, headers →
  response bytes) rather than calling `urllib` directly in `embed`. This is the
  same "injected endpoint" discipline used across TrustRAG: tests pass a fake
  transport returning canned JSON, so they are hermetic and flake-free. The
  DEFAULT transport is a tiny `urllib.request` wrapper — stdlib only, no `httpx`.
  Alternative considered: monkeypatching `urllib` in tests — rejected as fragile
  and not matching the codebase's injected-endpoint style.

- **API key by env-var name, read at call time.** The plugin stores only the
  env-var *name* (`api_key_env`), never the value. On each call it reads
  `os.environ[name]` (if set) and builds `Authorization: Bearer <value>` into the
  headers handed to the transport. Nothing else sees the value; nothing logs it.
  This honors the hard rule that a secret's value must never enter code, logs, or
  test fixtures.

- **Batching as a free function, not a method.** `embed_in_batches(plugin,
  texts, batch_size=64)` keeps the plugin a thin endpoint adapter and lets the
  batcher wrap any `EmbeddingPlugin`. Default 64 balances request size against
  endpoint limits; `EmbeddingConfig.batch_size` can override at the call site.

## Risks / Trade-offs

- **Dense-only is an honest, deliberate limitation.** BGE-M3 also produces
  **sparse** term weights, but vanilla Ollama's `/embeddings` does NOT expose
  them — only a sparse-capable endpoint (FlagEmbedding / infinity) does. Faking a
  sparse vector here would be dishonest signal. → Mitigation: this plugin returns
  dense vectors only; the lexical (sparse) retrieval signal is handled separately
  by a BM25-lite scorer over the stored EU text. When a sparse-capable endpoint
  is available, a sibling plugin can add sparse without changing this one.

- **Endpoint shape drift** (a server that nests embeddings differently) → the
  parser targets the documented OpenAI `data[].embedding` shape; a divergent
  server is out of scope and would get its own plugin.

- **Secret leakage** → Mitigation: the value is read at call time, lives only in
  the `Authorization` header passed to the transport, is never stored on `self`,
  and never appears in logs or test fixtures (tests assert on the env-var name /
  header presence, not the value).

## Migration Plan

Additive only — new module and tests. No existing behavior changes; nothing
imports the new module yet, so there is nothing to roll back beyond deleting the
new files.

## Open Questions

- Whether `EmbeddingConfig` should gain an `api_key_env` field (it has none
  today, unlike `LLMConfig`). Out of scope here — the plugin takes `api_key_env`
  as a constructor argument so the config wiring can decide later without
  touching this code.
