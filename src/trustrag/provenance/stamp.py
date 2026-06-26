"""Provenance stamps — the ``produced_by`` bookkeeping carried on artifacts (§4c).

S3 is the source of truth and every index is a rebuildable cache (§2); that only
pays off if a model/plugin swap rebuilds the *minimum*. To compute the stale set
later, each generated artifact records exactly what produced it: an
``artifact_version`` plus a per-stage descriptor (producing plugin name, its
``plugin_version``, and the endpoint model / embedding dimension where relevant).

These are pure pydantic v2 value types — frozen, ``extra="forbid"``, fully JSON
round-trippable. No I/O: persisting a ``ModelManifest`` as ``model_manifest.json``
or a ``ProvenanceManifest`` per partition belongs to the storage layer.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class StageStamp(BaseModel):
    """What a single pipeline stage used to produce an artifact.

    ``endpoint_model`` and ``dim`` are populated only where they matter — vision
    and embedding stages carry the injected endpoint model, and embedding also
    carries its vector dimension; pure-plugin stages leave both ``None``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    plugin: str
    plugin_version: str
    endpoint_model: str | None = None
    dim: int | None = None


class ProducedBy(BaseModel):
    """The ``produced_by`` stamp on a generated artifact (§4c).

    Carries the ``artifact_version`` and one :class:`StageStamp` per stage that
    actually produced the artifact. A stage that did not contribute (e.g. a
    text-only artifact has no ``vision``) is left ``None``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_version: int
    extractor: StageStamp | None = None
    chunker: StageStamp | None = None
    vision: StageStamp | None = None
    embedding: StageStamp | None = None
    graph_extractor: StageStamp | None = None


class ModelManifest(BaseModel):
    """The *current* plugin/model set for a partition.

    Sourced from the plugin registry's current ``plugin_version``s and persisted
    per partition (as ``model_manifest.json``; file I/O is out of scope here).
    The rebuild planner diffs this against an artifact's :class:`ProducedBy` to
    find stale layers. ``reranker`` and ``llm`` are query-time plugins that
    produce no stored artifact, so they are tracked here but never seed a
    rebuild.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    extractor: StageStamp | None = None
    chunker: StageStamp | None = None
    vision: StageStamp | None = None
    embedding: StageStamp | None = None
    graph_extractor: StageStamp | None = None
    reranker: StageStamp | None = None
    llm: StageStamp | None = None


class ProvenanceManifest(BaseModel):
    """A small map from artifact id to its :class:`ProducedBy` stamp.

    A convenience value type for carrying many stamps together (e.g. all
    artifacts in a partition) while staying I/O-free and round-trippable.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    stamps: dict[str, ProducedBy]
