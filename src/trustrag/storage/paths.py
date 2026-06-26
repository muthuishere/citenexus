"""Partition → S3 prefix resolution (spec §6b).

A ``PartitionPath`` of any depth maps to a stable key segment ``<P>`` of ordered
``level=value`` parts, under which every storage layer has a fixed prefix. The
encoding is deterministic and depth-agnostic — the hierarchy is data.
"""

from __future__ import annotations

from enum import StrEnum

from trustrag.domain.partition import PartitionPath


class Layer(StrEnum):
    """The standard storage layers under a partition (§5 layout)."""

    raw = "raw"
    extracted = "extracted"
    knowledge = "knowledge"
    graph = "graph"
    vector = "vector"
    manifests = "manifests"
    eval = "eval"


def partition_segment(partition: PartitionPath) -> str:
    """The ``<P>`` key segment, e.g. ``org=acme/product_line=contracts``."""
    return "/".join(f"{level}={value}" for level, value in partition.as_pairs())


def layer_prefix(layer: Layer, partition: PartitionPath) -> str:
    """The prefix for ``layer`` under ``partition``, e.g. ``raw/org=acme/...``."""
    return f"{layer.value}/{partition_segment(partition)}"


def leaf_vector_uri(base_uri: str, partition: PartitionPath) -> str:
    """The LanceDB database URI for a leaf partition's vector store."""
    return f"{base_uri.rstrip('/')}/{layer_prefix(Layer.vector, partition)}/lancedb"
