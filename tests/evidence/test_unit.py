"""EvidenceUnit, Citation, EUType (spec §7, §7c)."""

import pytest
from pydantic import ValidationError

from trustrag.domain.partition import PartitionPath
from trustrag.evidence.unit import Citation, EUType, EvidenceUnit


def _partition() -> PartitionPath:
    return PartitionPath.of(
        ("org", "acme"), ("product_line", "contracts"), ("product", "nda-review")
    )


def _citation() -> Citation:
    return Citation(
        page=12,
        bbox=(120, 300, 510, 380),
        passage="The employee shall not disclose confidential information...",
    )


def test_minimal_evidence_unit_constructs() -> None:
    eu = EvidenceUnit(
        eu_id="eu_001",
        document_id="nda_2026",
        type=EUType.paragraph,
        language="en",
        text="The employee shall not disclose...",
        partition=_partition(),
        citation=_citation(),
    )
    assert eu.dense_vector is None
    assert eu.sparse_vector is None
    assert eu.entities == ()


def test_missing_required_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        EvidenceUnit(  # type: ignore[call-arg]
            eu_id="eu_001",
            document_id="nda_2026",
            type=EUType.paragraph,
            language="en",
            partition=_partition(),
            citation=_citation(),
        )


def test_unknown_eu_type_rejected() -> None:
    with pytest.raises(ValidationError):
        EvidenceUnit(
            eu_id="x",
            document_id="d",
            type="footnote",
            language="en",
            text="t",
            partition=_partition(),
            citation=_citation(),
        )


def test_known_eu_type_accepted() -> None:
    eu = EvidenceUnit(
        eu_id="x",
        document_id="d",
        type=EUType.community_summary,
        language="en",
        text="t",
        partition=_partition(),
        citation=_citation(),
    )
    assert eu.type is EUType.community_summary


def test_citation_with_bbox_has_length_four() -> None:
    c = Citation(page=12, bbox=(120, 300, 510, 380), passage="p")
    assert c.bbox is not None
    assert len(c.bbox) == 4


def test_malformed_bbox_rejected() -> None:
    with pytest.raises(ValidationError):
        Citation(page=1, bbox=(1, 2, 3), passage="p")


def test_acl_stored_verbatim_and_round_trips() -> None:
    acl = {"roles": ["partner"], "matter": "m7"}
    eu = EvidenceUnit(
        eu_id="x",
        document_id="d",
        type=EUType.paragraph,
        language="en",
        text="t",
        partition=_partition(),
        citation=_citation(),
        acl=acl,
    )
    assert eu.acl == acl
    back = EvidenceUnit.model_validate_json(eu.model_dump_json())
    assert back.acl == acl


def test_acl_defaults_to_none() -> None:
    eu = EvidenceUnit(
        eu_id="x",
        document_id="d",
        type=EUType.paragraph,
        language="en",
        text="t",
        partition=_partition(),
        citation=_citation(),
    )
    assert eu.acl is None


def test_evidence_unit_json_round_trip() -> None:
    eu = EvidenceUnit(
        eu_id="x",
        document_id="d",
        type=EUType.paragraph,
        language="en",
        text="t",
        partition=_partition(),
        citation=_citation(),
        acl={"k": "v"},
        structure_path=("Agreement", "5. Confidentiality", "5.2"),
    )
    assert EvidenceUnit.model_validate_json(eu.model_dump_json()) == eu
