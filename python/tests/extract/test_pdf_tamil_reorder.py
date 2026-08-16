"""Tamil left-side vowel signs must come out of a PDF in LOGICAL order.

A PDF stores glyphs as drawn. Tamil's pre-base vowel signs (ெ U+0BC6, ே U+0BC7,
ை U+0BC8) are drawn to the LEFT of the consonant they logically follow, so raw
extraction returns ``வேண்டும்`` as ``ேவண்டும்``.

Nothing is lost — measured against the two real Tamil PDFs in
``examples/multilingual/corpus``, zero glyphs go missing — but for this library
the ORDER is the whole point: a citation must be verbatim, and a reordered
passage both fails to match its source and fails ``is_supported`` against a
correctly ordered claim, turning a perfectly grounded answer into a false
abstention. That downstream failure is asserted here directly.

Measured on the real PDFs: **67.7% -> 100%** of extracted words appear verbatim
in the source text these PDFs were rendered from.
"""

from __future__ import annotations

import unicodedata
from pathlib import Path

import pytest

from citenexus.answer.verify import is_supported, is_supported_v2
from citenexus.extract.pdf import (
    PdfExtractor,
    _is_visual_order_tamil,
    _repair_left_vowel_order,
)

CORPUS = Path(__file__).resolve().parents[3] / "examples" / "multilingual" / "corpus"
CORPUS_SRC = CORPUS.parent / "corpus-src"

TAMIL_PDFS = (
    "07-ta-maternity-creche-annexure",
    "08-ta-termination-appeal-annexure",
)


# --------------------------------------------------------------------------- #
# The pure repair function.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("visual", "logical"),
    [
        # ெ (U+0BC6) — "vēṇṭum", the canonical example.
        ("ேவண்டும்", "வேண்டும்"),
        # ே (U+0BC7).
        ("ேமலும்", "மேலும்"),
        # ை (U+0BC8) mid-word. In ISOLATION this is ambiguous — ``வ ை ர`` could
        # be ``வை``+``ர`` or ``வ``+``ரை`` — so it is resolved by the surrounding
        # text carrying the visual-order signature (see the dedicated test
        # below). Here a signature-bearing word rides along.
        ("ேவ வைர", "வே வரை"),
        ("ேவ ஊழியைர", "வே ஊழியரை"),
        # Two-part vowel ொ = ெ + ா: the left half is misplaced, the right half
        # is not, and reuniting them must RECOMPOSE to the NFC single code point.
        ("ெபாருந்தும்", "பொருந்தும்"),
        # ோ = ே + ா.
        ("மகப்ேபறு", "மகப்பேறு"),
        # Several signs in one word.
        ("ெசன்ைன", "சென்னை"),
        # A sign at the very start of the text (word-initial in visual order).
        ("ெதாடர்", "தொடர்"),
    ],
)
def test_visual_order_is_repaired_to_logical_order(visual: str, logical: str) -> None:
    assert _repair_left_vowel_order(visual) == unicodedata.normalize("NFC", logical)


def test_an_isolated_mid_word_sign_is_left_alone_because_it_is_ambiguous() -> None:
    """``வ ை ர`` in isolation is a legal logical-order string (``வை`` + ``ர``)
    AND the visual form of ``வரை``. Nothing local can tell them apart, so the
    repair declines rather than guessing — it only fires on text that carries
    the unambiguous signature (a sign not preceded by a consonant) somewhere.
    That is what keeps it safe on correctly ordered documents."""
    assert _repair_left_vowel_order("வைர") == "வைர"
    assert not _is_visual_order_tamil("வைர")
    # ...but one signature anywhere in the text resolves the whole text.
    assert _repair_left_vowel_order("ேவண்டும் வைர") == "வேண்டும் வரை"


def test_repair_is_idempotent() -> None:
    once = _repair_left_vowel_order("ேவண்டும் ெசன்ைன வைர")
    assert _repair_left_vowel_order(once) == once


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Employees are entitled to thirty days of annual leave.",
        "ஊழியர் விடுப்பு",  # Tamil with no left-side vowel sign at all.
        "வேண்டும் சென்னை வரை",  # Tamil ALREADY in logical order.
        "员工可以享受产假",
        "कर्मचारी मातृत्व अवकाश",  # Devanagari — deliberately out of scope.
        "ఉద్యోగి సెలవు",
    ],
)
def test_correct_text_passes_through_byte_for_byte(text: str) -> None:
    """The repair must never touch text that does not carry the visual-order
    signature — including scripts it deliberately does not handle."""
    assert _repair_left_vowel_order(text) == text


def test_repair_is_lossless_at_the_character_level() -> None:
    """Reordering only: the multiset of characters is preserved exactly."""
    visual = "ேவண்டும் ெசன்ைன அலுவலகம் — ெபாருந்தும் 2026"
    repaired = _repair_left_vowel_order(visual)
    assert sorted(unicodedata.normalize("NFD", repaired)) == sorted(
        unicodedata.normalize("NFD", visual)
    )


def test_mixed_latin_and_tamil_leaves_latin_untouched() -> None:
    repaired = _repair_left_vowel_order("LANGUAGE: ta — ேவண்டும் (VTPL-ANX-CHN-05)")
    assert repaired == "LANGUAGE: ta — வேண்டும் (VTPL-ANX-CHN-05)"


def test_virama_joined_cluster_keeps_the_sign_on_the_whole_cluster() -> None:
    """``க்ஷ`` is a ligature: the pre-base sign belongs to the cluster, not to
    its first consonant, so a bare swap with the next character would be wrong."""
    assert _repair_left_vowel_order("ெக்ஷ") == "க்ஷெ"


def test_visual_order_signature_detection() -> None:
    assert _is_visual_order_tamil("ேவண்டும்")
    assert not _is_visual_order_tamil("வேண்டும்")
    assert not _is_visual_order_tamil("plain ascii")


# --------------------------------------------------------------------------- #
# The real PDFs.
# --------------------------------------------------------------------------- #


def _extracted_text(name: str) -> str:
    doc = PdfExtractor().extract(str(CORPUS / f"{name}.pdf"))
    return "\n".join(block.text for block in doc.blocks)


def _verbatim_ratio(name: str) -> tuple[int, int]:
    source_words = set(
        unicodedata.normalize(
            "NFC", (CORPUS_SRC / f"{name}.txt").read_text(encoding="utf-8")
        ).split()
    )
    words = unicodedata.normalize("NFC", _extracted_text(name)).split()
    return sum(1 for w in words if w in source_words), len(words)


@pytest.mark.parametrize("name", TAMIL_PDFS)
def test_every_word_of_a_real_tamil_pdf_extracts_verbatim(name: str) -> None:
    """The measurement that motivated the fix. Before the repair this was
    69.2% / 66.2% (67.7% overall); after it, every single word matches."""
    hits, total = _verbatim_ratio(name)
    assert total > 100, "sanity: the PDF really did extract text"
    assert hits == total, f"{name}: {hits}/{total} words verbatim"


@pytest.mark.parametrize("name", TAMIL_PDFS)
def test_real_tamil_pdf_extraction_is_idempotent_under_the_repair(name: str) -> None:
    text = _extracted_text(name)
    assert _repair_left_vowel_order(text) == text


def test_a_known_tamil_phrase_survives_extraction_verbatim() -> None:
    text = _extracted_text("07-ta-maternity-creche-annexure")
    assert "சென்னை அலுவலகம்" in text
    assert "மகப்பேறு" in text
    # The broken forms must be gone.
    assert "ெசன்ைன" not in text
    assert "மகப்ேபறு" not in text


# --------------------------------------------------------------------------- #
# The downstream failure this actually fixes.
# --------------------------------------------------------------------------- #


def test_extracted_tamil_passage_supports_a_claim_quoting_it() -> None:
    """The real cost of visual order: ``is_supported`` compares the claim's
    tokens against the passage's, and a reordered passage tokenizes to different
    words — so a claim quoting its own source is judged unsupported and the
    answer abstains. Extraction must produce a passage the gate accepts."""
    text = _extracted_text("07-ta-maternity-creche-annexure")
    sentences = [
        line.strip()
        for line in text.split("\n")
        if len(line.strip()) > 40 and not any(ch.isascii() and ch.isalpha() for ch in line)
    ]
    assert sentences, "sanity: the PDF has substantial all-Tamil lines"
    passage = sentences[0]
    # is_supported_v2 is the gate the answer path runs (ADR-0009); the frozen
    # v1 predicate is ASCII-only by contract and can never accept Tamil.
    assert is_supported_v2(passage, passage)
    assert not is_supported(passage, passage)  # v1, frozen: ASCII only.


def test_visually_ordered_passage_would_fail_the_gate() -> None:
    """The counterfactual, pinned: a correctly ordered claim against a
    visually-ordered passage is rejected — which is exactly the false
    abstention the repair removes."""
    claim = "சென்னை அலுவலக ஊழியர்களுக்கு மகப்பேறு விடுப்பு பொருந்தும்"
    visual_passage = "ெசன்ைன அலுவலக ஊழியர்களுக்கு மகப்ேபறு விடுப்பு ெபாருந்தும்"
    assert not is_supported_v2(claim, visual_passage)
    assert is_supported_v2(claim, _repair_left_vowel_order(visual_passage))
