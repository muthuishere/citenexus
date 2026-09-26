"""Glossary entries with lemmas, separable particles and classes.

Port of ``golang/answer/glossary.go`` (ADR-0016). ``VerifyOptions.glossary`` is
a list of term pairs; a pair matches only the surface forms it names. A
:class:`GlossaryEntry` adds what a matcher needs to read a form through its
lemma: every NL form of a lemma translates to every EN form of it, a split
separable verb matches only with its particle, and a class (party | group |
verb | hedge | qualifier) says whether a noun is a party at all.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from citenexus.answer import _gostr as go


@dataclass(frozen=True)
class GlossaryEntry:
    """One NL/EN surface pair with its lemmas, particle and class."""

    nl: str
    en: str
    lemma_nl: str = ""
    lemma_en: str = ""
    sep: str = ""
    class_: str = ""


class GlossaryError(ValueError):
    """A glossary file that cannot be read."""


def parse_glossary_tsv(lines: Iterable[str]) -> list[GlossaryEntry]:
    """Read a tab-separated glossary with a header row (nl, en, lemma_nl,
    lemma_en, sep, class; unknown columns ignored)."""
    col: dict[str, int] | None = None
    out: list[GlossaryEntry] = []
    for raw in lines:
        line = raw.rstrip("\n").removesuffix("\r")
        f = line.split("\t")
        if col is None:
            col = {go.lower(go.trim_space(h)): i for i, h in enumerate(f)}
            if "nl" not in col:
                raise GlossaryError("answer: glossary header has no nl column")
            if "en" not in col:
                raise GlossaryError("answer: glossary header has no en column")
            continue

        def get(name: str, f: list[str] = f, col: dict[str, int] = col) -> str:
            i = col.get(name)
            if i is not None and i < len(f):
                return go.lower(go.trim_space(f[i]))
            return ""

        e = GlossaryEntry(
            nl=get("nl"),
            en=get("en"),
            lemma_nl=get("lemma_nl"),
            lemma_en=get("lemma_en"),
            sep=get("sep"),
            class_=get("class"),
        )
        if e.nl and e.en:
            out.append(e)
    return out


def _append_unique(items: list[str], *new: str) -> None:
    for item in new:
        if item not in items:
            items.append(item)


def expand_glossary(
    entries: Sequence[GlossaryEntry],
) -> tuple[list[tuple[str, str]], dict[str, str], dict[str, str]]:
    """Entries as term pairs, plus the particle and class of each NL form."""
    pairs: list[tuple[str, str]] = []
    sep: dict[str, str] = {}
    cls: dict[str, str] = {}
    nl_forms: dict[str, list[str]] = {}
    en_forms: dict[str, list[str]] = {}
    plain: set[str] = set()  # forms that are also a verb on their own
    for e in entries:
        pairs.append((e.nl, e.en))
        if e.sep:
            sep[e.nl] = e.sep
        else:
            plain.add(e.nl)
        if e.class_:
            cls[e.nl] = e.class_
        if not e.lemma_nl:
            continue
        _append_unique(nl_forms.setdefault(e.lemma_nl, []), e.nl, e.lemma_nl)
        _append_unique(en_forms.setdefault(e.lemma_nl, []), e.en)
        if e.lemma_en:
            _append_unique(en_forms[e.lemma_nl], e.lemma_en)
        if e.class_:
            cls[e.lemma_nl] = e.class_
    # A form that is also a plain verb needs no particle.
    for form in plain:
        sep.pop(form, None)
    for lemma, nls in nl_forms.items():
        for n in nls:
            for en in en_forms.get(lemma, []):
                pairs.append((n, en))
    return pairs, sep, cls


@dataclass(frozen=True)
class SepKey:
    rest: str  # the key after the particle: "sluiten" in "afsluiten"
    trs: list[list[str]]


@dataclass(frozen=True)
class PreparedGlossary:
    """A glossary indexed once; immutable, safe to share across calls."""

    #: A single-token term -> its translations.
    index: dict[str, list[list[str]]] = field(default_factory=dict)
    #: A split separable form -> its particle.
    sep_of: dict[str, str] = field(default_factory=dict)
    #: An NL form or lemma -> its class.
    class_of: dict[str, str] = field(default_factory=dict)
    #: Particle -> joined separable forms under it.
    sep_keys: dict[str, list[SepKey]] = field(default_factory=dict)


def prepare_glossary(
    pairs: Sequence[tuple[str, str]] | None, entries: Sequence[GlossaryEntry] | None
) -> PreparedGlossary:
    """Index term pairs and glossary entries once."""
    from citenexus.answer.verify_conditions import glossary_index
    from citenexus.answer.verify_parties import SEPARABLE_PARTICLES

    entry_pairs, sep, cls = expand_glossary(entries or ())
    index = glossary_index([*(pairs or ()), *entry_pairs])
    sep_keys: dict[str, list[SepKey]] = {}
    for key, trs in index.items():
        for p in sorted(SEPARABLE_PARTICLES):
            if key.startswith(p) and go.blen(key) > go.blen(p) + 2:
                sep_keys.setdefault(p, []).append(SepKey(rest=key[len(p) :], trs=trs))
    return PreparedGlossary(index=index, sep_of=sep, class_of=cls, sep_keys=sep_keys)


def is_empty(g: PreparedGlossary | None) -> bool:
    return g is None or not g.index
