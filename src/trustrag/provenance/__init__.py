"""Artifact provenance stamps + the dependency-aware partial-rebuild planner (§4c).

The stamp (:class:`ProducedBy`) records what produced each artifact; the planner
(:func:`plan`) diffs the current plugin/model set against a stamp and returns the
stale :class:`Layer` set — making "indexes are rebuildable caches" economical.
"""

from trustrag.provenance.rebuild_planner import Layer, plan, plan_all
from trustrag.provenance.stamp import (
    ModelManifest,
    ProducedBy,
    ProvenanceManifest,
    StageStamp,
)

__all__ = [
    "Layer",
    "ModelManifest",
    "ProducedBy",
    "ProvenanceManifest",
    "StageStamp",
    "plan",
    "plan_all",
]
