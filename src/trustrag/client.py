"""Public TrustRAG client — construct, ingest, retrieve, ask, evaluate."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from trustrag.answer.anthropic import AnthropicGenerator
from trustrag.answer.flow import AnswerFlow, Generator
from trustrag.answer.generator import OpenAICompatibleGenerator
from trustrag.answer.generator import Transport as ChatTransport
from trustrag.answer.result import Decision, Result
from trustrag.config.schema import LLMProvider, TrustRAGConfig
from trustrag.config.signals import Signal, resolve_signals
from trustrag.domain.partition import PartitionPath
from trustrag.domain.trust import TrustMode
from trustrag.embed import OpenAICompatibleEmbedding
from trustrag.embed import Transport as EmbedTransport
from trustrag.evaluate import EvaluationReport, Evaluator
from trustrag.evidence.chunked_builder import Contextualizer as ContextualizerSeam
from trustrag.evidence.contextualize import Contextualizer
from trustrag.graph import GraphRetriever, GraphStore
from trustrag.ingest.pipeline import IngestPipeline, VisionDescriber
from trustrag.ingest.result import IngestResult
from trustrag.ingest.web import FetchTransport, crawl, fetch_url, is_url
from trustrag.memory import MemoryStore, MemoryTurn
from trustrag.plugins.base import LanguageDetectorPlugin, RerankerPlugin, RetrieverPlugin
from trustrag.retrieve.engine import RetrievalEngine
from trustrag.retrieve.lexical import LexicalRetriever
from trustrag.retrieve.rerank import OpenAICompatibleReranker
from trustrag.retrieve.structure import StructureRetriever
from trustrag.retrieve.types import Candidate
from trustrag.retrieve.vector import QueryEmbedder, VectorRetriever
from trustrag.storage.backend import LocalFsBackend, S3Backend, StorageBackend
from trustrag.storage.lance_store import LeafVectorStore, StorageOptions
from trustrag.storage.paths import leaf_vector_uri
from trustrag.stream import stream_result
from trustrag.telemetry.events import Outcome, Stage, StageEvent
from trustrag.telemetry.sinks import TelemetrySink
from trustrag.vision import OpenAICompatibleVision
from trustrag.wiki import WikiRetriever, WikiStore


class _IdentityReranker(RerankerPlugin):
    plugin_version = "identity-rerank-v1"

    def rerank(self, query: str, candidates: Sequence[Candidate]) -> list[Candidate]:
        return list(candidates)


class _SingleTextEmbedder:
    """Adapt a batch ``OpenAICompatibleEmbedding`` to the single-text seam.

    Ingest and the vector retriever call ``embed(text) -> list[float]``; the
    OpenAI-compatible plugin's ``embed`` takes a sequence. This wraps its
    ``embed_query`` convenience so the batch plugin drops into the client.
    """

    def __init__(self, plugin: OpenAICompatibleEmbedding) -> None:
        self._plugin = plugin

    def embed(self, text: str) -> list[float]:
        return self._plugin.embed_query(text)


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
        sink: TelemetrySink | None = None,
        vision: VisionDescriber | None = None,
        fetch_transport: FetchTransport | None = None,
        chunking_enabled: bool = True,
        chunk_max_tokens: int = 450,
        chunk_overlap: int = 60,
        contextualizer: ContextualizerSeam | None = None,
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
        self._memory = MemoryStore(self._backend, self.partition, max_turns=memory_max_turns)
        self._ingest = IngestPipeline(
            backend=self._backend,
            base_uri=self.base_uri,
            partition=self.partition,
            embedder=embedder,
            detector=detector,
            signals=self.signals,
            storage_options=storage_options,
            default_answer_language=default_answer_language,
            vision=vision,
            chunking_enabled=chunking_enabled,
            chunk_max_tokens=chunk_max_tokens,
            chunk_overlap=chunk_overlap,
            contextualizer=contextualizer,
        )
        retrievers: list[RetrieverPlugin] = []
        if Signal.embedding in self.signals:
            retrievers.append(VectorRetriever(self._store, embedder))
        if Signal.text in self.signals:
            retrievers.append(LexicalRetriever(self._store))
        if Signal.structure in self.signals:
            retrievers.append(StructureRetriever(self._backend, self.partition, self._store))
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
        self._generator = generator
        self._sink = sink
        self._fetch_transport = fetch_transport
        self._top_k = top_k

    @classmethod
    def from_config(
        cls,
        config: TrustRAGConfig,
        *,
        partition: PartitionPath | None = None,
        backend: StorageBackend | None = None,
        storage_options: StorageOptions | None = None,
        detector: LanguageDetectorPlugin | None = None,
        embed_transport: EmbedTransport | None = None,
        llm_transport: ChatTransport | None = None,
        rerank_transport: EmbedTransport | None = None,
        vision_transport: ChatTransport | None = None,
        context_transport: ChatTransport | None = None,
        sink: TelemetrySink | None = None,
    ) -> TrustRAG:
        """Build a client with real OpenAI-compatible plugins from ``config``.

        Endpoints, models, and ``llm.temperature`` come from the typed config;
        API keys are referenced only by env-var name (``*.api_key_env``) and
        never read here. Transports are injectable so this stays unit-testable.
        """
        if config.llm.endpoint is None:
            raise ValueError("config.llm.endpoint is required to build a generator")
        if config.embedding.endpoint is None:
            raise ValueError("config.embedding.endpoint is required to build an embedder")

        embedding_plugin = OpenAICompatibleEmbedding(
            base_url=config.embedding.endpoint,
            model=config.embedding.model,
            api_key_env=config.embedding.api_key_env,
            transport=embed_transport,
        )
        generator: Generator
        if config.llm.provider is LLMProvider.anthropic:
            generator = AnthropicGenerator(
                base_url=config.llm.endpoint,
                model=config.llm.model,
                api_key_env=config.llm.api_key_env,
                temperature=config.llm.temperature,
                max_tokens=config.llm.max_tokens or 1024,
                transport=llm_transport,
            )
        else:
            generator = OpenAICompatibleGenerator(
                base_url=config.llm.endpoint,
                model=config.llm.model,
                api_key_env=config.llm.api_key_env,
                temperature=config.llm.temperature,
                max_tokens=config.llm.max_tokens,
                transport=llm_transport,
            )
        reranker: RerankerPlugin | None = None
        if config.reranker.enabled and config.reranker.endpoint is not None:
            reranker = OpenAICompatibleReranker(
                base_url=config.reranker.endpoint,
                model=config.reranker.model,
                api_key_env=config.reranker.api_key_env,
                transport=rerank_transport,
            )

        # Vision is optional: build a client only when enabled + configured.
        # Without one, ingest stays text-level (images are skipped, never an error).
        vision: VisionDescriber | None = None
        if config.vision.enabled and config.vision.endpoint and config.vision.model:
            vision = OpenAICompatibleVision(
                base_url=config.vision.endpoint,
                model=config.vision.model,
                api_key_env=config.vision.api_key_env,
                transport=vision_transport,
            )

        # Contextual retrieval is optional: build the small-model contextualizer
        # only when enabled + configured. Without one, chunks index un-enriched.
        contextualizer: Contextualizer | None = None
        if (
            config.context_model.enabled
            and config.context_model.endpoint
            and config.context_model.model
        ):
            contextualizer = Contextualizer(
                base_url=config.context_model.endpoint,
                model=config.context_model.model,
                api_key_env=config.context_model.api_key_env,
                transport=context_transport,
            )

        return cls(
            config.storage.bucket,
            partition=partition,
            signals=config.signals,
            embedder=_SingleTextEmbedder(embedding_plugin),
            generator=generator,
            reranker=reranker,
            detector=detector,
            backend=backend,
            storage_options=storage_options,
            default_answer_language=config.multilingual.fallback_language,
            top_k=config.retrieval.top_k,
            memory_max_turns=config.memory.max_turns,
            sink=sink,
            vision=vision,
            chunking_enabled=config.chunking.enabled,
            chunk_max_tokens=config.chunking.max_tokens,
            chunk_overlap=config.chunking.overlap,
            contextualizer=contextualizer,
        )

    def ingest(
        self,
        source: Any = None,
        *,
        text: str | None = None,
        document_id: str | None = None,
        source_type: Any = None,
        acl: Any = None,
    ) -> IngestResult:
        # A URL is just another source: fetch it, then ingest as HTML.
        if text is None and is_url(source):
            return self._ingest_url(source, document_id=document_id, acl=acl)
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

    def _ingest_url(self, url: str, *, document_id: str | None, acl: Any) -> IngestResult:
        """Fetch a URL and ingest its body via the content-appropriate extractor."""
        from trustrag.extract.types import SourceType

        data, content_type = fetch_url(url, transport=self._fetch_transport)
        source_type = SourceType.html if "html" in content_type else None
        result = self._ingest.ingest(
            data,
            document_id=document_id or url,
            source_type=source_type,
            acl=acl,
        )
        if result.status == "ingested":
            self.refresh_slow_path()
        return result

    def crawl(
        self,
        seed_url: str,
        *,
        max_pages: int = 50,
        max_depth: int = 3,
        acl: Any = None,
    ) -> list[IngestResult]:
        """Crawl a website (same-domain, capped) and ingest each page as HTML."""
        from trustrag.extract.types import SourceType

        results: list[IngestResult] = []
        for page in crawl(
            seed_url,
            transport=self._fetch_transport,
            max_pages=max_pages,
            max_depth=max_depth,
        ):
            result = self._ingest.ingest(
                page.html.encode("utf-8"),
                document_id=page.url,
                source_type=SourceType.html,
                acl=acl,
            )
            results.append(result)
        if any(r.status == "ingested" for r in results):
            self.refresh_slow_path()
        return results

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
        retrieval_query = self._retrieval_query(question, conversation_id=conversation_id)
        result = self._answer.ask(
            question,
            self._retrieve.retrieve(retrieval_query, k or self._top_k),
            mode=mode,
            answer_language=answer_language,
            evidence_query=retrieval_query,
        )
        self._emit_generate(result)
        if conversation_id is not None:
            self._memory.append(conversation_id, question, result.answer)
        return result

    def _emit_generate(self, result: Result) -> None:
        """Emit the answering-model telemetry event (§6c). No-op without a sink.

        Carries the generator's real token usage (when the plugin surfaces it via
        ``last_usage``) and the answer/refuse outcome, attributed to the partition
        — the single stream the cost view and quality counters read.
        """
        if self._sink is None:
            return
        outcome = Outcome.ok if result.evidence.decision is Decision.answered else Outcome.refused
        self._sink.emit(
            StageEvent(
                stage=Stage.generate,
                partition=self.partition,
                tokens=getattr(self._generator, "last_usage", None),
                outcome=outcome,
            )
        )

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

    def recall(self, conversation_id: str, query: str, *, limit: int = 3) -> tuple[MemoryTurn, ...]:
        return self._memory.recall(conversation_id, query, limit=limit)

    def _retrieval_query(self, question: str, *, conversation_id: str | None) -> str:
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
