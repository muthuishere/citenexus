"""conformance/cases/eu_ids.json asserted as a BINDING contract.

The eu_id is the citation handle: if two ports mint different ids for the same
document, a citation that resolves in one resolves to nothing in the other.
Go pins it (``golang/euid/euid_test.go:29``), JS pins it
(``js/src/euid/euid.test.ts:30``).
"""

from __future__ import annotations

import hashlib
from typing import Any

import pytest

from citenexus.domain.partition import PartitionPath
from citenexus.evidence.builder import build_evidence_units
from citenexus.evidence.chunked_builder import build_chunked_units
from citenexus.extract.types import BlockKind, ExtractedBlock, ExtractedDoc, SourceType

from .fixtures import load_case

FIXTURE: dict[str, Any] = load_case("eu_ids.json")
CASES: list[dict[str, Any]] = FIXTURE["cases"]

EXPECTED_COUNT = 2

_PARTITION = PartitionPath.of(("workspace", "default"))


def test_vector_count() -> None:
    assert len(CASES) == EXPECTED_COUNT


def _doc(spec: dict[str, Any]) -> ExtractedDoc:
    return ExtractedDoc(
        document_id=spec["document_id"],
        source_type=SourceType.plain,
        blocks=tuple(
            ExtractedBlock(
                order=b["order"], kind=BlockKind(b["kind"]), text=b["text"], page=b["page"]
            )
            for b in spec["blocks"]
        ),
    )


@pytest.mark.parametrize("case", [pytest.param(c, id=c["name"]) for c in CASES])
def test_block_builder_eu_ids(case: dict[str, Any]) -> None:
    units = build_evidence_units(_doc(case), partition=_PARTITION, language="en")
    assert [u.eu_id for u in units] == case["block_builder_eu_ids"], case["name"]


@pytest.mark.parametrize("case", [pytest.param(c, id=c["name"]) for c in CASES])
def test_chunked_builder_eu_ids(case: dict[str, Any]) -> None:
    units = build_chunked_units(
        _doc(case),
        partition=_PARTITION,
        language="en",
        max_tokens=case["chunk_max_tokens"],
        overlap=case["chunk_overlap"],
    )
    assert [u.eu_id for u in units] == case["chunked_builder_eu_ids"], case["name"]


def test_checksum_example() -> None:
    """Content addressing is sha256 over the raw UTF-8 bytes, in every port."""
    example = FIXTURE["checksum_example"]
    digest = hashlib.sha256(example["raw_utf8"].encode("utf-8")).hexdigest()
    assert digest == example["sha256"]
    assert len(example["sha256"]) == 64
