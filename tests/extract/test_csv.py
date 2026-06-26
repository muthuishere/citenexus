"""CsvExtractor — header → table_schema, rows → table blocks (§8)."""

from __future__ import annotations

from trustrag.extract.csv import CsvExtractor
from trustrag.extract.types import BlockKind, SourceType, StructureType


def test_header_schema_and_row_blocks() -> None:
    doc = CsvExtractor().extract("name,age\nalice,30\nbob,25\n")
    assert doc.source_type is SourceType.csv
    assert doc.structure_type is StructureType.table_schema
    assert [b.kind for b in doc.blocks] == [BlockKind.table, BlockKind.table]
    assert [b.order for b in doc.blocks] == [0, 1]
    first = doc.blocks[0]
    assert first.structure_path == ("name", "age")
    assert first.level == 0
    assert "alice" in first.text
    assert "30" in first.text


def test_empty_csv_has_no_structure() -> None:
    doc = CsvExtractor().extract("")
    assert doc.structure_type is StructureType.none
    assert doc.blocks == ()
