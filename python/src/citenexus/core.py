"""Opt-in binding to the shared Rust engine (citenexus-core) for structured
document units: the PDF model contract and OOXML units (ADR-0017, ADR-0010
tier 3; the contract is ``docs/pdf-model-contract.md``).

- ``pdf_units`` — the no-model base extractor.
- ``pdf_prepare`` → the host fulfils ``requests`` with ITS OWN models →
  ``pdf_assemble`` applies every response that passes the core's checks.
  Nothing in this module ever calls a model or the network.
- ``ooxml_units`` — DOCX/PPTX headings, lists, tables from OOXML structure.
- ``citable_text`` — the only text a host may cite: disputed vision text and
  image descriptions removed.

The core is loaded with ``ctypes`` on first use, from ``CITENEXUS_CORE_LIB``
(a path to the cdylib), else a development checkout's ``rust/target/{release,
debug}``. PDF calls need the core built with ``--features pdf`` and libpdfium
loadable (``PDFIUM_DYNAMIC_LIB_PATH``). One C ABI, shared with the Go and JS
bindings: the same bytes in give the same JSON out.

This is separate from the Python ``extract()`` PDF path, which is unchanged.
"""

from __future__ import annotations

import ctypes
import json
import os
import platform
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

__all__ = [
    "CoreError",
    "CoreUnavailableError",
    "DocUnit",
    "PdfCell",
    "PdfDocumentSignals",
    "PdfGrid",
    "PdfOptions",
    "PdfPageInfo",
    "PdfPrepared",
    "PdfRequest",
    "PdfResponse",
    "PdfSpannedCell",
    "PdfUnitsOutput",
    "PdfWord",
    "Provenance",
    "citable_text",
    "ooxml_units",
    "pdf_assemble",
    "pdf_assemble_json",
    "pdf_prepare",
    "pdf_prepare_json",
    "pdf_units",
    "pdf_units_json",
]


class CoreError(RuntimeError):
    """The core reported an error (``{"error": ...}``): not a PDF, no ``pdf``
    feature, libpdfium missing, bad input."""


class CoreUnavailableError(CoreError):
    """The citenexus-core library could not be found or loaded."""


# ---------------------------------------------------------------- types ----

# Frozen like the rest of the public models; `extra="ignore"` because the core
# APPENDS fields over time (ADR-0017: append-only, serde defaults), and an older
# Python binding must keep reading newer output.
_CFG = ConfigDict(frozen=True, extra="ignore")


class PdfOptions(BaseModel):
    model_config = _CFG
    language: str | None = None
    layout_text: bool = False
    model_tables: bool = False


class Provenance(BaseModel):
    model_config = _CFG
    route: str
    table_source: str | None = None
    vision_transcribed: bool = False
    table_uncertain: bool = False
    failed_check: str | None = None
    heading_source: str | None = None
    joined_hyphen: bool = False
    vision_disputed: bool = False
    header_flattened: bool = False
    model_verdict: str | None = None


class DocUnit(BaseModel):
    """One unit: kind is heading|paragraph|list|table|furniture|image|image_description;
    bbox is [x0, y0, x1, y1] in points, top-left origin."""

    model_config = _CFG
    page: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    kind: str
    level: int | None = None
    markdown: str
    provenance: Provenance


class PdfPageInfo(BaseModel):
    model_config = _CFG
    page: int
    width: float
    height: float
    route: str
    signals: dict[str, Any]
    layout_text: str | None = None


class PdfDocumentSignals(BaseModel):
    model_config = _CFG
    pages: int
    responses_applied: int = 0
    responses_rejected: int = 0
    heading_source: str | None = None
    hyphen_markers: int = 0
    furniture_units: int = 0


class PdfUnitsOutput(BaseModel):
    model_config = _CFG
    units: list[DocUnit]
    pages: list[PdfPageInfo]
    document: PdfDocumentSignals


class PdfWord(BaseModel):
    model_config = _CFG
    id: str
    text: str
    bbox: tuple[float, float, float, float]
    marker: bool = False


class PdfRequest(BaseModel):
    """kind: table_structure (answer with ``tables`` over ``words`` IDs) |
    vision_page | vision_region (answer with ``markdown``; issued twice,
    ``variant`` 1 and 2, see ``hint``)."""

    model_config = _CFG
    id: str
    page: int
    kind: Literal["table_structure", "vision_page", "vision_region"]
    prompt: str
    bbox: tuple[float, float, float, float]
    words: list[PdfWord] = []
    variant: int | None = None
    hint: str | None = None


class PdfPrepared(BaseModel):
    model_config = _CFG
    units: list[DocUnit]
    pages: list[PdfPageInfo]
    document: PdfDocumentSignals
    requests: list[PdfRequest]


class PdfSpannedCell(BaseModel):
    model_config = _CFG
    words: list[str]
    colspan: int | None = None
    rowspan: int | None = None


PdfCell = list[str] | PdfSpannedCell


class PdfGrid(BaseModel):
    model_config = _CFG
    rows: list[list[PdfCell]]


class PdfResponse(BaseModel):
    """The host's answer to one request. ``tables`` for table_structure
    (``[]`` = "no table here"), ``markdown`` for vision; ``mode`` is
    ``"description"`` when a vision_region has no text and is described."""

    model_config = _CFG
    request_id: str
    finish_reason: str | None = None
    tables: list[PdfGrid] | None = None
    markdown: str | None = None
    mode: Literal["transcription", "description"] | None = None


# --------------------------------------------------------------- loader ----

_LIB_NAME = {
    "Darwin": "libcitenexus_core.dylib",
    "Linux": "libcitenexus_core.so",
    "Windows": "citenexus_core.dll",
}.get(platform.system(), "libcitenexus_core.so")

_lib: ctypes.CDLL | None = None


def _library_path() -> Path:
    override = os.environ.get("CITENEXUS_CORE_LIB")
    if override:
        return Path(override)
    rust = Path(__file__).resolve().parents[3] / "rust" / "target"
    for profile in ("release", "debug"):
        candidate = rust / profile / _LIB_NAME
        if candidate.exists():
            return candidate
    raise CoreUnavailableError(
        f"{_LIB_NAME} not found: set CITENEXUS_CORE_LIB or build it "
        "(cd rust && cargo build --release --features pdf)"
    )


def _load() -> ctypes.CDLL:
    global _lib
    if _lib is not None:
        return _lib
    path = _library_path()
    try:
        lib = ctypes.CDLL(str(path))
    except OSError as err:
        raise CoreUnavailableError(f"could not load {path}: {err}") from err
    three = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p]
    for name, args in (
        ("citenexus_pdf_units", three),
        ("citenexus_pdf_prepare", three),
        ("citenexus_pdf_assemble", [*three, ctypes.c_char_p]),
        ("citenexus_ooxml_units", three),
    ):
        fn = getattr(lib, name)
        fn.restype = ctypes.c_void_p  # raw pointer: freed by citenexus_free_string
        fn.argtypes = args
    lib.citenexus_free_string.argtypes = [ctypes.c_void_p]
    lib.citenexus_free_string.restype = None
    _lib = lib
    return lib


def _take(lib: ctypes.CDLL, ptr: int | None) -> str:
    if not ptr:
        raise CoreError("citenexus-core returned a null string")
    try:
        raw = ctypes.string_at(ptr)
    finally:
        lib.citenexus_free_string(ptr)
    text = raw.decode("utf-8")
    if text.startswith('{"error"'):
        raise CoreError(str(json.loads(text).get("error", text)))
    return text


def _opts_json(options: PdfOptions | None) -> bytes:
    opts = options or PdfOptions()
    return opts.model_dump_json().encode("utf-8")


def _responses_json(responses: Sequence[PdfResponse] | str) -> bytes:
    if isinstance(responses, str):
        return responses.encode("utf-8")
    payload = [r.model_dump(mode="json", exclude_none=True) for r in responses]
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


# ------------------------------------------------------------------ API ----


def pdf_units_json(pdf: bytes, options: PdfOptions | None = None) -> str:
    """The base output (no model), as the core's JSON bytes, untouched."""
    lib = _load()
    return _take(lib, lib.citenexus_pdf_units(pdf, len(pdf), _opts_json(options)))


def pdf_prepare_json(pdf: bytes, options: PdfOptions | None = None) -> str:
    lib = _load()
    return _take(lib, lib.citenexus_pdf_prepare(pdf, len(pdf), _opts_json(options)))


def pdf_assemble_json(
    pdf: bytes,
    responses: Sequence[PdfResponse] | str,
    options: PdfOptions | None = None,
) -> str:
    """Apply ``responses`` (typed, or a JSON array string) and return the
    core's JSON untouched: byte-identical across Python, Go and JS."""
    lib = _load()
    return _take(
        lib,
        lib.citenexus_pdf_assemble(pdf, len(pdf), _opts_json(options), _responses_json(responses)),
    )


def pdf_units(pdf: bytes, options: PdfOptions | None = None) -> PdfUnitsOutput:
    """The base output: ``pdf_assemble`` with no responses."""
    return PdfUnitsOutput.model_validate_json(pdf_units_json(pdf, options))


def pdf_prepare(pdf: bytes, options: PdfOptions | None = None) -> PdfPrepared:
    """Phase one: the base output plus the requests the host may fulfil."""
    return PdfPrepared.model_validate_json(pdf_prepare_json(pdf, options))


def pdf_assemble(
    pdf: bytes,
    responses: Sequence[PdfResponse] | str,
    options: PdfOptions | None = None,
) -> PdfUnitsOutput:
    """Phase two: the PDF is re-parsed and every response that passes the
    checks is applied. A missing or failed response = base output (the latter
    with ``provenance.failed_check``)."""
    return PdfUnitsOutput.model_validate_json(pdf_assemble_json(pdf, responses, options))


def ooxml_units(data: bytes, source_type: Literal["docx", "pptx"]) -> list[DocUnit]:
    """DOCX/PPTX units from their own OOXML structure (no model)."""
    lib = _load()
    raw = _take(lib, lib.citenexus_ooxml_units(data, len(data), source_type.encode("utf-8")))
    return [DocUnit.model_validate(u) for u in json.loads(raw)]


_BLOCKS = ("<!-- vision_disputed", "<!-- image_description")


def citable_text(markdown: str) -> str:
    """``markdown`` with every ``<!-- vision_disputed … -->`` and
    ``<!-- image_description … -->`` block removed: the only text a host may
    cite or quote-match. Mirrors the core's ``vision::citable_text``."""
    out: list[str] = []
    rest = markdown
    while True:
        starts = [i for i in (rest.find(b) for b in _BLOCKS) if i >= 0]
        if not starts:
            out.append(rest)
            break
        start = min(starts)
        out.append(rest[:start])
        end = rest.find("-->", start)
        if end < 0:
            break
        rest = rest[end + 3 :]
    lines = [line.rstrip() for line in "".join(out).splitlines()]
    return "\n".join(line for line in lines if line.strip())
