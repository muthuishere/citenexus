"""The Unicode-aware tokenizer (ADR-0011).

v1 is `[a-z0-9]+` over `.lower()` — ASCII only — so every non-Latin script
produced zero tokens and the faithfulness gate rejected a verbatim quote of its
own source. v2 is Unicode letter/number/mark classes with case folding, plus
character-bigram segmentation for the scripts that do not put spaces between
words.
"""

# Greek omicron, fullwidth forms and Cyrillic lookalikes are the SUBJECT of this
# file, not typos — ruff's ambiguous-character lint is noise here, exactly as in
# `answer/segment.py`.
# ruff: noqa: RUF001

from __future__ import annotations

import pytest

from citenexus.answer.verify import is_supported_v2
from citenexus.tokenize import (
    SUPPORTED_SCRIPTS,
    TOKENIZER_VERSION,
    scripts_in,
    tokenize,
    tokenize_v2,
    unsupported_scripts,
)

# One sentence per script, each a plausible sentence of evidence.
SAMPLES: dict[str, str] = {
    "latin": "The employee shall not disclose confidential information.",
    "greek": "Ο εργαζόμενος δεν πρέπει να αποκαλύπτει εμπιστευτικές πληροφορίες.",
    "cyrillic": "Работник не должен раскрывать конфиденциальную информацию.",
    "hebrew": "העובד לא יגלה מידע סודי.",
    "arabic": "لا يجوز للموظف إفشاء المعلومات السرية.",
    "devanagari": "कर्मचारी गोपनीय जानकारी प्रकट नहीं करेगा।",
    "tamil": "ஊழியர் ரகசியத் தகவலை வெளியிடக் கூடாது.",
    "han": "员工不得披露机密信息。",
    "hiragana": "従業員は機密情報を開示してはならない。",
    "hangul": "직원은 기밀 정보를 공개해서는 안 된다.",
    "thai": "พนักงานต้องไม่เปิดเผยข้อมูลที่เป็นความลับ",
}


# --------------------------------------------------------------------------- #
# the defect ADR-0011 records
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("script", sorted(SAMPLES))
def test_v1_is_ascii_only_and_v2_is_not(script: str) -> None:
    """v1 stays frozen and broken; v2 is the fix. Both are asserted together so
    nobody 'fixes' v1 and silently breaks the pinned ports."""
    text = SAMPLES[script]
    if script == "latin":
        assert tokenize(text)
    else:
        assert tokenize(text) == [], "v1 must stay frozen (SPEC-PORTS-v1 §4)"
    assert tokenize_v2(text), f"v2 produced no tokens for {script}"


@pytest.mark.parametrize("script", sorted(SAMPLES))
def test_verbatim_quote_of_its_own_source_is_supported(script: str) -> None:
    """The measured symptom: the gate rejected a verbatim quote of its source."""
    text = SAMPLES[script]
    assert is_supported_v2(text, text) is True


@pytest.mark.parametrize("script", sorted(SAMPLES))
def test_unrelated_text_is_still_rejected(script: str) -> None:
    """The fix must not turn the gate into a rubber stamp."""
    other = "Employees are entitled to thirty days of annual leave."
    assert is_supported_v2(SAMPLES[script], other) is False


# --------------------------------------------------------------------------- #
# v1/v2 agreement on ASCII — the reason existing fixtures do not move
# --------------------------------------------------------------------------- #

_ASCII_CASES = [
    "Hello, World!",
    "The price is $4.50 (approx).",
    "ISO-9001:2015 certified",
    "MixedCASE tokens123abc under_score",
    "co-operate re-use state-of-the-art",
    "3.14159 and 2e10 numbers",
    "",
    "   \n\t  ",
    "The employee shall not disclose confidential information.",
]


@pytest.mark.parametrize("text", _ASCII_CASES)
def test_v2_agrees_with_v1_on_pure_ascii(text: str) -> None:
    assert tokenize_v2(text) == tokenize(text)


# --------------------------------------------------------------------------- #
# Unicode word characters
# --------------------------------------------------------------------------- #


def test_accented_latin_is_one_token_not_a_truncated_stub() -> None:
    # v1 yields ["caf"] — it truncates at the first non-ASCII byte.
    assert tokenize("Café") == ["caf"]
    assert tokenize_v2("Café") == ["café"]


def test_case_folding_not_lowercasing() -> None:
    """casefold() maps ß→ss; .lower() does not. Caseless matching needs folding."""
    assert tokenize_v2("STRASSE") == tokenize_v2("Straße") == ["strasse"]


def test_nfkc_normalization_unifies_compatibility_forms() -> None:
    assert tokenize_v2("ＡＢＣ１２３") == ["abc123"]
    # Precomposed and decomposed é must produce the same token.
    assert tokenize_v2("café") == tokenize_v2("café") == ["café"]


def test_combining_marks_stay_attached_to_their_base() -> None:
    """Devanagari matras are Mn — dropping them would shred the word."""
    assert tokenize_v2("कर्मचारी") == ["कर्मचारी"]


def test_punctuation_and_symbols_are_separators_in_every_script() -> None:
    assert tokenize_v2("«Ω», Ω!") == ["ω", "ω"]
    assert tokenize_v2("日本語。中国") == ["日本", "本語", "中国"]


def test_script_change_splits_a_run() -> None:
    assert tokenize_v2("東京tokyo") == ["東京", "tokyo"]
    assert tokenize_v2("абвabc") == ["абв", "abc"]


def test_digits_do_not_split_a_latin_run() -> None:
    assert tokenize_v2("tokens123abc") == ["tokens123abc"]


# --------------------------------------------------------------------------- #
# scripts without spaces need SEGMENTATION, not classification
# --------------------------------------------------------------------------- #


def test_cjk_is_bigram_indexed_not_one_token_per_sentence() -> None:
    """Whitespace splitting yields one token per sentence, which makes BM25 and
    any containment predicate degenerate."""
    tokens = tokenize_v2("员工不得披露机密信息")
    assert tokens[:3] == ["员工", "工不", "不得"]
    assert len(tokens) == len("员工不得披露机密信息") - 1


def test_japanese_bigrams_do_not_cross_the_kanji_kana_boundary() -> None:
    """Lucene's CJKBigramFilter semantics: bigrams form WITHIN a script run, not
    across one. 従業員 (Han) and は (Hiragana) are separate runs, so the kana
    particle does not glue itself onto the noun."""
    assert tokenize_v2("従業員は") == ["従業", "業員", "は"]


def test_single_character_run_yields_that_character() -> None:
    assert tokenize_v2("木") == ["木"]


def test_thai_is_bigram_indexed() -> None:
    tokens = tokenize_v2("พนักงาน")
    assert len(tokens) == len("พนักงาน") - 1


def test_korean_is_space_delimited_not_bigram_indexed() -> None:
    """Hangul writes spaces between words, so bigrams would be a regression."""
    assert tokenize_v2("직원은 기밀 정보를") == ["직원은", "기밀", "정보를"]


def test_cjk_substring_containment_holds_through_bigrams() -> None:
    assert is_supported_v2("机密信息", "员工不得披露机密信息") is True


def test_cjk_reordering_is_still_rejected() -> None:
    """Bigram indexing must not weaken the ordered-containment guarantee."""
    assert is_supported_v2("信息披露不得员工", "员工不得披露机密信息") is False


# --------------------------------------------------------------------------- #
# unsupported_script as a real signal
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("script", sorted(SAMPLES))
def test_every_claimed_script_is_actually_claimed(script: str) -> None:
    assert script in SUPPORTED_SCRIPTS
    assert unsupported_scripts(SAMPLES[script]) == ()


def test_scripts_in_reports_what_it_found() -> None:
    assert scripts_in("hello 日本") == ("han", "latin")
    assert scripts_in("123 !?") == ()  # digits and punctuation carry no script


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("khmer", "បុគ្គលិកមិនត្រូវបង្ហាញព័ត៌មានសម្ងាត់"),
        ("lao", "ພະນັກງານບໍ່ຄວນເປີດເຜີຍຂໍ້ມູນລັບ"),
        ("myanmar", "ဝန်ထမ်းသည် လျှို့ဝှက်ချက်ကို မဖော်ထုတ်ရ"),
        ("georgian", "თანამშრომელმა არ უნდა გაამჟღავნოს"),
        ("armenian", "Աշխատողը չպետք է բացահայտի"),
    ],
)
def test_unclaimed_scripts_are_reported_not_silently_half_working(name: str, text: str) -> None:
    """A script with no golden fixture is NOT claimed. The library must say so
    rather than returning the evidence-absent refusal for a capability gap."""
    assert name not in SUPPORTED_SCRIPTS
    assert unsupported_scripts(text) == (name,)


def test_supported_text_reports_no_unsupported_script() -> None:
    assert unsupported_scripts("The employee shall not disclose.") == ()


def test_mixed_text_reports_only_the_unsupported_part() -> None:
    assert unsupported_scripts("see also បុគ្គលិក") == ("khmer",)


# --------------------------------------------------------------------------- #
# versioning
# --------------------------------------------------------------------------- #


def test_tokenizer_version_is_recorded() -> None:
    assert TOKENIZER_VERSION == 2


def test_tokenize_v2_is_deterministic() -> None:
    for text in [*SAMPLES.values(), *_ASCII_CASES]:
        assert tokenize_v2(text) == tokenize_v2(text)
