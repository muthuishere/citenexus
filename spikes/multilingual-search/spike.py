"""SPIKE — multilingual search fan-out (en / ta / te).

Offline, deterministic, no network, no keys. Measures, with the library's OWN
`tokenize_v2`, `unsupported_scripts`, `Bm25TextSearch`, `LexicalRetriever`,
`rrf_fuse` and `RetrievalEngine`:

  M1  Does an English question retrieve anything from a Tamil / Telugu corpus?
  M2  Is Telugu actually claimed by the ADR-0011 tokenizer?
  M3  What does fanning out to N languages cost (model calls, retrieval calls)?
  M4  Does RRF across N language-variant lists behave, or does one dominate?
  M5  Does a dead reformulation endpoint degrade or explode?

Run:  cd python && ./.venv/bin/python ../spikes/multilingual-search/spike.py
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "python" / "src"))

from citenexus.retrieve.engine import RetrievalEngine  # noqa: E402
from citenexus.retrieve.fusion import rrf_fuse  # noqa: E402
from citenexus.retrieve.lexical import LexicalRetriever  # noqa: E402
from citenexus.retrieve.reformulate import QueryReformulator  # noqa: E402
from citenexus.retrieve.types import Candidate  # noqa: E402
from citenexus.tokenize import (  # noqa: E402
    SUPPORTED_SCRIPTS,
    scripts_in,
    tokenize_v2,
    unsupported_scripts,
)

# --------------------------------------------------------------------------- #
# A tiny trilingual corpus. Same three facts, once per language. The English
# rows deliberately do NOT contain the answer to Q2/Q3 — only the Tamil and
# Telugu rows do — so "retrieved nothing" is a real miss, not a corpus artifact.
# --------------------------------------------------------------------------- #

CORPUS: list[dict[str, Any]] = [
    # --- English -----------------------------------------------------------
    {
        "eu_id": "en-1",
        "language": "en",
        "text": (
            "The employee shall not disclose confidential information to any third party "
            "during the term of employment or thereafter."
        ),
    },
    {
        "eu_id": "en-2",
        "language": "en",
        "text": (
            "This agreement is governed by the laws of the State of California and "
            "clause 14.2 survives termination."
        ),
    },
    {
        "eu_id": "en-3",
        "language": "en",
        "text": "Either party may terminate this agreement by giving written notice.",
    },
    # --- Tamil -------------------------------------------------------------
    {
        "eu_id": "ta-1",
        "language": "ta",
        "text": (
            "ஊழியர் ரகசியத் தகவலை மூன்றாம் தரப்பினருக்கு வெளியிடக் கூடாது, "
            "பணிக்காலத்தில் அல்லது அதற்குப் பிறகும்."
        ),
    },
    {
        "eu_id": "ta-2",
        "language": "ta",
        "text": "நோட்டீஸ் காலம் அறுபது நாட்கள் ஆகும். பிரிவு 14.2 நீடிக்கும்.",
    },
    {
        "eu_id": "ta-3",
        "language": "ta",
        "text": "இந்த ஒப்பந்தம் தமிழ்நாடு சட்டங்களின் கீழ் நிர்வகிக்கப்படுகிறது.",
    },
    # --- Telugu ------------------------------------------------------------
    {
        "eu_id": "te-1",
        "language": "te",
        "text": (
            "ఉద్యోగి రహస్య సమాచారాన్ని మూడవ పక్షానికి వెల్లడించకూడదు, "
            "ఉద్యోగ కాలంలో లేదా ఆ తర్వాత కూడా."
        ),
    },
    {
        "eu_id": "te-2",
        "language": "te",
        "text": "నోటీసు వ్యవధి తొంభై రోజులు. నిబంధన 14.2 కొనసాగుతుంది.",
    },
    {
        "eu_id": "te-3",
        "language": "te",
        "text": "ఈ ఒప్పందం తెలంగాణ చట్టాల ప్రకారం నిర్వహించబడుతుంది.",
    },
]

QUESTION_EN = "Can the employee disclose confidential information?"
# Human reference translations of the same question (what a reformulator emits).
QUESTION_TA = "ஊழியர் ரகசியத் தகவலை வெளியிட முடியுமா?"
QUESTION_TE = "ఉద్యోగి రహస్య సమాచారాన్ని వెల్లడించవచ్చా?"


class MemoryStore:
    """Minimal scan-capable VectorStore — enough for Bm25TextSearch."""

    def __init__(self, rows: Sequence[dict[str, Any]]) -> None:
        self._rows = [dict(r) for r in rows]
        self.scans = 0

    def scan(self, limit: int | None = None) -> list[dict[str, Any]]:
        self.scans += 1
        return list(self._rows[:limit] if limit else self._rows)

    # Unused by the lexical path, present for protocol shape.
    def upsert(self, rows: Sequence[dict[str, Any]]) -> None:  # pragma: no cover
        self._rows.extend(dict(r) for r in rows)

    def search(self, *a: Any, **kw: Any) -> list[dict[str, Any]]:  # pragma: no cover
        return []

    def delete_document(self, document_id: str) -> None:  # pragma: no cover
        pass


class CountingRetriever:
    """Wraps a retriever and counts calls — the fan-out cost meter."""

    plugin_version = "counting-v1"

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.calls: list[str] = []

    def retrieve(self, query: str, k: int) -> list[Candidate]:
        self.calls.append(query)
        return list(self._inner.retrieve(query, k))


class IdentityReranker:
    def rerank(self, query: str, candidates: Sequence[Candidate]) -> list[Candidate]:
        return list(candidates)


def rule(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


# --------------------------------------------------------------------------- #
# M1 — cross-lingual lexical recall today
# --------------------------------------------------------------------------- #


def m1_cross_lingual_recall() -> None:
    rule("M1  English question over a trilingual corpus — what comes back today?")

    store = MemoryStore(CORPUS)
    retriever = LexicalRetriever(store)

    q_tokens = set(tokenize_v2(QUESTION_EN))
    print(f"query tokens ({len(q_tokens)}): {sorted(q_tokens)}\n")

    print(f"{'eu_id':8} {'lang':5} {'shared query tokens':>20} {'jaccard':>9}")
    for row in CORPUS:
        toks = set(tokenize_v2(row["text"]))
        shared = q_tokens & toks
        jac = len(shared) / len(q_tokens | toks) if (q_tokens | toks) else 0.0
        print(f"{row['eu_id']:8} {row['language']:5} {len(shared):>20} {jac:>9.3f}")

    for label, query in (("en", QUESTION_EN), ("ta", QUESTION_TA), ("te", QUESTION_TE)):
        hits = retriever.retrieve(query, 5)
        by_lang: dict[str, int] = {}
        for c in hits:
            lang = next(r["language"] for r in CORPUS if r["eu_id"] == c.eu_id)
            by_lang[lang] = by_lang.get(lang, 0) + 1
        print(f"\nBM25 top-5 for the {label} phrasing: {len(hits)} hits, by language {by_lang}")
        print(f"  order: {[c.eu_id for c in hits]}")

    en_hits = retriever.retrieve(QUESTION_EN, 5)
    non_latin = [c.eu_id for c in en_hits if not c.eu_id.startswith("en-")]
    print(
        f"\n>>> M1: the English question retrieves {len(non_latin)} non-English EU(s) "
        f"out of {len(CORPUS) - 3} in the corpus. Lexical cross-lingual recall = "
        f"{len(non_latin) / (len(CORPUS) - 3):.0%}."
    )


# --------------------------------------------------------------------------- #
# M2 — is Telugu actually claimed?
# --------------------------------------------------------------------------- #


def m2_script_claims() -> None:
    rule("M2  Which of en / ta / te does the ADR-0011 tokenizer actually CLAIM?")

    for label, text in (("en", QUESTION_EN), ("ta", QUESTION_TA), ("te", QUESTION_TE)):
        scripts = scripts_in(text)
        gap = unsupported_scripts(text)
        toks = tokenize_v2(text)
        print(
            f"{label}: scripts={scripts} unsupported={gap} tokens={len(toks)} "
            f"claimed={'YES' if not gap else 'NO'}"
        )

    print(f"\nSUPPORTED_SCRIPTS ({len(SUPPORTED_SCRIPTS)}): {sorted(SUPPORTED_SCRIPTS)}")
    print(
        "\n>>> M2: 'telugu' is NOT in SUPPORTED_SCRIPTS — it is not even in the script\n"
        "    range table, so every Telugu character resolves to script 'unknown'.\n"
        "    NOTE the subtlety: tokenize_v2 still PRODUCES tokens for Telugu (unknown\n"
        "    scripts fall through the delimited path), so BM25 would half-work. That is\n"
        "    exactly the failure ADR-0011 forbids: serving an unclaimed script silently."
    )


# --------------------------------------------------------------------------- #
# M3 — fan-out cost
# --------------------------------------------------------------------------- #


class ScriptedTransport:
    """A fake chat transport: returns a canned translation, counts calls."""

    def __init__(self, table: dict[str, str], *, fail: bool = False) -> None:
        self._table = table
        self.calls = 0
        self._fail = fail

    def __call__(self, url: str, body: bytes, headers: dict[str, str]) -> bytes:
        import json

        self.calls += 1
        if self._fail:
            raise ConnectionError("reformulation endpoint is down")
        payload = json.loads(body)
        prompt = payload["messages"][0]["content"]
        out = next((v for k, v in self._table.items() if k in prompt), "")
        return json.dumps({"choices": [{"message": {"content": out}}]}).encode()


def m3_fanout_cost() -> None:
    rule("M3  Fan-out cost: model calls and retrieval calls per question")

    store = MemoryStore(CORPUS)
    counting = CountingRetriever(LexicalRetriever(store))
    engine = RetrievalEngine([counting], IdentityReranker())

    # One reformulator per target language (what the generalised design does).
    transport = ScriptedTransport({QUESTION_EN: QUESTION_TA})
    ref = QueryReformulator(base_url="http://fake", model="small", transport=transport)

    for _ in range(3):  # ask(), retrieve(), evaluate() row — same question
        ref.reformulate(QUESTION_EN)
    print(f"3 reformulations of the SAME query -> {transport.calls} model call(s) (cache works)")

    n_langs = 3
    n_retrievers = 1
    engine.retrieve(QUESTION_EN, 5, extra_queries=(QUESTION_TA, QUESTION_TE))
    print(f"fan-out to {n_langs} languages -> {len(counting.calls)} retriever invocation(s)")
    print(f"  queries seen by the retriever: {counting.calls}")
    print(
        f"\n>>> M3: per DISTINCT question, cost = (N-1) cached model calls "
        f"[N={n_langs} incl. the original, which is never translated]\n"
        f"    + N x R retrieval calls [R={n_retrievers} retrievers here; the real wiring "
        f"has vector+lexical+structure = 3, i.e. {n_langs * 3} calls].\n"
        "    Latency: retrievals are independent and embarrassingly parallel; the model\n"
        "    calls are the serial floor and they are cache-amortised to ~0 on repeat."
    )


# --------------------------------------------------------------------------- #
# M4 — does RRF let one language dominate?
# --------------------------------------------------------------------------- #


def _lists_per_language() -> dict[str, list[Candidate]]:
    store = MemoryStore(CORPUS)
    retriever = LexicalRetriever(store)
    return {
        "en": retriever.retrieve(QUESTION_EN, 5),
        "ta": retriever.retrieve(QUESTION_TA, 5),
        "te": retriever.retrieve(QUESTION_TE, 5),
    }


def m4_fusion_balance() -> None:
    rule("M4  RRF across N language-variant lists — dominance and determinism")

    per_lang = _lists_per_language()
    for lang, lst in per_lang.items():
        print(f"  {lang} list ({len(lst)}): {[c.eu_id for c in lst]}")

    fused = rrf_fuse(list(per_lang.values()))
    print(f"\nfused ({len(fused)}): {[(c.eu_id, round(c.score, 5)) for c in fused]}")

    top5 = fused[:5]
    share: dict[str, int] = {}
    for c in top5:
        share[c.eu_id[:2]] = share.get(c.eu_id[:2], 0) + 1
    print(f"top-5 share by language: {share}")

    # Determinism: fuse in a different input order, expect the same output order.
    reordered = rrf_fuse([per_lang["te"], per_lang["en"], per_lang["ta"]])
    same = [c.eu_id for c in fused] == [c.eu_id for c in reordered]
    print(f"input-order independent: {same}")

    # An empty list (a language that found nothing) must not perturb.
    with_empty = rrf_fuse([*per_lang.values(), []])
    print(
        "an empty per-language list is inert: "
        f"{[c.eu_id for c in fused] == [c.eu_id for c in with_empty]}"
    )

    # Degenerate case: one language returns MANY, others few.
    flood = [
        Candidate(eu_id=f"flood-{i}", score=1.0 - i * 0.01, signal=per_lang["en"][0].signal)
        for i in range(20)
    ]
    fused_flood = rrf_fuse([flood, per_lang["ta"], per_lang["te"]])
    top10 = [c.eu_id for c in fused_flood[:10]]
    flooded = sum(1 for e in top10 if e.startswith("flood-"))
    print(f"\nflood test: a 20-hit list vs two 3-hit lists -> {flooded}/10 of the fused top-10")
    print(
        ">>> M4: RRF is rank-based, so a language's INFLUENCE is bounded by 1/(k+rank+1)\n"
        "    per list, not by its score scale. A verbose language cannot outbid a\n"
        "    confident one; it can only fill the tail. But note the real asymmetry:\n"
        "    a language whose list is EMPTY contributes nothing, which is precisely\n"
        "    why an unsupported script must refuse rather than silently return []."
    )


# --------------------------------------------------------------------------- #
# M5 — dead endpoint
# --------------------------------------------------------------------------- #


def m5_dead_endpoint() -> None:
    rule("M5  A dead reformulation endpoint")

    transport = ScriptedTransport({}, fail=True)
    ref = QueryReformulator(base_url="http://dead", model="small", transport=transport)
    out = [ref.reformulate(QUESTION_EN) for _ in range(5)]
    print(f"5 calls against a dead endpoint -> results {out}, transport hits {transport.calls}")

    store = MemoryStore(CORPUS)
    counting = CountingRetriever(LexicalRetriever(store))
    engine = RetrievalEngine([counting], IdentityReranker())
    hits = engine.retrieve(QUESTION_EN, 5, extra_queries=())
    print(f"retrieval with zero reformulations still works: {len(hits)} hits")
    print(
        ">>> M5: failures are cached too, so a dead endpoint costs ONE attempt per\n"
        "    distinct query and degrades to single-query retrieval — today's behaviour."
    )


def m6_recall_lift() -> None:
    rule("M6  Recall@5 for the SAME English question, before vs after fan-out")

    # Gold: the three EUs that actually answer "can the employee disclose?"
    gold = {"en-1", "ta-1", "te-1"}

    store = MemoryStore(CORPUS)
    engine = RetrievalEngine([LexicalRetriever(store)], IdentityReranker())

    before = engine.retrieve(QUESTION_EN, 5)
    after = engine.retrieve(QUESTION_EN, 5, extra_queries=(QUESTION_TA, QUESTION_TE))

    hit_before = {c.eu_id for c in before} & gold
    hit_after = {c.eu_id for c in after} & gold
    print(f"before: {[c.eu_id for c in before]}  recall@5 = {len(hit_before)}/{len(gold)}")
    print(f"after : {[c.eu_id for c in after]}  recall@5 = {len(hit_after)}/{len(gold)}")
    print(
        f"\n>>> M6: recall@5 {len(hit_before)}/{len(gold)} -> {len(hit_after)}/{len(gold)}. "
        "The original English query is retained, so every EU\n"
        "    it already found is still found — fan-out is strictly additive at retrieval."
    )

    # And the honest cost: fan-out also drags in CONFLICTING evidence.
    conflict = engine.retrieve(
        "What is the notice period?",
        5,
        extra_queries=("நோட்டீஸ் காலம் என்ன?", "నోటీసు వ్యవధి ఎంత?"),
    )
    print(
        f"\nconflict probe: {[c.eu_id for c in conflict]} — ta-2 says 60 days, "
        "te-2 says 90 days.\n    Fan-out surfaces a conflict that the single-language "
        "query never saw. Per ADR-0007\n    that is correct behaviour, but it means "
        "abstention can RISE, not only fall."
    )


def main() -> None:
    m1_cross_lingual_recall()
    m2_script_claims()
    m3_fanout_cost()
    m4_fusion_balance()
    m5_dead_endpoint()
    m6_recall_lift()
    print("\nspike complete.")


if __name__ == "__main__":
    main()
