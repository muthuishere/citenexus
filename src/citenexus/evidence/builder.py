"""Evidence-builder — turn extracted blocks into Evidence Units (spec §7).

Each ``ExtractedBlock`` from an extractor becomes exactly one ``EvidenceUnit``:
the atomic, bbox-cited, retrievable object the rest of CiteNexus is built on. The
mapping is pure and deterministic — same document in, same units out — so the
ingest pipeline can hash, cache, and partially rebuild it (§4c). The builder
carries (never enforces) the partition and opaque ``acl`` (§7c) and stamps the
caller-detected language (§11a) onto every unit.
"""

from __future__ import annotations

from typing import Any

from citenexus.domain.partition import PartitionPath
from citenexus.evidence.unit import Citation, EUType, EvidenceUnit
from citenexus.extract.types import BlockKind, ExtractedBlock, ExtractedDoc

# Closed BlockKind → EUType mapping (§7). A slide is a page-level summary unit; a
# thread turn reads as a paragraph; OCR text keeps its own provenance-bearing type.
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


def _build_unit(
    block: ExtractedBlock,
    *,
    doc: ExtractedDoc,
    partition: PartitionPath,
    language: str,
    acl: Any,
) -> EvidenceUnit:
    return EvidenceUnit(
        eu_id=f"{doc.document_id}::{block.order}",
        partition=partition,
        document_id=doc.document_id,
        type=_KIND_TO_TYPE[block.kind],
        language=language,
        text=block.text,
        citation=Citation(passage=block.text, page=block.page, bbox=block.bbox),
        page=block.page,
        source_uri=doc.source_uri,
        structure_path=block.structure_path,
        acl=acl,
    )


def build_evidence_units(
    doc: ExtractedDoc,
    *,
    partition: PartitionPath,
    language: str,
    acl: Any = None,
) -> list[EvidenceUnit]:
    """Map each non-empty block of ``doc`` to one Evidence Unit, in document order.

    ``eu_id`` is ``f"{document_id}::{order}"``; the ``BlockKind`` is mapped to its
    ``EUType``; the verbatim block text becomes both the unit text and its
    ``Citation.passage`` (with the block's page + bbox). The block's
    ``structure_path`` is carried through, the caller-detected ``language`` is
    stamped, and the ``partition`` plus opaque ``acl`` are carried verbatim
    (never parsed). Blocks whose text is empty or whitespace-only are skipped.
    """
    return [
        _build_unit(block, doc=doc, partition=partition, language=language, acl=acl)
        for block in doc.blocks
        if block.text.strip()
    ]
