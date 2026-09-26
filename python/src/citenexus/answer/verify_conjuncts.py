"""The conjunct-token guard: a claim that drops a conjunct of the unit's
condition which holds a LANGUAGE-FREE token — a number or a proper name.

Port of ``golang/answer/verify_conjuncts.go`` (ADR-0016). The condition guard
judges a word missing across languages only through the caller's glossary; a
number ("3 jaar in dienst") or a name reads the same in every language, so a
conjunct holding one can be judged without it. Only language-free tokens
decide. Can only refuse.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from citenexus.answer import _gostr as go
from citenexus.answer import verify_answer as _va
from citenexus.answer import verify_conditions, verify_parties
from citenexus.answer.numbers import numbers_in
from citenexus.answer.verify_guards_model import number_word_value, soft_join
from citenexus.tokenize import tokenize_v2

if TYPE_CHECKING:
    from citenexus.answer.verify_answer import EvidenceUnit
    from citenexus.answer.verify_guards import GuardConfig

CONJUNCT_OPENER = go.compile_go(
    r"\b(mits|indien|tenzij|zolang|op voorwaarde dat|alleen als|provided that|provided"
    r"|unless|only if|as long as)\b",
    ignore_case=True,
)
CONJUNCT_SPLIT = go.compile_go(r",|\b(?:en|and)\b", ignore_case=True)
CONJUNCT_COORDINATOR = go.compile_go(r"\b(?:en|and)\b", ignore_case=True)
TOT_EN_MET_WORDS = go.compile_go(r"\btot en met\b|\bup to and including\b", ignore_case=True)


def language_free(text: str, language: str) -> set[str]:
    """The number keys ("#…") and proper names ("@…") of a text."""
    out = {"#" + m.reading.key for m in numbers_in(text, language)}
    words = go.fields(text)
    for i, raw in enumerate(words):
        w = raw.strip(".,;:()\"'!?")
        if i == 0 or len(w) < 3 or not go.is_upper(w[0]):
            continue
        prev = words[i - 1]
        if prev.endswith((".", ":")):
            continue  # a sentence start inside the text
        out.add("@" + go.lower(w))
    return out


def claim_carries_token(tok: str, claim_free: set[str], claim_tokens: list[str]) -> bool:
    """The claim holds the token — the number key, spelled out, or the name."""
    if tok in claim_free:
        return True
    if tok.startswith("@"):
        return tok[1:] in claim_tokens
    return any("#" + (number_word_value(t) or "\x00") == tok for t in claim_tokens)


def condition_conjuncts(sentence: str, language: str) -> list[set[str]] | None:
    """The conjuncts of a sentence's condition, each with its language-free
    tokens; None when the sentence has none, or only one."""
    loc = CONJUNCT_OPENER.search(sentence)
    if loc is None:
        return None
    span = TOT_EN_MET_WORDS.sub("tot_en_met", sentence[loc.end() :])
    segs = span.split(",")
    while len(segs) > 1 and not CONJUNCT_COORDINATOR.search(segs[-1]):
        segs = segs[:-1]
    out: list[set[str]] = []
    parts = 0
    for p in go.split(CONJUNCT_SPLIT, ",".join(segs)):
        if go.trim_space(p) == "":
            continue
        parts += 1
        out.append(language_free(p, language))
    if parts < 2:
        return None
    return out


def conjunct_token_guard(
    claim: str, claim_language: str, eu: EvidenceUnit, cfg: GuardConfig
) -> str:
    """See the module docstring."""
    if cfg.fragment:
        return ""
    sentences = go.split(verify_parties.SENTENCE_BREAK, soft_join(eu.text))
    claim_tokens = tokenize_v2(claim)
    claim_free = language_free(claim, claim_language)

    # Which sentence the claim follows. Language-free first.
    free = [language_free(s, eu.language) for s in sentences]
    best = -1
    for i in range(len(sentences)):
        for tok in claim_free:
            if tok not in free[i]:
                continue
            unique = all(not (j != i and tok in free[j]) for j in range(len(sentences)))
            if unique:
                if best >= 0 and best != i:
                    return ""  # anchored to two sentences: no verdict
                best = i
    if best < 0:
        cross = _va.cross_language(claim_language, eu.language)
        c = verify_conditions.Carrier(
            set(claim_tokens), cross, verify_conditions.gloss_idx(cfg.gloss)
        )
        best_n, tie = 0, False
        for i, s in enumerate(sentences):
            n = 0
            seen: set[str] = set()
            for t in tokenize_v2(s):
                has, _ = c.carried(t)
                if has and verify_conditions.condition_content(t) and t not in seen:
                    seen.add(t)
                    n += 1
            if n > best_n:
                best, best_n, tie = i, n, False
            elif n == best_n and n > 0:
                tie = True
        if best_n < 2 or tie:
            return ""
    for conj in condition_conjuncts(sentences[best], eu.language) or []:
        if not conj:
            continue  # no language-free token: no verdict on this conjunct
        missing = ""
        for tok in conj:
            if claim_carries_token(tok, claim_free, claim_tokens):
                missing = ""
                break
            if missing == "" or tok < missing:
                missing = tok
        if missing != "":
            return (
                "condition guard: the passage's condition includes "
                f"{go.quote(missing.lstrip('#@'))} and the claim drops that part"
            )
    return ""
