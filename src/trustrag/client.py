"""Public TrustRAG client — construct, ingest, retrieve, ask, evaluate."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from trustrag.answer.flow import AnswerFlow, Generator
from trustrag.answer.result import Result
from trustrag.config.signals import Signal, resolve_signals
from trustrag.domain.partition import PartitionPath
from trustrag.domain.trust import TrustMode
from trustrag.evaluate import EvaluationReport, Evaluator
from trustrag.graph import GraphRetriever, GraphStore
from trustrag.ingest.pipeline import IngestPipeline
from trustrag.ingest.result import IngestResult
from trustrag.memory import MemoryStore, MemoryTurn
from trustrag.plugins.base import LanguageDetectorPlugin, RerankerPlugin, RetrieverPlugin
from trustrag.retrieve.engine import RetrievalEngine
from trustrag.retrieve.lexical import LexicalRetriever
from trustrag.retrieve.structure import StructureRetriever
from trustrag.retrieve.types import Candidate
from trustrag.retrieve.vector import QueryEmbedder, VectorRetriever
from trustrag.storage.backend import LocalFsBackend, S3Backend, StorageBackend
from trustrag.storage.lance_store import LeafVectorStore, StorageOptions
from trustrag.storage.paths import leaf_vector_uri
from trustrag.stream import stream_result
from trustrag.wiki import WikiRetriever, WikiStore


class _IdentityReranker(RerankerPlugin):
    plugin_version = "identity-rerank-v1"

    def rerank(
        self, query: str, candidates: Sequence[Candidate]
    ) -> list[Candidate]:
        return list(candidates)


class TrustRAG:
    """The v0.1 public surface.

    Models are still injected. The client wires the existing ingest/retrieve
    layers into the answer/evaluate front doors that users call.
    """

    def __init__(
        self,
        base_uri: str | Path,
        *,
        partition: PartitionPath | None = None,
        signals: Iterable[str | Signal] | None = None,
        embedder: QueryEmbedder,
        generator: Generator,
        reranker: RerankerPlugin | None = None,
        detector: LanguageDetectorPlugin | None = None,
        backend: StorageBackend | None = None,
        storage_options: StorageOptions | None = None,
        default_answer_language: str = "en",
        top_k: int = 5,
        memory_max_turns: int = 20,
    ) -> None:
        self.base_uri = str(base_uri)
        self.partition = partition or PartitionPath.of(("workspace", "default"))
        self.signals = resolve_signals(signals)
        self._backend = backend or _backend_for(self.base_uri)
        self._store = LeafVectorStore(
            leaf_vector_uri(self.base_uri, self.partition), storage_options
        )
        self._graph_store = GraphStore(self._backend, self.partition)
        self._wiki_store = WikiStore(self._backend, self.partition)
        self._memory = MemoryStore(
            self._backend, self.partition, max_turns=memory_max_turns
        )
        self._ingest = IngestPipeline(
            backend=self._backend,
            base_uri=self.base_uri,
            partition=self.partition,
            embedder=embedder,
            detector=detector,
            signals=self.signals,
            storage_options=storage_options,
            default_answer_language=default_answer_language,
        )
        retrievers: list[RetrieverPlugin] = []
        if Signal.embedding in self.signals:
            retrievers.append(VectorRetriever(self._store, embedder))
        if Signal.text in self.signals:
            retrievers.append(LexicalRetriever(self._store))
        if Signal.structure in self.signals:
            retrievers.append(
                StructureRetriever(self._backend, self.partition, self._store)
            )
        if Signal.graph in self.signals or Signal.community in self.signals:
            retrievers.append(GraphRetriever(self._graph_store, self._store))
        if Signal.wiki in self.signals:
            retrievers.append(WikiRetriever(self._wiki_store, self._store))
        self._retrieve = RetrievalEngine(
            retrievers=retrievers,
            reranker=reranker or _IdentityReranker(),
        )
        self._answer = AnswerFlow(
            generator=generator,
            default_answer_language=default_answer_language,
        )
        self._top_k = top_k

    def ingest(
        self,
        source: Any = None,
        *,
        text: str | None = None,
        document_id: str | None = None,
        source_type: Any = None,
        acl: Any = None,
    ) -> IngestResult:
        result = self._ingest.ingest(
            source,
            text=text,
            document_id=document_id,
            source_type=source_type,
            acl=acl,
        )
        if result.status == "ingested":
            self.refresh_slow_path()
        return result

    def refresh_slow_path(self) -> None:
        """Rebuild deterministic slow-path graph/wiki artifacts for this leaf."""
        if Signal.graph in self.signals or Signal.community in self.signals:
            self._graph_store.build_from_store(self._store)
        if Signal.wiki in self.signals:
            self._wiki_store.build_from_store(self._store)

    def retrieve(
        self,
        question: str,
        *,
        k: int | None = None,
        conversation_id: str | None = None,
    ) -> list[Candidate]:
        return self._retrieve.retrieve(
            self._retrieval_query(question, conversation_id=conversation_id),
            k or self._top_k,
        )

    def ask(
        self,
        question: str,
        *,
        mode: TrustMode = TrustMode.strict,
        k: int | None = None,
        answer_language: str | None = None,
        conversation_id: str | None = None,
    ) -> Result:
        retrieval_query = self._retrieval_query(
            question, conversation_id=conversation_id
        )
        result = self._answer.ask(
            question,
            self._retrieve.retrieve(retrieval_query, k or self._top_k),
            mode=mode,
            answer_language=answer_language,
            evidence_query=retrieval_query,
        )
        if conversation_id is not None:
            self._memory.append(conversation_id, question, result.answer)
        return result

    def stream(
        self,
        question: str,
        *,
        mode: TrustMode = TrustMode.strict,
        k: int | None = None,
        answer_language: str | None = None,
        conversation_id: str | None = None,
    ) -> Sequence[str]:
        result = self.ask(
            question,
            mode=mode,
            k=k,
            answer_language=answer_language,
            conversation_id=conversation_id,
        )
        return tuple(stream_result(result))

    def evaluate(self, csv_path: str | Path) -> EvaluationReport:
        return Evaluator(self.ask).evaluate(csv_path)

    def recall(
        self, conversation_id: str, query: str, *, limit: int = 3
    ) -> tuple[MemoryTurn, ...]:
        return self._memory.recall(conversation_id, query, limit=limit)

    def _retrieval_query(
        self, question: str, *, conversation_id: str | None
    ) -> str:
        if conversation_id is None:
            return question
        turns = self._memory.recall(conversation_id, question)
        if not turns:
            return question
        context = " ".join(f"{turn.question} {turn.answer}" for turn in turns)
        return f"{context} {question}"


def _backend_for(base_uri: str) -> StorageBackend:
    if base_uri.startswith("s3://"):
        bucket = base_uri.removeprefix("s3://").split("/", 1)[0]
        if not bucket:
            raise ValueError("s3 base_uri must include a bucket")
        return S3Backend(bucket)
    return LocalFsBackend(Path(base_uri))
