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
    "embed_one",
    "embed_texts",
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
        return list(embedder.embed_many(list(texts)))
    return [embedder.embed(text) for text in texts]


def embed_one(embedder: EmbeddingProvider | SingleTextEmbedder, text: str) -> Vector:
    """Embed a single text — a batch of one under the contract."""
    return embed_texts(embedder, [text])[0]
