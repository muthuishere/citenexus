# 0014 — The model seam is a contract, not an endpoint

Status: proposed · 2026-08-16 · written by a would-be provider, not by the library

## Context

`CLAUDE.md` states the rule as **"Models are injected OpenAI-compatible *endpoints*"**, and
that word is doing more work than it looks like it is. An endpoint is a URL. Requiring one
excludes three things that are not exotic:

- **an in-process model** — a library loaded into the same process, no socket
- **a mock** — the thing every test in this repo would rather use than a live model
- **anything that is not HTTP** — a queue, a local daemon on a unix socket, a cached fixture

The code already disagrees with the rule, which is the strongest evidence that the rule is
wrong. Embedding alone is injected through **four different abstractions in Python**, plus one
each in Go and JS, and no two agree:

| where | shape |
|---|---|
| `plugins/base.py:62` | `EmbeddingPlugin.embed(texts: Sequence[str]) -> list[Embedding]` — batch, ABC |
| `ingest/pipeline.py:49` | `Embedder(Protocol).embed(text: str) -> list[float]` — single, Protocol |
| `embed/batcher.py:17` | `_BatchEmbedder(Protocol)` — a third shape |
| `client.py:84,104` | `_SingleTextEmbedder`, `_ZeroEmbedder` — adapters between the first two |
| `golang/ingest/ingest.go:24` | `Embedder interface { Embed(text string) []float64 }` |
| `js/src/ingest/ingest.ts:16` | `type Embedder = (text: string) => number[]` |

`_SingleTextEmbedder` exists *only* to bridge two of our own abstractions. That is the tell.

And `pipeline.py:391` reaches for batching by duck-typing:

```python
embed_many = getattr(self._embedder, "embed_many", None)
if callable(embed_many) and texts:
```

A capability discovered by `getattr` is a capability no port can see, no type checker can
verify, and no provider knows to offer.

### What this costs a provider today

Two of the six shapes are **structurally unable** to accept a real provider:

- **Go returns no error.** `Embed(text string) []float64`. A model that times out, refuses, or
  runs out of memory has no way to say so. It returns a zero vector and ingest indexes it. The
  corpus is then quietly wrong in a way retrieval cannot detect.
- **JS is synchronous.** `(text: string) => number[]`. No network- and no
  model-backed embedder can satisfy that type at all. It works today only because whatever is
  behind it is already resident.

Neither is a style complaint. They are the reason a provider cannot plug in.

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

### R3 — The seam must not assume a transport

No `base_url`, no headers, no status codes, no `timeout` in the signature. Those belong to
*one* implementation of the contract, not to the contract. A provider that never opens a socket
must be able to satisfy it without inventing an HTTP response to hand back.

This is the requirement that turns "OpenAI-compatible endpoint" into "OpenAI-compatible
**provider**", and it is the one that unblocks in-process models and mocks in the same stroke.

### R4 — The same contract across the ports

Same fields, same semantics, idiomatic spelling. Go returns `(T, error)`, Python raises, JS
returns a `Promise`. What must not differ is *what the seam is for* and *what it promises*.

`conformance/` is where this becomes real: a provider that satisfies the contract in one port
must satisfy it in all of them, and that is testable in the way this repo already tests
everything else.

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

- **Every test can run offline.** A mock satisfying the contract needs no server, no fixture
  process, and no network. That is worth more than the in-process-model case that prompted
  this.
- **Two real bugs get fixed** on the way: Go's silent zero vector, and JS's un-satisfiable
  synchronous type.
- **`_SingleTextEmbedder` and `_ZeroEmbedder` disappear.** They are adapters between our own
  abstractions and have no reason to exist once there is one.
- **`getattr(self._embedder, "embed_many")` disappears.** Batch is the contract, not a
  discovered capability.
- **Breaking**, in Go and JS especially. Better now than after either has consumers.
- CiteNexus becomes composable with anything — including toolnexus, whose client is precisely a
  `Completion`, and including a local in-process model. Neither library imports the other; the
  glue is an adapter someone else ships.

## Open

- **Async or sync in Python.** The library is synchronous today. A contract that is sync-only
  excludes async providers; one that is async-only forces every caller to adopt it. This ADR
  does not decide it, and it should be decided before the contract is written rather than
  discovered afterwards.
- **Whether `Embedding` stays the return type** (dense + optional sparse weights) or the
  contract returns vectors and sparsity moves elsewhere.
- **Whether reranking is one contract with embedding or two.** Cross-encoder reranking is a
  different operation with a different model; sharing a plugin base may be convenience rather
  than truth.
