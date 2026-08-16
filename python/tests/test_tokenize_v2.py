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

import itertools
import unicodedata

import pytest

from citenexus.answer.verify import is_supported_v2
from citenexus.tokenize import (
    _SCRIPT_RANGES,
    SUPPORTED_SCRIPTS,
    TOKENIZER_VERSION,
    script_of,
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
    "telugu": "ఉద్యోగి రహస్య సమాచారాన్ని వెల్లడించకూడదు.",
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
        # Telugu's Indic neighbours. The range table NAMES them — which is what
        # stops the next one reading as a neighbour plus "unknown", the way
        # Telugu did — but none carries a golden fixture, so none is claimed.
        ("gurmukhi", "ਕਰਮਚਾਰੀ ਗੁਪਤ ਜਾਣਕਾਰੀ ਜ਼ਾਹਰ ਨਹੀਂ ਕਰੇਗਾ"),
        ("gujarati", "કર્મચારી ગોપનીય માહિતી જાહેર કરશે નહીં"),
        ("oriya", "କର୍ମଚାରୀ ଗୋପନୀୟ ସୂଚନା ପ୍ରକାଶ କରିବେ ନାହିଁ"),
        ("kannada", "ಉದ್ಯೋಗಿ ಗೌಪ್ಯ ಮಾಹಿತಿಯನ್ನು ಬಹಿರಂಗಪಡಿಸಬಾರದು"),
        ("malayalam", "ജീവനക്കാരൻ രഹസ്യ വിവരങ്ങൾ വെളിപ്പെടുത്തരുത്"),
        ("sinhala", "සේවකයා රහස්‍ය තොරතුරු හෙළි නොකළ යුතුය"),
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
# the range table itself — the layer Telugu fell through
#
# Telugu (U+0C00-U+0C7F) was not in `_SCRIPT_RANGES` at all. It therefore read as
# a NEIGHBOUR plus "unknown", and still emitted six delimited tokens, so BM25
# ranked a script no fixture had ever validated while `answer/flow.py` filtered
# every Telugu passage out of the grounding set. These tests make both halves of
# that impossible to repeat: a claimed script must classify to ITSELF over its
# whole Unicode repertoire, and an unnamed script must not tokenize at all.
# --------------------------------------------------------------------------- #


def test_script_ranges_are_sorted_and_disjoint() -> None:
    for prev, nxt in itertools.pairwise(_SCRIPT_RANGES):
        assert prev[0] <= prev[1], prev
        assert prev[1] < nxt[0], (prev, nxt)


# Japanese genuinely mixes Han and Hiragana in one sentence; nothing else here
# is legitimately multi-script.
_EXPECTED_SAMPLE_SCRIPTS = {script: (script,) for script in SAMPLES} | {
    "hiragana": ("han", "hiragana")
}


@pytest.mark.parametrize("script", sorted(SAMPLES))
def test_each_sample_classifies_to_exactly_its_own_script(script: str) -> None:
    """Not 'contains its script' — IS its script, with no second script and no
    "unknown" riding along. Telugu's symptom was exactly that extra member:
    ('devanagari', 'unknown')."""
    found = scripts_in(SAMPLES[script])
    assert found == _EXPECTED_SAMPLE_SCRIPTS[script]
    assert set(found) <= SUPPORTED_SCRIPTS


# The Unicode character name is the independent source of truth here: Python's
# stdlib has no Script property, but every character in these scripts is named
# after it ("TELUGU LETTER A", "CYRILLIC SMALL LETTER A"). Restricted to
# characters that survive NFKC, because tokenize_v2 normalizes before it
# classifies — a compatibility character never reaches the table.
_NAME_PREFIX_TO_SCRIPT = {
    "ARABIC": "arabic",
    "BENGALI": "bengali",
    "CJK": "han",
    "CYRILLIC": "cyrillic",
    "DEVANAGARI": "devanagari",
    "GREEK": "greek",
    "HANGUL": "hangul",
    "HEBREW": "hebrew",
    "HIRAGANA": "hiragana",
    "KATAKANA": "katakana",
    "LATIN": "latin",
    "TAMIL": "tamil",
    "TELUGU": "telugu",
    "THAI": "thai",
}


def test_every_claimed_script_covers_its_whole_unicode_repertoire() -> None:
    """A claimed script must classify to ITSELF for every character Unicode names
    as belonging to it. This is the sweep that would have caught Telugu — it was
    absent from the table entirely, so there was nothing to decline."""
    assert set(_NAME_PREFIX_TO_SCRIPT.values()) == SUPPORTED_SCRIPTS
    holes: list[tuple[str, str, str]] = []
    for cp in range(0x110000):
        ch = chr(cp)
        if unicodedata.category(ch)[0] not in ("L", "N", "M"):
            continue
        if unicodedata.normalize("NFKC", ch) != ch:
            continue
        name = unicodedata.name(ch, "")
        want = next(
            (s for p, s in _NAME_PREFIX_TO_SCRIPT.items() if name.startswith(p + " ")),
            None,
        )
        if want is None:
            continue
        got = script_of(ch)
        if got != want:
            holes.append((f"U+{cp:04X}", want, got))
    assert holes == [], f"claimed scripts with uncovered characters: {holes[:10]}"


_UNNAMED_SCRIPT_SAMPLES = [
    "የሰራተኛው ሚስጥራዊ መረጃ",  # Ethiopic
    "ᏗᏙᎳᏅᏍᏗ ᎠᏓᏅᏙ",  # Cherokee
    "ཞིབ་འཇུག",  # Tibetan
]


@pytest.mark.parametrize("text", _UNNAMED_SCRIPT_SAMPLES)
def test_a_script_absent_from_the_table_does_not_tokenize_at_all(text: str) -> None:
    """The structural half of the fix. A script the table has never heard of has
    no validated segmentation rule, so it produces NOTHING — BM25 cannot rank it
    and the gate cannot accept it. ADR-0011: answering through an unvalidated
    segmentation is worse than refusing."""
    assert scripts_in(text) == ("unknown",)
    assert unsupported_scripts(text) == ("unknown",)
    assert tokenize_v2(text) == []


@pytest.mark.parametrize("text", _UNNAMED_SCRIPT_SAMPLES)
def test_an_unnamed_script_refuses_rather_than_rubber_stamping(text: str) -> None:
    """Zero tokens must mean REFUSE, never vacuous-true: an empty claim has no
    alignment, so the gate rejects even a verbatim quote of the passage."""
    assert is_supported_v2(text, text) is False


def test_an_unnamed_script_does_not_take_the_rest_of_the_sentence_with_it() -> None:
    """Only the unknown run is dropped; the validated part still tokenizes, so a
    stray character cannot silence an otherwise-supported passage."""
    assert tokenize_v2("የሰራተኛው 2026 policy") == ["2026", "policy"]


# --------------------------------------------------------------------------- #
# Telugu — the regression this file exists for
# --------------------------------------------------------------------------- #


def test_telugu_tokenizes_and_classifies_as_telugu() -> None:
    text = SAMPLES["telugu"]
    assert scripts_in(text) == ("telugu",)  # was ('devanagari', 'unknown')
    assert tokenize_v2(text) == [
        "ఉద్యోగి",
        "రహస్య",
        "సమాచారాన్ని",
        "వెల్లడించకూడదు",
    ]
    assert unsupported_scripts(text) == ()


def test_telugu_is_delimited_not_bigram_indexed() -> None:
    """Telugu writes spaces. Bigramming it would be the mirror defect."""
    assert tokenize_v2("ఉద్యోగి రహస్య") == ["ఉద్యోగి", "రహస్య"]


def test_the_measured_wrong_answer_can_now_be_cited() -> None:
    """examples/multilingual: the Hyderabad annexure caps carry-forward at 5 days
    and overrides the English handbook's 10. Telugu classified as unknown, so
    `answer/flow.py` filtered the passage out of the grounding set and the
    English "maximum of 10 days" was cited instead — grounded, correctly cited
    and WRONG. The gate must accept the Telugu passage's own words."""
    passage = "వాడని ఆర్జిత సెలవులో గరిష్ఠంగా 5 రోజులు మాత్రమే తదుపరి సెలవు సంవత్సరానికి బదిలీ చేయవచ్చు."
    claim = "గరిష్ఠంగా 5 రోజులు బదిలీ చేయవచ్చు"
    assert unsupported_scripts(passage) == ()
    assert is_supported_v2(claim, passage) is True
    assert is_supported_v2("గరిష్ఠంగా 10 రోజులు బదిలీ చేయవచ్చు", passage) is False


# --------------------------------------------------------------------------- #
# versioning
# --------------------------------------------------------------------------- #


def test_tokenizer_version_is_recorded() -> None:
    assert TOKENIZER_VERSION == 2


def test_tokenize_v2_is_deterministic() -> None:
    for text in [*SAMPLES.values(), *_ASCII_CASES]:
        assert tokenize_v2(text) == tokenize_v2(text)
