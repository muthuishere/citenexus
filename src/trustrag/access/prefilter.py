"""The allowed-partitions hard pre-filter + an optional opaque-acl predicate
(spec §7c).

TrustRAG is RBAC-*ready*, not an RBAC engine. Enforcement is an external
operator-managed store's job; the library only consumes the *result* of that
decision: a set of allowed :class:`~trustrag.domain.partition.PartitionPath`s
the caller already resolved. A candidate partition is allowed iff some allowed
path is a prefix of it (authorization at a prefix grants the whole sub-tree).

This runs as a pre-filter — disallowed partitions are dropped *before*
retrieval, so it only ever shrinks the search space (it improves latency, never
costs it). An empty allowed set means nothing is visible.

The optional ``acl`` predicate is a finer, second-stage filter over already
partition-allowed objects. The library NEVER parses an object's ``acl``: it is
opaque and is handed verbatim to the caller's predicate, which is the only thing
that interprets it. Coarse partition enforcement is solid; the acl stage is
weaker (see ``design.md``).
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterable
from typing import TypeVar

from trustrag.domain.partition import PartitionPath

T = TypeVar("T")


def allowed_partition(
    candidate: PartitionPath, allowed_set: Collection[PartitionPath]
) -> bool:
    """True iff some path in ``allowed_set`` is a prefix of ``candidate``.

    An empty ``allowed_set`` always returns ``False`` (nothing is visible).
    """
    return any(allowed.is_prefix_of(candidate) for allowed in allowed_set)


def filter_partitions(
    candidates: Iterable[PartitionPath], allowed_set: Collection[PartitionPath]
) -> list[PartitionPath]:
    """Drop every candidate not authorized by ``allowed_set``, preserving order."""
    return [c for c in candidates if allowed_partition(c, allowed_set)]


def apply_acl_predicate(
    objects: Iterable[T],
    acl_of: Callable[[T], object],
    predicate: Callable[[object], bool] | None = None,
) -> list[T]:
    """Filter already partition-allowed ``objects`` by their opaque ``acl``.

    ``acl_of`` extracts each object's opaque acl; ``predicate`` decides whether
    to keep it. The acl is passed through untouched — the library never inspects
    it. With no ``predicate`` (the default), every object is kept (the acl stage
    is a no-op), preserving order in all cases.
    """
    if predicate is None:
        return list(objects)
    return [obj for obj in objects if predicate(acl_of(obj))]
