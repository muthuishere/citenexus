"""Access pre-filter — RBAC-ready partition gating (spec §7c, §6b).

TrustRAG carries the partition hierarchy + an opaque ``acl`` but enforces
neither; it consumes a caller-resolved ``allowed_partitions`` set as a hard
pre-filter that runs before retrieval. ``resolve_scope`` turns a query scope
into a :class:`~trustrag.domain.partition.PartitionPath` prefix; ``prefilter``
gates candidate partitions (and, optionally, objects' opaque acl) against it.
"""

from trustrag.access.prefilter import (
    allowed_partition,
    apply_acl_predicate,
    filter_partitions,
)
from trustrag.access.scope import resolve_scope

__all__ = [
    "allowed_partition",
    "apply_acl_predicate",
    "filter_partitions",
    "resolve_scope",
]
