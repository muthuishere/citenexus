"""Universal extraction: any input → an ``ExtractedDoc`` (shared types here)."""

from citenexus.extract.markdown import to_markdown
from citenexus.extract.types import (
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
    "to_markdown",
]
