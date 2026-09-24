"""The Python binding of the PDF model contract (ADR-0017; docs/pdf-model-contract.md).

`citenexus.core` loads the Rust cdylib and exposes pdf_units / pdf_prepare /
pdf_assemble / ooxml_units. The host fulfils requests itself; nothing here calls
a model. The committed synthetic fixture must reproduce the Rust golden byte for
byte, as the Go binding does (ADR-0017 decision 11).

Skips when the core is not built with the ``pdf`` feature or libpdfium is not
loadable (set ``PDFIUM_DYNAMIC_LIB_PATH``):

    cd rust && cargo build --release --features pdf
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from citenexus import core

_DATA = Path(__file__).resolve().parents[3] / "rust" / "tests" / "data"
_PDF = _DATA / "pdf"
_OPTS = core.PdfOptions(language="nl", model_tables=True)


@pytest.fixture(scope="module")
def pdf_bytes() -> bytes:
    data = (_PDF / "assemble-mixed.pdf").read_bytes()
    try:
        core.pdf_units(data, core.PdfOptions(language="nl"))
    except core.CoreUnavailableError as err:
        pytest.skip(f"citenexus-core unavailable: {err}")
    except core.CoreError as err:
        if "pdf" in str(err) or "libpdfium" in str(err):
            pytest.skip(f"SKIP: {err} (build with --features pdf, set PDFIUM_DYNAMIC_LIB_PATH)")
        raise
    return data


def test_assemble_reproduces_the_rust_golden_byte_for_byte(pdf_bytes: bytes) -> None:
    responses = (_PDF / "assemble-mixed.responses.json").read_text(encoding="utf-8")
    golden = (_PDF / "assemble-mixed.golden.json").read_text(encoding="utf-8")
    assert core.pdf_assemble_json(pdf_bytes, responses, _OPTS) == golden


def test_prepare_fulfil_assemble_typed_loop(pdf_bytes: bytes) -> None:
    prep = core.pdf_prepare(pdf_bytes, _OPTS)
    assert [r.id for r in prep.requests] == [
        "p1:table0",
        "p2:page:v1",
        "p2:page:v2",
        "p3:img0:v1",
        "p3:img0:v2",
    ]
    table_req = prep.requests[0]
    assert table_req.kind == "table_structure"
    assert table_req.variant is None
    assert all(w.id.startswith("p1w") for w in table_req.words)
    assert [r.variant for r in prep.requests[1:3]] == [1, 2]

    # The host fulfils each request (here: the committed answers, re-typed).
    answers = [
        core.PdfResponse.model_validate(r)
        for r in json.loads((_PDF / "assemble-mixed.responses.json").read_text(encoding="utf-8"))
    ]
    out = core.pdf_assemble(pdf_bytes, answers, _OPTS)
    assert out.document.responses_applied == 5
    tables = [u for u in out.units if u.kind == "table"]
    assert len(tables) == 1
    assert tables[0].provenance.table_source == "ruled"
    assert tables[0].provenance.table_uncertain is False
    scan = [u for u in out.units if u.page == 2 and u.provenance.vision_transcribed]
    assert len(scan) == 1 and scan[0].provenance.vision_disputed
    citable = core.citable_text(scan[0].markdown)
    assert "Diner 1.250,00 vooraf betaald" in citable
    assert "geen" not in citable  # the moved "geen" is disputed, not content


def test_units_is_assemble_without_responses(pdf_bytes: bytes) -> None:
    assert core.pdf_assemble_json(pdf_bytes, "[]", _OPTS) == core.pdf_units_json(pdf_bytes, _OPTS)


def test_errors_surface_as_core_error(pdf_bytes: bytes) -> None:
    with pytest.raises(core.CoreError):
        core.pdf_units(b"not a pdf", core.PdfOptions())


def test_ooxml_units_typed() -> None:
    data = (_DATA / "ooxml" / "sample.docx").read_bytes()
    try:
        units = core.ooxml_units(data, "docx")
    except core.CoreUnavailableError as err:
        pytest.skip(f"citenexus-core unavailable: {err}")
    kinds = [(u.kind, u.markdown) for u in units]
    assert kinds[0] == ("heading", "# Vergoedingen")
    table = [u for u in units if u.kind == "table"]
    assert table and "| Reiskosten | 7.000,00 |" in table[0].markdown
    assert table[0].provenance.route == "ooxml"


def test_citable_text_strips_disputed_and_descriptions() -> None:
    md = (
        "Diner 1.250,00 vooraf betaald.\n<!-- vision_disputed\nv1: Hotel 5.100,00 per jaar.\n"
        "v2: Hotel 5.100,00 geen per jaar.\n-->\nArtikel I.3."
    )
    assert core.citable_text(md) == "Diner 1.250,00 vooraf betaald.\nArtikel I.3."
    assert core.citable_text("<!-- image_description\nEen logo\n-->") == ""
