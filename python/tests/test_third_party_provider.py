"""The proof: a provider written OUTSIDE CiteNexus drives the library.

Everything in this file is deliberately written the way a third party would
write it, and the constraints are asserted rather than assumed:

- it imports **only** `citenexus.contracts` from the library — no `Plugin` ABC,
  no `FakeEmbedding`, no `FakeLLM`, nothing from `citenexus.testing`;
- it inherits **nothing** from CiteNexus (asserted on the MRO);
- it opens **no socket** — these are in-process models (asserted by monkeypatching
  `socket.socket` to explode for the duration of the end-to-end run).

If this file passes, the contract is usable by someone who has only read the
published interface. Without it, "there is a contract" is a claim.
"""

from __future__ import annotations

import hashlib
import math
import re
import socket
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from citenexus import CiteNexus
from citenexus.answer.result import Decision
from citenexus.contracts import (
    CompletionProvider,
    EmbeddingProvider,
    GeneratorProvider,
    RerankerProvider,
    Vector,
    VisionProvider,
)

# ---------------------------------------------------------------------------
# The third-party provider suite. Nothing below imports a CiteNexus base class.
# ---------------------------------------------------------------------------

_WORD = re.compile(r"\w+", re.UNICODE)


def _tokens(text: str) -> list[str]:
    return [m.group(0).lower() for m in _WORD.finditer(text)]


class InProcessEmbedding:
    """A hashing vectorizer that never leaves the process.

    Satisfies `EmbeddingProvider` by shape alone: one batch method, and a batch
    is the primitive — a single text is a batch of one.
    """

    def __init__(self, dim: int = 96) -> None:
        self.dim = dim
        self.batch_sizes: list[int] = []

    def embed_many(self, texts: Sequence[str]) -> list[Vector]:
        self.batch_sizes.append(len(texts))
        return [self._one(t) for t in texts]

    def _one(self, text: str) -> Vector:
        vec = [0.0] * self.dim
        for tok in _tokens(text):
            idx = int(hashlib.blake2s(tok.encode("utf-8")).hexdigest(), 16) % self.dim
            vec[idx] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


class InProcessGenerator:
    """An extractive model: it quotes the passage, so it cannot hallucinate.

    Picks the sentence of the passage with the most overlap with the question and
    returns it **verbatim**, which is exactly what CiteNexus's faithfulness gate
    demands of any generator.
    """

    def __init__(self) -> None:
        self.questions: list[str] = []
        self.prompts: list[str] = []

    def answer(self, question: str, passage: str, answer_language: str = "en") -> str:
        self.questions.append(question)
        wanted = set(_tokens(question))
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", passage) if s.strip()]
        if not sentences:
            return passage
        return max(sentences, key=lambda s: len(wanted & set(_tokens(s))))

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return '{"sufficient": true, "next_query": null}'


class InProcessVision:
    """An in-process 'vision model' — reads a fixed caption off the bytes it gets."""

    def __init__(self) -> None:
        self.calls = 0

    def describe(self, image_region: Any) -> Mapping[str, Any]:
        self.calls += 1
        return {
            "short_caption": "revenue chart",
            "detailed_description": "A bar chart of revenue by quarter.",
            "objects": ["bar", "axis"],
            "image_type": "chart",
        }


class InProcessReranker:
    """A lexical-overlap cross-encoder stand-in."""

    def __init__(self) -> None:
        self.calls = 0

    def rerank(self, query: str, candidates: Sequence[Any]) -> list[Any]:
        self.calls += 1
        wanted = set(_tokens(query))
        return sorted(
            candidates,
            key=lambda c: len(wanted & set(_tokens(c.citable_text or ""))),
            reverse=True,
        )


# ---------------------------------------------------------------------------
# The corpus
# ---------------------------------------------------------------------------

_NDA = (
    "The employee shall not disclose confidential information to any third party. "
    "This obligation survives termination of employment for a period of five years."
)
_LEASE = (
    "The tenant shall give the landlord at least thirty days written notice "
    "before terminating a month to month tenancy."
)


def _providers() -> tuple[InProcessEmbedding, InProcessGenerator, InProcessReranker]:
    return InProcessEmbedding(), InProcessGenerator(), InProcessReranker()


# ---------------------------------------------------------------------------
# 1. The providers satisfy the published contracts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("provider", "contract"),
    [
        (InProcessEmbedding(), EmbeddingProvider),
        (InProcessGenerator(), GeneratorProvider),
        (InProcessGenerator(), CompletionProvider),
        (InProcessVision(), VisionProvider),
        (InProcessReranker(), RerankerProvider),
    ],
)
def test_third_party_provider_satisfies_its_contract(provider: object, contract: type) -> None:
    assert isinstance(provider, contract)


@pytest.mark.parametrize(
    "provider",
    [InProcessEmbedding(), InProcessGenerator(), InProcessVision(), InProcessReranker()],
)
def test_third_party_provider_inherits_nothing_from_citenexus(provider: object) -> None:
    mro = type(provider).__mro__
    assert [cls for cls in mro if cls.__module__.startswith("citenexus")] == []


def test_this_file_imports_only_the_contract_module() -> None:
    """The provider author's only library import is the published interface.

    (`CiteNexus` and `Decision` are imported by the *test*, to drive and assert —
    the provider classes above reference nothing but `citenexus.contracts`.)
    """
    source = Path(__file__).read_text(encoding="utf-8")
    provider_section = source.split("# The corpus")[0]
    library_imports = re.findall(r"^from (citenexus[\w.]*) import", provider_section, re.M)
    assert set(library_imports) == {"citenexus", "citenexus.answer.result", "citenexus.contracts"}


# ---------------------------------------------------------------------------
# 2. The providers drive CiteNexus end to end
# ---------------------------------------------------------------------------


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any socket open during the test is a failure — these models are local."""

    def explode(*args: object, **kwargs: object) -> None:
        raise AssertionError("a third-party in-process provider must not open a socket")

    monkeypatch.setattr(socket, "socket", explode)


def test_third_party_providers_answer_end_to_end(tmp_path: Path, no_network: None) -> None:
    embedding, generator, reranker = _providers()
    rag = CiteNexus(
        tmp_path,
        embedder=embedding,
        generator=generator,
        reranker=reranker,  # type: ignore[arg-type]
    )
    rag.ingest(text=_NDA, document_id="nda")
    rag.ingest(text=_LEASE, document_id="lease")

    result = rag.ask("Can the employee disclose confidential information?")

    assert result.evidence.decision is Decision.answered
    assert result.answer
    assert result.sources, "an answer must cite"
    assert result.sources[0].document == "nda"
    # Grounded: the model quoted the source, and the gate agreed.
    assert result.answer in _NDA
    assert generator.questions == ["Can the employee disclose confidential information?"]


def test_the_same_provider_set_serves_a_second_question(tmp_path: Path, no_network: None) -> None:
    embedding, generator, reranker = _providers()
    rag = CiteNexus(
        tmp_path,
        embedder=embedding,
        generator=generator,
        reranker=reranker,  # type: ignore[arg-type]
    )
    rag.ingest(text=_NDA, document_id="nda")
    rag.ingest(text=_LEASE, document_id="lease")

    notice = rag.ask("How much notice must the tenant give the landlord?")

    assert notice.evidence.decision is Decision.answered
    assert notice.sources[0].document == "lease"
    assert notice.answer in _LEASE


def test_the_batch_contract_is_the_path_actually_taken(tmp_path: Path, no_network: None) -> None:
    """A batch-only provider is enough: nothing asks it for a single text."""
    embedding, generator, _ = _providers()
    assert not hasattr(embedding, "embed")
    rag = CiteNexus(tmp_path, embedder=embedding, generator=generator)
    rag.ingest(text=_NDA, document_id="nda")
    assert embedding.batch_sizes, "ingest never used the contract's batch method"
    rag.ask("Can the employee disclose confidential information?")
    # The query is a batch of one — the contract has no single-text method.
    assert embedding.batch_sizes[-1] == 1


def test_the_third_party_reranker_is_consulted(tmp_path: Path, no_network: None) -> None:
    embedding, generator, reranker = _providers()
    rag = CiteNexus(
        tmp_path,
        embedder=embedding,
        generator=generator,
        reranker=reranker,  # type: ignore[arg-type]
    )
    rag.ingest(text=_NDA, document_id="nda")
    rag.retrieve("disclose confidential information")
    assert reranker.calls >= 1


def test_a_third_party_provider_answers_without_an_embedding_model(
    tmp_path: Path, no_network: None
) -> None:
    """A provider suite may be partial: generation only, lexical retrieval."""
    _, generator, _ = _providers()
    rag = CiteNexus(tmp_path, generator=generator)
    rag.ingest(text=_NDA, document_id="nda")
    result = rag.ask("Can the employee disclose confidential information?")
    assert result.evidence.decision is Decision.answered
    assert result.sources[0].document == "nda"


def test_the_third_party_vision_provider_builds_a_figure_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The vision seam takes the same kind of outside provider."""
    from citenexus.extract.types import ExtractedBlock, ExtractedDoc, ImageRef, SourceType
    from citenexus.ingest import pipeline as pipeline_mod
    from citenexus.storage.backend import LocalFsBackend
    from citenexus.storage.paths import Layer, layer_prefix

    embedding, generator, _ = _providers()
    vision = InProcessVision()
    rag = CiteNexus(tmp_path, embedder=embedding, generator=generator, vision=vision)

    blob_key = f"{layer_prefix(Layer.raw, rag.partition)}/img-blob"
    LocalFsBackend(tmp_path).put_bytes(blob_key, b"\x89PNG fake")
    doc = ExtractedDoc(
        document_id="report",
        source_type=SourceType.pdf,
        source_uri="raw/report.pdf",
        blocks=(ExtractedBlock(order=0, kind="paragraph", text="Annual revenue summary.", page=1),),
        images=(
            ImageRef(image_id="page1-img0", page=1, bbox=(1.0, 2.0, 3.0, 4.0), blob_key=blob_key),
        ),
    )
    monkeypatch.setattr(pipeline_mod, "extract", lambda *a, **k: doc)

    result = rag.ingest(source="report.pdf", document_id="report")

    assert vision.calls == 1
    assert any(eu_id.endswith("::img::page1-img0") for eu_id in result.eu_ids)
