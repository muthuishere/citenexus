"""PdfExtractor — text per page with page numbers + word bboxes via pdfplumber (§8)."""

from __future__ import annotations

import io
from typing import Any, cast

import pdfplumber
from PIL import Image, UnidentifiedImageError

from citenexus.evidence.unit import BBox, DocumentMetadata
from citenexus.extract.plain import open_binary
from citenexus.extract.types import (
    BlockKind,
    ExtractedBlock,
    ExtractedDoc,
    ImageRef,
    SourceType,
    StructureType,
)
from citenexus.plugins.base import ExtractorPlugin

# --------------------------------------------------------------------------- #
# Tamil left-side vowel reordering repair.
#
# A PDF stores glyphs in VISUAL order. For Indic scripts with a *pre-base*
# (left-side) vowel sign the glyph is drawn to the LEFT of the consonant it
# logically follows, so text extraction returns the vowel sign BEFORE its
# consonant: ``வேண்டும்`` comes back as ``ேவண்டும்``.
#
# Nothing is lost at the character level — measured against the two real Tamil
# PDFs in ``examples/multilingual/corpus``, zero glyphs go missing — but the
# ORDER is wrong, and for this library that is a correctness bug rather than a
# cosmetic one: a citation must be verbatim, and a reordered passage neither
# matches its source nor survives the faithfulness gate against a correctly
# ordered claim, so a perfectly grounded answer abstains.
#
# The repair is deterministic, pure, and idempotent. A *single* misplaced sign
# is genuinely ambiguous in isolation — ``வ ை ர`` could be read as ``வை`` + ``ர``
# or as ``வ`` + ``ரை`` — so the decision is made once for the whole text, from a
# signature that cannot occur in correct Tamil: a left-side vowel sign that is
# not preceded by a consonant (word-initial, or after a space, virama, digit or
# punctuation) is illegal in logical order and only ever appears in visual order.
# One such position anywhere means the producer emitted the whole text visually,
# and every left-side sign in it is then reordered. Correctly ordered text
# contains no illegal position, so it passes through byte for byte — which also
# makes re-running the repair a no-op.
#
# Scope: Tamil only, on purpose. See ``_repair_left_vowel_order``.
_TAMIL_LEFT_VOWELS = frozenset("\u0bc6\u0bc7\u0bc8")  # ெ ே ை
_TAMIL_VIRAMA = "\u0bcd"  # pulli / virama
_TAMIL_CONSONANT_FIRST = "\u0b95"  # க
_TAMIL_CONSONANT_LAST = "\u0bb9"  # ஹ

# The three canonical Tamil two-part vowels. The right-hand half (ா / ௗ) is
# a post-base glyph and so is extracted in the correct position already; moving
# the pre-base half back next to it re-forms the decomposed pair, which must be
# recomposed to match NFC source text.
_TAMIL_COMPOSE = (
    ("\u0bc6\u0bbe", "\u0bca"),
    ("\u0bc7\u0bbe", "\u0bcb"),
    ("\u0bc6\u0bd7", "\u0bcc"),
)


def _is_tamil_consonant(ch: str) -> bool:
    """Tamil consonant letters (U+0B95..U+0BB9) — the only bases a left-side
    vowel sign can attach to. Independent vowels (U+0B85..U+0B94) and the
    aytham (U+0B83) are deliberately excluded: a vowel sign never follows one,
    so treating them as bases would move a sign onto the wrong cluster."""
    return _TAMIL_CONSONANT_FIRST <= ch <= _TAMIL_CONSONANT_LAST


def _is_visual_order_tamil(text: str) -> bool:
    """Does ``text`` carry the visual-order signature — a Tamil left-side vowel
    sign that is not preceded by a consonant?

    That position is unrepresentable in correct (logical) Tamil: a dependent
    vowel sign always follows the consonant it modifies. Seeing one means the
    producer laid the glyphs out left-to-right as drawn. This is what lets the
    repair be unconditional *within* a text without risking correctly ordered
    text: no signature, no repair.
    """
    previous = ""
    for char in text:
        if char in _TAMIL_LEFT_VOWELS and not _is_tamil_consonant(previous):
            return True
        previous = char
    return False


def _repair_left_vowel_order(text: str) -> str:
    """Put visually-ordered Tamil left-side vowel signs back in logical order.

    Each sign is moved to just after the consonant cluster it precedes, where a
    cluster is ``C (virama C)*`` — one consonant, plus any virama-joined
    continuation. The cluster walk (rather than a bare swap with the next
    character) is what keeps ligatures such as ``க்ஷ`` intact: the sign belongs
    to the whole cluster, not to its first consonant.

    **Deliberately Tamil-only.** Devanagari (U+093F), Bengali (U+09BF),
    Gujarati, Gurmukhi, Oriya, Malayalam and Sinhala all have the same class of
    pre-base vowel sign and almost certainly the same extraction artefact — but
    their conjunct formation differs, so where a producer places the sign
    relative to a multi-consonant cluster is a per-script empirical question.
    Guessing would risk *corrupting* text that extracted correctly, which is
    strictly worse than leaving a known-broken script alone. Adding a script is
    a one-line table change plus a golden fixture from a real PDF in that
    script; until such a fixture exists, the script stays out.
    """
    # Fast path: every non-Tamil and every correctly ordered document is untouched.
    if not _is_visual_order_tamil(text):
        return text

    out: list[str] = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char in _TAMIL_LEFT_VOWELS:
            end = index + 1
            if end < length and _is_tamil_consonant(text[end]):
                end += 1
                while (
                    end + 1 < length
                    and text[end] == _TAMIL_VIRAMA
                    and _is_tamil_consonant(text[end + 1])
                ):
                    end += 2
                out.extend(text[index + 1 : end])
                out.append(char)
                index = end
                continue
        out.append(char)
        index += 1

    repaired = "".join(out)
    for decomposed, composed in _TAMIL_COMPOSE:
        repaired = repaired.replace(decomposed, composed)
    return repaired


def _pdf_metadata(pdf: Any) -> DocumentMetadata:
    """Real ``/Info`` dictionary values — title/author/created — plus page
    count. Every field is best-effort: absence in the source PDF is not an
    extraction failure."""
    info = pdf.metadata or {}
    return DocumentMetadata(
        title=info.get("Title") or None,
        author=info.get("Author") or None,
        created=info.get("CreationDate") or None,
        page_count=len(pdf.pages),
    )


def _image_data(img: Any) -> bytes | None:
    """Decode one ``page.images`` entry's raw raster bytes, or ``None`` if unusable.

    ``pdfplumber``/``pdfminer`` expose the undecoded raster via the ``stream``
    key's ``.get_data()``. Not every embedded stream is a valid standalone
    image (some filters need page-level context to interpret) — validated by
    a real Pillow decode so a bad image is skipped rather than breaking the
    whole page.
    """
    stream = img.get("stream")
    if stream is None:
        return None
    try:
        data = cast("bytes", stream.get_data())
    except Exception:
        return None
    if not data:
        return None
    try:
        Image.open(io.BytesIO(data)).load()
    except (UnidentifiedImageError, OSError, ValueError):
        return None
    return data


def _page_text_bbox(page: Any) -> BBox | None:
    """The bounding box covering every extracted word on the page, where feasible."""
    words = page.extract_words()
    if not words:
        return None
    x0 = min(float(w["x0"]) for w in words)
    top = min(float(w["top"]) for w in words)
    x1 = max(float(w["x1"]) for w in words)
    bottom = max(float(w["bottom"]) for w in words)
    return (x0, top, x1, bottom)


def _text_excluding_tables(page: Any, tables: list[Any]) -> Any:
    """``page``, with every detected table's region cropped out.

    Without this, a table's cell text is captured TWICE: once as its own typed
    ``BlockKind.table`` row (see ``_extract_tables``) and again inside the raw
    page paragraph text — which both dilutes the paragraph EU and lets it tie
    a table row on retrieval score for the exact fact the table row exists to
    answer. Mirrors how an embedded image never leaks into paragraph text.
    """
    filtered = page
    for table in tables:
        filtered = filtered.outside_bbox(table.bbox)
    return filtered


def _extract_tables(
    tables: list[Any], page_number: int, start_order: int
) -> tuple[list[ExtractedBlock], int]:
    """Real ruled/aligned tables (already located via ``page.find_tables()``)
    -> one ``BlockKind.table`` block per data row (first row is the header,
    carried as ``structure_path``) — the same ``"col: value"`` rendering
    ``extract/csv.py`` uses, so a table row from a PDF cites identically to
    one from a CSV. Returns the new blocks and the next free ``order`` value
    (``ExtractedBlock.order`` must stay globally unique — it feeds ``eu_id``
    downstream).
    """
    blocks: list[ExtractedBlock] = []
    order = start_order
    for table in tables:
        rows = table.extract()
        if len(rows) < 2:
            continue
        header = tuple(_repair_left_vowel_order(cell or "") for cell in rows[0])
        bbox = cast("BBox", tuple(float(v) for v in table.bbox))
        for row_index, row in enumerate(rows[1:]):
            rendered = _repair_left_vowel_order(
                ", ".join(f"{col}: {val or ''}" for col, val in zip(header, row, strict=False))
            )
            blocks.append(
                ExtractedBlock(
                    order=order,
                    kind=BlockKind.table,
                    text=rendered,
                    page=page_number,
                    bbox=bbox,
                    level=row_index,
                    structure_path=header,
                )
            )
            order += 1
    return blocks, order


class PdfExtractor(ExtractorPlugin):
    """One paragraph block per page (text + page number + a word-derived bbox);
    page images become ``ImageRef``s anchored to their page and box."""

    plugin_version = "pdf/1"

    def __init__(self, document_id: str | None = None) -> None:
        self.document_id = document_id

    def extract(self, source: Any) -> ExtractedDoc:
        opened, doc_id, source_uri = open_binary(source, self.document_id)

        blocks: list[ExtractedBlock] = []
        images: list[ImageRef] = []
        image_bytes: dict[str, bytes] = {}
        image_page_area: dict[str, float] = {}
        order = 0
        with pdfplumber.open(opened) as pdf:
            metadata = _pdf_metadata(pdf)
            for index, page in enumerate(pdf.pages):
                number = index + 1
                tables = page.find_tables()
                text_page = _text_excluding_tables(page, tables) if tables else page
                text = _repair_left_vowel_order((text_page.extract_text() or "").strip())
                blocks.append(
                    ExtractedBlock(
                        order=order,
                        kind=BlockKind.paragraph,
                        text=text,
                        page=number,
                        bbox=_page_text_bbox(text_page),
                    )
                )
                order += 1
                table_blocks, order = _extract_tables(tables, number, order)
                blocks.extend(table_blocks)
                page_area = float(page.width) * float(page.height)
                for img_index, img in enumerate(page.images):
                    image_id = f"page{number}-img{img_index}"
                    x0, top, x1, bottom = (
                        float(img["x0"]),
                        float(img["top"]),
                        float(img["x1"]),
                        float(img["bottom"]),
                    )
                    images.append(
                        ImageRef(
                            image_id=image_id,
                            page=number,
                            bbox=(x0, top, x1, bottom),
                            width=round(x1 - x0),
                            height=round(bottom - top),
                        )
                    )
                    image_page_area[image_id] = page_area
                    data = _image_data(img)
                    if data is not None:
                        image_bytes[image_id] = data

        return ExtractedDoc(
            document_id=doc_id,
            source_type=SourceType.pdf,
            structure_type=StructureType.page_layout,
            source_uri=source_uri,
            metadata=metadata,
            blocks=tuple(blocks),
            images=tuple(images),
            image_bytes=image_bytes,
            image_page_area=image_page_area,
        )
