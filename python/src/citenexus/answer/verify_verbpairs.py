"""The verb guard: two distinct acts on the same object.

Port of ``golang/answer/verify_verbpairs.go`` (ADR-0016). Applying for leave
and taking it are different acts, and the model reads them as one. A
:class:`VerbPair` is a closed class of two acts, each with its forms in any
language; a Dutch separable form is written "vraagt+aan". Refused when a unit
clause sharing an object word with the claim has the other act and the unit
never states the claim's act. Across languages without a glossary, no verdict.
Can only refuse.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from citenexus.answer import _gostr as go
from citenexus.answer import verify_answer as _va
from citenexus.answer import verify_conditions, verify_roles
from citenexus.answer.verify import is_stopword
from citenexus.answer.verify_guards_model import CONTEXT_STOP
from citenexus.tokenize import tokenize_v2

if TYPE_CHECKING:
    from citenexus.answer.verify_answer import EvidenceUnit
    from citenexus.answer.verify_guards import GuardConfig


@dataclass(frozen=True)
class VerbPair:
    """Two distinct acts, each with its forms in any language (lowercase;
    "verb+particle" for a Dutch separable verb)."""

    a: tuple[str, ...]
    b: tuple[str, ...]


#: Applying for something and taking or using it.
DEFAULT_VERB_PAIRS: tuple[VerbPair, ...] = (
    VerbPair(
        a=(
            "aanvragen",
            "aanvraagt",
            "aangevraagd",
            "aanvraag",
            "aanvragen",
            "application",
            "vraagt+aan",
            "vraag+aan",
            "vragen+aan",
            "apply",
            "applies",
            "applied",
            "request",
            "requests",
            "requested",
        ),
        b=(
            "opnemen",
            "opneemt",
            "opgenomen",
            "opname",
            "opnames",
            "neemt+op",
            "neem+op",
            "nemen+op",
            "take",
            "takes",
            "taken",
            "took",
            "use",
            "uses",
            "used",
        ),
    ),
)


def side_in(tokens: Sequence[str], pair: VerbPair) -> tuple[int, set[int]]:
    """0 (A), 1 (B), -1 none or both, and the matched tokens' positions."""

    def hit(forms: Sequence[str]) -> set[int]:
        at: set[int] = set()
        for f in forms:
            verb, sep, particle = f.partition("+")
            for i, t in enumerate(tokens):
                if t != verb:
                    continue
                if not sep:
                    at.add(i)
                    continue
                for k in range(i + 1, len(tokens)):
                    if tokens[k] == particle:
                        at.update((i, k))
                        break
        return at

    a, b = hit(pair.a), hit(pair.b)
    if a and not b:
        return 0, a
    if b and not a:
        return 1, b
    return -1, set()


def verb_pair_guard(
    claim: str,
    claim_language: str,
    eu: EvidenceUnit,
    pairs: Sequence[VerbPair],
    cfg: GuardConfig,
) -> str:
    """See the module docstring."""
    from citenexus.answer.glossary import is_empty

    cross = _va.cross_language(claim_language, eu.language)
    if cross and is_empty(cfg.gloss):
        return ""
    for pair in pairs:
        for cc in verify_roles.role_clauses(claim):
            ct = tokenize_v2(cc)
            side, verb_at = side_in(ct, pair)
            if side < 0:
                continue
            c = verify_conditions.Carrier(
                {t for i, t in enumerate(ct) if i not in verb_at},
                cross,
                verify_conditions.gloss_idx(cfg.gloss),
            )
            agrees, other = False, ""
            for uc in verify_roles.role_clauses(eu.text):
                ut = tokenize_v2(uc)
                us, u_at = side_in(ut, pair)
                if us < 0:
                    continue
                # The claim's act anywhere in the unit leaves room for it.
                if us == side:
                    agrees = True
                    continue
                shared = False
                for i, t in enumerate(ut):
                    if i in u_at or is_stopword(t) or t in CONTEXT_STOP or len(t) < 4:
                        continue
                    if c.carried(t)[0]:
                        shared = True
                        break
                if not shared:
                    continue
                if other == "":
                    for i in range(len(ut)):
                        if i in u_at:
                            other = ut[i]
                            break
            if not agrees and other != "":
                claim_verb = next((ct[i] for i in range(len(ct)) if i in verb_at), "")
                return (
                    f"verb guard: the claim says {go.quote(claim_verb)} "
                    f"where the passage says {go.quote(other)}"
                )
    return ""
