# Design — model seam contracts (ADR-0014 R1 + R4, Python reference)

## The defect in one line

CiteNexus publishes four model **constructors** and zero model **contracts**, so
"anyone can use the interface contract" is currently false: there is no interface
to use, only call sites to reverse-engineer.

## Where the contracts live, and why there

**`python/src/citenexus/contracts.py`**, re-exported from `citenexus/__init__.py`.

Three candidate homes were considered:

1. **`plugins/base.py`** (the existing ABC layer) — rejected. That module is the
   *eleven pipeline extension points* (extractor, chunker, retriever, judge,
   evaluator, memory, …). Model seams are five of eleven, and a provider author
   should not have to read past `ChunkerPlugin` and `MemoryPlugin` to find the
   thing they must implement. It is also the ABC layer, and the new contracts are
   deliberately structural (below).
2. **Each client's own package** (`embed/`, `answer/`, `vision/`, `retrieve/`) —
   rejected, and this is the status quo that produced the problem. Four seams in
   four packages is exactly why nobody could see that they were the same kind of
   thing, and why two of them ended up with no contract at all.
3. **A single top-level `contracts` module** — chosen. It is one import
   (`from citenexus.contracts import EmbeddingProvider`), it is discoverable from
   the package root, it is the obvious name, and it pulls in nothing heavy: the
   module's only non-stdlib import is `Candidate` (a pydantic model in
   `retrieve/types.py`, which imports nothing of ours). A third party can import
   the contracts without importing `CiteNexus`, LanceDB, or a storage backend.

## Protocol, not ABC — and why that is the point

The `Plugin` ABCs exist so the **registry** can *reject* a non-conforming object
at runtime (`plugins/base.py` docstring: "typed, not duck-typed"). That reasoning
holds for the registry and those ABCs stay exactly as they are.

It is the wrong tool for a published provider contract. An ABC forces
`import citenexus` **into the provider's own source** and makes CiteNexus a
build-time dependency of anyone who wants to be compatible. A
`@runtime_checkable` `Protocol` inverts that: **matching the shape is enough**.
An in-process model, a mock, a cached fixture, or an adapter someone else ships
for a third library (toolnexus is the ADR's example) can satisfy the contract
without ever naming us. That is ADR-0014's stated goal.

`@runtime_checkable` buys the `isinstance` check the pipeline needs to pick the
batch path. Its limits are known and accepted: it checks *method presence*, not
signatures. That is sufficient here because presence is exactly the question
being asked (*"does this provider offer batching?"*), and mypy `--strict` checks
the signatures statically for anyone who type-checks.

Our own four clients **inherit** their contract anyway. Inheriting a Protocol
does not make them protocols; it makes mypy verify each client against the
published shape on every run, which is the cheapest possible guarantee that the
contract we document is the contract we ship.

## The embedding shape: batch is the primitive, and it is called `embed_many`

ADR-0014 R1 says one embedder abstraction, batch-primitive. The contract is:

```python
@runtime_checkable
class EmbeddingProvider(Protocol):
    def embed_many(self, texts: Sequence[str]) -> list[Vector]: ...
```

**Why not reuse the name `embed`?** Because `embed` already means two
incompatible things in this codebase — `embed(texts) -> list[Vector]`
(`EmbeddingPlugin`, batch) and `embed(text) -> Vector` (`Embedder`,
`QueryEmbedder`, `FakeEmbedding`, single) — and **`str` is itself a
`Sequence[str]`**. A contract spelled `embed` therefore cannot separate them:
`runtime_checkable` certainly cannot, and a type checker will not either, because
passing a `str` where a `Sequence[str]` is expected is legal. Publishing `embed`
as *the* contract would silently accept the wrong implementation and return a
list of floats where a list of vectors was promised.

`embed_many` is unambiguous, and it is not invented: it is precisely the name
`ingest/pipeline.py:391` already duck-types for. Adopting it as the contract is
what turns that `getattr` into something a provider can *know about*, which was
the whole complaint.

The two legacy spellings are published beside it as
`SingleTextEmbedder`/`SequenceEmbedder`, marked deprecated. Naming them is not
endorsing them — it means `Embedder`, `QueryEmbedder` and `_BatchEmbedder` become
**aliases of one definition** instead of three independent redeclarations that can
drift apart. That is the collapse ADR-0014 asks for, achieved without breaking
the public constructor.

Selection is a single helper:

```python
def embed_texts(embedder, texts):
    if isinstance(embedder, EmbeddingProvider):
        return embedder.embed_many(list(texts))     # the contract
    return [embedder.embed(t) for t in texts]       # legacy single-text
```

One dispatch point, contract-first, legacy second. `_SingleTextEmbedder` — an
adapter between two of our own abstractions, which ADR-0014 correctly calls "the
tell" — has nothing left to do and is deleted.

## `_ZeroEmbedder` is a missing default, not a provider

`_ZeroEmbedder` was never an embedder. It existed because `IngestPipeline`
required one, and a lexical-only client has none; it returned `[0.0]` so the row
had *something* in its vector column. Modelling "no model" as a fake model is
what forced it to be a class.

`IngestPipeline.embedder` becomes `... | None`, and the pipeline writes the 1-dim
placeholder itself when it is `None`. That is honest — the placeholder is the
storage layer's business, not a provider's — and it removes the risk of a
zero-vector "embedder" being mistaken for a real one, which is the same failure
ADR-0014 flags in Go ("a zero vector is not an error value").

## Failure (R2) needs no new machinery in Python

R2 says failure must be expressible in the port's own idiom. In Python that is a
raised exception, and every contract here is free to raise — the contracts are
`-> str` / `-> list[Vector]`, never `-> str | None` and never a sentinel. The
spec states it so a provider knows raising is correct and returning a zero vector
or an empty string is not. This is a documentation requirement in Python and a
type-signature change in Go; only the former is in scope.

## Sync vs async: not decided, not foreclosed

ADR-0014 leaves this open and says it must be settled *before* the contract is
written. It has not been settled, so this change keeps the library synchronous
and the contracts synchronous — the only option that changes nothing today.

What it does do is avoid making the decision unreachable. The contracts are
Protocols, and Protocols compose: an async seam can later be published as a
**separate** protocol (`AsyncEmbeddingProvider.aembed_many`, …) that a provider
may implement instead of, or alongside, the sync one, with the same
`isinstance` dispatch choosing the path. Nothing here forces a future async
provider to also implement a blocking method, and nothing here forces existing
callers into an event loop. The decision stays open on purpose; see ADR-0014
"Open".

## Not in scope

- **R3 (no transport in the contract).** `transport`, `base_url` and `headers`
  are **constructor** parameters, not contract methods, so none of them appear in
  any protocol published here — a provider that never opens a socket already
  satisfies every contract in this change. Actually *removing* them from the
  shipped clients is breaking and is entangled with the sync/async question.
- **`Embedding` vs plain vectors.** ADR-0014 leaves it open. The contract returns
  `list[Vector]` (`list[list[float]]`) because that is what every producer and
  consumer in the Python reference actually exchanges today; `EmbeddingPlugin`'s
  `Embedding = Any` alias is untouched.
- **Whether reranking shares a contract with embedding.** Open in ADR-0014;
  they ship as two contracts here because they are two operations with two
  models, which is the status quo and requires no ruling.
- **Ports.** `golang/`, `js/`, `rust/` and `conformance/` are untouched.
