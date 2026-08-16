# Port provider contracts (ADR-0014 R4)

## Why

ADR-0014 **R4** says the model seam is one contract with several *spellings*:

> the same contract, idiomatic in each language — Go returns `(T, error)`,
> JS returns a `Promise`.

`model-seam-contracts` delivered R1+R4 **for Python only**. Python now publishes
five `@runtime_checkable` Protocols in `citenexus.contracts`, every shipped client
declares its own, and `python/tests/test_third_party_provider.py` proves an
outside provider — no CiteNexus class in its MRO, sockets blocked — drives
ingest → ask to a cited answer.

**Go and JS publish no contract set at all.** After the R2 fix each port has a
corrected *ingest* seam (`ingest.Embedder` in Go, the `Embedder` function type in
JS) and shipped HTTP clients in `golang/models/` and `js/src/models/` — but:

| | Go | JS |
|---|---|---|
| a published embedding contract a provider can implement | ✗ | ✗ |
| a published generation contract | ✗ | ✗ |
| the shipped clients declare any contract | ✗ | ✗ |
| the end-to-end `ask` flow accepts an injected model | ✗ — hardcodes `fakes.FakeEmbedding{}` / `fakes.FakeLLM{}` | ✗ — hardcodes `new FakeEmbedding()` / `new FakeLLM()` |
| a third-party-provider proof test | ✗ | ✗ |

So "anyone can write a provider" is **true in Python and false in Go and JS**.
Worse, the last row means the ports' only end-to-end path *cannot be reached by
an injected model at all*: `golang/answer/answer.go` and `js/src/answer/answer.ts`
construct the deterministic fakes inline. A contract published against that
would be a type with no caller.

## What Changes

### Only the seams the ports can honestly honour

Python publishes **five** contracts. Go and JS get **two**. The other three are
deliberately **not shipped**, because neither port has anything that would call
them — and a contract with no consumer is worse than no contract, since it
advertises support that does not exist:

| seam | Go / JS consumer today | shipped? |
|---|---|---|
| embedding | ingest + the `ask` flow's retrieval | **yes** |
| generation | the `ask` flow's answer step | **yes** |
| completion | none — deep-ask is Python-only (`result.go:75` already says so) | **no** |
| vision | none — no conditional-vision path, no image extraction consumer | **no** |
| reranking | none — no `rerank` symbol exists anywhere in either port | **no** |

### Go

- **New package `golang/contracts`** — imports nothing, so a provider author's
  only dependency is an interface file:
  - `EmbeddingProvider` — `Embed(texts []string) ([][]float64, error)`
  - `GeneratorProvider` — `Answer(question, passage, answerLanguage string) (string, error)`
  - `SingleTextEmbedder` — `Embed(text string) ([]float64, error)`, the named,
    deprecated single-text shape; `ingest.Embedder` becomes an **alias** of it so
    there is one definition and two names
  - `EmbedTexts` / `EmbedOne` — the dispatch helpers, batch path preferred
  - `SingleFrom` — adapts a batch provider to the single-text ingest seam
- **`answer.AskWith(corpus, question, topK, Providers{...}) (result.Result, error)`**
  — the same flow, with the models injected. `answer.Ask` keeps its exact
  signature and behaviour (it is pinned by `conformance/cases/e2e_hermetic.json`)
  and is now `AskWith` with an empty `Providers`, which falls back to the fakes.
- **Both shipped generators and the embedding client declare their contract**
  by compile-time assertion (`var _ contracts.GeneratorProvider = …`).

### JS

- **New module `js/src/contracts.ts`**, exported from the package root:
  - `EmbeddingProvider` — `embed(texts: readonly string[]): Awaitable<Vector[]>`
  - `GeneratorProvider` — `answer(question, passage, answerLanguage?): Awaitable<string>`
  - `SingleTextEmbedder` = the existing `Embedder` function type, re-published
  - `isEmbeddingProvider` / `embedTexts` / `embedOne` — runtime dispatch
- **`askWith(corpus, question, opts): Promise<Result>`** — the injected twin of
  `ask`, which stays synchronous and fixture-pinned.
- **`OpenAIEmbedder`, `OpenAIChatGenerator`, `AnthropicGenerator` declare their
  contract** with a `satisfies`-style static assertion checked by `tsc --strict`.

### The proof, per port

- `golang/contracts/thirdparty_test.go` and `js/src/contracts.thirdparty.test.ts`
  — an in-process provider defined in the test file, depending on **no CiteNexus
  concrete type**, driving `AskWith` / `askWith` to a cited, gate-passing answer.
  Go's test additionally asserts the provider package's import graph is empty;
  JS's asserts the provider object is not an instance of any CiteNexus class.

## Impact

- Additive in both ports. `Ask` / `ask`, both conformance fixtures, and the
  library-stress probes are untouched.
- `python/`, `rust/`, `conformance/`, `site/`, `docs/adr/` are **not touched**.
