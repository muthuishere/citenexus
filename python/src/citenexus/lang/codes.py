"""The named language and script code sets — ``Language`` and ``Script``.

Language and script codes used to be bare strings at every public entry point,
which meant the domain was undiscoverable: nothing told a caller that 41 search
languages exist, that 14 scripts are claimed, or that ``"auto"`` is a sentinel
rather than a language. These two enums name all of it, once.

**They are a convenience layer, not a migration.** Both are ``StrEnum``, so a
member *is* its code:

    >>> Language.TAMIL == "ta"
    True
    >>> import json; json.dumps(Language.TAMIL)
    '"ta"'

Every public entry point takes ``str | Language``, never ``Language`` alone.
``rag.ask(q, answer_language="ta")`` and ``rag.ask(q, answer_language=Language.TAMIL)``
are equally correct, forever — the string form is not deprecated, does not warn,
and is not "the old way". That is the whole design constraint, and the ``StrEnum``
choice is what makes it free: equality, hashing, ``str()``, ``json.dumps`` and
sorting all behave exactly as the bare strings did, so ``Result`` JSON and every
conformance fixture are byte-identical.

**This module has no imports from the rest of the library**, deliberately:
``tokenize`` and ``lang.search`` both build their tables from it, and a dependency
here would knot the import graph.

Opt-in strictness
-----------------
Because a ``StrEnum`` member *is* a ``str``, an annotation of ``str | Language``
collapses to ``str`` and a type checker cannot flag ``"tamiil"``. That is the
honest cost of accepting both; the runtime still refuses the typo by name, before
any model call is made. Callers who want the compile-time catch in *their own*
code can use the ``LanguageCode`` / ``ScriptCode`` aliases exported here — they
accept a member or a known literal and reject anything else. They are deliberately
NOT used in library signatures, because narrowing to a ``Literal`` would reject a
caller's computed ``str``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

__all__ = [
    "AUTO",
    "Language",
    "LanguageCode",
    "LanguageLike",
    "Script",
    "ScriptCode",
    "ScriptLike",
]


class Language(StrEnum):
    """A language code (ISO 639-1), plus the one non-language sentinel.

    The member set is exactly the ``lang.search.SEARCH_LANGUAGES`` table — every
    language CiteNexus can *name*, including the ones it deliberately refuses to
    search because ADR-0011 carries no fixture for their script. A language must
    be nameable to be refused by name.
    """

    # --- latin ------------------------------------------------------------
    ENGLISH = "en"
    FRENCH = "fr"
    GERMAN = "de"
    SPANISH = "es"
    PORTUGUESE = "pt"
    ITALIAN = "it"
    DUTCH = "nl"
    POLISH = "pl"
    TURKISH = "tr"
    VIETNAMESE = "vi"
    INDONESIAN = "id"
    SWAHILI = "sw"
    # --- other claimed scripts --------------------------------------------
    RUSSIAN = "ru"
    UKRAINIAN = "uk"
    GREEK = "el"
    HEBREW = "he"
    ARABIC = "ar"
    PERSIAN = "fa"
    URDU = "ur"
    HINDI = "hi"
    MARATHI = "mr"
    NEPALI = "ne"
    BENGALI = "bn"
    ASSAMESE = "as"
    TAMIL = "ta"
    THAI = "th"
    KOREAN = "ko"
    CHINESE = "zh"
    JAPANESE = "ja"
    # --- known, NAMED, and not supported (ADR-0011 has no fixture) ----------
    TELUGU = "te"
    KANNADA = "kn"
    MALAYALAM = "ml"
    GUJARATI = "gu"
    PUNJABI = "pa"
    ODIA = "or"
    SINHALA = "si"
    KHMER = "km"
    LAO = "lo"
    BURMESE = "my"
    GEORGIAN = "ka"
    ARMENIAN = "hy"

    # --- the sentinel, not a language --------------------------------------
    #: "detect it from my question". Named here so it is discoverable next to
    #: the real codes; deliberately ABSENT from ``SEARCH_LANGUAGES``, so asking
    #: to *search* ``"auto"`` still raises "unknown search language" as before.
    AUTO = "auto"


class Script(StrEnum):
    """A writing system, as classified by ``tokenize._SCRIPT_RANGES``.

    Three tiers, per ADR-0011 — the enum names all three, because naming is what
    turns a silent half-service into a precise refusal:

    - claimed and fixture-backed (``tokenize.SUPPORTED_SCRIPTS``);
    - named by the range table but unclaimed — tokenized by a deliberate
      segmentation choice, reported via ``unsupported_scripts``;
    - :attr:`UNKNOWN` — outside the table entirely, so it produces no tokens.
    """

    ARABIC = "arabic"
    ARMENIAN = "armenian"
    BENGALI = "bengali"
    CYRILLIC = "cyrillic"
    DEVANAGARI = "devanagari"
    GEORGIAN = "georgian"
    GREEK = "greek"
    GUJARATI = "gujarati"
    GURMUKHI = "gurmukhi"
    HAN = "han"
    HANGUL = "hangul"
    HEBREW = "hebrew"
    HIRAGANA = "hiragana"
    KANNADA = "kannada"
    KATAKANA = "katakana"
    KHMER = "khmer"
    LAO = "lao"
    LATIN = "latin"
    MALAYALAM = "malayalam"
    MYANMAR = "myanmar"
    ORIYA = "oriya"
    SINHALA = "sinhala"
    TAMIL = "tamil"
    TELUGU = "telugu"
    THAI = "thai"

    #: Script-neutral characters — digits, combining diacriticals. They inherit
    #: the script of the run they sit in and carry no claim of their own.
    COMMON = "common"
    #: Outside the range table. Reported as a capability signal, never tokenized.
    UNKNOWN = "unknown"


#: The sentinel, re-exported under its short name for ``from ... import AUTO``.
AUTO = Language.AUTO

# --------------------------------------------------------------------------- #
# Type aliases.
#
# ``*Like`` is what LIBRARY signatures take: both forms, no narrowing, no break
# for anyone on 0.10.1. ``*Code`` is the opt-in strict alias for CALLER code —
# it rejects ``"tamiil"`` at type-check time. See the module docstring.
# --------------------------------------------------------------------------- #

LanguageLike = Language | str
ScriptLike = Script | str

LanguageCode = (
    Language
    | Literal[
        "en",
        "fr",
        "de",
        "es",
        "pt",
        "it",
        "nl",
        "pl",
        "tr",
        "vi",
        "id",
        "sw",
        "ru",
        "uk",
        "el",
        "he",
        "ar",
        "fa",
        "ur",
        "hi",
        "mr",
        "ne",
        "bn",
        "as",
        "ta",
        "th",
        "ko",
        "zh",
        "ja",
        "te",
        "kn",
        "ml",
        "gu",
        "pa",
        "or",
        "si",
        "km",
        "lo",
        "my",
        "ka",
        "hy",
        "auto",
    ]
)

ScriptCode = (
    Script
    | Literal[
        "arabic",
        "armenian",
        "bengali",
        "cyrillic",
        "devanagari",
        "georgian",
        "greek",
        "gujarati",
        "gurmukhi",
        "han",
        "hangul",
        "hebrew",
        "hiragana",
        "kannada",
        "katakana",
        "khmer",
        "lao",
        "latin",
        "malayalam",
        "myanmar",
        "oriya",
        "sinhala",
        "tamil",
        "telugu",
        "thai",
        "common",
        "unknown",
    ]
)


if __debug__:
    # The Literal aliases are hand-written (a Literal cannot be built from an
    # enum at type-check time), so a member added above without a literal below
    # would silently weaken the opt-in strict alias. Pin them together.
    from typing import get_args as _get_args

    _lang_literals = {a for arm in _get_args(LanguageCode) for a in _get_args(arm)}
    assert _lang_literals == {m.value for m in Language}, "LanguageCode literals drifted"
    _script_literals = {a for arm in _get_args(ScriptCode) for a in _get_args(arm)}
    assert _script_literals == {m.value for m in Script}, "ScriptCode literals drifted"
