# 0014 — The model seam is a contract, not an endpoint

Status: **accepted, implemented** (R1, R2, R4 · R3 was already true — see below) · 2026-08-16
· written by a would-be provider, not by the library · corrected 2026-08-16 against the
implementation and the feasibility spike (`spikes/model-seam-contract/`)

> **Read this first.** The argument below is sound and is left as written. What changed is
> the facts: R3 turned out to be **already satisfied** before any code moved, the Python
> embedding count was **five, not four**, and two of the claims about the ports were
> *understated* rather than wrong. Every correction in this document was verified by
> construction — `spikes/model-seam-contract/spike.py` runs offline and reproduces each
> one, including the Go corpus-poisoning bug exactly as claimed here.

## Context

`CLAUDE.md` states the rule as **"Models are injected OpenAI-compatible *endpoints*"**, and
that word is doing more work than it looks like it is. An endpoint is a URL. Requiring one
excludes three things that are not exotic:

- **an in-process model** — a library loaded into the same process, no socket
- **a mock** — the thing every test in this repo would rather use than a live model
- **anything that is not HTTP** — a queue, a local daemon on a unix socket, a cached fixture

The code already disagrees with the rule, which is the strongest evidence that the rule is
wrong. Embedding alone was injected through **five different abstractions in Python**
(the first draft of this ADR said four and missed the one on the public constructor), plus
one each in Go and JS, and no two agreed:

| where | shape |
|---|---|
| `plugins/base.py:62` | `EmbeddingPlugin.embed(texts: Sequence[str]) -> list[Embedding]` — batch, ABC |
| `ingest/pipeline.py:49` | `Embedder(Protocol).embed(text: str) -> list[float]` — single, Protocol |
| `embed/batcher.py:17` | `_BatchEmbedder(Protocol).embed(texts) -> list[list[float]]` — a third shape, and *not* interchangeable with the ABC's `list[Embedding]` |
| `retrieve/vector.py:21` | `QueryEmbedder(Protocol).embed(text: str) -> list[float]` — **the one on the public constructor** (`client.py:153` `embedder: QueryEmbedder \| None`) |
| `smoke/pipeline.py:32` | `Embedder(Protocol)` — the single-text shape declared a second time |
| `client.py:84` | `_SingleTextEmbedder` — an adapter between two of the above |
| `golang/ingest/ingest.go:24` | `Embedder interface { Embed(text string) []float64 }` |
| `js/src/ingest/ingest.ts:16` | `type Embedder = (text: string) => number[]` |

`_SingleTextEmbedder` exists *only* to bridge two of our own abstractions. That is the tell.
Specifically, it bridged the *batch wire plugin* down to the *single-text seam sitting on the
public constructor* — so under R1 it does not merely disappear, it would have had to flip
direction into a single→batch shim. (It did not: the constructor now accepts either shape and
the library dispatches. See "What was built".)

`_ZeroEmbedder` (`client.py:104`) was listed here in the first draft as a third adapter. That
was a misfiling, and the correction matters: **it was not an adapter at all — it was a missing
default**, and it was the exact anti-pattern R2 names below ("a zero vector is not an error
value"), sitting inside the *Python reference*, not only in Go. It existed because
`IngestPipeline` demanded an embedder and a lexical-only client has none, so it returned
`[0.0]` to put *something* in the vector column. Modelling "no model" as a fake model is what
forced it to be a class.

And `pipeline.py:391` reaches for batching by duck-typing:

```python
embed_many = getattr(self._embedder, "embed_many", None)
if callable(embed_many) and texts:
```

A capability discovered by `getattr` is a capability no port can see, no type checker can
verify, and no provider knows to offer.

### What this costs a provider today

Two of the shapes are **structurally unable** to accept a real provider. Both claims were
reproduced by construction in the spike, and both turned out to be *worse* than written here:

- **Go returns no error.** `Embed(text string) []float64`. A model that times out, refuses, or
  runs out of memory has no way to say so. It returns a zero vector and ingest indexes it. The
  corpus is then quietly wrong in a way retrieval cannot detect. Reproduced exactly:
  `ingest() returned err = <nil>`, 3 rows written (same as the healthy run), the poisoned row
  scoring `cosine=0.0000` with no error and no flag — and the poisoned row was the
  polarity-flipped "may not disclose" clause, the one sentence a legal corpus cannot lose.
  The honest signature is *structurally rejected* by the compiler:
  `have Embed(string) ([]float64, error) / want Embed(string) []float64`.
  What the first draft missed: Go **already had** the contract this ADR asks for —
  `golang/models/embed.go:33` `Embed(texts []string) ([][]float64, error)`, batch,
  error-returning, transport-injected. It simply could not be plugged into `ingest.Ingest`.
  Go's real model client and Go's ingest seam had never met.
- **JS is synchronous.** `(text: string) => number[]`. No network- and no model-backed embedder
  can satisfy that type at all. This ADR first said it "works today only because whatever is
  behind it is already resident"; the truth is **nothing was behind it**. Underneath sat a
  second type lie: `Transport` was declared `(url, body, headers) => string`, while the only
  concrete transport is `async send(): Promise<string>` — so `models/embed.ts` was doing
  `JSON.parse` on a Promise and dying in `Unexpected token 'o', "[object Promise]"`. Every test
  that exercised it injected a *synchronous fake* transport, which is exactly what hid it.
  **The JS port had no working real-model ingest path at all.**

Neither is a style complaint. They are the reason a provider cannot plug in. The honest framing
is stronger than "breaking change to two ports": *neither Go nor JS had ever run a real model
through ingest*, so the migration was smaller than it sounds and the defect larger.

## Decision

**Specify the model seam as a contract that any implementation can satisfy, and stop
specifying it as an endpoint.**

Four requirements. They are what a provider needs in order to exist; how each port spells them
is the port's business.

### R1 — One embedding shape, and it is batch

One embedder abstraction per port. Batch is the primitive; a single text is a batch of one, not
a second method. Batching is where the throughput is, and today only Python can find it — by
`getattr`.

### R2 — Failure must be expressible

Every model call can fail, and the seam must let it say so in the port's own idiom: an `error`
return in Go, a raised exception in Python, a rejected promise in JS.

A zero vector is not an error value. It is a valid embedding of something, and once written it
is indistinguishable from a document that genuinely embeds near the origin.

**R2 does not apply to Python.** The first draft lumped all three ports together; it should
not have. Python's seam is untyped about failure but is not *broken* by it — a raising embedder
propagates and nothing is written. Python's problem was **R1 only**: five declarations and a
`getattr`, a discoverability defect, not a correctness one. R2 is a Go and JS finding. The one
place Python did commit R2's own anti-pattern was `_ZeroEmbedder`, and that was a missing
default rather than a seam (see Context).

### R3 — The seam must not assume a transport — **already satisfied; nothing to do**

*This requirement, as written, misdirects effort. Read the correction before acting on it.*

The rule stands: no `base_url`, no headers, no status codes, no `timeout` in the signature.
Those belong to *one* implementation of the contract, not to the contract. A provider that
never opens a socket must be able to satisfy it without inventing an HTTP response to hand
back.

But the codebase **already obeyed it, everywhere, before any of this changed.** No seam in any
port — embedding, rerank, vision, completion, generator — names a URL, a header, a status code
or a timeout. `base_url`, `headers` and `transport` are **constructor** parameters of the HTTP
clients and were never method parameters, so an in-process provider satisfied every contract on
day one. R3 unblocked nothing, because nothing was blocked.

What is left of R3 is narrow and should be described as such: removing `transport` and friends
from the *shipped HTTP clients' constructors* would be breaking, and is a different and much
smaller thing than "the seam assumes a transport". It is deliberately out of scope. Do not plan
work against R3 as originally phrased.

### R4 — The same contract across the ports

Same fields, same semantics, idiomatic spelling. Go returns `(T, error)`, Python raises, JS
returns a `Promise`. What must not differ is *what the seam is for* and *what it promises*.

`conformance/` is where this becomes real: a provider that satisfies the contract in one port
must satisfy it in all of them, and that is testable in the way this repo already tests
everything else.

#### The ABCs are not the thing to extend — and `plugins/base.py` is not wrong either

R4's "matching the shape is enough" reads as a direct contradiction of `plugins/base.py`'s
stated rationale: *"These are `abc.ABC` protocols (NOT `typing.Protocol`) on purpose: the
registry must reject non-conforming objects at runtime, and an `isinstance` gate against an ABC
is reliable where structural checks are not."* Both are right, for different jobs, and the ADR
owes the reader the split:

- **Registry rejection wants nominal ABCs.** Subclassing forces the method to exist and gives
  the registry a reliable gate plus the `plugin_version` provenance stamp. That reasoning is
  unaffected and those ABCs stay exactly as they are.
- **A published provider contract must be structural.** An ABC forces `import citenexus` into a
  third party's own source and makes this library a build-time dependency of anyone who wants
  to be compatible — the precise opposite of "an in-process model, a mock, or an adapter
  someone else ships can satisfy it without naming us".

So the two layers coexist: `@runtime_checkable` `Protocol`s in `citenexus.contracts` are what a
provider implements; the `Plugin` ABCs remain what the registry gates on. A reader should not
conclude from R4 that the way to add a model seam is to extend the ABCs.

### Applies to every model seam, not only embeddings

`EmbeddingPlugin`, `RerankerPlugin`, `VisionPlugin`, `DecisionModel` (`answer/decision.py:33`)
and `Completion` (`answer/decision.py:39`) are the same problem in five places. `Completion` —
*"one prompt in, one string out"* — is already almost exactly right, and is the model the others
should follow.

## What this is not

- **Not a factory.** Which provider to build is the host's decision, and a factory in the
  library either hardcodes the list or grows a registry of strings. The contract is what is
  missing.
- **Not a dependency on any provider.** CiteNexus keeps "no bundled models" exactly as it is.
  The contract names no implementation.
- **Not an HTTP client abstraction.** R3 is the opposite of that: HTTP becomes one
  implementation among several rather than the shape everything must fit.

## Consequences

- **The offline test suite becomes honest.** The first draft claimed "every test can run
  offline" as a consequence. It was **already true** — every test in the repo already ran
  offline through `FakeEmbedding` / `FakeLLM` / a fake `Transport`. The contract buys nothing
  there, and the real argument is sharper: *the fakes were the only things that could satisfy
  the Go and JS seams*, so the suite was green precisely because it never exercised a real
  provider. Offline was not the achievement; it was the camouflage. What the contract buys is a
  suite in which a mock and a real provider are the same shape, so passing means something.
- **Two real bugs get fixed** on the way: Go's silent zero vector, and JS's un-satisfiable
  synchronous type (plus the dead `Transport` underneath it).
- **`_SingleTextEmbedder` and `_ZeroEmbedder` disappear** — for different reasons.
  `_SingleTextEmbedder` was an adapter between our own abstractions and has nothing left to
  bridge; `_ZeroEmbedder` was a missing default, now modelled as `embedder=None` with
  `IngestPipeline` writing its own 1-dim placeholder. The placeholder is the storage layer's
  business, not a provider's, and "no model" is no longer spelled as a fake model.
- **`getattr(self._embedder, "embed_many")` disappears.** Batch is the contract, not a
  discovered capability.
- **Breaking**, in Go and JS especially. Better now than after either has consumers.
- CiteNexus becomes composable with anything — including toolnexus, whose client is precisely a
  `Completion`, and including a local in-process model. Neither library imports the other; the
  glue is an adapter someone else ships.

## Resolved (was "Open")

All three were settled by the spike, before the contract was written, as this ADR asked.

- **Async or sync in Python → sync, and batch.** The two are the same decision. A sync *batch*
  contract does **not** exclude an async provider: the provider runs its own event loop inside
  `embed_many(texts)` and CiteNexus never sees a coroutine. What excludes an async provider is a
  sync *single-text* contract, where there is nothing to gather. So R1 buys Q1 for free. Shipping
  `aembed`/`AsyncEmbeddingPlugin` was rejected: it doubles the API surface and the conformance
  matrix, and the async colour spreads up the whole stack (`IngestPipeline` → `ingest` → `ask`)
  for a caller base that has asked for none of it. Protocols compose, so an async seam can still
  be published *beside* these later without forcing any provider to also offer a blocking method.
  Reopen only if CiteNexus must be callable from inside a running event loop (FastAPI handlers) —
  the answer there is a documented thread-pool bridge, still not a second seam.
- **`Embedding` as the return type → dropped. The contract returns dense `list[Vector]`.**
  `plugins/base.py:28` is literally `Embedding = Any  # a dense vector + optional sparse term
  weights` — it documented an intention and enforced nothing, and `mypy --strict` was passing on
  it vacuously. And `EvidenceUnit.sparse_vector` has **zero writes and zero reads**: one
  declaration, no assignments, no call sites. The lexical signal is BM25 over stored EU text and
  never touches the embedder. Sparsity is already elsewhere, so this is not a decision to move
  it — it is deleting an alias that never described reality. A sparse-capable endpoint, if one
  ever lands, is a separate `SparseEmbedding` contract fused as a third retrieval signal.
- **Reranking with embedding, or separate → two contracts.** Different arity and different
  meaning: `embed_many(texts) -> vectors` is a pure map; `rerank(query, candidates) ->
  candidates` is a query-conditioned reordering, and a cross-encoder has no vector to hand back
  at all. They already share nothing but the `Plugin` base, and the real clients share only
  `Transport`. Reranking is also the seam most likely to grow options (top-n, thresholds,
  instruction prefixes) that embedding will never want. Keep the *requirements* shared (R1, R2,
  R4); keep the *contracts* separate — same for vision and completion.

## What was built

Python (`citenexus.contracts`, re-exported top-level) — five `@runtime_checkable` Protocols:
`EmbeddingProvider.embed_many`, `GeneratorProvider.answer`, `CompletionProvider.complete`,
`VisionProvider.describe`, `RerankerProvider.rerank`. All four shipped clients declare theirs,
so `mypy --strict` checks each against the published shape. The `Plugin` ABCs are retained under
the 0.x deprecated-not-removed policy. Gone: `_SingleTextEmbedder`, `_ZeroEmbedder`,
`_BatchEmbedder`, and the `getattr(…, "embed_many")` probe.

**The method is `embed_many`, not `embed`, and the reason is worth preserving.** `str` *is* a
`Sequence[str]`, so a contract spelled `embed` cannot be distinguished from the single-text shape
— not by `isinstance`, and not by a type checker either, since passing a `str` where a
`Sequence[str]` is expected is legal. A contract spelled `embed` would silently accept the wrong
implementation and return a list of floats where a list of vectors was promised. `embed_many` is
unambiguous, and it is not invented: it is the exact name ingest was already duck-typing for.

Go — `Embed(text) ([]float64, error)` plus an `EmbedderFunc` adapter, which plugs the existing
real client (`golang/models/embed.go`) into ingest with no new abstraction. `models.EmbedQuery`
no longer returns `(nil, nil)` on empty data — the same silent poison in miniature, inside the
real client. Zero-length and wrong-dimension vectors are refused at the *write* path as well as
at the seam, and a failed embed is fail-closed and all-or-nothing: the ingest aborts and writes
nothing. Skip-and-report was rejected because a document missing one chunk is, at retrieval
time, indistinguishable from a document that never contained that sentence.

JS — `Embedder` may be async, and `Transport` may return a `Promise`. The second half was not
optional: without it the change would have been cosmetic on top of a dead transport.

## What remains

**Go and JS publish no contract set.** Both ports now have the corrected *seams* (R2), but
neither has a `GeneratorProvider` / `VisionProvider` / `RerankerProvider` equivalent, because
neither port has an `ask()` facade or a config layer to hang one on. So the headline claim —
*"anyone can write a provider"* — is **true in Python and not yet true in Go or JS**. Say it
that way until it is true everywhere.

Also unfinished, and unrelated to this ADR except that implementing it surfaced the fact:
**`ingest_async` does not exist** anywhere in `python/`, `js/`, `golang/` or `rust/`, yet
`CLAUDE.md:188` and `CHANGELOG.md:182` both present it as shipped. What actually exists is
durability, not concurrency — a SQLite-backed `DurableQueue` and an `Executor` that *computes*
backoff without sleeping. Either build it or correct both documents.
