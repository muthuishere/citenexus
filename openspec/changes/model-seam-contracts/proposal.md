## Why

The owner's ask, in their words:

> *"so create interface contracts for `OpenAICompatibleEmbedding`,
> `OpenAICompatibleGenerator`, `OpenAICompatibleVision`, `OpenAICompatibleReranker`,
> and then anyone can use the interface contract"*

That is ADR-0014 **R1 (one shape per seam)** and **R4 (same contract, idiomatic
spelling)**, scoped to the Python reference.

The four shipped model clients already share one **constructor** — keyword-only
`base_url`, `model`, `transport`, `headers`. What they do *not* share is a
**contract**, and a constructor is not something a third party can implement.
Today the contract each one satisfies is decided by accident:

| client | contract it declares |
|---|---|
| `OpenAICompatibleEmbedding` | `EmbeddingPlugin` ABC (`plugins/base.py:62`) |
| `OpenAICompatibleReranker` | `RerankerPlugin` ABC (`plugins/base.py:96`) |
| `OpenAICompatibleGenerator` | **nothing** — a `Generator` Protocol exists at `answer/flow.py:38` and it does not declare it |
| `OpenAICompatibleVision` | **nothing** — `VisionPlugin` exists at `plugins/base.py:69` and it does not declare it |

So a would-be provider has to read our call sites to discover what to implement.
That is reverse-engineering, not an interface.

The embedding seam is worse: ADR-0014 counts **four** Python abstractions for it,
none of which is published as *the* one —

- `plugins/base.py:62` `EmbeddingPlugin.embed(texts) -> list[Embedding]` (batch, ABC)
- `ingest/pipeline.py:49` `Embedder.embed(text) -> list[float]` (single, Protocol)
- `embed/batcher.py:17` `_BatchEmbedder` (private, a third spelling of the first)
- `client.py:84,104` `_SingleTextEmbedder` / `_ZeroEmbedder` — adapters between
  two of **our own** abstractions

plus `retrieve/vector.py:21` `QueryEmbedder`, a fifth. And batching is found by
duck-typing at `ingest/pipeline.py:391`:

```python
embed_many = getattr(self._embedder, "embed_many", None)
```

A capability discovered by `getattr` is a capability no type checker can verify
and **no provider knows to offer** — the batch path is unreachable for every
third-party embedder ever written, because nothing tells them the name.

## What Changes

- **A new published module `citenexus/contracts.py`** — one contract per model
  seam, `@runtime_checkable` `Protocol`s, re-exported from the top-level
  `citenexus` package:
  - `EmbeddingProvider.embed_many(texts) -> list[Vector]` — **batch is the
    primitive** (ADR-0014 R1)
  - `GeneratorProvider.answer(question, passage, answer_language="en") -> str`
  - `CompletionProvider.complete(prompt) -> str` — ADR-0014 calls this "already
    almost exactly right"; it is now named, not implied
  - `VisionProvider.describe(image_region) -> Mapping[str, Any]`
  - `RerankerProvider.rerank(query, candidates) -> list[Candidate]`
  - plus two **named-and-deprecated** legacy shapes so the old spellings stop
    being anonymous: `SingleTextEmbedder.embed(text) -> Vector` and
    `SequenceEmbedder.embed(texts) -> list[Vector]`
  - and one dispatch helper, `embed_texts(embedder, texts)`, which prefers the
    contract's batch path and falls back to the legacy single-text shape.
- **All four shipped clients declare their contract** by inheriting it, so mypy
  `--strict` checks each one against the published shape:
  `OpenAICompatibleEmbedding` gains `embed_many` (+ an additive `batch_size=`),
  `OpenAICompatibleGenerator` and `AnthropicGenerator` declare
  `GeneratorProvider` + `CompletionProvider`, `OpenAICompatibleVision` declares
  `VisionPlugin` (the ABC that already existed and it never used) +
  `VisionProvider`, `OpenAICompatibleReranker` declares `RerankerProvider`.
- **The duplicate seams become aliases of the published contracts**, so there is
  one definition and several names rather than several definitions:
  `answer/flow.Generator`, `answer/decision.Completion`,
  `ingest/pipeline.Embedder`, `ingest/pipeline.VisionDescriber`,
  `retrieve/vector.QueryEmbedder`, `embed/batcher._BatchEmbedder`.
- **`_SingleTextEmbedder`, `_ZeroEmbedder` and the `getattr("embed_many")` probe
  are deleted.** `IngestPipeline` takes `embedder: ... | None` and writes the
  1-dim placeholder vector itself when there is none; batching is selected by
  `isinstance(embedder, EmbeddingProvider)` — a contract check a provider can
  read and a type checker can verify.
- **A third-party provider test** (`tests/test_third_party_provider.py`): an
  in-process, no-network implementation of every contract, written the way an
  outside author would write one — importing only `citenexus.contracts`, never
  inheriting a CiteNexus base class — asserted to ingest and **answer** through
  `CiteNexus(...)` end to end.

Not touched: the four constructors, the `Plugin` ABCs (public API, 0.x policy is
deprecated-not-removed), `answer/verify.py`, and every non-Python port.

## Capabilities

### New Capabilities
- `model-seam-contracts`: one published, runtime-checkable contract per model
  seam (embedding / generation / completion / vision / reranking); the shipped
  clients declaring them; batch as the embedding primitive; and the
  third-party-provider conformance proof.

## Impact

- **Code:** new `python/src/citenexus/contracts.py`; edits to `__init__.py`,
  `embed/client.py`, `embed/batcher.py`, `answer/generator.py`,
  `answer/anthropic.py`, `answer/flow.py`, `answer/decision.py`,
  `vision/client.py`, `retrieve/rerank.py`, `retrieve/vector.py`,
  `ingest/pipeline.py`, `client.py`.
- **Behavioural:** none intended. Existing single-text embedders keep working
  through the legacy path; `from_config` now hands `OpenAICompatibleEmbedding`
  straight to the pipeline instead of through an adapter, and the batch path is
  selected by contract rather than by `getattr` — the same requests, chosen
  legibly.
- **Out of scope, deliberately:** ADR-0014 **R3** (strip `transport` from the
  contract — breaking, and entangled with the next line) and the **sync-vs-async**
  question, which ADR-0014 leaves open and says must be settled first. The
  library stays synchronous; see `design.md` for how the contract avoids
  permanently excluding an async provider.
