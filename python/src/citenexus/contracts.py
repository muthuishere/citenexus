"""The published model-seam contracts — one shape per seam (ADR-0014 R1 + R4).

CiteNexus bundles no models. What it *does* owe anyone who wants to supply one is
an interface they can implement without reading our call sites. That is this
module: the single, obvious place a provider author looks.

Five contracts, one per model seam::

    EmbeddingProvider   embed_many(texts)              -> list[Vector]
    GeneratorProvider   answer(question, passage, ...) -> str
    CompletionProvider  complete(prompt)               -> str
    VisionProvider      describe(image_region)         -> Mapping[str, Any]
    RerankerProvider    rerank(query, candidates)      -> list[Candidate]

**They are ``Protocol``s, not ABCs, on purpose.** The ``Plugin`` ABCs in
``plugins/base.py`` exist so the *registry* can reject a non-conforming object at
runtime, and they stay exactly as they are. But an ABC forces ``import citenexus``
into a provider's own source and makes this library a build-time dependency of
anyone who wants to be compatible. A ``@runtime_checkable`` ``Protocol`` inverts
that: **matching the shape is enough**. An in-process model, a mock, a cached
fixture, or an adapter someone else ships for a third library can satisfy these
without ever naming us — which is precisely what ADR-0014 asks for.

Our own shipped clients inherit their contract anyway, so ``mypy --strict``
checks each of them against the published shape on every run.

**Nothing here mentions a transport.** ``base_url``, ``headers`` and
``transport`` are *constructor* parameters of the HTTP clients, never contract
methods, so a provider that never opens a socket satisfies every contract in this
module (ADR-0014 R3).

**Failure is raised.** Every contract returns a value or raises; none defines a
sentinel. A zero vector is not an error value — it is a valid embedding of
something, indistinguishable once written from a document that genuinely embeds
near the origin (ADR-0014 R2). Likewise an empty string is an answer, not a
failure. If a provider cannot fulfil a call, it must raise.

**Sync, for now.** ADR-0014 leaves sync-vs-async open and says it must be settled
before the contract is written. It has not been, so these contracts are
synchronous — the only choice that changes nothing today. It is not foreclosed:
Protocols compose, so an async seam can later be published *beside* these as
separate protocols, with the same ``isinstance`` dispatch choosing the path. No
future async provider is forced to also offer a blocking method.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover - typing only
    # Deferred on purpose: `citenexus.retrieve` imports the rerank CLIENT, which
    # imports this module. Keeping `Candidate` a type-only reference is what lets
    # a provider author import the contracts without dragging in the retrieval
    # stack -- and what keeps this module import-light, as promised above.
    from citenexus.retrieve.types import Candidate

__all__ = [
    "CompletionProvider",
    "EmbeddingProvider",
    "GeneratorProvider",
    "RerankerProvider",
    "SequenceEmbedder",
    "SingleTextEmbedder",
    "Vector",
    "VisionProvider",
    "check_batch",
    "check_batch_arity",
    "check_vector",
    "embed_one",
    "embed_texts",
    "is_zero_vector",
]

#: One dense embedding. ADR-0014 leaves open whether the seam should carry sparse
#: term weights too; today every producer and consumer in the Python reference
#: exchanges plain dense vectors, so that is what the contract promises.
Vector = list[float]


# ---------------------------------------------------------------------------
# The model seams
# ---------------------------------------------------------------------------


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Turn texts into dense vectors. **Batch is the primitive** (ADR-0014 R1).

    A single text is a batch of one, not a second method — batching is where the
    throughput is, and a seam that hides it behind a second, optional method is a
    seam nobody uses.

    Why ``embed_many`` and not ``embed``? Because ``embed`` already means two
    incompatible things in this codebase — ``embed(texts) -> list[Vector]``
    (``EmbeddingPlugin``) and ``embed(text) -> Vector`` (the older single-text
    seams) — and **``str`` is itself a ``Sequence[str]``**, so neither
    ``isinstance`` nor a type checker can tell the two apart. A contract spelled
    ``embed`` would silently accept the wrong implementation. ``embed_many`` is
    unambiguous, and it is not invented: it is the exact name ingest used to
    duck-type for with ``getattr``. Naming it makes the batch path something a
    provider can *know about*.

    Implementations MUST return one vector per input text, in input order, and
    MUST raise rather than return a zero vector when the model fails.
    """

    def embed_many(self, texts: Sequence[str]) -> list[Vector]:
        """Embed every text, preserving input order. Raise on failure."""
        ...


@runtime_checkable
class GeneratorProvider(Protocol):
    """Produce a grounded answer from one already-selected passage.

    The provider is handed the passage the library chose and the ISO code the
    answer must be in. It does not retrieve, it does not choose evidence, and it
    is not trusted: whatever it returns goes through the per-claim faithfulness
    gate before it can become an answer. The best possible generator is therefore
    an extractive one — quote the passage.

    Implementations MUST raise on failure rather than return an empty string.
    """

    def answer(self, question: str, passage: str, answer_language: str = "en") -> str:
        """Answer ``question`` from ``passage``, in ``answer_language``."""
        ...


@runtime_checkable
class CompletionProvider(Protocol):
    """One prompt in, one string out — the deep-ask decision seam.

    ADR-0014 calls this shape "already almost exactly right"; it is now named
    rather than implied. Deliberately NOT provider tool/function-calling: the
    library scripts the loop and parses a small JSON decision off this plain
    completion, so the model never owns control flow.
    """

    def complete(self, prompt: str) -> str:
        """Complete ``prompt``. Raise on failure."""
        ...


@runtime_checkable
class VisionProvider(Protocol):
    """Describe an image region for the conditional-vision path (spec §9).

    The return is a mapping of the fields a figure Evidence Unit needs —
    ``short_caption``, ``detailed_description``, ``objects``, ``relationships``,
    ``ocr_text``, ``data_values``, ``image_type``. Every key is optional except
    ``short_caption``; unknown keys are ignored.
    """

    def describe(self, image_region: Any) -> Mapping[str, Any]:
        """Describe the image. Raise on failure."""
        ...


@runtime_checkable
class RerankerProvider(Protocol):
    """Re-order already-retrieved candidates for a query.

    A reranker may only reorder or drop; it can never introduce a candidate that
    retrieval did not produce, so it cannot bypass the grounding guarantee.
    """

    def rerank(self, query: str, candidates: Sequence[Candidate]) -> list[Candidate]:
        """Return ``candidates`` most-relevant-first. Raise on failure."""
        ...


# ---------------------------------------------------------------------------
# The legacy embedding shapes — named so they stop being anonymous
# ---------------------------------------------------------------------------


@runtime_checkable
class SingleTextEmbedder(Protocol):
    """DEPRECATED: the older one-text-at-a-time embedding seam.

    Published so ``ingest.pipeline.Embedder`` and ``retrieve.vector.QueryEmbedder``
    are *aliases of one definition* rather than two redeclarations that can drift.
    Still fully supported — `embed_texts` falls back to it — but a new provider
    should implement `EmbeddingProvider` instead: this shape cannot batch, and one
    request per Evidence Unit does not survive a real corpus.
    """

    def embed(self, text: str) -> Vector:
        """Embed one text. Raise on failure."""
        ...


@runtime_checkable
class SequenceEmbedder(Protocol):
    """DEPRECATED: the batch-``embed`` shape of the `EmbeddingPlugin` ABC.

    Same semantics as `EmbeddingProvider`, spelled with the overloaded name.
    Kept so `embed_in_batches` and `EmbeddingPlugin` name one shape rather than
    two, and so the existing ABC subclasses keep working unchanged.
    """

    def embed(self, texts: Sequence[str]) -> list[Vector]:
        """Embed every text, preserving input order. Raise on failure."""
        ...


# ---------------------------------------------------------------------------
# Dispatch — contract first, legacy second
# ---------------------------------------------------------------------------


def embed_texts(
    embedder: EmbeddingProvider | SingleTextEmbedder,
    texts: Sequence[str],
) -> list[Vector]:
    """Embed ``texts``, preferring the batch contract.

    This is the ONE place the library decides how to talk to an embedder. It
    replaces ``getattr(embedder, "embed_many", None)`` — ADR-0014: "a capability
    discovered by ``getattr`` is a capability no port can see, no type checker can
    verify, and no provider knows to offer."
    """
    if not texts:
        return []
    if isinstance(embedder, EmbeddingProvider):
        vectors = list(embedder.embed_many(list(texts)))
        check_batch_arity(len(texts), len(vectors))
        return vectors
    return [embedder.embed(text) for text in texts]


def embed_one(embedder: EmbeddingProvider | SingleTextEmbedder, text: str) -> Vector:
    """Embed a single text — a batch of one under the contract."""
    return embed_texts(embedder, [text])[0]


# ---------------------------------------------------------------------------
# What a VALID EMBEDDING BATCH is — the one definition, three ports
# ---------------------------------------------------------------------------
#
# Go's twin is golang/contracts/contracts.go (CheckVector / EmbedTexts); JS's is
# js/src/contracts.ts (checkVector / embedTexts). All three are held to
# conformance/cases/vector_validation.json, and ADR-0010 puts this in tier 1
# (structural/arithmetic), so each port implements it NATIVELY -- no Rust, no
# native library, plain `go build` and plain ESM keep working.
#
# A provider given N texts must return EXACTLY N vectors, in input order, and
# each one must be:
#
#   * a sequence of real numbers        (non_vector)
#   * non-empty                         (empty)
#   * the same dimension as the run     (dimension)
#   * finite in every component         (non_finite)
#   * not the all-zeros vector          (zero)
#
# The REJECTION ORDER above is part of the contract, not an implementation
# detail: a vector can fail more than one rule at once, and three ports that
# disagree about which error to report are three ports that disagree about the
# contract. Batch arity is checked FIRST, before any per-vector rule.
#
# Why each rule earns its place -- every one of these was measured, not assumed:
#
#   cardinality  The most damaging, and the one Python missed entirely. Fewer
#                vectors than texts shifts EVERY subsequent text->vector pairing,
#                so the index is not broken, it is *plausibly wrong forever*:
#                retrieval still returns confident, well-formed, correctly-cited
#                results -- for the wrong passage. Nothing downstream can see it.
#   zero         The silent poison ADR-0014 names. Cosine against the origin does
#                not raise; it ranks meaninglessly. Once written it is
#                indistinguishable from a document that genuinely embeds near the
#                origin. This is exactly why no seam here may return a zero
#                vector as a failure sentinel: it is a valid embedding of
#                something, so it cannot also mean "I failed".
#   non_finite   NaN propagates through cosine and makes ranking nondeterministic
#                -- every comparison with NaN is false, so the sort order depends
#                on the algorithm rather than the data.
#   empty        Unguarded, it surfaces much later as a dimension error deep
#                inside the store, misattributed to storage rather than to the
#                model that produced it.
#   dimension    One run's vectors must be mutually comparable to be ranked.
#   non_vector   Python and JS can both be handed a non-numeric payload by an
#                untyped provider (Go's type system makes it unrepresentable).
#
# Every rejection names the offending EU id / text index, so the failure points
# at the unit that caused it rather than at the run.


def is_zero_vector(vec: Sequence[float]) -> bool:
    """Is ``vec`` the all-zeros vector -- an embedding carrying no signal at all?

    Cosine similarity against a zero vector does not raise; it just ranks
    meaninglessly, so a corpus built on one *passes or fails at random while
    appearing to measure something*.

    This used to live in ``citenexus.testing.fakes`` -- a real write-path guard
    misfiled as a test helper, which is a large part of why the write path had no
    guard at all. ``citenexus.testing.fakes.is_zero_vector`` is now an alias of
    this function, so the tests and the shipped path share ONE definition.
    """
    return all(v == 0.0 for v in vec)


def check_batch_arity(text_count: int, vector_count: int) -> None:
    """Reject a batch that does not return one vector per input text.

    Raises ``ValueError`` when the counts differ. This is the check whose absence
    corrupts an index *silently*: with fewer vectors than texts every subsequent
    pairing shifts by one, and no downstream signal -- not the row count, not the
    scores, not the citations -- looks unhealthy.
    """
    if vector_count != text_count:
        raise ValueError(
            f"contracts: embedder returned {vector_count} vectors for {text_count} "
            "texts; the contract is one vector per input text, in input order"
        )


def check_vector(label: str, vec: object, dim: int) -> Vector:
    """Reject a vector that must never be indexed or scored, and return it.

    ``label`` names the thing being embedded -- an ``eu_id`` on the write path, a
    document id or ``"question"`` on the ask path -- so the error points at the
    offending unit. ``dim`` is the dimensionality already established by this run
    (``0`` for the first vector, which defines it).

    Raises ``TypeError`` for a payload that is not a sequence of numbers, and
    ``ValueError`` for a vector that is one but must not be used. The rejection
    ORDER is pinned by ``conformance/cases/vector_validation.json``.
    """
    if isinstance(vec, (str, bytes)) or not isinstance(vec, Sequence):
        raise TypeError(f"embedder returned a non-vector for {label}")
    values: list[float] = []
    for component in vec:
        if isinstance(component, bool) or not isinstance(component, (int, float)):
            raise TypeError(f"embedder returned a non-vector for {label}")
        values.append(float(component))
    if not values:
        raise ValueError(f"embedder returned an empty vector for {label}")
    if dim > 0 and len(values) != dim:
        raise ValueError(
            f"embedder returned a {len(values)}-dim vector for {label}; this run is {dim}-dim"
        )
    if any(math.isnan(v) or math.isinf(v) for v in values):
        raise ValueError(f"embedder returned a non-finite vector for {label}")
    if is_zero_vector(values):
        raise ValueError(
            f"embedder returned the zero vector for {label} -- it carries no signal "
            "and would rank meaninglessly against every query"
        )
    return values


def check_batch(labels: Sequence[str], vectors: Sequence[object]) -> list[Vector]:
    """Validate a whole batch: arity first, then every vector in order.

    The dimension of the run is defined by the first vector, exactly as in Go's
    ``ingest`` loop and JS's ``ingest()``. Returns the validated vectors.
    """
    check_batch_arity(len(labels), len(vectors))
    out: list[Vector] = []
    dim = 0
    for label, vec in zip(labels, vectors, strict=True):
        checked = check_vector(label, vec, dim)
        dim = len(checked)
        out.append(checked)
    return out
