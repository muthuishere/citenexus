"""PartitionPath — a variable-depth physical partition key (spec §6b).

A partition is an ordered list of named ``(level, value)`` pairs of *any* depth.
The library never assumes a fixed number of levels or fixed level names — the
hierarchy is data. Any prefix of a path addresses a sub-tree, which is how query
scopes and the deferred-RBAC pre-filter (§7c) select partitions.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class PartitionLevel(BaseModel):
    """A single ``(level, value)`` pair, e.g. ``(org, acme)``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    level: str
    value: str


class PartitionPath(BaseModel):
    """An ordered, variable-depth sequence of partition levels."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    levels: tuple[PartitionLevel, ...]

    @classmethod
    def of(cls, *pairs: tuple[str, str]) -> PartitionPath:
        """Build a path from ``(level, value)`` tuples, in order."""
        return cls(levels=tuple(PartitionLevel(level=lvl, value=val) for lvl, val in pairs))

    @property
    def depth(self) -> int:
        return len(self.levels)

    def as_pairs(self) -> tuple[tuple[str, str], ...]:
        """The path as plain ``(level, value)`` tuples — a stable, neutral view."""
        return tuple((lvl.level, lvl.value) for lvl in self.levels)

    def is_prefix_of(self, other: PartitionPath) -> bool:
        """True iff this path is an ancestor of (or equal to) ``other``."""
        if self.depth > other.depth:
            return False
        return other.levels[: self.depth] == self.levels
