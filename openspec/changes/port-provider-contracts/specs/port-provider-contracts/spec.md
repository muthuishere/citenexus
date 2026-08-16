## ADDED Requirements

### Requirement: Every port publishes a contract for each model seam it can consume

Each non-reference port (Go, JavaScript/TypeScript) SHALL publish an interface
contract for every model seam that port actually consumes, from a single
importable location — the `contracts` package in Go, the `contracts` module
re-exported from the package root in JS.

A port SHALL NOT publish a contract for a seam it has no consumer for. A
published contract asserts that implementing it makes the library use the
provider; a contract with no call site in that port would make that assertion
falsely.

Contracts SHALL name only the operation. Transport concerns — base URL, headers,
transport, timeouts, status codes — SHALL NOT appear in any contract method
signature, so a provider that never opens a socket satisfies every contract.

Contracts SHALL be satisfiable by structural shape alone: an implementation
SHALL NOT be required to embed, extend, or otherwise name a CiteNexus concrete
type.

#### Scenario: The embedding and generation contracts are published by both ports

- **WHEN** a provider author looks for the model seam contracts in the Go port
- **THEN** `contracts.EmbeddingProvider` and `contracts.GeneratorProvider` resolve
  from `github.com/muthuishere/citenexus/golang/contracts`
- **AND** the same two contracts resolve by name from the JS package root

#### Scenario: The unconsumed seams are absent, not stubbed

- **GIVEN** the completion, vision and reranking seams have no consumer in either
  port
- **WHEN** the published contract set of that port is enumerated
- **THEN** it contains no completion, vision or reranking contract

#### Scenario: No contract mentions a transport

- **WHEN** the parameters of every published contract method are inspected
- **THEN** none is a base URL, a header map, a transport, or a timeout

#### Scenario: The contracts package depends on nothing

- **WHEN** the Go `contracts` package's imports are inspected
- **THEN** it imports no other CiteNexus package

### Requirement: The port contracts carry Python's semantics in the port's spelling

A port contract SHALL express the same operation, the same meaning, and the same
failure expectation as the Python reference contract it mirrors, and SHALL be
spelled the way that language spells things.

Failure SHALL be reported through the language's error channel — Go returns a
non-nil `error`, JS rejects or throws. A contract SHALL NOT define a sentinel
return: a zero vector, an empty answer, and a nil-nil pair are not failures.

Batching SHALL be the embedding primitive: the contract takes a list of texts and
returns one vector per input text in input order. A single text is a batch of one.

Ports MAY use a method name different from Python's where Python's name exists
only to work around a Python-specific ambiguity, provided the port documents why
the ambiguity does not arise there.

#### Scenario: Go reports failure as an error

- **GIVEN** a Go provider that cannot fulfil a call
- **WHEN** the contract method returns
- **THEN** its `error` result is non-nil
- **AND** its value result is not a placeholder the caller could mistake for data

#### Scenario: JS reports failure by rejecting

- **GIVEN** a JS provider that cannot fulfil a call
- **WHEN** the contract method is awaited
- **THEN** the promise rejects

#### Scenario: A synchronous JS provider still satisfies the contract

- **GIVEN** an in-process JS provider that returns a value rather than a promise
- **WHEN** a consumer awaits it
- **THEN** the call succeeds, because the contract's return type is `T | Promise<T>`

#### Scenario: Batch order is preserved

- **GIVEN** an embedding provider given N texts
- **WHEN** it returns
- **THEN** it returns exactly N vectors, the i-th being the embedding of the i-th text

#### Scenario: The single-text and batch shapes cannot be confused

- **GIVEN** a value implementing only the deprecated single-text embedding shape
- **WHEN** it is tested against the batch `EmbeddingProvider` contract
- **THEN** the test fails, in Go at compile time and by type assertion, in JS by
  the published type guard

### Requirement: The shipped clients declare their contract

Every model client shipped by a port SHALL declare the contract it satisfies in a
way the port's compiler verifies on every build, so a client that drifts from the
published shape fails the build rather than a runtime call.

#### Scenario: Each shipped client is checked against its contract

- **WHEN** the Go port is built
- **THEN** `OpenAIEmbedding` is asserted to satisfy `EmbeddingProvider`, and
  `OpenAIChatGenerator` and `AnthropicGenerator` to satisfy `GeneratorProvider`
- **AND** the JS port's `tsc --strict` run asserts the same for `OpenAIEmbedder`,
  `OpenAIChatGenerator` and `AnthropicGenerator`

### Requirement: The end-to-end flow accepts injected providers

Each port's cite-or-abstain flow SHALL offer an entry point that takes the
embedding and generation providers as arguments, so a published contract has a
call site.

The existing fixture-pinned entry point (`Ask` / `ask`) SHALL keep its exact
signature and behaviour and SHALL be defined in terms of the injecting entry
point with an empty provider set.

A provider set MAY be partial: an absent provider SHALL fall back to that port's
deterministic fake, so a generation-only or embedding-only provider is valid.

A provider failure SHALL surface as an error, and SHALL NOT be reported as a
refusal. A refusal states a finding about the evidence; a failed model call is
not one.

Vectors entering the flow SHALL be rejected if they are empty, inconsistent in
dimension with the run, or all zeros — the same three rejections the ingest write
path applies.

#### Scenario: The pinned entry point is unchanged

- **WHEN** the hermetic end-to-end conformance fixture is replayed through `Ask` / `ask`
- **THEN** every case yields the pinned decision, answer, document, passage and eu_id

#### Scenario: Injected providers produce a cited answer

- **GIVEN** an embedding provider and a generation provider supplied by the caller
- **WHEN** the injecting entry point is called with a corpus and a question the
  corpus answers
- **THEN** the decision is `answered`, the answer is verbatim from the cited
  passage, and the cited source is the document that contains it

#### Scenario: A provider failure is an error, not an abstention

- **GIVEN** an embedding provider that fails
- **WHEN** the injecting entry point is called
- **THEN** it reports the failure as an error
- **AND** it does not return a refusal result

#### Scenario: A degenerate vector is refused

- **GIVEN** an embedding provider that returns the zero vector without failing
- **WHEN** the injecting entry point is called
- **THEN** it reports an error naming the degenerate vector, and answers nothing

### Requirement: Each port proves a third-party provider drives it

Each port SHALL carry a test in which a provider is defined inside the test file,
implements only the published contracts, depends on no CiteNexus concrete type,
opens no network connection, and drives that port's end-to-end flow to a cited
answer.

The test SHALL assert those constraints rather than assume them.

#### Scenario: An outside provider answers end to end

- **GIVEN** a provider defined in the test file that names only the published
  contracts
- **WHEN** it is passed to the port's injecting entry point over a two-document corpus
- **THEN** the result is `answered`, cites the correct document, and the answer
  text appears verbatim in that document

#### Scenario: The provider's independence is asserted, not assumed

- **WHEN** the test runs
- **THEN** it asserts the provider takes no CiteNexus concrete type, and that no
  network call was made during the end-to-end run

#### Scenario: A batch-only provider is sufficient

- **GIVEN** a provider implementing only the batch embedding contract
- **WHEN** the flow embeds the corpus and then the question
- **THEN** both go through the batch method, the question as a batch of one
