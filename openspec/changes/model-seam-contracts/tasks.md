# Tasks — model seam contracts

## 1. Publish the contracts

- [x] 1.1 Red: `tests/contracts/test_contracts_module.py` — all five contracts
      import from `citenexus` and `citenexus.contracts`; each is a
      `runtime_checkable` Protocol
- [x] 1.2 Red: a class inheriting nothing from CiteNexus satisfies each contract
      by shape (`isinstance` passes)
- [x] 1.3 Red: no contract method parameter is named `base_url` / `headers` /
      `transport` / `timeout` (R3 posture, asserted by introspection)
- [x] 1.4 Implement `src/citenexus/contracts.py`: `Vector`,
      `EmbeddingProvider`, `GeneratorProvider`, `CompletionProvider`,
      `VisionProvider`, `RerankerProvider`, the deprecated `SingleTextEmbedder`
      / `SequenceEmbedder` legacy shapes, and `embed_texts()`
- [x] 1.5 Re-export all of it from `citenexus/__init__.py`

## 2. Declare the contracts on the shipped clients

- [x] 2.1 Red: each of the four clients `isinstance`-checks against its contract
- [x] 2.2 Red: the uniform keyword-only constructor still works for all four
- [x] 2.3 `OpenAICompatibleEmbedding`: add `embed_many` (+ additive
      `batch_size=`), declare `EmbeddingProvider`
- [x] 2.4 `OpenAICompatibleGenerator` + `AnthropicGenerator`: declare
      `GeneratorProvider`, `CompletionProvider`
- [x] 2.5 `OpenAICompatibleVision`: declare `VisionPlugin` (the ABC it never
      used) and `VisionProvider`
- [x] 2.6 `OpenAICompatibleReranker`: declare `RerankerProvider`

## 3. Collapse the duplicated seams

- [x] 3.1 Red: `answer.flow.Generator`, `answer.decision.Completion`,
      `ingest.pipeline.Embedder`, `ingest.pipeline.VisionDescriber`,
      `retrieve.vector.QueryEmbedder` are each the published contract object
- [x] 3.2 Alias them; delete `embed/batcher._BatchEmbedder` in favour of
      `SequenceEmbedder`

## 4. Batch by contract, not by `getattr`

- [x] 4.1 Red: an `EmbeddingProvider` ingest calls `embed_many` once with every
      text and never `embed`
- [x] 4.2 Red: a legacy single-text embedder still ingests
- [x] 4.3 Red: batch order is preserved across more texts than one batch
- [x] 4.4 Replace `getattr(self._embedder, "embed_many", None)` in
      `ingest/pipeline.py` with `contracts.embed_texts`
- [x] 4.5 `retrieve/vector.py` embeds the query through the same dispatch

## 5. Delete the private adapters

- [x] 5.1 Red: `CiteNexus` with no embedder ingests + answers lexically
- [x] 5.2 Red: `from_config` with an embedding endpoint ingests + answers
- [x] 5.3 `IngestPipeline.embedder` becomes `| None`; the pipeline writes the
      1-dim placeholder itself
- [x] 5.4 Delete `_SingleTextEmbedder` and `_ZeroEmbedder` from `client.py`;
      pass `OpenAICompatibleEmbedding` straight through
- [x] 5.5 Assert by grep-test that neither name, nor the `getattr` probe, remains

## 6. Failure is raised

- [x] 6.1 Red: a raising `embed_many` propagates out of ingest
- [x] 6.2 Red: a raising `answer` propagates out of `ask`

## 7. The proof: a third-party provider

- [x] 7.1 `tests/test_third_party_provider.py` — an in-process, no-network
      provider suite (embedding, generation, vision, reranking) written against
      `citenexus.contracts` alone, inheriting no CiteNexus class
- [x] 7.2 Assert each satisfies its contract by `isinstance`
- [x] 7.3 Assert the suite drives `CiteNexus(...)` through ingest → ask and
      produces a grounded answer with a citation to the ingested document
- [x] 7.4 Assert the same provider set is reused for a second question, and that
      the vision provider is exercised through the ingest seam

## 8. Gates

- [x] 8.1 `task check` — no existing test changes verdict
- [x] 8.2 `uv run python ../spikes/library-stress/stress.py` — four probes PASS
