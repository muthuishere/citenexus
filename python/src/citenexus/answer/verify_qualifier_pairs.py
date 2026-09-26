"""Bilingual qualifier pairs, bound to a number.

Port of ``golang/answer/verify_qualifier_pairs.go`` (ADR-0016). A pair is a
language-independent class (bruto/gross ⇄ netto/net). A number anchors the
comparison: the claim's number binds to the nearest qualifier form within
``QUALIFIER_NUMBER_WINDOW`` words; each unit clause holding the same number
binds its own. Refused when no such unit clause carries the claim's side and at
least one carries the other. Without a number nothing is compared.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from citenexus.answer import _gostr as go
from citenexus.answer import verify_answer as _va
from citenexus.answer import verify_roles
from citenexus.answer.numbers import numbers_in
from citenexus.answer.verify_guards_model import any_form

if TYPE_CHECKING:
    from citenexus.answer.verify_answer import EvidenceUnit


@dataclass(frozen=True)
class QualifierPair:
    """Two opposite qualifiers, each with its forms in any language."""

    a: tuple[str, ...]
    b: tuple[str, ...]


#: gross/net, permanent/temporary contract, full/part time.
DEFAULT_QUALIFIER_PAIRS: tuple[QualifierPair, ...] = (
    QualifierPair(a=("bruto", "gross"), b=("netto", "net")),
    QualifierPair(
        a=("vast", "vaste", "permanent", "indefinite"), b=("tijdelijk", "tijdelijke", "temporary")
    ),
    QualifierPair(
        a=("voltijd", "voltijds", "fulltime", "full-time"),
        b=("deeltijd", "deeltijds", "parttime", "part-time"),
    ),
)

QUALIFIER_NUMBER_WINDOW = 3


def side_near(words: Sequence[str], i: int, pair: QualifierPair) -> tuple[int, str]:
    """Which side (0 = A, 1 = B, -1 none) the nearest form within the window of
    word i carries, and the form."""
    for d in range(QUALIFIER_NUMBER_WINDOW + 1):
        for j in (i - d, i + d):
            if j < 0 or j >= len(words):
                continue
            w = words[j]
            a, b = any_form(w, pair.a), any_form(w, pair.b)
            if a and not b:
                return 0, w
            if b and not a:
                return 1, w
    return -1, ""


def lower_words(clause: str) -> list[str]:
    return [go.lower(w.strip(verify_roles.ROLE_TRIM)) for w in _va.LIST_LEAD_TOKEN.findall(clause)]


def number_word_keys(clause: str, language: str) -> dict[int, list[str]]:
    """Per word index, the ADR-0015 keys of its numbers."""
    out: dict[int, list[str]] = {}
    for i, w in enumerate(_va.LIST_LEAD_TOKEN.findall(clause)):
        for m in numbers_in(w, language):
            out.setdefault(i, []).append(m.reading.key)
    return out


def qualifier_pair_guard(
    claim: str, claim_language: str, eu: EvidenceUnit, pairs: Sequence[QualifierPair]
) -> str:
    """See the module docstring."""
    unit = [
        (lower_words(c), number_word_keys(c, eu.language))
        for c in verify_roles.role_clauses(eu.text)
    ]
    for c in verify_roles.role_clauses(claim):
        words = lower_words(c)
        for i, keys in sorted(number_word_keys(c, claim_language).items()):
            for pair in pairs:
                side, form = side_near(words, i, pair)
                if side < 0:
                    continue
                agrees, other = False, ""
                for uwords, ukeys_by_word in unit:
                    for j, ukeys in sorted(ukeys_by_word.items()):
                        if not shares_key(keys, ukeys):
                            continue
                        # The claim's side anywhere in a clause holding the number
                        # agrees; the other side counts only right at the number.
                        if clause_has_side(uwords, side, pair):
                            agrees = True
                            continue
                        us, uform = side_near(uwords, j, pair)
                        if us >= 0 and us != side and other == "":
                            other = uform
                if not agrees and other != "":
                    return (
                        f"qualifier guard: the claim says {go.quote(form)} "
                        f"where the passage says {go.quote(other)}"
                    )
    return ""


def shares_key(a: Sequence[str], b: Sequence[str]) -> bool:
    return any(x == y for x in a for y in b)


def clause_has_side(words: Sequence[str], side: int, pair: QualifierPair) -> bool:
    forms = pair.b if side == 1 else pair.a
    return any(any_form(w, forms) for w in words)
