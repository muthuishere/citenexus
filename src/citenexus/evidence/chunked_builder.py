"""Chunk-based, optionally-contextualized evidence building (spec §7).

The default builder maps one block → one EU, which for a page-level PDF block
means a citation points at a whole page. This builder refines that: an oversized
block is split by the recursive chunker into several **child** EUs so citations
land at clause/paragraph granularity — the precision legal/medical needs.

Two enhancements layer on, both preserving provenance:

- **Contextual retrieval** (optional): a small model situates each child chunk;
  the prefix goes into the EU's ``text`` (what is embedded/indexed), while the
  ``citation.passage`` stays the VERBATIM chunk. The model's words aid retrieval
  but are never cited.
- **Parent-child identity**: a child's ``eu_id`` is ``{document_id}::{order}::{i}``
  so it never collides with a whole-block EU and its parent block is recoverable.

Small blocks (within ``max_tokens``) pass through unchanged as a single EU.
"""

from __future__ import annotations

from typing import Any, Protocol

from citenexus.domain.partition import PartitionPath
from citenexus.evidence.chunker import chunk_text
from citenexus.evidence.unit import Citation, EUType, EvidenceUnit
from citenexus.extract.types import BlockKind, ExtractedDoc

_KIND_TO_TYPE: dict[BlockKind, EUType] = {
    BlockKind.paragraph: EUType.paragraph,
    BlockKind.heading: EUType.section,
    BlockKind.table: EUType.table,
    BlockKind.code: EUType.code_block,
    BlockKind.image: EUType.image,
    BlockKind.slide: EUType.page_summary,
    BlockKind.thread_turn: EUType.paragraph,
    BlockKind.ocr_block: EUType.ocr_block,
}


class Contextualizer(Protocol):
    """The small-model context seam (satisfied by evidence.contextualize)."""

    def contextualize(self, *, chunk: str, document: str) -> str: ...


def build_chunked_units(
    doc: ExtractedDoc,
    *,
    partition: PartitionPath,
    language: str,
    acl: Any = None,
    max_tokens: int = 450,
    overlap: int = 60,
    contextualizer: Contextualizer | None = None,
) -> list[EvidenceUnit]:
    """Chunk each block into child EUs; verbatim citation, optional context prefix."""
    document_text = "\n\n".join(block.text for block in doc.blocks if block.text.strip())
    units: list[EvidenceUnit] = []
    for block in doc.blocks:
        if not block.text.strip():
            continue
        chunks = chunk_text(block.text, max_tokens=max_tokens, overlap=overlap)
        for index, chunk in enumerate(chunks):
            indexed_text = chunk
            if contextualizer is not None:
                indexed_text = contextualizer.contextualize(chunk=chunk, document=document_text)
            units.append(
                EvidenceUnit(
                    eu_id=f"{doc.document_id}::{block.order}::{index}",
                    partition=partition,
                    document_id=doc.document_id,
                    type=_KIND_TO_TYPE[block.kind],
                    language=language,
                    # indexed/embedded text may carry the context prefix ...
                    text=indexed_text,
                    # ... but the citation passage is ALWAYS the verbatim chunk.
                    citation=Citation(passage=chunk, page=block.page, bbox=block.bbox),
                    page=block.page,
                    source_uri=doc.source_uri,
                    structure_path=block.structure_path,
                    acl=acl,
                )
            )
    return units
