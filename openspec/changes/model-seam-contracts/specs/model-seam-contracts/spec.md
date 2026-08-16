## ADDED Requirements

### Requirement: One published contract per model seam

The library SHALL publish exactly one interface contract for each model seam —
embedding, generation, raw completion, vision, and reranking — from a single
module, `citenexus.contracts`, re-exported from the top-level `citenexus`
package.

Each contract SHALL be a `@runtime_checkable` `typing.Protocol`, so that an
implementation satisfies it by **matching its shape** and is never required to
import from or inherit a CiteNexus class.

Each contract SHALL name only the operation. Transport concerns — `base_url`,
`headers`, `transport`, timeouts, status codes — SHALL NOT appear in any
contract method signature.

#### Scenario: The contracts are importable from the package root

- **WHEN** a provider author imports `EmbeddingProvider`, `GeneratorProvider`,
  `CompletionProvider`, `VisionProvider` and `RerankerProvider`
- **THEN** all five resolve from `citenexus` and from `citenexus.contracts`

#### Scenario: A provider satisfies a contract without inheriting it

- **GIVEN** a class that defines the contract's methods and inherits nothing
  from CiteNexus
- **WHEN** it is checked with `isinstance` against the contract
- **THEN** the check passes

#### Scenario: No contract mentions a transport

- **WHEN** the parameters of every published contract method are inspected
- **THEN** none is named `base_url`, `headers`, `transport`, or `timeout`

### Requirement: Batch is the embedding primitive

The embedding contract SHALL be batch-first: `embed_many(texts) -> list[Vector]`,
where a single text is a batch of one. Batching SHALL NOT be discovered by
attribute probing.

The ingest pipeline SHALL select the batch path by checking the embedder against
the published contract, and SHALL fall back to the deprecated single-text shape
only when the embedder does not satisfy it.

The order of returned vectors SHALL match the order of the input texts.

#### Scenario: A contract-satisfying embedder is called once per batch

- **GIVEN** an embedder implementing `EmbeddingProvider`
- **WHEN** a document with several Evidence Units is ingested
- **THEN** `embed_many` is called with all of the texts
- **AND** no per-text call is made

#### Scenario: A legacy single-text embedder still works

- **GIVEN** an embedder that offers only `embed(text) -> Vector`
- **WHEN** a document with several Evidence Units is ingested
- **THEN** each text is embedded individually and ingest succeeds

#### Scenario: Batching preserves input order

- **GIVEN** an embedder implementing `EmbeddingProvider`
- **WHEN** more texts than one batch are embedded
- **THEN** the nth returned vector is the embedding of the nth input text

### Requirement: The shipped clients declare their contracts

Every model client the library ships SHALL declare the contract it implements,
so that each is a statically checkable implementation of the published shape:

- `OpenAICompatibleEmbedding` SHALL satisfy `EmbeddingProvider`
- `OpenAICompatibleGenerator` and `AnthropicGenerator` SHALL satisfy
  `GeneratorProvider` and `CompletionProvider`
- `OpenAICompatibleVision` SHALL satisfy `VisionProvider`
- `OpenAICompatibleReranker` SHALL satisfy `RerankerProvider`

The uniform keyword-only constructor of these clients — `base_url`, `model`,
`transport`, `headers`, plus role-specific extras — SHALL be unchanged.

#### Scenario: Each shipped client checks against its contract

- **WHEN** each of the four clients is constructed with a fake transport
- **THEN** `isinstance` against its declared contract passes

#### Scenario: The constructors are unchanged

- **WHEN** each client is constructed with keyword-only `base_url`, `model`,
  `transport` and `headers`
- **THEN** construction succeeds

### Requirement: Failure is raised, never encoded in a return value

A provider that cannot fulfil a call SHALL raise. The contracts SHALL NOT define
a sentinel success value: an embedding contract SHALL NOT return a zero vector to
signal failure, and a generation contract SHALL NOT return an empty string to
signal failure.

A raised provider error SHALL propagate to the caller rather than being converted
into a degraded result.

#### Scenario: A raising embedder fails ingest loudly

- **GIVEN** an embedder whose `embed_many` raises
- **WHEN** a document is ingested
- **THEN** the error propagates and no Evidence Unit is indexed with a
  placeholder vector in its place

#### Scenario: A raising generator fails the ask loudly

- **GIVEN** a generator whose `answer` raises
- **WHEN** a question is asked against a corpus with evidence
- **THEN** the error propagates rather than being reported as a refusal

### Requirement: One definition per seam, several names

Each duplicated model seam declaration in the library SHALL be an alias of the
corresponding published contract rather than an independent redeclaration:
`answer.flow.Generator`, `answer.decision.Completion`,
`ingest.pipeline.Embedder`, `ingest.pipeline.VisionDescriber` and
`retrieve.vector.QueryEmbedder`.

The private adapters that bridged the library's own embedding abstractions
SHALL be removed, and an absent embedder SHALL be modelled as absent rather than
as a provider returning a constant vector.

#### Scenario: The duplicate seams are the published contracts

- **WHEN** `answer.flow.Generator`, `answer.decision.Completion`,
  `ingest.pipeline.VisionDescriber` and `retrieve.vector.QueryEmbedder` are
  compared to their published counterparts
- **THEN** each is the same object

#### Scenario: A client with no embedder still ingests and searches lexically

- **GIVEN** a `CiteNexus` constructed with no embedder
- **WHEN** a document is ingested and a lexical question is asked
- **THEN** ingest succeeds and the answer is grounded in the document

### Requirement: A third-party provider can drive the library end to end

A provider written only against the published contracts — importing nothing from
CiteNexus but `citenexus.contracts`, inheriting no CiteNexus class, and opening
no network connection — SHALL be usable as the embedding, generation, vision and
reranking model of a `CiteNexus` client, and SHALL produce a grounded, cited
answer.

#### Scenario: An in-process third-party provider answers

- **GIVEN** embedding, generation and reranking providers that satisfy the
  published contracts and never touch the network
- **WHEN** they are injected into `CiteNexus`, a corpus is ingested, and a
  question is asked
- **THEN** the answer is grounded and carries a citation to the ingested
  document
