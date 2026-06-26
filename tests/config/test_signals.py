"""Signal enum + capability gate (spec §15)."""

import pytest

from trustrag.config.signals import (
    SLOW_PATH_SIGNALS,
    Signal,
    all_signals,
    ask_queries,
    ingest_builds,
    requires_slow_path,
    resolve_signals,
)


def test_enum_membership_is_exactly_six() -> None:
    assert {s.value for s in Signal} == {
        "embedding",
        "text",
        "graph",
        "community",
        "structure",
        "wiki",
    }
    assert len(Signal) == 6


def test_unknown_signal_name_is_rejected() -> None:
    with pytest.raises(ValueError):
        Signal("telepathy")


def test_default_resolves_to_all_six() -> None:
    assert resolve_signals(None) == all_signals()
    assert resolve_signals(None) == set(Signal)


def test_embedding_text_gates_out_slow_path_for_both_phases() -> None:
    declared = ["embedding", "text"]
    for gated in (Signal.graph, Signal.community, Signal.wiki):
        assert ingest_builds(gated, declared) is False
        assert ask_queries(gated, declared) is False
    for kept in (Signal.embedding, Signal.text):
        assert ingest_builds(kept, declared) is True
        assert ask_queries(kept, declared) is True


def test_requires_slow_path_only_when_slow_signal_declared() -> None:
    assert requires_slow_path(["embedding", "text", "structure"]) is False
    assert requires_slow_path(["embedding", "graph"]) is True
    assert requires_slow_path(None) is True  # default = all six includes slow signals


def test_slow_path_signal_set() -> None:
    assert set(SLOW_PATH_SIGNALS) == {Signal.graph, Signal.community, Signal.wiki}
