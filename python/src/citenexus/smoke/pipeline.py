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
from citenexus.answer.segment import split_claims
from citenexus.answer.verify import has_relevance_overlap_v2, is_supported_v2
from citenexus.domain.trust import TrustMode
from citenexus.storage.lance_store import LanceVectorStore, StorageOptions
from citenexus.storage.manifest import (
    EtagManifest,
    load_manifest,
    record_tokenizer_version,
    save_manifest,
)
from citenexus.storage.paths import Layer, layer_prefix, leaf_vector_uri

if TYPE_CHECKING:
    from citenexus.domain.partition import PartitionPath
    from citenexus.storage.backend import StorageBackend


class Embedder(Protocol):
    def embed(self, text: str) -> list[float]: ...


class Generator(Protocol):
    def answer(self, question: str, passage: str) -> str: ...


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
        record_tokenizer_version(self._backend, self._partition)
        return eu_id

    def ask(self, question: str, *, mode: TrustMode = TrustMode.strict) -> Result:
        """Answer grounded in retrieved evidence, or refuse if there is none."""
        qvec = self._embedder.embed(question)
        hits = self._store.search(qvec, limit=self._top_k)
        # The relevance gate must be the Unicode-aware one (ADR-0011), the same
        # predicate `answer/flow.py:216` uses. The frozen v1 `content_tokens` is
        # ASCII-only by contract, so it tokenized every non-Latin question to the
        # empty set and this path refused a Japanese question that grounds
        # perfectly against its own passage -- a false abstention, and a
        # divergence from the Go and JS ports, which already use v2. Measured
        # over conformance/cases/e2e_hermetic.json: v1 and v2 agree on all 48
        # question/document pairs, so no pinned vector moves.
        grounded = [h for h in hits if has_relevance_overlap_v2(question, str(h["text"]))]
        if not grounded:
            return self._refuse(mode)

        top = grounded[0]
        passage = str(top["text"])
        generated = self._generator.answer(question, passage)
        # Cite-or-drop, PER ATOMIC CLAIM (ADR-0009), through the same shared
        # predicate the real answer flow uses -- ``is_supported_v2`` over
        # ``split_claims``. This module used to carry a private re-implementation
        # of set containment, which made it a third, silently diverging copy of
        # the faithfulness gate: it accepted reordered and de-negated claims long
        # after the answer flow stopped doing so.
        verdicts = [(claim, is_supported_v2(claim, passage)) for claim in split_claims(generated)]
        supported_claims = [claim for claim, supported in verdicts if supported]
        if not supported_claims:
            return self._refuse(mode)
        removed = len(verdicts) - len(supported_claims)
        answer = " ".join(supported_claims)

        eu_id = str(top["eu_id"])
        document_id = str(top["document_id"])
        source = SourceRef(
            document=document_id,
            passage=passage,
            passage_language="en",
            source_uri=str(top["raw_uri"]),
        )
        # Every claim carries its own verdict, so a drop is auditable rather than
        # silent; only supported claims reach ``answer`` and provenance.
        claims = tuple(
            Claim(claim=claim, supported=supported, sources=(eu_id,) if supported else ())
            for claim, supported in verdicts
        )
        provenance = tuple(
            ProvenanceEntry(
                claim=claim,
                evidence_unit=eu_id,
                document_id=document_id,
                s3_object=str(top["raw_uri"]),
                checksum=str(top["checksum"]),
                produced_by={"embedding": "fake-hashing"},
            )
            for claim in supported_claims
        )
        signals = EvidenceSignals(
            decision=Decision.answered,
            supporting_sources=len(grounded),
            distinct_documents=len({str(h["document_id"]) for h in grounded}),
            all_claims_verified=removed == 0,
            unsupported_claims_removed=removed,
            languages_in_evidence=("en",),
        )
        return Result(
            answer=answer,
            answer_language="en",
            mode=mode,
            evidence=signals,
            claims=claims,
            sources=(source,),
            provenance=provenance,
        )

    def _refuse(self, mode: TrustMode) -> Result:
        return Result(
            answer="I can't answer that from the available evidence.",
            answer_language="en",
            mode=mode,
            evidence=EvidenceSignals(decision=Decision.refused),
            missing_evidence=("no sufficiently relevant evidence found",),
        )
