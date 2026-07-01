"""Rebuild planner — the §4c rebuild matrix as behaviour (spec §4c).

Each matrix row is one parametrized case asserting BOTH what rebuilds and what
stays untouched. Rebuild scope is modelled at *layer* granularity; per-document
scoping (e.g. "graph of unaffected docs") is a worker concern, not the pure
planner, so untouched is asserted only on layers the planner can distinguish.
"""

from __future__ import annotations

import pytest

from trustrag.provenance import (
    Layer,
    ModelManifest,
    ProducedBy,
    StageStamp,
    plan,
    plan_all,
)

ALL_LAYERS: frozenset[Layer] = frozenset(Layer)


def _baseline_stamp() -> ProducedBy:
    return ProducedBy(
        artifact_version=1,
        extractor=StageStamp(plugin="pdfplumber", plugin_version="1.0"),
        chunker=StageStamp(plugin="recursive", plugin_version="1.0"),
        vision=StageStamp(plugin="qwen-vl", plugin_version="1.0", endpoint_model="qwen2-vl"),
        embedding=StageStamp(
            plugin="bge-m3", plugin_version="1.0", endpoint_model="bge-m3", dim=1024
        ),
        graph_extractor=StageStamp(plugin="llm-graph", plugin_version="1.0"),
    )


def _manifest(
    stamp: ProducedBy,
    *,
    extractor: StageStamp | None = None,
    chunker: StageStamp | None = None,
    vision: StageStamp | None = None,
    embedding: StageStamp | None = None,
    graph_extractor: StageStamp | None = None,
    reranker: StageStamp | None = None,
    llm: StageStamp | None = None,
) -> ModelManifest:
    """A manifest that matches ``stamp`` except for the overridden stage(s)."""
    return ModelManifest(
        extractor=extractor or stamp.extractor,
        chunker=chunker or stamp.chunker,
        vision=vision or stamp.vision,
        embedding=embedding or stamp.embedding,
        graph_extractor=graph_extractor or stamp.graph_extractor,
        reranker=reranker,
        llm=llm,
    )


_STAMP = _baseline_stamp()

# (id, current manifest, layers that MUST rebuild, layers that MUST stay untouched)
_MATRIX: list[tuple[str, ModelManifest, set[Layer], set[Layer]]] = [
    (
        "embedding-swap",
        _manifest(
            _STAMP,
            embedding=StageStamp(
                plugin="bge-m3", plugin_version="2.0", endpoint_model="bge-m3", dim=1024
            ),
        ),
        {Layer.embedding},
        set(ALL_LAYERS) - {Layer.embedding},
    ),
    (
        "vision-swap",
        _manifest(
            _STAMP,
            vision=StageStamp(plugin="florence", plugin_version="1.0", endpoint_model="florence-2"),
        ),
        {Layer.vision, Layer.eu_chunk, Layer.embedding},
        {Layer.extract, Layer.ocr},
    ),
    (
        "chunker-swap",
        _manifest(_STAMP, chunker=StageStamp(plugin="semantic", plugin_version="1.0")),
        {Layer.eu_chunk, Layer.embedding, Layer.structure, Layer.graph, Layer.community_summary},
        {Layer.extract, Layer.ocr, Layer.vision},
    ),
    (
        "graph-extractor-swap",
        _manifest(_STAMP, graph_extractor=StageStamp(plugin="graphrag", plugin_version="1.0")),
        {Layer.graph, Layer.community_summary},
        {Layer.extract, Layer.ocr, Layer.vision, Layer.eu_chunk, Layer.embedding, Layer.structure},
    ),
    (
        "reranker-swap",
        _manifest(_STAMP, reranker=StageStamp(plugin="bge-reranker", plugin_version="2.0")),
        set(),
        set(ALL_LAYERS),
    ),
    (
        "llm-swap",
        _manifest(
            _STAMP, llm=StageStamp(plugin="qwen2.5", plugin_version="2.0", endpoint_model="qwen2.5")
        ),
        set(),
        set(ALL_LAYERS),
    ),
    (
        "identical",
        _manifest(_STAMP),
        set(),
        set(ALL_LAYERS),
    ),
]


@pytest.mark.parametrize(
    ("current", "rebuilt", "untouched"),
    [pytest.param(c, r, u, id=name) for name, c, r, u in _MATRIX],
)
def test_rebuild_matrix(current: ModelManifest, rebuilt: set[Layer], untouched: set[Layer]) -> None:
    result = plan(current, _STAMP)
    assert rebuilt <= result, f"missing expected rebuild layers: {rebuilt - result}"
    assert result & untouched == set(), f"unexpectedly rebuilt: {result & untouched}"


def test_identical_yields_empty() -> None:
    """Idempotent: current set identical to the stamp ⇒ no rebuild."""
    assert plan(_manifest(_STAMP), _STAMP) == set()


def test_upstream_change_marks_all_downstream_and_no_upstream() -> None:
    """DAG property: an upstream stage change closes over every downstream layer
    and never marks an upstream layer."""
    current = _manifest(_STAMP, chunker=StageStamp(plugin="semantic", plugin_version="1.0"))
    result = plan(current, _STAMP)
    assert result == {
        Layer.eu_chunk,
        Layer.embedding,
        Layer.structure,
        Layer.graph,
        Layer.community_summary,
    }
    assert Layer.extract not in result
    assert Layer.ocr not in result
    assert Layer.vision not in result


def test_plan_all_unions_over_stamps() -> None:
    """A set of stamps ⇒ the union of each stamp's rebuild set."""
    embed_current = _manifest(
        _STAMP,
        embedding=StageStamp(
            plugin="bge-m3", plugin_version="2.0", endpoint_model="bge-m3", dim=1024
        ),
    )
    other = ProducedBy(
        artifact_version=1,
        extractor=StageStamp(plugin="pdfplumber", plugin_version="1.0"),
        embedding=StageStamp(
            plugin="bge-m3", plugin_version="1.0", endpoint_model="bge-m3", dim=1024
        ),
    )
    assert plan_all(embed_current, [_STAMP, other]) == (
        plan(embed_current, _STAMP) | plan(embed_current, other)
    )


def test_plan_all_empty_iterable_is_empty() -> None:
    assert plan_all(_manifest(_STAMP), []) == set()
