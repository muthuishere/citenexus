"""Shared extraction types — the interface between extractors and the rest of L3.

Every extractor (pdf/docx/pptx/html/md/txt/csv/image/plain) returns an
``ExtractedDoc`` of ordered ``ExtractedBlock``s plus any ``ImageRef``s. The
evidence-builder turns blocks into Evidence Units, the structure-index reads the
heading/sequence/schema, and conditional-vision decides what to do with images —
all against these types, so the pieces compose without knowing each other.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from citenexus.evidence.unit import BBox


class SourceType(StrEnum):
    """The input format an extractor handled."""

    pdf = "pdf"
    docx = "docx"
    pptx = "pptx"
    html = "html"
    md = "md"
    txt = "txt"
    csv = "csv"
    image = "image"
    plain = "plain"


class StructureType(StrEnum):
    """What a document's structure *is* — polymorphic, best-effort (§7b)."""

    heading_tree = "heading_tree"
    code_ast = "code_ast"
    slide_sequence = "slide_sequence"
    table_schema = "table_schema"
    thread_order = "thread_order"
    page_layout = "page_layout"
    none = "none"


class BlockKind(StrEnum):
    """The role of a block within a document."""

    heading = "heading"
    paragraph = "paragraph"
    table = "table"
    code = "code"
    image = "image"
    slide = "slide"
    thread_turn = "thread_turn"
    ocr_block = "ocr_block"


class ImageRef(BaseModel):
    """A meaningful image asset — a candidate for conditional vision (§9)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    image_id: str
    page: int | None = None
    bbox: BBox | None = None
    width: int | None = None
    height: int | None = None
    # Where the bytes live (a backend key) or None if not persisted yet.
    blob_key: str | None = None


class ExtractedBlock(BaseModel):
    """One ordered unit of extracted content."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    order: int
    kind: BlockKind
    text: str
    page: int | None = None
    bbox: BBox | None = None
    # Heading depth / slide index / table row — meaning depends on structure_type.
    level: int | None = None
    # Path of ancestor headings/sections, if known (feeds EvidenceUnit.structure_path).
    structure_path: tuple[str, ...] = ()


class ExtractedDoc(BaseModel):
    """The parsed form of one source document."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    document_id: str
    source_type: SourceType
    structure_type: StructureType = StructureType.none
    source_uri: str | None = None
    blocks: tuple[ExtractedBlock, ...] = ()
    images: tuple[ImageRef, ...] = ()
    # Transient: raw bytes for images in `images`, keyed by `ImageRef.image_id`.
    # Not persisted itself — the ingest pipeline reads this once to store each
    # image via StorageBackend.put_bytes and stamp `ImageRef.blob_key`. Kept off
    # the frozen `ImageRef` model to avoid copying large blobs on every access.
    image_bytes: dict[str, bytes] = Field(default_factory=dict)
