"""CsvExtractor — header → table_schema, each data row → a table block (§8)."""

from __future__ import annotations

import csv as _csv
import io
from typing import Any

from trustrag.extract.plain import load_text
from trustrag.extract.types import (
    BlockKind,
    ExtractedBlock,
    ExtractedDoc,
    SourceType,
    StructureType,
)
from trustrag.plugins.base import ExtractorPlugin


class CsvExtractor(ExtractorPlugin):
    """The first row is the schema (carried on each block's ``structure_path``);
    every subsequent row becomes a table block rendered as ``col: value`` pairs."""

    plugin_version = "csv/1"

    def __init__(self, document_id: str | None = None) -> None:
        self.document_id = document_id

    def extract(self, source: Any) -> ExtractedDoc:
        text, doc_id, source_uri = load_text(source, self.document_id)
        rows = list(_csv.reader(io.StringIO(text)))

        blocks: list[ExtractedBlock] = []
        structure = StructureType.none
        if rows:
            header = tuple(rows[0])
            structure = StructureType.table_schema
            for row_index, row in enumerate(rows[1:]):
                rendered = ", ".join(f"{col}: {val}" for col, val in zip(header, row, strict=False))
                blocks.append(
                    ExtractedBlock(
                        order=row_index,
                        kind=BlockKind.table,
                        text=rendered,
                        level=row_index,
                        structure_path=header,
                    )
                )

        return ExtractedDoc(
            document_id=doc_id,
            source_type=SourceType.csv,
            structure_type=structure,
            source_uri=source_uri,
            blocks=tuple(blocks),
        )
