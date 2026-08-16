# Design — port provider contracts

## 1. The decision that comes first: which seams are real

The brief for R4 is "same contract, idiomatic spelling". The temptation is to
transliterate all five Python Protocols into Go interfaces and TS interfaces and
call the ports done. That would be **decoration**, and it fails the same test
ADR-0014 applies to `getattr("embed_many")`: an interface nobody calls tells a
provider author nothing about whether implementing it will do anything.

So each seam was checked against a single question — *what in this port would
consume it?*

| seam | evidence | verdict |
|---|---|---|
| **embedding** | `golang/ingest/ingest.go` embeds every chunk; `golang/answer/answer.go` embeds the corpus and the question. JS twins in `js/src/ingest/ingest.ts`, `js/src/answer/answer.ts`. Shipped clients: `models.OpenAIEmbedding`, `OpenAIEmbedder`. | **ship** |
| **generation** | `answer.go` / `answer.ts` call `FakeLLM.Answer(question, passage)` — the answer step of the flow. Shipped clients: `OpenAIChatGenerator`, `AnthropicGenerator` ×2 ports. | **ship** |
| **completion** | grep for `Complete` / deep-ask over both ports: no consumer. `golang/result/result.go:75` states it outright — *"Deep-ask is Python-only today, so Go always emits null"*. There is no decision loop to feed. | **do not ship** |
| **vision** | grep for `vision` / `describe` / image extraction over both ports: nothing. Neither port has a conditional-vision path, an `ImageRef`, or a figure Evidence Unit. | **do not ship** |
| **reranking** | grep for `rerank` over both ports: **zero hits, including tests.** Neither port has a `Candidate` type for the contract to be written in terms of, so the contract could not even be *spelled* without inventing the retrieval layer it reorders. | **do not ship** |

The three unshipped seams are not refused on principle — they are refused
*until the ports grow the path*. Each becomes a one-file addition the day a port
has a caller, and the contract's shape is already settled by Python. Publishing
them now would put a type in the public API of two packages that nothing reads,
which is exactly the "capability no provider knows to offer" ADR-0014 objects to,
inverted: a capability no library knows to use.

Two further Python-only things stay Python-only for the same reason and are
called out here so their absence is not read as an oversight: the **authority
policy** and the answer-language **`"auto"` sentinel** both live in the config
layer, and neither port has a config layer or an `ask()` facade over one.

## 2. The seam that had no caller either, and what we did about it

Both ports *do* have an end-to-end cite-or-abstain flow — and both hardcode the
fakes inside it:

```go
func Ask(corpus []Doc, question string, topK int) result.Result {
	embedder := fakes.FakeEmbedding{}          // golang/answer/answer.go
	...
	ans := fakes.FakeLLM{}.Answer(question, passage)
```

```ts
export function ask(corpus, question, topK = 5): Result {
  const embedder = new FakeEmbedding();       // js/src/answer/answer.ts
  const llm = new FakeLLM();
```

So publishing `GeneratorProvider` on its own would have produced precisely the
type-with-no-caller this design rejects. The contracts are therefore landed
**together with an injection point**, not before one.

`Ask` / `ask` cannot simply take the providers as parameters: both are pinned
byte-for-byte by `conformance/cases/e2e_hermetic.json`, which this change is
forbidden to regenerate. The shape is instead **additive**:

- `Ask(corpus, question, topK) result.Result` — unchanged signature, unchanged
  behaviour, still the fixture's entry point. It now delegates to `AskWith` with
  an empty provider set.
- `AskWith(corpus, question, topK, Providers) (result.Result, error)` — the same
  flow with `Providers.Embedding` / `Providers.Generator` injected. A nil field
  falls back to the corresponding fake, so a **partial** provider set is valid
  (mirroring Python's `test_a_third_party_provider_answers_without_an_embedding_model`).

JS mirrors it as `ask` (sync, pinned) and `askWith` (async, injected).

### Failure is an error, not a refusal

`AskWith` returns `(zero Result, err)` when a provider fails. It deliberately
does **not** convert a model failure into an abstention, even though abstaining
is the library's safe default everywhere else. A refusal is a *finding* — "we
searched the evidence and it does not support an answer". A timed-out embedding
model is not a finding about the evidence; reporting it as one would be the same
class of lie as the zero vector R2 removed: a failure wearing the costume of a
successful negative result.

## 3. Where the ports must diverge from Python's spelling

### 3.1 `embed`, not `embed_many` — and *why* the hazard is Python-only

Python named the batch method `embed_many`. From `contracts.py`:

> `str` is itself a `Sequence[str]`, so neither `isinstance` nor a type checker
> can tell the two apart. A contract spelled `embed` would silently accept the
> wrong implementation.

That hazard is a property of Python's `Sequence` protocol and **does not exist in
either port**:

- **Go** — `string` and `[]string` are unrelated types. `Embed(string) ([]float64, error)`
  and `Embed([]string) ([][]float64, error)` are two different method signatures;
  the compiler rejects the wrong one at the assignment, and a runtime
  `x.(EmbeddingProvider)` type assertion cannot match the single-text shape.
- **TypeScript** — `string` is not assignable to `readonly string[]`, and
  `tsc --strict` rejects the mismatch. At runtime the two shapes are not even the
  same *kind* of value: the single-text seam is a **function type**
  (`(text: string) => …`), the batch contract is an **object with an `embed`
  method**, so `typeof x === "function"` discriminates them with certainty.

So both ports use the natural name `Embed` / `embed`, which has the added
benefit that both shipped batch clients (`models.OpenAIEmbedding.Embed`,
`OpenAIEmbedder.embed`) **already** have exactly that name and satisfy the
contract without being renamed. Python's `embed_many` remains correct for
Python; R4 asks for identical semantics, not identical identifiers.

The one thing a port must not do is publish *both* shapes under the name `Embed`
in a way a single type could try to satisfy — in Go a type may not declare two
methods called `Embed`, which is enforcement rather than convention.

### 3.2 Error channel

| | Python | Go | JS |
|---|---|---|---|
| success | return value | `(T, nil)` | resolved `Promise<T>` |
| failure | `raise` | `(zero, err)` | rejected promise / `throw` |

No sentinels in any of the three: no zero vector, no empty answer, no `nil, nil`.
`golang/models/embed.go` already establishes this for `EmbedQuery`; the contracts
make it the published rule.

### 3.3 Sync vs async

Python's contracts are synchronous — ADR-0014 left sync-vs-async open and
"synchronous changes nothing today".

- **Go** takes the same position: a Go interface is synchronous and concurrency
  is the *caller's* to add with a goroutine, so there is nothing to decide.
- **JS cannot.** `HttpClient.send` is `async`, and R2 already widened the port's
  `Embedder` and `Transport` to `T | Promise<T>` precisely because the strict
  `=> T` spelling was unsatisfiable by any real provider. The contracts follow
  that established local precedent with a named `Awaitable<T> = T | Promise<T>`:
  a provider MAY return synchronously (the hermetic fakes do), consumers ALWAYS
  `await`. Declaring the contracts `Promise<T>`-only would have locked the
  deterministic fakes out of the contract they are the reference implementation
  of, for no gain — `await` on a plain value is already correct.

### 3.4 How a client "declares" its contract

Python declares by inheritance, so `mypy --strict` re-checks each client on every
run. Neither port has inheritance-based structural typing, so both use the
idiomatic compile-time assertion instead — same effect, checked by `go build` /
`tsc --noEmit`:

```go
var _ contracts.EmbeddingProvider = (*OpenAIEmbedding)(nil)
```

```ts
const _generatorContract: GeneratorProvider = null! as OpenAIChatGenerator;
```

### 3.5 The dispatch helper

Python's `embed_texts` dispatches with `isinstance(embedder, EmbeddingProvider)`.

- **Go**: `contracts.EmbedTexts(embedder any, texts []string)` type-switches on
  `EmbeddingProvider` then `SingleTextEmbedder`, and returns a *named error* for
  anything else. `any` is unpleasant, but the alternative — a union type Go does
  not have — is worse, and this is the one place the library chooses how to talk
  to an embedder, exactly as in Python.
- **JS**: `embedTexts(embedder, texts)` branches on
  `isEmbeddingProvider(embedder)`, a published type guard, then falls back to
  calling the function-shaped `SingleTextEmbedder` per text.

Both also ship the inverse adapter (`contracts.SingleFrom` / `singleFrom`) so a
batch provider plugs straight into the existing single-text ingest seam without
the author writing glue.

## 4. Vector sanity in `AskWith`

R2 put `checkVector` on the *ingest* write path. `AskWith` indexes in memory and
never touches that path, so it applies the same three rejections itself —
empty, dimension-inconsistent, all-zeros — before a vector can be scored. Without
it an injected provider could hand the flow a zero vector and the cosine would
rank it 0.0 with no error, which is the exact silent poison R2 exists to stop.

The Go port additionally needs a **length-guarded** dot product: `fakes.Cosine`
indexes `b[i]` for every `i` in `a` and would panic on a short vector. `fakes` is
left frozen (it is conformance-adjacent); `AskWith` uses its own guarded cosine.

## 5. What the third-party test has to prove

Mirroring `python/tests/test_third_party_provider.py`, but asserting the port's
own version of "outside":

| Python asserts | Go asserts | JS asserts |
|---|---|---|
| no CiteNexus class in the MRO | the provider type's only CiteNexus import is `contracts`, verified by reading the test file's own import block | the provider's prototype chain contains no CiteNexus class, and its constructor is declared in the test file |
| no socket opened | the provider is a struct literal with no `net`/`http` import in the file | the provider uses no `fetch`/`http` — asserted by stubbing `globalThis.fetch` to throw for the run |
| ingest → ask → cited answer | corpus → `AskWith` → `Decision.answered` with a citing `Sources[0]` | corpus → `askWith` → `Decision.answered` with a citing `sources[0]` |

Both ports' providers are the same pair Python uses, ported: a hashing
vectorizer, and an **extractive** generator that returns the passage sentence
with the most question overlap verbatim — the only kind of generator that can
survive the faithfulness gate, which is the point.
