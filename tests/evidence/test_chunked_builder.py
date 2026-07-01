"""Chunk-based evidence building — parent-child EUs + contextual prefix (§7).

Combines the recursive chunker and the contextualizer into the evidence builder:
an oversized block becomes several child EUs (precise citations), each optionally
carrying a small-model context prefix in its *indexed text* while the *citation
passage stays verbatim*. Small blocks pass through as a single EU (parent).
"""

from __future__ import annotations

from trustrag.domain.partition import PartitionPath
from trustrag.evidence.chunked_builder import build_chunked_units
from trustrag.extract.types import BlockKind, ExtractedBlock, ExtractedDoc, SourceType


def _doc(text: str, *, page: int = 1) -> ExtractedDoc:
    return ExtractedDoc(
        document_id="doc",
        source_type=SourceType.txt,
        source_uri="raw/doc.txt",
        blocks=(ExtractedBlock(order=0, kind=BlockKind.paragraph, text=text, page=page),),
    )


def _part() -> PartitionPath:
    return PartitionPath.of(("org", "acme"))


def test_small_block_is_single_unit_verbatim() -> None:
    doc = _doc("A short clause about disclosure.")
    units = build_chunked_units(doc, partition=_part(), language="en", max_tokens=50, overlap=5)
    assert len(units) == 1
    assert units[0].text == "A short clause about disclosure."
    assert units[0].citation.passage == "A short clause about disclosure."


def test_large_block_splits_into_child_units() -> None:
    big = " ".join(f"word{i}" for i in range(400))
    units = build_chunked_units(
        _doc(big), partition=_part(), language="en", max_tokens=100, overlap=10
    )
    assert len(units) > 1
    # child eu_ids are namespaced and ordered
    assert units[0].eu_id == "doc::0::0"
    assert units[1].eu_id == "doc::0::1"
    # every child keeps the parent block's page for citation
    assert all(u.page == 1 for u in units)


def test_citation_stays_verbatim_even_with_context_prefix() -> None:
    class FakeContextualizer:
        def contextualize(self, *, chunk: str, document: str) -> str:
            return f"CONTEXT: from doc.\n{chunk}"

    big = " ".join(f"word{i}" for i in range(400))
    units = build_chunked_units(
        _doc(big),
        partition=_part(),
        language="en",
        max_tokens=100,
        overlap=10,
        contextualizer=FakeContextualizer(),
    )
    first = units[0]
    # indexed text carries the context prefix ...
    assert first.text.startswith("CONTEXT: from doc.")
    # ... but the CITATION passage is the verbatim chunk, no context leaked in
    assert "CONTEXT:" not in first.citation.passage
    # the citation passage is exactly the chunk that was indexed (context stripped)
    assert first.text.endswith(first.citation.passage)
    assert first.citation.passage.split()[0] == "word0"


def test_no_contextualizer_indexes_bare_chunk() -> None:
    big = " ".join(f"word{i}" for i in range(300))
    units = build_chunked_units(
        _doc(big), partition=_part(), language="en", max_tokens=100, overlap=10
    )
    # text == citation passage when no contextualizer is configured
    assert units[0].text == units[0].citation.passage
