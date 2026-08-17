"""Search-language capability table for the `search_languages` fan-out (ADR-0013).

An English question over a Tamil corpus retrieves **nothing**: the token sets are
disjoint, so BM25's ``tf`` is zero for every query term. Measured 0/6 in
``spikes/multilingual-search/``. The fix is to reformulate the question into each
requested language and fuse the retrievals — but only for languages the library
can actually tokenize.

That "actually" is what this module is for. ADR-0011's ``SUPPORTED_SCRIPTS`` is
the claim; this table maps an ISO-639-1 code to the script(s) it is written in and
checks the claim before anything is spent. Two failure modes it exists to prevent:

- **The silent half-service.** Telugu is not in ADR-0011's script range table at
  all, so it classifies as ``"unknown"`` — yet ``tokenize_v2`` still emits tokens
  for it (unknown scripts take the delimited path). BM25 would return
  plausible-looking rankings for a script the library makes no claim about, and
  ``unsupported_scripts`` would report the useless label ``"unknown"``.
- **The empty result that looks like an answer.** Returning ``[]`` for a language
  we cannot search is indistinguishable from "the corpus does not contain this".

So an unsupported language **raises**, naming the language and the script, before
any model call. That is deliberate and it follows ``tokenize.py``'s own rule: a
capability gap is not an evidence judgement, and routing it through the abstention
channel is precisely what let the ASCII-only tokenizer hide.

Codes are **never guessed**. A code absent from the table raises too — inferring a
script from an unknown code is how a false claim gets made.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from citenexus.lang.codes import Language, LanguageLike, Script, ScriptLike
from citenexus.tokenize import SUPPORTED_SCRIPTS

__all__ = [
    "SEARCH_LANGUAGES",
    "SearchLanguage",
    "UnsupportedSearchLanguageError",
    "resolve_search_languages",
]


@dataclass(frozen=True)
class SearchLanguage:
    """One searchable language: its code, its prompt-facing name, its script(s)."""

    code: Language
    name: str
    scripts: tuple[Script, ...]

    @property
    def unsupported(self) -> tuple[Script, ...]:
        """The scripts this language needs that ADR-0011 does not claim."""
        return tuple(s for s in self.scripts if s not in SUPPORTED_SCRIPTS)

    @property
    def is_supported(self) -> bool:
        return not self.unsupported


def _lang(code: Language, name: str, *scripts: Script) -> tuple[Language, SearchLanguage]:
    return code, SearchLanguage(code=code, name=name, scripts=scripts)


# The table is deliberately explicit and deliberately includes languages we
# CANNOT serve. A language must be nameable to be refused by name; dropping
# Telugu from the table would turn a precise "telugu is not supported" into a
# vague "unknown language code", which is a worse answer to the same question.
# Keyed by ``LanguageLike`` (``Language | str``) on purpose: the runtime keys ARE
# ``Language`` members, but the annotation must keep ``SEARCH_LANGUAGES["ta"]``
# type-checking for every caller who already writes the plain code. Narrowing the
# key type to ``Language`` would make a published, working call site a type error.
SEARCH_LANGUAGES: Mapping[LanguageLike, SearchLanguage] = dict(
    (
        # --- latin ---------------------------------------------------------
        _lang(Language.ENGLISH, "English", Script.LATIN),
        _lang(Language.FRENCH, "French", Script.LATIN),
        _lang(Language.GERMAN, "German", Script.LATIN),
        _lang(Language.SPANISH, "Spanish", Script.LATIN),
        _lang(Language.PORTUGUESE, "Portuguese", Script.LATIN),
        _lang(Language.ITALIAN, "Italian", Script.LATIN),
        _lang(Language.DUTCH, "Dutch", Script.LATIN),
        _lang(Language.POLISH, "Polish", Script.LATIN),
        _lang(Language.TURKISH, "Turkish", Script.LATIN),
        _lang(Language.VIETNAMESE, "Vietnamese", Script.LATIN),
        _lang(Language.INDONESIAN, "Indonesian", Script.LATIN),
        _lang(Language.SWAHILI, "Swahili", Script.LATIN),
        # --- other claimed scripts ------------------------------------------
        _lang(Language.RUSSIAN, "Russian", Script.CYRILLIC),
        _lang(Language.UKRAINIAN, "Ukrainian", Script.CYRILLIC),
        _lang(Language.GREEK, "Greek", Script.GREEK),
        _lang(Language.HEBREW, "Hebrew", Script.HEBREW),
        _lang(Language.ARABIC, "Arabic", Script.ARABIC),
        _lang(Language.PERSIAN, "Persian", Script.ARABIC),
        _lang(Language.URDU, "Urdu", Script.ARABIC),
        _lang(Language.HINDI, "Hindi", Script.DEVANAGARI),
        _lang(Language.MARATHI, "Marathi", Script.DEVANAGARI),
        _lang(Language.NEPALI, "Nepali", Script.DEVANAGARI),
        _lang(Language.BENGALI, "Bengali", Script.BENGALI),
        _lang(Language.ASSAMESE, "Assamese", Script.BENGALI),
        _lang(Language.TAMIL, "Tamil", Script.TAMIL),
        _lang(Language.THAI, "Thai", Script.THAI),
        _lang(Language.KOREAN, "Korean", Script.HANGUL),
        _lang(Language.CHINESE, "Chinese", Script.HAN),
        _lang(Language.JAPANESE, "Japanese", Script.HAN, Script.HIRAGANA, Script.KATAKANA),
        # --- known, NAMED, and not supported (ADR-0011 has no fixture) --------
        _lang(Language.TELUGU, "Telugu", Script.TELUGU),
        _lang(Language.KANNADA, "Kannada", Script.KANNADA),
        _lang(Language.MALAYALAM, "Malayalam", Script.MALAYALAM),
        _lang(Language.GUJARATI, "Gujarati", Script.GUJARATI),
        _lang(Language.PUNJABI, "Punjabi", Script.GURMUKHI),
        _lang(Language.ODIA, "Odia", Script.ORIYA),
        _lang(Language.SINHALA, "Sinhala", Script.SINHALA),
        _lang(Language.KHMER, "Khmer", Script.KHMER),
        _lang(Language.LAO, "Lao", Script.LAO),
        _lang(Language.BURMESE, "Burmese", Script.MYANMAR),
        _lang(Language.GEORGIAN, "Georgian", Script.GEORGIAN),
        _lang(Language.ARMENIAN, "Armenian", Script.ARMENIAN),
    )
)


class UnsupportedSearchLanguageError(ValueError):
    """A requested search language cannot be served — a capability refusal.

    Deliberately an error and not an abstention. An abstention says *the evidence
    does not support this*; this says *we cannot look*. Collapsing the two is the
    failure ADR-0011 was written to end, so they do not share a channel.

    A ``ValueError`` subclass so existing ``except ValueError`` call sites keep
    behaving; ``language`` and ``script`` are carried for programmatic handling.
    """

    def __init__(
        self,
        message: str,
        *,
        language: LanguageLike | None = None,
        script: ScriptLike | None = None,
    ):
        super().__init__(message)
        self.language = language
        self.script = script


def resolve_search_languages(codes: Iterable[LanguageLike]) -> tuple[SearchLanguage, ...]:
    """The requested search languages, in caller order, de-duplicated.

    Raises ``UnsupportedSearchLanguageError`` — before any model call is made —
    for an empty request, an unknown code, or a language whose script ADR-0011
    does not claim.
    """
    resolved: list[SearchLanguage] = []
    seen: set[str] = set()
    for raw in codes:
        code = raw.strip().lower()
        if code in seen:
            continue
        language = SEARCH_LANGUAGES.get(code)
        if language is None:
            raise UnsupportedSearchLanguageError(
                f"unknown search language {raw!r}: language codes are never guessed. "
                f"Known codes: {', '.join(sorted(SEARCH_LANGUAGES))}",
                language=raw,
            )
        missing = language.unsupported
        if missing:
            raise UnsupportedSearchLanguageError(
                f"search language {code!r} ({language.name}) is written in "
                f"{str(missing[0])!r}, which this tokenizer does not claim (ADR-0011). "
                "Searching it would return plausible-looking results for a script "
                "the library makes no claim about, so it is refused instead. "
                f"Claimed scripts: {', '.join(sorted(SUPPORTED_SCRIPTS))}",
                language=code,
                script=missing[0],
            )
        seen.add(code)
        resolved.append(language)
    if not resolved:
        raise UnsupportedSearchLanguageError(
            "search_languages must name at least one language (default is ('en',))"
        )
    return tuple(resolved)
