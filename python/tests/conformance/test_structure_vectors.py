"""conformance/cases/structure.json asserted as a BINDING contract (§7b)."""

from __future__ import annotations

from typing import Any

import pytest

from citenexus.evidence.structure import build_structure
from citenexus.extract.types import (
    BlockKind,
    ExtractedBlock,
    ExtractedDoc,
    SourceType,
    StructureType,
)

from .fixtures import load_case

CASES: list[dict[str, Any]] = load_case("structure.json")["cases"]

EXPECTED_COUNT = 11


def test_vector_count() -> None:
    assert len(CASES) == EXPECTED_COUNT


def test_the_no_structure_case_is_present() -> None:
    """"No structure → empty, not failure" is the invariant; it needs a vector."""
    assert "none" in {c["structure_type"] for c in CASES}


@pytest.mark.parametrize("case", [pytest.param(c, id=c["name"]) for c in CASES])
def test_structure_vector(case: dict[str, Any]) -> None:
    doc = ExtractedDoc(
        document_id=case["document_id"],
        source_type=SourceType.plain,
        structure_type=StructureType(case["structure_type"]),
        blocks=tuple(
            ExtractedBlock(
                order=b["order"], kind=BlockKind(b["kind"]), text=b["text"], level=b["level"]
            )
            for b in case["blocks"]
        ),
    )
    assert build_structure(doc).model_dump(mode="json") == case["expected"], case["name"]
