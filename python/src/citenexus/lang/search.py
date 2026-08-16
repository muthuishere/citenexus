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

    code: str
    name: str
    scripts: tuple[str, ...]

    @property
    def unsupported(self) -> tuple[str, ...]:
        """The scripts this language needs that ADR-0011 does not claim."""
        return tuple(s for s in self.scripts if s not in SUPPORTED_SCRIPTS)

    @property
    def is_supported(self) -> bool:
        return not self.unsupported


def _lang(code: str, name: str, *scripts: str) -> tuple[str, SearchLanguage]:
    return code, SearchLanguage(code=code, name=name, scripts=scripts)


# The table is deliberately explicit and deliberately includes languages we
# CANNOT serve. A language must be nameable to be refused by name; dropping
# Telugu from the table would turn a precise "telugu is not supported" into a
# vague "unknown language code", which is a worse answer to the same question.
SEARCH_LANGUAGES: Mapping[str, SearchLanguage] = dict(
    (
        # --- latin ---------------------------------------------------------
        _lang("en", "English", "latin"),
        _lang("fr", "French", "latin"),
        _lang("de", "German", "latin"),
        _lang("es", "Spanish", "latin"),
        _lang("pt", "Portuguese", "latin"),
        _lang("it", "Italian", "latin"),
        _lang("nl", "Dutch", "latin"),
        _lang("pl", "Polish", "latin"),
        _lang("tr", "Turkish", "latin"),
        _lang("vi", "Vietnamese", "latin"),
        _lang("id", "Indonesian", "latin"),
        _lang("sw", "Swahili", "latin"),
        # --- other claimed scripts ------------------------------------------
        _lang("ru", "Russian", "cyrillic"),
        _lang("uk", "Ukrainian", "cyrillic"),
        _lang("el", "Greek", "greek"),
        _lang("he", "Hebrew", "hebrew"),
        _lang("ar", "Arabic", "arabic"),
        _lang("fa", "Persian", "arabic"),
        _lang("ur", "Urdu", "arabic"),
        _lang("hi", "Hindi", "devanagari"),
        _lang("mr", "Marathi", "devanagari"),
        _lang("ne", "Nepali", "devanagari"),
        _lang("bn", "Bengali", "bengali"),
        _lang("as", "Assamese", "bengali"),
        _lang("ta", "Tamil", "tamil"),
        _lang("th", "Thai", "thai"),
        _lang("ko", "Korean", "hangul"),
        _lang("zh", "Chinese", "han"),
        _lang("ja", "Japanese", "han", "hiragana", "katakana"),
        # --- known, NAMED, and not supported (ADR-0011 has no fixture) --------
        _lang("te", "Telugu", "telugu"),
        _lang("kn", "Kannada", "kannada"),
        _lang("ml", "Malayalam", "malayalam"),
        _lang("gu", "Gujarati", "gujarati"),
        _lang("pa", "Punjabi", "gurmukhi"),
        _lang("or", "Odia", "oriya"),
        _lang("si", "Sinhala", "sinhala"),
        _lang("km", "Khmer", "khmer"),
        _lang("lo", "Lao", "lao"),
        _lang("my", "Burmese", "myanmar"),
        _lang("ka", "Georgian", "georgian"),
        _lang("hy", "Armenian", "armenian"),
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

    def __init__(self, message: str, *, language: str | None = None, script: str | None = None):
        super().__init__(message)
        self.language = language
        self.script = script


def resolve_search_languages(codes: Iterable[str]) -> tuple[SearchLanguage, ...]:
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
                f"{missing[0]!r}, which this tokenizer does not claim (ADR-0011). "
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
