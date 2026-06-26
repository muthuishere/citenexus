## ADDED Requirements

### Requirement: Versioned Plugin base

Every plugin SHALL derive from a common `Plugin` base that carries a
`plugin_version` identifier. Registration of a plugin without a non-empty
`plugin_version` SHALL be rejected, because §4c provenance stamps depend on it.

#### Scenario: Plugin exposes plugin_version

- **WHEN** any concrete plugin instance is inspected
- **THEN** it has a `plugin_version` attribute that is a non-empty string

#### Scenario: Missing plugin_version is rejected

- **WHEN** an object that satisfies a protocol's methods but has no (or empty)
  `plugin_version` is registered
- **THEN** registration raises an error and the object is not registered

### Requirement: The eleven typed plugin protocols exist

The library SHALL define exactly these abstract plugin protocols, each with the
abstract method(s) naming its input/output contract: `ExtractorPlugin`
(`extract(source) -> ExtractedDoc`), `ChunkerPlugin`
(`chunk(doc) -> list[EvidenceUnit]`), `EmbeddingPlugin`
(`embed(texts) -> list[Embedding]` producing dense and optional sparse vectors),
`VisionPlugin` (`describe(image_region) -> VisionResult`), `GraphExtractorPlugin`
(`extract_graph(units) -> GraphFragment`), `RetrieverPlugin`
(`retrieve(query, k) -> list[Candidate]`), `RerankerPlugin`
(`rerank(query, candidates) -> list[Candidate]`), `JudgePlugin`
(`judge(question, answer, evidence, golden) -> Verdict`), `EvaluatorPlugin`
(`evaluate(corpus, golden) -> Metrics`), `LanguageDetectorPlugin`
(`detect(text) -> LanguageResult`), and `MemoryPlugin`
(`store(turn)` and `recall(query) -> list[Turn]`). Each protocol SHALL be an
abstract base that cannot be instantiated directly.

#### Scenario: All eleven protocols are defined and abstract

- **WHEN** the plugin base module is imported
- **THEN** all eleven protocol classes are present and each is abstract
  (instantiating one directly raises `TypeError`)

#### Scenario: A protocol declares its contract method

- **WHEN** a subclass of `EmbeddingPlugin` omits the `embed` method
- **THEN** instantiating that subclass raises `TypeError` for the unimplemented
  abstract method

### Requirement: Typed registration, not duck-typed

The registry SHALL accept a plugin only if it is an instance of one of the
declared protocols. An object that merely resembles a plugin (loose / untyped)
SHALL be rejected, because §4c must know exactly what produced each artifact.

#### Scenario: Conforming plugin registers and resolves by protocol type

- **WHEN** a concrete `EmbeddingPlugin` is registered
- **THEN** `resolve(EmbeddingPlugin)` returns that same instance

#### Scenario: Non-conforming object is rejected

- **WHEN** a plain object that is not an instance of any plugin protocol is
  registered
- **THEN** registration raises a `TypeError` (or a dedicated registration error)
  and nothing is stored

### Requirement: Single-slot replacement and the retriever fusion set

The registry MUST treat single-slot stages (extractor, chunker, embedding,
vision, graph extractor, reranker, judge, evaluator, language detector, memory)
as last-wins: registering a new plugin MUST replace the current one for that
protocol. Retrievers MUST instead form a fusion set: `register_retriever` MUST
add a retriever so multiple retrievers coexist and all contribute candidates.

#### Scenario: Re-registering a single-slot stage replaces it

- **WHEN** two different `EmbeddingPlugin` instances are registered in turn
- **THEN** `resolve(EmbeddingPlugin)` returns the most recently registered one

#### Scenario: Multiple retrievers coexist in the fusion set

- **WHEN** two distinct `RetrieverPlugin` instances are registered via
  `register_retriever`
- **THEN** the retriever fusion set contains both, in registration order

### Requirement: `use()` dispatches by protocol type

The registry SHALL expose a single `use(plugin)` verb (§15) that inspects the
plugin's protocol type and routes it to the correct slot — single-slot stages
to their slot, retrievers into the fusion set — without the caller naming the
protocol.

#### Scenario: use() routes a retriever into the fusion set

- **WHEN** `use(my_retriever)` is called with a `RetrieverPlugin`
- **THEN** the retriever appears in the fusion set (same as `register_retriever`)

#### Scenario: use() routes a single-slot plugin to its slot

- **WHEN** `use(my_reranker)` is called with a `RerankerPlugin`
- **THEN** `resolve(RerankerPlugin)` returns that reranker

### Requirement: Built-ins are plugins too (no privileged path)

Built-in default implementations SHALL register through the same mechanism as
third-party plugins; there is no special-cased code path that bypasses the
registry.

#### Scenario: A built-in registers via the public mechanism

- **WHEN** a built-in default plugin is installed into a registry
- **THEN** it is registered through the same `use()`/`register_*` API and is
  resolvable identically to a third-party plugin

### Requirement: Fusion stays in core

A `RetrieverPlugin` SHALL only return a ranked list of candidates. The protocol
SHALL NOT expose any hook to perform fusion, reranking, grounding, or to emit a
final answer, so a third-party retriever can never bypass the RRF + grounding
guarantees that remain in core.

#### Scenario: RetrieverPlugin contract is limited to ranked candidates

- **WHEN** the `RetrieverPlugin` protocol is inspected
- **THEN** its only abstract contract method returns a ranked candidate list,
  and it declares no fusion / grounding / answer-emitting method
