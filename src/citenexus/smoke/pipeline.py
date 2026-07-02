"""A thin, end-to-end evidence-first pipeline (smoke-e2e)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from citenexus.answer.result import (
    Claim,
    Decision,
    EvidenceSignals,
    ProvenanceEntry,
    Result,
    SourceRef,
)
from citenexus.domain.trust import TrustMode
from citenexus.storage.lance_store import LanceVectorStore, StorageOptions
from citenexus.storage.manifest import EtagManifest, load_manifest, save_manifest
from citenexus.storage.paths import Layer, layer_prefix, leaf_vector_uri
from citenexus.testing.fakes import tokenize

if TYPE_CHECKING:
    from citenexus.domain.partition import PartitionPath
    from citenexus.storage.backend import StorageBackend


class Embedder(Protocol):
    def embed(self, text: str) -> list[float]: ...


class Generator(Protocol):
    def answer(self, question: str, passage: str) -> str: ...


# Trivial words carry no evidential signal; overlap on them must not "ground" an
# answer (otherwise every question matches every document via "the"/"of"/...).
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "could",
        "do",
        "does",
        "for",
        "from",
        "how",
        "i",
        "in",
        "is",
        "it",
        "its",
        "may",
        "much",
        "no",
        "not",
        "of",
        "on",
        "or",
        "shall",
        "should",
        "that",
        "the",
        "this",
        "to",
        "was",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "you",
        "your",
    }
)


def _content_tokens(text: str) -> set[str]:
    return set(tokenize(text)) - _STOPWORDS


def _supported(answer: str, passage: str) -> bool:
    """Faithfulness gate: every answer token must appear in the cited passage."""
    a = set(tokenize(answer))
    p = set(tokenize(passage))
    return bool(a) and a <= p


class SmokePipeline:
    """Ingest text and answer questions, citing evidence or abstaining."""

    ETAG = "etag_manifest.json"

    def __init__(
        self,
        *,
        backend: StorageBackend,
        base_uri: str,
        partition: PartitionPath,
        embedder: Embedder,
        generator: Generator,
        storage_options: StorageOptions | None = None,
        top_k: int = 5,
    ) -> None:
        self._backend = backend
        self._partition = partition
        self._embedder = embedder
        self._generator = generator
        self._top_k = top_k
        self._store = LanceVectorStore(leaf_vector_uri(base_uri, partition), storage_options)

    def ingest(self, text: str, document_id: str) -> str:
        """Store a document as one Evidence Unit and index it. Returns its eu_id."""
        eu_id = f"{document_id}::0"
        raw_prefix = layer_prefix(Layer.raw, self._partition)
        checksum = self._backend.put_blob(raw_prefix, text.encode("utf-8"))
        raw_uri = f"{raw_prefix}/{checksum}"
        self._store.upsert(
            [
                {
                    "eu_id": eu_id,
                    "vector": self._embedder.embed(text),
                    "text": text,
                    "document_id": document_id,
                    "checksum": checksum,
                    "raw_uri": raw_uri,
                }
            ]
        )
        manifest = load_manifest(self._backend, self._partition, self.ETAG, EtagManifest)
        assert isinstance(manifest, EtagManifest)
        manifest.record(document_id, checksum)
        save_manifest(self._backend, self._partition, self.ETAG, manifest)
        return eu_id

    def ask(self, question: str, *, mode: TrustMode = TrustMode.strict) -> Result:
        """Answer grounded in retrieved evidence, or refuse if there is none."""
        qvec = self._embedder.embed(question)
        hits = self._store.search(qvec, limit=self._top_k)
        q_terms = _content_tokens(question)
        grounded = [h for h in hits if q_terms & _content_tokens(str(h["text"]))]
        if not grounded:
            return self._refuse(mode)

        top = grounded[0]
        passage = str(top["text"])
        answer = self._generator.answer(question, passage)
        if not _supported(answer, passage):  # cite-or-drop: never an ungrounded claim
            return self._refuse(mode)

        eu_id = str(top["eu_id"])
        document_id = str(top["document_id"])
        source = SourceRef(
            document=document_id,
            passage=passage,
            passage_language="en",
            source_uri=str(top["raw_uri"]),
        )
        claim = Claim(claim=answer, supported=True, sources=(eu_id,))
        provenance = ProvenanceEntry(
            claim=answer,
            evidence_unit=eu_id,
            document_id=document_id,
            s3_object=str(top["raw_uri"]),
            checksum=str(top["checksum"]),
            produced_by={"embedding": "fake-hashing"},
        )
        signals = EvidenceSignals(
            decision=Decision.answered,
            supporting_sources=len(grounded),
            distinct_documents=len({str(h["document_id"]) for h in grounded}),
            all_claims_verified=True,
            languages_in_evidence=("en",),
        )
        return Result(
            answer=answer,
            answer_language="en",
            mode=mode,
            evidence=signals,
            claims=(claim,),
            sources=(source,),
            provenance=(provenance,),
        )

    def _refuse(self, mode: TrustMode) -> Result:
        return Result(
            answer="I can't answer that from the available evidence.",
            answer_language="en",
            mode=mode,
            evidence=EvidenceSignals(decision=Decision.refused),
            missing_evidence=("no sufficiently relevant evidence found",),
        )
