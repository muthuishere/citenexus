"""``rag.schema.ingest_from(file | doc)`` — the typed schema-intake verb.

A schema **artifact** (a SQL DDL file or an OpenAPI/JSON-Schema document) is
ingested through its own namespaced verb, never the generic ``ingest()`` firehose
— the same shape as ``rag.code.ingest_from``. This sub-facade classifies the
source (SQL vs OpenAPI/JSON-Schema), drives the matching core extractor into
verbatim schema Evidence Units, and rebuilds the structural graph once so the
injected schema distiller can emit FK / ``$ref`` edges (``confidence=extracted``).

Scope guard — schema **artifacts you already have**, never a live database:

- ``source`` is a **path or bytes**, not a connection URL. A ``postgres://`` /
  ``mysql://`` / ``mongodb://`` / ``redis://`` URL is **rejected** (fail-loud) —
  live-DB connectors are a network-service surface, out of core (a later change).
- A source that is neither SQL nor OpenAPI/JSON-Schema degrades to **plain** text
  (ingested, never raises).

It enforces the same precondition as code: a schema corpus is meaningless without
its structural graph, so it raises immediately if the instance was created without
the ``graph`` (or ``community``) signal — no silent partial ingest.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from citenexus.config.signals import Signal
from citenexus.extract.plain import load_text, resolve_path
from citenexus.extract.types import SourceType
from citenexus.ingest.result import IngestResult

# Live-DB connection URL schemes — explicitly OUT of scope here (a connector is a
# network-service surface / not a verbatim-citable artifact). Rejected fail-loud.
_CONNECTOR_SCHEMES = ("postgres://", "postgresql://", "mysql://", "mongodb://", "redis://")


class _SchemaClient(Protocol):
    """The slice of ``CiteNexus`` the schema facade drives."""

    @property
    def signals(self) -> Collection[Signal]: ...

    def ingest(
        self,
        source: object = ...,
        *,
        text: str | None = ...,
        document_id: str | None = ...,
        source_type: object = ...,
        acl: object = ...,
    ) -> IngestResult: ...

    def refresh_slow_path(self) -> None: ...


@dataclass
class SchemaIngestReport:
    """What one ``ingest_from`` call ingested."""

    document_id: str
    source_type: SourceType

    @property
    def is_schema(self) -> bool:
        return self.source_type in (SourceType.schema_sql, SourceType.schema_openapi)


class SchemaFacade:
    """Lazy ``rag.schema`` sub-facade — bound to one ``CiteNexus`` instance."""

    def __init__(self, client: _SchemaClient) -> None:
        self._client = client

    def ingest_from(
        self,
        source: str | Path | bytes,
        *,
        document_id: str | None = None,
    ) -> SchemaIngestReport:
        """Ingest a schema artifact — a SQL DDL file or an OpenAPI/JSON-Schema doc.

        ``source`` is a path (``str``/``Path``) or raw ``bytes`` — **not** a live
        connection URL. The kind is classified from the filename and content; an
        unrecognised source ingests as plain text (never raises).
        """
        self._require_graph_signal()
        self._reject_connection_url(source)

        source_type = self._classify(source)
        result = self._client.ingest(
            source=source,
            document_id=document_id,
            source_type=source_type,
        )
        # One graph rebuild after the ingest — runs the injected schema distiller
        # (FK / $ref edges), grounding each edge endpoint against a real schema EU.
        self._client.refresh_slow_path()
        return SchemaIngestReport(
            document_id=result.document_id,
            source_type=source_type or SourceType.plain,
        )

    def _require_graph_signal(self) -> None:
        signals = set(self._client.signals)
        if Signal.graph not in signals and Signal.community not in signals:
            raise ValueError(
                "rag.schema.ingest_from requires the 'graph' (or 'community') signal — "
                "a schema corpus is meaningless without its structural graph. Construct "
                "CiteNexus(..., signals=[..., 'graph']). No schema was ingested."
            )

    @staticmethod
    def _reject_connection_url(source: str | Path | bytes) -> None:
        if isinstance(source, str) and source.lower().startswith(_CONNECTOR_SCHEMES):
            raise ValueError(
                "rag.schema.ingest_from ingests schema ARTIFACTS (a .sql file or an "
                "OpenAPI/JSON-Schema document), not a live connection URL. Live-database "
                "connectors are out of scope for this capability (a separate change). "
                "Export the schema to an artifact and pass that instead."
            )

    @staticmethod
    def _classify(source: str | Path | bytes) -> SourceType | None:
        """SQL vs OpenAPI/JSON-Schema vs unknown (→ ``None`` = plain), by filename
        then content sniff. Never connects to or reads anything but the artifact."""
        path = resolve_path(source) if not isinstance(source, bytes) else None
        if path is not None:
            suffix = path.suffix.lower()
            if suffix == ".sql":
                return SourceType.schema_sql
            if suffix in (".json", ".yaml", ".yml") or "openapi" in path.name.lower():
                # JSON is span-extracted; YAML degrades to plain inside the extractor.
                return SourceType.schema_openapi

        text, _doc_id, _uri = load_text(source, None)
        head = text.lstrip()
        if _looks_like_sql(text):
            return SourceType.schema_sql
        if head.startswith("{") and _looks_like_openapi(text):
            return SourceType.schema_openapi
        return None  # unknown → plain (handled by dispatch)


def _looks_like_sql(text: str) -> bool:
    lowered = text.lower()
    return "create table" in lowered


_OPENAPI_MARKERS = ('"openapi"', '"paths"', '"components"', '"$defs"', '"definitions"')


def _looks_like_openapi(text: str) -> bool:
    return any(marker in text for marker in _OPENAPI_MARKERS)
