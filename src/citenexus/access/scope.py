"""Query-scope resolution — a scope dict + a hierarchy order → a PartitionPath
prefix (spec §7c, §6b).

The deployment declares a variable-depth ``partition_hierarchy`` (e.g.
``("org", "product_line", "product")``). A query scope names values for a
*contiguous prefix* of that hierarchy: a full scope targets one leaf partition,
a shorter prefix targets the whole sub-tree beneath it. The resolved
:class:`~citenexus.domain.partition.PartitionPath` is then matched against the
caller-supplied ``allowed_partitions`` set by the pre-filter (see
``prefilter.py``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from citenexus.domain.partition import PartitionPath


def resolve_scope(scope: Mapping[str, str], hierarchy: Sequence[str]) -> PartitionPath:
    """Resolve ``scope`` against the ordered ``hierarchy`` into a prefix path.

    Walks ``hierarchy`` in order and consumes the contiguous run of levels
    present in ``scope``. A prefix may not skip a level: if a level is absent,
    no deeper level may be present (a gap raises). Any scope key outside the
    hierarchy raises. An empty scope resolves to the depth-0 root prefix.
    """
    unknown = set(scope) - set(hierarchy)
    if unknown:
        raise ValueError(
            f"scope keys not in partition hierarchy: {sorted(unknown)} "
            f"(hierarchy={list(hierarchy)})"
        )

    pairs: list[tuple[str, str]] = []
    gap_seen = False
    for level in hierarchy:
        if level in scope:
            if gap_seen:
                raise ValueError(
                    f"scope has a gap before level {level!r}: a partition prefix "
                    f"must be contiguous from the root (hierarchy={list(hierarchy)})"
                )
            pairs.append((level, scope[level]))
        else:
            gap_seen = True

    return PartitionPath.of(*pairs)
