"""Signal — the six retrieval capabilities and the gate ingest/ask consult (§15).

The single most important client knob is which of the six retrieval signals a
deployment builds and queries. ``signals=[...]`` is declared once on the client and
honored in both phases: ingest builds only declared signals, ask queries only
declared signals. When ``signals`` is omitted the client behaves as though all six
were declared (the zero-config path builds and queries the full set).

This module is the single source of truth for the signal set *and* for the
phase/speed mapping, so neither the ingest pipeline nor the ask path ever
hard-codes "is this a slow-path signal?".
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum


class Signal(StrEnum):
    """The closed set of six retrieval signals (§10, §15)."""

    embedding = "embedding"
    text = "text"
    graph = "graph"
    community = "community"
    structure = "structure"
    wiki = "wiki"


# The slow-path signals: graph, graph-community, and wiki-navigation are the
# layers an ingest never pays for unless declared, and the only ones that make
# ``ask`` take the slow path.
SLOW_PATH_SIGNALS: frozenset[Signal] = frozenset({Signal.graph, Signal.community, Signal.wiki})


def all_signals() -> frozenset[Signal]:
    """Every member of :class:`Signal` — the default (omitted ``signals``) set."""
    return frozenset(Signal)


def resolve_signals(declared: Iterable[str | Signal] | None) -> frozenset[Signal]:
    """Resolve a declared signal list to a set; ``None`` means *all six*.

    Each entry is validated against :class:`Signal`; an unknown name raises
    ``ValueError`` naming the invalid signal.
    """
    if declared is None:
        return all_signals()
    return frozenset(Signal(s) for s in declared)


def ingest_builds(signal: str | Signal, declared: Iterable[str | Signal] | None) -> bool:
    """Does the ingest phase build ``signal`` for the given declaration?"""
    return Signal(signal) in resolve_signals(declared)


def ask_queries(signal: str | Signal, declared: Iterable[str | Signal] | None) -> bool:
    """Does the ask phase query ``signal`` for the given declaration?"""
    return Signal(signal) in resolve_signals(declared)


def requires_slow_path(declared: Iterable[str | Signal] | None) -> bool:
    """True iff any declared signal is a slow-path (graph/community/wiki) signal."""
    return bool(resolve_signals(declared) & SLOW_PATH_SIGNALS)
