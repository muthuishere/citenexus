"""Public CiteNexus client — construct, ingest, retrieve, ask, evaluate."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from citenexus.answer.agentic import AgenticAnswerFlow, LoopBudget
from citenexus.answer.anthropic import AnthropicGenerator
from citenexus.answer.decision import CompletionDecisionModel, DecisionModel, LoopDecision
from citenexus.answer.flow import AnswerFlow, Generator
from citenexus.answer.generator import OpenAICompatibleGenerator
from citenexus.answer.result import Decision, Result
from citenexus.config.schema import CiteNexusConfig
from citenexus.config.signals import Signal, resolve_signals
from citenexus.contracts import EmbeddingProvider, SingleTextEmbedder
from citenexus.delete import DeleteResult
from citenexus.domain.authority import AuthorityPolicy
from citenexus.domain.partition import PartitionPath
from citenexus.domain.trust import TrustMode
from citenexus.embed import OpenAICompatibleEmbedding
from citenexus.embed import Transport as EmbedTransport
from citenexus.evaluate import EvaluationReport, Evaluator
from citenexus.evidence.chunked_builder import Contextualizer as ContextualizerSeam
from citenexus.evidence.contextualize import Contextualizer
from citenexus.graph import GraphDistiller, GraphRetriever, GraphStore, LLMGraphDistiller
from citenexus.hooks import Hooks
from citenexus.http import HttpEndpoint
from citenexus.http import Transport as ChatTransport
from citenexus.ingest.pipeline import IngestPipeline, VisionDescriber
from citenexus.ingest.result import IngestResult
from citenexus.ingest.web import FetchTransport, crawl, fetch_url, is_url
from citenexus.lang.codes import Language, LanguageLike
from citenexus.lang.detect import FastTextDetector
from citenexus.lang.search import UnsupportedSearchLanguageError, resolve_search_languages
from citenexus.memory import MemoryStore, MemoryTurn
from citenexus.plugins.base import LanguageDetectorPlugin, RerankerPlugin, RetrieverPlugin
from citenexus.retrieve.engine import RetrievalEngine
from citenexus.retrieve.lexical import LexicalRetriever
from citenexus.retrieve.reformulate import QueryReformulator, Reformulator
from citenexus.retrieve.rerank import OpenAICompatibleReranker
from citenexus.retrieve.structure import StructureRetriever
from citenexus.retrieve.types import Candidate
from citenexus.retrieve.vector import VectorRetriever
from citenexus.storage.backend import LocalFsBackend, S3Backend, StorageBackend
from citenexus.storage.lance_store import LanceVectorStore, StorageOptions
from citenexus.storage.location import S3
from citenexus.storage.manifest import EtagManifest, load_manifest, save_manifest
from citenexus.storage.paths import Layer, layer_prefix, leaf_vector_uri, partition_segment
from citenexus.storage.postgres_store import PostgresVectorStore, table_name_for
from citenexus.storage.protocols import TextSearch, VectorStore
from citenexus.stream import stream_result
from citenexus.telemetry.events import Outcome, Stage, StageEvent, UnitCount
from citenexus.telemetry.sinks import TelemetrySink
from citenexus.vision import OpenAICompatibleVision
from citenexus.wiki import LLMWikiDistiller, WikiDistiller, WikiRetriever, WikiStore

if TYPE_CHECKING:
    from citenexus.code import CodeFacade
    from citenexus.reconcile.manifest import CorpusManifest
    from citenexus.reconcile.report import ReconcileReport, RemediationReport
    from citenexus.schema import SchemaFacade


class _SingleHopDecider:
    """Fallback deep-ask decider: one gather hop, then answer from that pool.

    Used when no answering model exposes a ``complete()`` decision path. Never
    reports "sufficient" and never proposes a next query, so the loop halts on
    ``no_new_evidence`` after the first retrieval — a bounded, deterministic
    default that still runs the pool through the per-claim single-EU gate.
    """

    def decide(self, question: str, evidence: Sequence[str]) -> LoopDecision:
        return LoopDecision()


class _IdentityReranker(RerankerPlugin):
    plugin_version = "identity-rerank-v1"

    def rerank(self, query: str, candidates: Sequence[Candidate]) -> list[Candidate]:
        return list(candidates)


def _authority_policy(config: CiteNexusConfig) -> AuthorityPolicy:
    """Build the ADR-0004 policy from the declarative config section.

    ``default.v1`` (the default) returns the unranked policy, so a config that
    never mentions authority produces exactly today's behaviour.
    """
    section = config.authority
    if section.profile == "default.v1":
        return AuthorityPolicy.unranked()
    if section.profile == "ordered.v1":
        return AuthorityPolicy.ordered(
            section.tier_order,
            minimum_tier=section.minimum_tier,
            key=section.metadata_key,
        )
    raise ValueError(
        f"unknown authority profile {section.profile!r} (expected 'default.v1' or 'ordered.v1')"
    )


# The search-language default. `("en",)` is today's behaviour exactly: one
# English reformulation when a reformulator is configured, nothing otherwise.
DEFAULT_SEARCH_LANGUAGES: tuple[Language, ...] = (Language.ENGLISH,)


class CiteNexus:
    """The v0.1 public surface.

    Models are still injected. The client wires the existing ingest/retrieve
    layers into the answer/evaluate front doors that users call.
    """

    def __init__(
        self,
        base_uri: str | Path | S3,
        *,
        partition: PartitionPath | None = None,
        signals: Iterable[str | Signal] | None = None,
        embedder: EmbeddingProvider | SingleTextEmbedder | None = None,
        generator: Generator | None = None,
        reranker: RerankerPlugin | None = None,
        detector: LanguageDetectorPlugin | None = None,
        backend: StorageBackend | None = None,
        storage_options: StorageOptions | None = None,
        default_answer_language: LanguageLike = Language.ENGLISH,
        top_k: int = 5,
        memory_max_turns: int = 20,
        sink: TelemetrySink | None = None,
        vision: VisionDescriber | None = None,
        fetch_transport: FetchTransport | None = None,
        reformulator: Reformulator | None = None,
        wiki_distiller: WikiDistiller | None = None,
        graph_distiller: GraphDistiller | None = None,
        vector_store: VectorStore | None = None,
        text_search: TextSearch | None = None,
        hooks: Hooks | None = None,
        chunking_enabled: bool = True,
        chunk_max_tokens: int = 450,
        chunk_overlap: int = 60,
        contextualizer: ContextualizerSeam | None = None,
        agentic_budget: LoopBudget | None = None,
        agentic_decider: DecisionModel | None = None,
        authority: AuthorityPolicy | None = None,
    ) -> None:
        # A first-class S3 location carries endpoint + credential names and
        # derives BOTH storage halves; strings/paths keep the simple behavior.
        if isinstance(base_uri, S3):
            backend = backend or base_uri.make_backend()
            storage_options = (
                storage_options if storage_options is not None else base_uri.lance_storage_options()
            )
            base_uri = base_uri.base_uri()
        self.base_uri = str(base_uri)
        self.partition = partition or PartitionPath.of(("workspace", "default"))
        self.signals = resolve_signals(signals)
        self._backend = backend or _backend_for(self.base_uri)
        # The injected VectorStore seam (spec §6b): LanceDB-per-leaf (S3-native,
        # zero infra) is the reference default; Postgres/pgvector drops in here.
        self._store: VectorStore = vector_store or LanceVectorStore(
            leaf_vector_uri(self.base_uri, self.partition), storage_options
        )
        self._graph_store = GraphStore(self._backend, self.partition, distiller=graph_distiller)
        self._wiki_store = WikiStore(self._backend, self.partition, distiller=wiki_distiller)
        self._memory = MemoryStore(self._backend, self.partition, max_turns=memory_max_turns)
        # Without an embedder the client is still a working lexical search
        # engine: ingest stores rows with a placeholder vector (never searched —
        # the vector retriever is simply not constructed) and BM25 serves text.
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
            vector_store=self._store,
            chunking_enabled=chunking_enabled,
            chunk_max_tokens=chunk_max_tokens,
            chunk_overlap=chunk_overlap,
            contextualizer=contextualizer,
            sink=sink,
        )
        retrievers: list[RetrieverPlugin] = []
        if Signal.embedding in self.signals and embedder is not None:
            retrievers.append(VectorRetriever(self._store, embedder))
        if Signal.text in self.signals:
            # Text search is its own store seam: an injected TextSearch wins;
            # otherwise the vector store is used (native if it ranks text itself
            # — Postgres tsvector — else wrapped in BM25-lite over scan()).
            retrievers.append(LexicalRetriever(text_search or self._store))
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
        # ADR-0004: source STANDING, applied after grounding. The default is
        # ``default.v1`` with no floor -- every tier equal, nothing dropped.
        self._authority = authority or AuthorityPolicy.unranked()
        self._detector = detector
        self._answer = (
            AnswerFlow(
                generator=generator,
                default_answer_language=default_answer_language,
                authority=self._authority,
                detector=detector,
            )
            if generator is not None
            else None
        )
        self._generator = generator
        self._default_answer_language = default_answer_language
        self._agentic_budget = agentic_budget
        self._agentic_decider = agentic_decider
        self._sink = sink
        self._fetch_transport = fetch_transport
        self._reformulator = reformulator
        self._hooks = hooks or Hooks()
        self._top_k = top_k

    @classmethod
    def from_config(
        cls,
        config: CiteNexusConfig,
        *,
        partition: PartitionPath | None = None,
        backend: StorageBackend | None = None,
        storage_options: StorageOptions | None = None,
        detector: LanguageDetectorPlugin | None = None,
        embed_transport: EmbedTransport | None = None,
        llm_transport: ChatTransport | None = None,
        rerank_transport: EmbedTransport | None = None,
        vision_transport: ChatTransport | None = None,
        reformulate_transport: ChatTransport | None = None,
        wiki_distill_transport: ChatTransport | None = None,
        graph_distill_transport: ChatTransport | None = None,
        context_transport: ChatTransport | None = None,
        sink: TelemetrySink | None = None,
    ) -> CiteNexus:
        """Build a client from typed config: every model rides an HttpEndpoint.

        The application resolves its own secrets and puts the key VALUE on the
        endpoint (SecretStr) — the library reads no environment. The endpoint
        TYPE selects the wire protocol (AnthropicHttpEndpoint -> Messages API).
        Transports are injectable so tests stay hermetic.
        """

        def styled(
            endpoint: HttpEndpoint | None, injected: ChatTransport | None
        ) -> ChatTransport | None:
            return endpoint.build_transport(injected) if endpoint is not None else injected

        # Every model is optional: no embedding endpoint -> lexical-only
        # search; no llm endpoint -> retrieve-only client (ask() explains).
        embedder: EmbeddingProvider | SingleTextEmbedder | None = None
        if config.embedding.endpoint is not None:
            # The client goes straight to the model. It satisfies
            # `EmbeddingProvider` itself, so there is no adapter between our own
            # abstractions any more (ADR-0014).
            embedder = OpenAICompatibleEmbedding(
                base_url=config.embedding.endpoint.base_url,
                model=config.embedding.model,
                transport=styled(config.embedding.endpoint, embed_transport),
                batch_size=config.embedding.batch_size,
            )

        generator: Generator | None = None
        if config.llm.endpoint is not None:
            llm_transport_final = styled(config.llm.endpoint, llm_transport)
            if config.llm.endpoint.protocol == "anthropic":
                generator = AnthropicGenerator(
                    base_url=config.llm.endpoint.base_url,
                    model=config.llm.model,
                    temperature=config.llm.temperature,
                    max_tokens=config.llm.max_tokens or 1024,
                    transport=llm_transport_final,
                )
            else:
                generator = OpenAICompatibleGenerator(
                    base_url=config.llm.endpoint.base_url,
                    model=config.llm.model,
                    temperature=config.llm.temperature,
                    max_tokens=config.llm.max_tokens,
                    transport=llm_transport_final,
                )

        reranker: RerankerPlugin | None = None
        if config.reranker.enabled and config.reranker.endpoint is not None:
            reranker = OpenAICompatibleReranker(
                base_url=config.reranker.endpoint.base_url,
                model=config.reranker.model,
                transport=styled(config.reranker.endpoint, rerank_transport),
            )

        # Vision is optional: without a client, ingest stays text-level.
        vision: VisionDescriber | None = None
        if config.vision.enabled and config.vision.endpoint is not None and config.vision.model:
            vision = OpenAICompatibleVision(
                base_url=config.vision.endpoint.base_url,
                model=config.vision.model,
                transport=styled(config.vision.endpoint, vision_transport),
            )

        # EN dual-query reformulation: small model, cached per query.
        reformulator: Reformulator | None = None
        if config.reformulation.enabled and config.reformulation.endpoint is not None:
            reformulator = QueryReformulator(
                base_url=config.reformulation.endpoint.base_url,
                model=config.reformulation.model,
                transport=styled(config.reformulation.endpoint, reformulate_transport),
            )

        # LLM wiki distillation: degrades to the deterministic wiki.
        wiki_distiller: WikiDistiller | None = None
        if config.wiki_distill.enabled and config.wiki_distill.endpoint is not None:
            wiki_distiller = LLMWikiDistiller(
                base_url=config.wiki_distill.endpoint.base_url,
                model=config.wiki_distill.model,
                transport=styled(config.wiki_distill.endpoint, wiki_distill_transport),
            )

        # LLM graph distillation: degrades to deterministic co-mention.
        graph_distiller: GraphDistiller | None = None
        if config.graph_distill.enabled and config.graph_distill.endpoint is not None:
            graph_distiller = LLMGraphDistiller(
                base_url=config.graph_distill.endpoint.base_url,
                model=config.graph_distill.model,
                transport=styled(config.graph_distill.endpoint, graph_distill_transport),
            )

        # Contextual retrieval: small-model chunk blurbs (indexed text only).
        contextualizer: Contextualizer | None = None
        if (
            config.context_model.enabled
            and config.context_model.endpoint is not None
            and config.context_model.model
        ):
            contextualizer = Contextualizer(
                base_url=config.context_model.endpoint.base_url,
                model=config.context_model.model,
                transport=styled(config.context_model.endpoint, context_transport),
            )

        # The real detector by default (§11a: fastText lid.176, lazy-downloaded).
        if detector is None and config.multilingual.detector == "fasttext-lid176":
            detector = FastTextDetector(threshold=config.multilingual.detect_confidence_threshold)

        # VectorStore backend (spec §6b): LanceDB-per-leaf is the S3-native
        # default; "postgres" brings pgvector + native tsvector text search.
        vector_store: VectorStore | None = None
        if config.vector_store.backend == "postgres":
            if not config.vector_store.uri:
                raise ValueError("vector_store.backend='postgres' needs vector_store.uri (a DSN)")
            effective_partition = partition or PartitionPath.of(("workspace", "default"))
            vector_store = PostgresVectorStore(
                dsn=config.vector_store.uri,
                table=table_name_for(
                    config.vector_store.table_prefix,
                    partition_segment(effective_partition),
                ),
            )

        # S3-compatible endpoints (MinIO / R2): storage.endpoint_url wires both
        # the object backend and the Lance store options from config alone.
        if (
            backend is None
            and config.storage.bucket.startswith("s3://")
            and config.storage.endpoint_url
        ):
            bucket = config.storage.bucket.removeprefix("s3://").split("/", 1)[0]
            backend = S3Backend(
                bucket,
                endpoint_url=config.storage.endpoint_url,
                region=config.storage.region or "us-east-1",
            )
            if storage_options is None:
                storage_options = {
                    "endpoint": config.storage.endpoint_url,
                    "region": config.storage.region or "us-east-1",
                }
                if config.storage.endpoint_url.startswith("http://"):
                    storage_options["allow_http"] = "true"

        # Deep-ask budget: the hop cap is honored from GraphConfig.max_hops (the
        # declared graph-traversal depth), the rest from AgenticConfig.
        agentic_budget = LoopBudget(
            max_hops=config.graph.max_hops,
            max_tool_calls=config.agentic.max_tool_calls,
            max_evidence_units=config.agentic.max_evidence_units,
            timeout_s=config.agentic.timeout_s,
            stop_when=config.agentic.stop_when,
            search_k=config.agentic.search_k,
        )

        return cls(
            config.storage.bucket,
            partition=partition,
            signals=config.signals,
            embedder=embedder,
            generator=generator,
            agentic_budget=agentic_budget,
            reranker=reranker,
            detector=detector,
            backend=backend,
            storage_options=storage_options,
            default_answer_language=config.multilingual.resolved_default_answer_language,
            top_k=config.retrieval.top_k,
            memory_max_turns=config.memory.max_turns,
            sink=sink,
            vision=vision,
            reformulator=reformulator,
            wiki_distiller=wiki_distiller,
            graph_distiller=graph_distiller,
            vector_store=vector_store,
            chunking_enabled=config.chunking.enabled,
            chunk_max_tokens=config.chunking.max_tokens,
            chunk_overlap=config.chunking.overlap,
            contextualizer=contextualizer,
            authority=_authority_policy(config),
        )

    def ingest(
        self,
        source: Any = None,
        *,
        text: str | None = None,
        document_id: str | None = None,
        source_type: Any = None,
        acl: Any = None,
        authority: Mapping[str, str] | None = None,
    ) -> IngestResult:
        """Ingest one source.

        ``authority`` is caller-supplied source METADATA (ADR-0004) -- e.g.
        ``{"authority_tier": "controlling-statute", "jurisdiction": "CA"}``. It
        is carried and persisted verbatim on the Evidence Unit rows and read only
        by an ``AuthorityProfile`` at answer time; the library never parses it and
        never derives standing from the document's text. Omitting it leaves the
        document unranked, which is exactly the pre-ADR-0004 behaviour.
        """
        # A URL is just another source: fetch it, then ingest as HTML.
        if text is None and is_url(source):
            return self._ingest_url(source, document_id=document_id, acl=acl, authority=authority)
        result = self._ingest.ingest(
            source,
            text=text,
            document_id=document_id,
            source_type=source_type,
            acl=acl,
            authority=authority,
        )
        if result.status == "ingested":
            self._refresh_incremental(result.document_id)
        self._hooks.fire("on_ingest", result)
        return result

    def _refresh_incremental(self, document_id: str) -> None:
        """Per-document slow-path refresh — scales to very large corpora.

        The graph is only marked dirty here (co-mention edges are corpus-wide, so a
        per-ingest full rebuild does not scale); the read path rebuilds it lazily.
        The wiki upserts ONE page (Karpathy-style compounding). A full rebuild —
        including LLM distillation — happens via refresh_slow_path().
        """
        if Signal.graph in self.signals or Signal.community in self.signals:
            self._graph_store.mark_dirty()
        if Signal.wiki in self.signals:
            self._wiki_store.integrate_document(document_id, self._store)

    @property
    def code(self) -> CodeFacade:
        """The ``rag.code`` sub-facade — typed intake for source-code corpora.

        ``rag.code.ingest_from(folder | git)`` acquires and ingests a code corpus
        as symbol Evidence Units, then rebuilds the structural graph. It reads the
        existing ``signals`` contract (raising if ``graph``/``community`` is not
        declared) and the shared stores — no new constructor surface.
        """
        from citenexus.code import CodeFacade

        return CodeFacade(self)

    @property
    def schema(self) -> SchemaFacade:
        """The ``rag.schema`` sub-facade — typed intake for schema artifacts.

        ``rag.schema.ingest_from(file | doc)`` ingests a SQL DDL file or an
        OpenAPI/JSON-Schema document (a path or bytes — never a live connection
        URL) into verbatim schema Evidence Units, then rebuilds the structural
        graph so the injected schema distiller can emit FK / ``$ref`` edges. It
        reads the existing ``signals`` contract (raising if ``graph``/``community``
        is not declared) and the shared stores — no new constructor surface.
        """
        from citenexus.schema import SchemaFacade

        return SchemaFacade(self)

    def revoke(self, document_id: str) -> DeleteResult:
        """Alias of :meth:`delete` — retract one document and all it produced."""
        return self.delete(document_id)

    def delete(self, document_id: str) -> DeleteResult:
        """Surgically revoke one ingested document — the inverse of ``ingest``.

        Removes the document's vector rows, structure index, and per-document
        image blobs, and — guarded by the shared-checksum reference rule — its
        content-addressed raw blob, then rebuilds the graph and drops its wiki
        page when those signals are declared. The etag-manifest entry is removed
        LAST (the commit point), so a revoke interrupted before that write leaves
        the document logically present and a re-run completes cleanly.

        Idempotent: an absent or already-revoked id returns status ``"absent"``
        and changes nothing; a document that existed returns ``"deleted"`` with
        the purged Evidence-Unit ids. After a successful revoke the document is
        neither retrievable nor citable by ``ask()``; every other document is
        untouched.
        """
        etag_name = IngestPipeline.ETAG
        manifest = load_manifest(self._backend, self.partition, etag_name, EtagManifest)
        assert isinstance(manifest, EtagManifest)
        if document_id not in manifest.etags:
            return DeleteResult(document_id=document_id, status="absent")
        checksum = manifest.etags[document_id]

        # Capture what will be purged before the rows are gone.
        removed = tuple(
            str(row["eu_id"])
            for row in self._store.scan()
            if str(row.get("document_id", row.get("eu_id"))) == document_id
        )

        # Derived artifacts first (resumable order): rows → structure → images.
        self._store.delete_document(document_id)
        knowledge_prefix = layer_prefix(Layer.knowledge, self.partition)
        self._backend.delete_prefix(f"{knowledge_prefix}/structure/{document_id}.json")
        raw_prefix = layer_prefix(Layer.raw, self.partition)
        self._backend.delete_prefix(f"{raw_prefix}/images/{document_id}/")

        # Raw blobs are content-addressed and shared by identical bytes — delete
        # one ONLY when no other document still owns the checksum (§1). Every
        # checksum this document ever wrote is swept, not just the current one:
        # a re-ingest retires the previous checksum into the manifest, and
        # skipping those would leave the revoked document's earlier full text in
        # the bucket while this call reported ``status="deleted"``.
        for owned in (checksum, *manifest.superseded_of(document_id)):
            if not manifest.owners_of(owned, excluding=document_id):
                self._backend.delete_prefix(f"{raw_prefix}/{owned}")

        # Navigation must not point at revoked evidence.
        if Signal.graph in self.signals or Signal.community in self.signals:
            self._graph_store.build_from_store(self._store)
        if Signal.wiki in self.signals:
            self._wiki_store.remove_document(document_id)

        # Commit point LAST: while the entry is present the doc is logically present.
        manifest.forget(document_id)
        save_manifest(self._backend, self.partition, etag_name, manifest)

        result = DeleteResult(document_id=document_id, status="deleted", removed_eu_ids=removed)
        self._hooks.fire("on_delete", result)
        return result

    def _ingest_url(
        self,
        url: str,
        *,
        document_id: str | None,
        acl: Any,
        authority: Mapping[str, str] | None = None,
    ) -> IngestResult:
        """Fetch a URL and ingest its body via the content-appropriate extractor."""
        from citenexus.extract.types import SourceType

        data, content_type = fetch_url(url, transport=self._fetch_transport)
        source_type = SourceType.html if "html" in content_type else None
        result = self._ingest.ingest(
            data,
            document_id=document_id or url,
            source_type=source_type,
            acl=acl,
            authority=authority,
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
        authority: Mapping[str, str] | None = None,
    ) -> list[IngestResult]:
        """Crawl a website (same-domain, capped) and ingest each page as HTML."""
        from citenexus.extract.types import SourceType

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
                authority=authority,
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
        search_languages: Sequence[LanguageLike] = DEFAULT_SEARCH_LANGUAGES,
    ) -> list[Candidate]:
        """Retrieve for ``question``, optionally fanned out across languages.

        ``search_languages`` (ADR-0013) reformulates the question into each named
        language and fuses every retrieval through the one RRF merge. The original
        question is always issued too, so fan-out is strictly additive. A language
        whose script the tokenizer does not claim raises rather than returning
        nothing.
        """
        candidates = self._retrieve.retrieve(
            self._retrieval_query(question, conversation_id=conversation_id),
            k or self._top_k,
            extra_queries=self._extra_queries(question, search_languages),
        )
        self._hooks.fire("on_retrieve", question, candidates)
        return candidates

    def ask(
        self,
        question: str,
        *,
        mode: TrustMode = TrustMode.strict,
        k: int | None = None,
        answer_language: LanguageLike | None = None,
        conversation_id: str | None = None,
        strategy: str = "strict",
        search_languages: Sequence[LanguageLike] = DEFAULT_SEARCH_LANGUAGES,
    ) -> Result:
        """Answer ``question``, cite or abstain.

        ``strategy="strict"`` (default) is the unchanged single-passage flow.
        ``strategy="deep"`` runs the bounded, library-scripted agentic loop
        (`answer/agentic.py`): gather verbatim EUs across hops, then answer through
        the per-claim single-EU gate. Budgets bound cost; only the gate bounds truth.

        ``search_languages`` (ADR-0013) decides which languages the question is
        *searched* in; ``answer_language`` decides which language it is *answered*
        in, and the caller states it:

        * an explicit code (``"ta"``) forces that language, unconditionally;
        * ``"auto"`` detects it from the QUESTION, via the injected detector;
        * unspecified (``None``) is the configured ``default_answer_language`` —
          a fixed, predictable value, never an inference.

        The evidence never votes. Deriving the answer language from the retrieved
        pool stamped 15 of 22 English questions ``te``/``ta`` on
        ``examples/multilingual/``, and ``search_languages`` fan-out would have
        made that worse by design.

        The two knobs are independent: a fan-out changes only which passages reach
        the gate, and citations stay verbatim in their own source language.
        """
        if strategy == "deep":
            # Deep-ask writes its own follow-up queries inside the loop; it does not
            # go through the reformulation seam. Silently ignoring a fan-out request
            # would search fewer languages than asked, so it is refused instead.
            if tuple(search_languages) != tuple(DEFAULT_SEARCH_LANGUAGES):
                raise UnsupportedSearchLanguageError(
                    "search_languages is not supported by strategy='deep': the "
                    "agentic loop issues its own queries. Use strategy='strict'."
                )
            return self._deep_ask(
                question,
                mode=mode,
                answer_language=answer_language,
                conversation_id=conversation_id,
            )
        if strategy != "strict":
            raise ValueError(f"unknown ask strategy {strategy!r} (expected 'strict' or 'deep')")
        retrieval_query = self._retrieval_query(question, conversation_id=conversation_id)
        extra_queries = self._extra_queries(question, search_languages)
        # The EN reformulation also counts for the relevance gate: it is the same
        # question in the evidence's language. Citations and the faithfulness
        # gate stay exactly as strict — this only widens *relevance* matching.
        evidence_query = " ".join([retrieval_query, *extra_queries])
        candidates = self._retrieve.retrieve(
            retrieval_query, k or self._top_k, extra_queries=extra_queries
        )
        self._hooks.fire("on_retrieve", question, candidates)
        self._emit_fusion(len(candidates))
        result = self._require_answer().ask(
            question,
            candidates,
            mode=mode,
            answer_language=answer_language,
            evidence_query=evidence_query,
        )
        self._emit_generate(result)
        if result.evidence.decision is Decision.answered:
            self._hooks.fire("on_answer", result)
        else:
            self._hooks.fire("on_refuse", result)
        if conversation_id is not None:
            self._memory.append(conversation_id, question, result.answer)
        return result

    def _deep_ask(
        self,
        question: str,
        *,
        mode: TrustMode,
        answer_language: LanguageLike | None,
        conversation_id: str | None,
    ) -> Result:
        """Run the agentic deep-ask loop over this client's tools + generator."""
        generator = self._generator
        if generator is None:
            self._require_answer()  # raises the clear search-only-client error
        decider = self._agentic_decider or self._default_decider(generator)
        flow = AgenticAnswerFlow(
            generator=generator,  # type: ignore[arg-type]
            decider=decider,
            tools=self.tools(),
            budget=self._agentic_budget or LoopBudget(),
            default_answer_language=self._default_answer_language,
            detector=self._detector,
            # The SAME policy object the strict flow got. A guarantee that holds
            # on one strategy and not the other is not a guarantee, and deep-ask
            # must not need its own ceremony to inherit it (ADR-0004).
            authority=self._authority,
        )
        result = flow.ask(question, mode=mode, answer_language=answer_language)
        self._emit_generate(result)
        if result.evidence.decision is Decision.answered:
            self._hooks.fire("on_answer", result)
        else:
            self._hooks.fire("on_refuse", result)
        if conversation_id is not None:
            self._memory.append(conversation_id, question, result.answer)
        return result

    def _default_decider(self, generator: Generator | None) -> DecisionModel:
        """The loop's decision model: parse a JSON decision off the completion path.

        A generator exposing ``complete()`` drives the structured single-decision
        (no provider tool-calling). Without one, the loop makes a single gather hop
        (never "sufficient", never a next query) and answers from that pool.
        """
        if generator is not None and hasattr(generator, "complete"):
            return CompletionDecisionModel(generator)  # type: ignore[arg-type]
        return _SingleHopDecider()

    def _extra_queries(
        self,
        question: str,
        search_languages: Sequence[LanguageLike] = DEFAULT_SEARCH_LANGUAGES,
    ) -> tuple[str, ...]:
        """One reformulation of ``question`` per requested search language.

        Cached inside the reformulator by (question, language), so
        ask/retrieve/evaluate share one model call per pair. A reformulation that
        fails, comes back empty, duplicates another, or equals the original
        contributes nothing — retrieval then proceeds with fewer queries, never an
        error. Ordering is the caller's ``search_languages`` order, so the issued
        queries are deterministic and inspectable at the call site.

        The capability check runs FIRST, so an unsupported language costs zero
        model calls (ADR-0013).
        """
        languages = resolve_search_languages(search_languages)
        if self._reformulator is None:
            if len(languages) > 1:
                raise UnsupportedSearchLanguageError(
                    "search_languages requests "
                    f"{len(languages)} languages but no reformulation endpoint is "
                    "configured, so the fan-out would issue no extra queries and "
                    "look like a search that simply found nothing. Enable the "
                    "reformulation config section, or search one language."
                )
            return ()
        rewritten: list[str] = []
        for language in languages:
            candidate = self._reformulator.reformulate(question, language.code)
            if candidate and candidate != question and candidate not in rewritten:
                rewritten.append(candidate)
        return tuple(rewritten)

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

    def _emit_fusion(self, n_candidates: int) -> None:
        """Emit the fused-retrieval telemetry event (§6c). No-op without a sink."""
        if self._sink is None:
            return
        self._sink.emit(
            StageEvent(
                stage=Stage.fusion,
                partition=self.partition,
                units=UnitCount(candidates=n_candidates),
            )
        )

    def stream(
        self,
        question: str,
        *,
        mode: TrustMode = TrustMode.strict,
        k: int | None = None,
        answer_language: LanguageLike | None = None,
        conversation_id: str | None = None,
    ) -> Sequence[str]:
        result = self.ask(
            question,
            mode=mode,
            k=k,
            answer_language=answer_language,
            conversation_id=conversation_id,
        )
        chunks = tuple(stream_result(result))
        for chunk in chunks:
            self._hooks.fire("on_chunk", chunk)
        return chunks

    def tools(self) -> list[dict[str, Any]]:
        """Agentic navigation tools over this client's corpus (toolnexus-style).

        Framework-neutral specs — {name, description, parameters, handler} —
        for any tool-calling LLM: hybrid search, wiki index/page navigation,
        graph neighbors, and verbatim evidence fetch. Navigate-not-cite holds:
        only search_evidence/get_evidence return quotable (verbatim) text.
        """
        from citenexus.tools import build_tools

        return build_tools(self)

    def evaluate(self, csv_path: str | Path) -> EvaluationReport:
        self._require_answer()
        return Evaluator(self.ask).evaluate(csv_path)

    def reconcile(self, manifest: CorpusManifest, *, audit: bool = True) -> ReconcileReport:
        """Diff this partition's index against a caller-declared corpus (ADR-0008).

        Answers the question the cite-or-abstain guarantee cannot: not "is this
        citation faithful to the index" but "is this index derived from exactly
        the corpus we agreed to". Returns three disjoint sets — ``orphans``
        (indexed, undeclared), ``missing`` (declared current, not indexed), and
        ``drifted`` (declared and indexed, hashes disagree, including a declared
        version that has been superseded).

        Read-only: it modifies no evidence layer and deletes nothing under any
        circumstances. By default it appends one line to the append-only
        reconciliation audit stream; ``audit=False`` writes nothing at all.

        The report is document-keyed, and says so in its own ``scope`` field — an
        empty report means the declared corpus and the index agree at document
        level, not that the bucket is clean.
        """
        from citenexus.reconcile.engine import reconcile as _reconcile

        return _reconcile(
            backend=self._backend,
            partition=self.partition,
            store=self._store,
            manifest=manifest,
            audit=audit,
        )

    def remediate(self, report: ReconcileReport, *, audit: bool = True) -> RemediationReport:
        """Act on a reconciliation report by revoking its ORPHANS — nothing else.

        Deliberately separate from :meth:`reconcile`: nothing is ever deleted as
        a side effect of a diagnostic. Removal goes through :meth:`delete`, so a
        remediated orphan leaves nothing behind in any layer. ``missing`` and
        ``drifted`` need an ingest and a re-ingest respectively — neither is a
        deletion, so neither is touched.
        """
        from citenexus.reconcile.engine import remediate as _remediate

        return _remediate(
            backend=self._backend,
            partition=self.partition,
            revoker=self,
            report=report,
            audit=audit,
        )

    def _require_answer(self) -> AnswerFlow:
        """The answer flow, or a clear error for search-only clients."""
        if self._answer is None:
            raise ValueError(
                "ask()/stream()/evaluate() need an answering model — construct "
                "CiteNexus(generator=...) or set llm.endpoint in the config. "
                "retrieve() works without one."
            )
        return self._answer

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
