"""Typed configuration schema for the full §17 surface (spec §17).

Every section of the §17 configuration is a small ``frozen``/``extra="forbid"``
pydantic sub-model, composed into the top-level :class:`TrustRAGConfig`. Defaults
live on the fields so a bare config — only ``storage.bucket`` supplied — is valid
and matches the documented defaults (strict mode, ``rrf_k=60``, ``top_k=11``,
``lexical_signal=bge_m3_sparse``, ``detect_confidence_threshold=0.50``,
``answer_in_query_language=true``, all six signals declared).

There is no pipeline behavior here: this is typed config only. Field names track
the §17 keys 1:1 so the schema can't silently drift from the spec.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from trustrag.config.signals import Signal
from trustrag.domain.trust import TrustMode


class _Section(BaseModel):
    """Shared config for every §17 sub-model: immutable, no unknown keys."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class LexicalSignal(StrEnum):
    """The sparse/lexical retrieval backend (§10)."""

    bge_m3_sparse = "bge_m3_sparse"
    bm25 = "bm25"


class LLMProvider(StrEnum):
    """The answering-model wire protocol (§4b).

    ``openai`` covers any OpenAI-compatible ``/chat/completions`` endpoint —
    OpenAI, Gemini's OpenAI-compat endpoint, Ollama, vLLM, OpenRouter, …
    ``anthropic`` is the native Messages API (different shape, own client).
    """

    openai = "openai"
    anthropic = "anthropic"


class StorageConfig(_Section):
    """S3-native storage + the variable-depth partition hierarchy (§6b)."""

    bucket: str
    # An ordered list of partition level names of *any* depth ≥ 1 — never assumed
    # to be exactly three levels (§6b).
    partition_hierarchy: tuple[str, ...] = Field(
        default=("org", "product_line", "product"), min_length=1
    )
    region: str | None = None
    endpoint_url: str | None = None
    prefix: str | None = None


class LLMConfig(_Section):
    """The injected answering model (§4b).

    ``provider`` selects the wire protocol — OpenAI-compatible (default; also
    Gemini/Ollama/OpenRouter) or Anthropic's native Messages API.
    """

    provider: LLMProvider = LLMProvider.openai
    model: str = "qwen2.5"
    endpoint: str | None = None
    api_key_env: str | None = None
    temperature: float = 0.0
    max_tokens: int | None = None
    timeout_s: float = 60.0


class EmbeddingConfig(_Section):
    """The dense+sparse embedding endpoint (§10, default bge-m3)."""

    model: str = "bge-m3"
    endpoint: str | None = None
    api_key_env: str | None = None
    dense: bool = True
    sparse: bool = True
    batch_size: int = 32
    dimensions: int | None = None


class RerankerConfig(_Section):
    """The cross-encoder reranker seam (§10b, default bge-reranker-v2-m3)."""

    enabled: bool = True
    model: str = "bge-reranker-v2-m3"
    endpoint: str | None = None
    api_key_env: str | None = None
    top_n: int = 20


class VisionPrefilterConfig(_Section):
    """The cheap pre-filter that gates the conditional vision pass (§9)."""

    enabled: bool = True
    min_image_area_px: int = 10_000
    skip_decorative: bool = True
    max_images_per_doc: int | None = None


class VisionConfig(_Section):
    """Conditional vision: a pre-filter then a 3-way decision (§9)."""

    enabled: bool = False
    model: str | None = None
    endpoint: str | None = None
    api_key_env: str | None = None
    prefilter: VisionPrefilterConfig = Field(default_factory=VisionPrefilterConfig)


class VectorStoreConfig(_Section):
    """The vector index backend (§4, default LanceDB)."""

    backend: str = "lancedb"
    uri: str | None = None
    table_prefix: str = "trustrag"


class GraphConfig(_Section):
    """Knowledge-graph + community layer (§10, slow-path signal)."""

    enabled: bool = False
    community_algorithm: str = "leiden"
    resolution: float = 1.0
    max_hops: int = 2


class RetrievalConfig(_Section):
    """Fusion + retrieval knobs (§10)."""

    rrf_k: int = 60
    top_k: int = 11
    lexical_signal: LexicalSignal = LexicalSignal.bge_m3_sparse
    candidate_pool: int = 100
    structure_signal: bool = True


class TrustConfig(_Section):
    """Answering posture (§14, default strict)."""

    default_mode: TrustMode = TrustMode.strict
    min_sources_strict: int = 2
    require_citations: bool = True


class MultilingualConfig(_Section):
    """Language detection + the answer-language invariant (§11, §11a)."""

    detector: str = "fasttext-lid176"
    detect_confidence_threshold: float = 0.50
    fallback_language: str = "en"
    # The answer is always returned in the query's language (§11) — regenerate on
    # mismatch; citations stay verbatim and are never translated in place.
    answer_in_query_language: bool = True
    translate_citations: bool = False


class AccessControlConfig(_Section):
    """Deferred-RBAC pre-filter wiring (§7c) — carried, not enforced in-library."""

    enabled: bool = False
    external_store: str | None = None
    allowed_partitions: tuple[str, ...] | None = None


class ProvenanceConfig(_Section):
    """Artifact provenance stamps + the rebuild DAG (§4c)."""

    enabled: bool = True
    stamp_artifacts: bool = True


class WorkerConfig(_Section):
    """Background worker / queue / retry / DLQ / resume (§5b)."""

    concurrency: int = 4
    max_retries: int = 3
    backoff_base_s: float = 1.0
    dlq_enabled: bool = True


class TelemetryConfig(_Section):
    """Unified telemetry + cost (§6c)."""

    enabled: bool = True
    cost_tracking: bool = True
    event_sink: str | None = None


class MemoryConfig(_Section):
    """Partition/acl-scoped conversation memory (§16b)."""

    enabled: bool = False
    max_turns: int = 20
    scope: str = "partition"


class JudgeConfig(_Section):
    """LLM-as-judge, online + offline, audit-tracked (§20b)."""

    enabled: bool = False
    mode: str = "offline"
    model: str | None = None


class StreamingConfig(_Section):
    """Token (normal) / sentence-gated (strict) streaming (§16c)."""

    enabled: bool = False
    mode: str = "sentence_gated"


class TrustRAGConfig(BaseModel):
    """The composed §17 configuration object.

    Only ``storage`` (with a ``bucket``) is required; every other section takes
    its documented defaults so a zero-config client just works. ``signals``
    declares the capability set (defaults to all six) and ``validate`` optionally
    points at a ``trustrag.validate.yaml`` allow-list.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    storage: StorageConfig
    llm: LLMConfig = Field(default_factory=LLMConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    reranker: RerankerConfig = Field(default_factory=RerankerConfig)
    vision: VisionConfig = Field(default_factory=VisionConfig)
    vector_store: VectorStoreConfig = Field(default_factory=VectorStoreConfig)
    graph: GraphConfig = Field(default_factory=GraphConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    trust: TrustConfig = Field(default_factory=TrustConfig)
    multilingual: MultilingualConfig = Field(default_factory=MultilingualConfig)
    access_control: AccessControlConfig = Field(default_factory=AccessControlConfig)
    plugins: dict[str, str] = Field(default_factory=dict)
    provenance: ProvenanceConfig = Field(default_factory=ProvenanceConfig)
    worker: WorkerConfig = Field(default_factory=WorkerConfig)
    telemetry: TelemetryConfig = Field(default_factory=TelemetryConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    judge: JudgeConfig = Field(default_factory=JudgeConfig)
    streaming: StreamingConfig = Field(default_factory=StreamingConfig)

    # Client-section knobs: the declared capability set (defaults to all six) and
    # the optional doc-type declaration + validate.yaml path the warn-only
    # validation contract consults.
    signals: tuple[Signal, ...] = Field(default_factory=lambda: tuple(Signal))
    doc_types: tuple[str, ...] | None = None
    # Path to an optional ``trustrag.validate.yaml`` allow-list (the client
    # ``validate`` knob); consumed by the warn-only validation contract.
    validate_path: str | None = None
