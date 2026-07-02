"""The signal-gated, idempotent fast-path ingest orchestrator (§8)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast

from trustrag.config.signals import Signal, requires_slow_path, resolve_signals
from trustrag.evidence.builder import build_evidence_units
from trustrag.evidence.structure import build_structure
from trustrag.extract.dispatch import extract
from trustrag.extract.types import SourceType
from trustrag.ingest.result import IngestResult
from trustrag.lang.detect import HeuristicDetector
from trustrag.lang.fallback import resolve_answer_language
from trustrag.storage.lance_store import LanceVectorStore, StorageOptions
from trustrag.storage.manifest import EtagManifest, load_manifest, save_manifest
from trustrag.storage.paths import Layer, layer_prefix, leaf_vector_uri, partition_segment
from trustrag.vision.describe import describe_image
from trustrag.vision.units import build_vision_units

if TYPE_CHECKING:
    from collections.abc import Iterable

    from trustrag.domain.partition import PartitionPath
    from trustrag.evidence.unit import EvidenceUnit
    from trustrag.extract.types import ImageRef
    from trustrag.plugins.base import LanguageDetectorPlugin, VisionPlugin
    from trustrag.storage.backend import StorageBackend
    from trustrag.storage.protocols import VectorStore
    from trustrag.vision.describe import VisionRecord
    from trustrag.worker.queue import DurableQueue


class Embedder(Protocol):
    def embed(self, text: str) -> list[float]: ...


class VisionDescriber(Protocol):
    """The injected vision seam — describe an image's bytes (§9).

    Optional: with no describer configured, ingest is text-level only. Satisfied
    by ``OpenAICompatibleVision`` and ``FakeVision``.
    """

    def describe(self, image_region: Any) -> Any: ...


class _BytesImage:
    """Carries an ``ImageRef``'s metadata plus its loaded bytes for the VL plugin.

    ``describe_image`` reads ``.image_id``; a real vision client reads ``.data``.
    This adapter satisfies both so the same call works for ``FakeVision`` (ignores
    bytes) and ``OpenAICompatibleVision`` (needs them).
    """

    def __init__(self, image: Any, data: bytes) -> None:
        self.image_id = getattr(image, "image_id", "img")
        self.page = getattr(image, "page", None)
        self.bbox = getattr(image, "bbox", None)
        self.data = data


def _raw_bytes(source: Any, text: str | None) -> bytes:
    if text is not None:
        return text.encode("utf-8")
    if isinstance(source, bytes):
        return source
    if isinstance(source, str | Path) and Path(source).exists():
        return Path(source).read_bytes()
    if isinstance(source, str):
        return source.encode("utf-8")
    raise TypeError(f"cannot read bytes from source of type {type(source).__name__}")


def _document_id(source: Any, text: str | None, given: str | None) -> str:
    if given:
        return given
    if text is None and isinstance(source, str | Path) and Path(source).exists():
        return Path(source).stem
    return "doc"


class IngestPipeline:
    """Turn a source into indexed, cited evidence — gated by declared signals."""

    ETAG = "etag_manifest.json"

    def __init__(
        self,
        *,
        backend: StorageBackend,
        base_uri: str,
        partition: PartitionPath,
        embedder: Embedder,
        detector: LanguageDetectorPlugin | None = None,
        signals: Iterable[str | Signal] | None = None,
        storage_options: StorageOptions | None = None,
        queue: DurableQueue | None = None,
        default_answer_language: str = "en",
        vision: VisionDescriber | None = None,
        vector_store: VectorStore | None = None,
    ) -> None:
        self._backend = backend
        self._partition = partition
        self._embedder = embedder
        self._detector: LanguageDetectorPlugin = detector or HeuristicDetector()
        self._signals = resolve_signals(signals)
        # The injected VectorStore seam; LanceDB-per-leaf is the default.
        self._store: VectorStore = vector_store or LanceVectorStore(
            leaf_vector_uri(base_uri, partition), storage_options
        )
        self._queue = queue
        self._default_language = default_answer_language
        self._vision = vision

    def ingest(
        self,
        source: Any = None,
        *,
        text: str | None = None,
        document_id: str | None = None,
        source_type: SourceType | None = None,
        acl: Any = None,
    ) -> IngestResult:
        raw = _raw_bytes(source, text)
        doc_id = _document_id(source, text, document_id)
        checksum = hashlib.sha256(raw).hexdigest()

        # Idempotency: skip unchanged content (§4c/§5).
        manifest = load_manifest(self._backend, self._partition, self.ETAG, EtagManifest)
        assert isinstance(manifest, EtagManifest)
        if not manifest.is_changed(doc_id, checksum):
            return IngestResult(document_id=doc_id, status="unchanged")

        if text is not None:
            doc = extract(text, source_type=SourceType.plain, document_id=doc_id)
        else:
            doc = extract(source, source_type=source_type, document_id=doc_id)

        language = self._detect_language(doc)
        units = build_evidence_units(doc, partition=self._partition, language=language, acl=acl)
        units.extend(self._vision_units(doc, doc_id=doc_id, language=language, acl=acl))

        # Persist the raw blob (content-addressed).
        raw_prefix = layer_prefix(Layer.raw, self._partition)
        self._backend.put_bytes(f"{raw_prefix}/{checksum}", raw)
        raw_uri = f"{raw_prefix}/{checksum}"

        # structure signal → build + persist the structure index.
        if Signal.structure in self._signals:
            index = build_structure(doc)
            key = f"{layer_prefix(Layer.knowledge, self._partition)}/structure/{doc_id}.json"
            self._backend.put_json(key, index.model_dump(mode="json"))

        # embedding/text signal → embed + upsert into the leaf vector store.
        if Signal.embedding in self._signals or Signal.text in self._signals:
            rows = [
                {
                    "eu_id": eu.eu_id,
                    "vector": self._embedder.embed(eu.text),
                    "text": eu.text,
                    "document_id": eu.document_id,
                    "language": eu.language,
                    "page": eu.citation.page if eu.citation.page is not None else -1,
                    "checksum": checksum,
                    "raw_uri": raw_uri,
                }
                for eu in units
            ]
            self._store.upsert(rows)

        # slow-path signals → enqueue the content hash on the durable worker.
        enqueued = False
        if requires_slow_path(self._signals) and self._queue is not None:
            self._queue.enqueue(
                checksum, partition_segment(self._partition), {"document_id": doc_id}
            )
            enqueued = True

        manifest.record(doc_id, checksum)
        save_manifest(self._backend, self._partition, self.ETAG, manifest)

        return IngestResult(
            document_id=doc_id,
            status="ingested",
            eu_ids=tuple(eu.eu_id for eu in units),
            n_units=len(units),
            enqueued_slow_path=enqueued,
        )

    def _vision_units(
        self, doc: Any, *, doc_id: str, language: str, acl: Any
    ) -> list[EvidenceUnit]:
        """Describe the doc's images into figure EUs — text-level only if unable.

        Guarded degradation (per design): with no vision plugin, or images that
        carry no retrievable bytes, this returns ``[]`` and ingest proceeds at
        text level. A per-image failure never fails the whole ingest.
        """
        vision = self._vision
        if vision is None or not getattr(doc, "images", ()):
            return []
        described: list[tuple[ImageRef, VisionRecord]] = []
        for image in doc.images:
            data = self._image_bytes(image)
            if data is None:
                continue
            try:
                record = describe_image(
                    cast("ImageRef", _BytesImage(image, data)),
                    cast("VisionPlugin", vision),
                )
            except Exception:
                continue
            described.append((image, record))
        if not described:
            return []
        return build_vision_units(
            described,
            document_id=doc_id,
            partition=self._partition,
            language=language,
            acl=acl,
            source_uri=getattr(doc, "source_uri", None),
        )

    def _image_bytes(self, image: Any) -> bytes | None:
        """Fetch an image's bytes from its ``blob_key`` (None if not persisted)."""
        blob_key = getattr(image, "blob_key", None)
        if not blob_key:
            return None
        try:
            return self._backend.get_bytes(blob_key)
        except Exception:
            return None

    def _detect_language(self, doc: Any) -> str:
        text = " ".join(block.text for block in doc.blocks)[:2000]
        detection = self._detector.detect(text) if text.strip() else None
        return resolve_answer_language(
            detection=detection, default_answer_language=self._default_language
        )
