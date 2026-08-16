"""Fully offline structural tests for the multilingual example.

No network, no API keys, no model endpoints — these run in CI while ``run.py``
(which spends real money on Jina + Gemini) does not. They assert the facts the
BASELINE measurement rests on, so a corpus edit cannot silently invalidate
RESULTS.md:

1.  Every declared document exists, is non-empty and is written in the script it
    claims. A "Tamil" document that is 90% English would make the whole
    cross-lingual measurement meaningless.
2.  The English documents do NOT contain the Tamil/Telugu-only facts. This is the
    load-bearing property of the whole example: if English could answer the
    Tamil-only questions, the fan-out would prove nothing.
3.  ``tokenize_v2`` produces non-zero tokens for the Tamil and Telugu text — the
    ADR-0011 payoff, since ``tokenize`` (v1, ASCII-only) produces zero.
4.  The exact-match-critical tokens (clause numbers, amounts) survive
    tokenization, because they are what a translated query destroys.
5.  ``golden.csv`` is well-formed and every ``correct_docs`` reference resolves.
6.  The two Tamil PDFs extract with zero lost glyphs.

Run:  cd python && ./.venv/bin/pytest ../examples/multilingual/test_corpus.py -q
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

from citenexus.testing import FakeEmbedding, FakeLLM, FakeReranker
from citenexus.tokenize import scripts_in, tokenize, tokenize_v2, unsupported_scripts

_HERE = Path(__file__).resolve().parent
_CORPUS = _HERE / "corpus"
_SRC = _HERE / "corpus-src"
_GOLDEN = _HERE / "golden.csv"

sys.path.insert(0, str(_HERE / "tools"))
from render_pdf import PDF_DOCS, repair_tamil_visual_order  # noqa: E402

# document stem -> (declared language, declared script, file extension)
DOCS: dict[str, tuple[str, str, str]] = {
    "01-en-leave-policy": ("en", "latin", ".txt"),
    "02-en-notice-period-policy": ("en", "latin", ".txt"),
    "03-en-probation-policy": ("en", "latin", ".txt"),
    "04-en-confidentiality-policy": ("en", "latin", ".txt"),
    "05-ta-chennai-leave-annexure": ("ta", "tamil", ".txt"),
    "06-ta-notice-buyout-annexure": ("ta", "tamil", ".txt"),
    "07-ta-maternity-creche-annexure": ("ta", "tamil", ".pdf"),
    "08-ta-termination-appeal-annexure": ("ta", "tamil", ".pdf"),
    "09-te-hyderabad-leave-annexure": ("te", "unknown", ".txt"),
    "10-te-probation-extension-annexure": ("te", "unknown", ".txt"),
    "11-te-confidentiality-annexure": ("te", "unknown", ".txt"),
    "12-te-shift-allowance-annexure": ("te", "unknown", ".txt"),
}

# The facts that exist ONLY outside English. If any of these strings appears in
# an English document, the example stops proving anything.
NON_LATIN_ONLY_FACTS = (
    "45,000",  # ta clause 7.2  notice buy-out per unserved month
    "12,500",  # te clause 4.4  extended-probation stipend
    "2,00,000",  # te clause 9.4  liquidated damages
    "850",  # te clause 6.2  night-shift allowance
    "26 வாரங்கள்",  # ta clause 5.4  maternity leave
    "6,000",  # ta clause 5.6  creche reimbursement
)


def _text(stem: str) -> str:
    """Source text of a document, whatever medium it ships in."""
    _lang, _script, ext = DOCS[stem]
    if ext == ".txt":
        return (_CORPUS / f"{stem}.txt").read_text(encoding="utf-8")
    return (_SRC / f"{stem}.txt").read_text(encoding="utf-8")


def _script_chars(text: str, lo: int, hi: int) -> int:
    return sum(1 for c in text if lo <= ord(c) <= hi)


# --------------------------------------------------------------------------
# 1. Every document exists, is substantial, and is in the script it claims.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("stem", sorted(DOCS))
def test_document_exists_and_is_substantial(stem: str) -> None:
    _lang, _script, ext = DOCS[stem]
    assert (_CORPUS / f"{stem}{ext}").exists(), f"{stem}{ext} missing from corpus/"
    text = _text(stem)
    assert len(text) > 900, f"{stem} is only {len(text)} chars — not a realistic document"
    assert text.count("\n\n") >= 4, f"{stem} has fewer than 5 paragraphs"


@pytest.mark.parametrize("stem", sorted(DOCS))
def test_document_is_in_its_declared_script(stem: str) -> None:
    lang, _script, _ext = DOCS[stem]
    text = _text(stem)
    tamil = _script_chars(text, 0x0B80, 0x0BFF)
    telugu = _script_chars(text, 0x0C00, 0x0C7F)
    if lang == "en":
        assert tamil == 0 and telugu == 0, f"{stem} claims English but carries Indic text"
    elif lang == "ta":
        assert tamil > 400, f"{stem} claims Tamil but has only {tamil} Tamil characters"
        assert telugu == 0
    else:
        assert telugu > 400, f"{stem} claims Telugu but has only {telugu} Telugu characters"
        assert tamil == 0


def test_corpus_has_no_undeclared_files() -> None:
    on_disk = {p.name for p in _CORPUS.iterdir() if p.suffix in {".txt", ".pdf"}}
    declared = {f"{s}{ext}" for s, (_l, _sc, ext) in DOCS.items()}
    assert on_disk == declared


# --------------------------------------------------------------------------
# 2. The whole point: English cannot answer the non-Latin questions.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("fact", NON_LATIN_ONLY_FACTS)
def test_fact_is_absent_from_every_english_document(fact: str) -> None:
    for stem, (lang, _sc, _ext) in DOCS.items():
        if lang != "en":
            continue
        assert fact not in _text(stem), (
            f"{fact!r} leaked into the English document {stem}. The Tamil/Telugu-only "
            "questions would then be answerable from English and the measurement is void."
        )


@pytest.mark.parametrize("fact", NON_LATIN_ONLY_FACTS)
def test_fact_is_present_in_some_non_english_document(fact: str) -> None:
    holders = [s for s, (lang, _sc, _e) in DOCS.items() if lang != "en" and fact in _text(s)]
    assert holders, f"{fact!r} is in no document at all — the golden question cannot be grounded"


def test_english_handbook_defers_rather_than_states() -> None:
    """The English documents must explicitly point at the annexures.

    Without this the corpus would just be incomplete; with it, the corpus is
    *correct* and the missing figure is genuinely only in the other language.
    """
    def flat(stem: str) -> str:
        return " ".join(_text(stem).split())

    assert "does not itself state a buy-out amount" in flat("02-en-notice-period-policy")
    assert "does not itself state the length of an extension" in flat("03-en-probation-policy")
    assert "this Part does not itself state that period" in flat("04-en-confidentiality-policy")


# --------------------------------------------------------------------------
# 3. The ADR-0011 payoff: v1 tokenizes Indic to nothing, v2 does not.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("stem", [s for s, (lang, _s, _e) in DOCS.items() if lang != "en"])
def test_v1_tokenizer_would_have_lost_the_document(stem: str) -> None:
    """The regression this example exists to keep visible.

    ``tokenize`` (v1, frozen, ASCII-only) reduces a Tamil or Telugu paragraph to
    only its Latin fragments — the SOURCE/LANGUAGE header lines and the ``INR``
    amounts. Strip those and v1 yields zero tokens, which is exactly the failure
    ADR-0011 documents: BM25 sees nothing, and the faithfulness gate then rejects
    a verbatim quote of the document's own words.
    """
    body = "\n".join(
        line
        for line in _text(stem).splitlines()
        if not line.startswith(("SOURCE:", "LANGUAGE:", "DOCUMENT:", "EFFECTIVE:", "STATUS:"))
    )
    indic_only = "".join(c for c in body if ord(c) > 0x0B00 or c.isspace())
    assert tokenize(indic_only) == [], "v1 unexpectedly tokenized Indic text"


@pytest.mark.parametrize("stem", [s for s, (lang, _s, _e) in DOCS.items() if lang != "en"])
def test_v2_tokenizer_produces_real_tokens(stem: str) -> None:
    text = _text(stem)
    tokens = tokenize_v2(text)
    assert len(tokens) > 150, f"{stem}: tokenize_v2 produced only {len(tokens)} tokens"
    # Not just the Latin header: genuine Indic tokens must be present.
    indic = [t for t in tokens if any(ord(c) > 0x0B00 for c in t)]
    assert len(indic) > 100, f"{stem}: only {len(indic)} Indic tokens"


def test_tamil_is_a_claimed_script_and_telugu_is_not() -> None:
    """Pins the known capability gap so its eventual fix is a visible change.

    ADR-0011's allowlist claims ``tamil``. It does not claim ``telugu`` — the
    range U+0C00-U+0C7F is a hole in the script table, so Telugu resolves to
    ``"unknown"``. ``tokenize_v2`` still emits tokens for it (unknown scripts take
    the delimited path), which is the dangerous half-service: retrieval looks
    like it works while the library claims nothing. Flip this test when a Telugu
    golden fixture lands.
    """
    tamil = _text("05-ta-chennai-leave-annexure")
    telugu = _text("09-te-hyderabad-leave-annexure")
    assert "tamil" in scripts_in(tamil)
    assert unsupported_scripts(tamil) == ()
    assert "unknown" in scripts_in(telugu)
    assert unsupported_scripts(telugu) == ("unknown",)
    assert len(tokenize_v2(telugu)) > 150  # ... and yet it tokenizes


# --------------------------------------------------------------------------
# 4. Exact-match-critical tokens survive tokenization.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("stem", "needles"),
    [
        ("05-ta-chennai-leave-annexure", ("2.9A", "4", "15", "31")),
        ("06-ta-notice-buyout-annexure", ("7.2", "45,000", "60", "2", "7")),
        ("07-ta-maternity-creche-annexure", ("5.4", "26", "6,000")),
        ("08-ta-termination-appeal-annexure", ("8.3", "21", "45")),
        ("09-te-hyderabad-leave-annexure", ("2.9C", "3", "5", "2.12")),
        ("10-te-probation-extension-annexure", ("4.3", "90", "12,500", "270")),
        ("11-te-confidentiality-annexure", ("9.1", "24", "2,00,000")),
        ("12-te-shift-allowance-annexure", ("6.2", "850", "10", "22:00")),
    ],
)
def test_exact_tokens_present_and_tokenizable(stem: str, needles: tuple[str, ...]) -> None:
    text = _text(stem)
    tokens = set(tokenize_v2(text))
    for needle in needles:
        assert needle in text, f"{stem}: exact token {needle!r} missing from the document"
        # Every numeric run of the needle must survive tokenization -- these are
        # precisely the strings a translated query would damage.
        for part in needle.replace(":", " ").replace(",", " ").replace(".", " ").split():
            assert part.casefold() in tokens, f"{stem}: {part!r} of {needle!r} did not tokenize"


# --------------------------------------------------------------------------
# 5. golden.csv is well-formed and every reference resolves.
# --------------------------------------------------------------------------


def _golden_rows() -> list[dict[str, str]]:
    with _GOLDEN.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_golden_is_well_formed() -> None:
    rows = _golden_rows()
    assert len(rows) >= 20
    required = {
        "question", "expected", "expect_decision",
        "probe", "answer_language", "correct_docs", "note",
    }
    for row in rows:
        assert required <= set(row), f"missing columns: {required - set(row)}"
        assert row["question"].strip()
        assert row["expect_decision"] in {"answer", "abstain"}
        assert row["note"].strip(), "every golden row must say WHY it is there"


def test_golden_references_real_documents() -> None:
    for row in _golden_rows():
        for doc in filter(None, row["correct_docs"].split("|")):
            assert doc in DOCS, f"golden.csv references unknown document {doc!r}"


def test_golden_covers_every_required_bucket() -> None:
    rows = _golden_rows()
    probes = [r["probe"] for r in rows]

    def n(prefix: str) -> int:
        return sum(1 for p in probes if p.startswith(prefix))

    assert n("ta_only") >= 4, "need English questions answerable ONLY from Tamil"
    assert n("te_only") >= 4, "need English questions answerable ONLY from Telugu"
    assert n("en") >= 3, "need a healthy-pipeline control group"
    assert n("none") >= 3, "need questions the corpus cannot ground at all"
    assert any(p.endswith("exact_token") for p in probes), "need exact-token probes"
    assert any(p.endswith("pdf") for p in probes), "need a question answered from a PDF"
    # Every answerable question must actually be grounded in the document it names.
    for row in rows:
        if row["expect_decision"] != "answer":
            assert not row["correct_docs"], "an abstain row must name no supporting document"
            continue
        docs = [d for d in row["correct_docs"].split("|") if d]
        assert docs, f"answerable row has no correct_docs: {row['question'][:60]}"
        assert row["expected"], "an answerable row must state the token the answer turns on"
        assert any(row["expected"] in _text(d) for d in docs), (
            f"expected token {row['expected']!r} is not in {docs}"
        )


# --------------------------------------------------------------------------
# 6. The PDFs: real files, and the Tamil text comes back out.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("stem", PDF_DOCS)
def test_pdf_is_real_and_tamil_survives_extraction(stem: str) -> None:
    pdfplumber = pytest.importorskip("pdfplumber")
    path = _CORPUS / f"{stem}.pdf"
    assert path.read_bytes()[:5] == b"%PDF-", "not actually a PDF"
    with pdfplumber.open(path) as pdf:
        got = " ".join(" ".join(p.extract_text() or "" for p in pdf.pages).split())

    # No tofu, no dropped glyphs. This is the check Telugu fails on every
    # renderer/font pair on macOS, which is why Telugu ships as .txt.
    assert "\x00" not in got and "(cid:" not in got

    assert len(tokenize_v2(got)) > 150
    # Left-side Tamil vowel signs come out in VISUAL order; the damage is
    # mechanical and fully reversible, which is the finding worth pinning.
    src = " ".join((_SRC / f"{stem}.txt").read_text(encoding="utf-8").split())
    words = [w for w in src.split() if any(ord(c) > 0x0B80 for c in w)]
    raw = sum(1 for w in words if w in got) / len(words)
    fixed = sum(1 for w in words if w in repair_tamil_visual_order(got)) / len(words)
    assert raw < 0.80, "extraction is cleaner than documented — update RESULTS.md"
    assert fixed == 1.0, "the reordering is no longer fully reversible — investigate"


# --------------------------------------------------------------------------
# 7. The fakes can drive the whole thing offline (smoke).
# --------------------------------------------------------------------------


def test_shipped_fakes_are_blind_to_indic_text() -> None:
    """A real limitation of ``citenexus.testing``, pinned so nobody trusts it here.

    ``FakeEmbedding`` hashes ``tokenize`` — v1, ASCII-only — so a Tamil or Telugu
    query embeds to the ZERO vector and every Indic document embeds to whatever
    Latin fragments its header happens to carry. That makes the shipped fakes
    unusable for offline multilingual retrieval work: an English query would
    appear to "beat" a Tamil query on a Tamil document, which is an artefact of
    the fake, not a fact about retrieval.

    This is why the cross-lingual claim in RESULTS.md is measured against LIVE
    multilingual endpoints and never against the fakes.
    """
    embed = FakeEmbedding()
    tamil = _text("06-ta-notice-buyout-annexure")
    tamil_query = "விலைக்கு வாங்கும் தொகை என்ன"

    assert tokenize(tamil_query) == []
    assert all(v == 0.0 for v in embed.embed(tamil_query)), (
        "FakeEmbedding grew Unicode support — re-point it at tokenize_v2 in the test above"
    )
    # v2 sees the same query perfectly well, and the words are really in the doc.
    tokens = tokenize_v2(tamil_query)
    assert len(tokens) == 4
    doc_tokens = set(tokenize_v2(tamil))
    assert {t for t in tokens if t in doc_tokens}, "Tamil query shares no token with its own source"

    # The other two fakes are language-neutral and usable.
    assert FakeLLM().answer("q", "passage") == "passage"
    assert FakeReranker().rerank("q", [1, 2, 3]) == [1, 2, 3]
