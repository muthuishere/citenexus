"""Universal extraction: any input → an ``ExtractedDoc`` (shared types here)."""

from trustrag.extract.types import (
    BlockKind,
    ExtractedBlock,
    ExtractedDoc,
    ImageRef,
    SourceType,
    StructureType,
)

__all__ = [
    "BlockKind",
    "ExtractedBlock",
    "ExtractedDoc",
    "ImageRef",
    "SourceType",
    "StructureType",
]
