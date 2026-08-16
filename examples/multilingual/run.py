"""CiteNexus MULTILINGUAL baseline — an English question over a Tamil/Telugu corpus.

The measurement
---------------
A twelve-document employment-policy corpus in three languages. The English
handbook is deliberately incomplete: it states the general rule and then says
"the regional annexure prevails" without ever stating the annexure's figure. The
figures live ONLY in the Tamil and Telugu annexures. So a question like

    "How much must a Chennai employee pay to buy out one unserved month?"

has exactly one grounded answer in the corpus (INR 45,000, Tamil clause 7.2),
and the question is asked in English. An English query shares zero BM25 tokens
with Tamil prose, so the lexical retriever contributes nothing at all, and the
dense retriever is left carrying the entire cross-lingual burden alone.

This script measures how far that gets you TODAY, before the multilingual
fan-out lands, so the fan-out's later numbers mean something. It reports, split
by the language the answer lives in:

  * answered vs abstained on Tamil-only questions
  * answered vs abstained on Telugu-only questions
  * answered vs abstained on English-answerable questions (the control)
  * abstention on the four questions the corpus cannot ground at all
  * groundedness rate, citation rate, expected-token support
  * per question: decision, cited document, and the LANGUAGE of the cited passage

Endpoints (the APPLICATION owns its environment; the library reads no env):
  embeddings + rerank -> Jina  (JINA_API_KEY)   jina-embeddings-v3 (cross-lingual)
  generation          -> Gemini (GEMINI_API_KEY) gemini-2.5-flash

Run:
  cd python && . .venv/bin/activate
  export JINA_API_KEY=...      # referenced by name; never printed
  export GEMINI_API_KEY=...
  python ../examples/multilingual/run.py
"""

from __future__ import annotations

import csv
import inspect
import json
import os
from collections import Counter
from pathlib import Path

from citenexus import CiteNexus, GeminiHttpEndpoint, OpenAIHttpEndpoint
from citenexus.answer.result import Decision, Result
from citenexus.config.schema import (
    CiteNexusConfig,
    EmbeddingConfig,
    LLMConfig,
    MultilingualConfig,
    ReformulationConfig,
    RerankerConfig,
    StorageConfig,
)
from citenexus.config.signals import Signal

# ===========================================================================
# THE ONE LINE.
#
# BASELINE (what this file measures): ("en",) -- the question is searched in the
# language it was asked in, which is what CiteNexus has always done. Every number
# in RESULTS.md was produced with this value.
#
# TODO(multilingual-fanout): when the search_languages fan-out lands, change the
# tuple below to ("en", "ta", "te") and re-run. Nothing else in this file needs
# to change; the reporting already splits results by evidence language, so the
# before/after tables line up column for column.
#
# CAVEAT, and it is not this file's to fix: ``citenexus.lang.search`` will RAISE
# UnsupportedSearchLanguageError on "te" until ADR-0011 adds telugu to
# SUPPORTED_SCRIPTS with a golden fixture (U+0C00-U+0C7F is currently a hole in
# the script range table, so Telugu classifies as "unknown"). Until then the
# runnable step is ("en", "ta"); the Telugu half of this corpus is measuring a
# CAPABILITY gap, not a retrieval gap, and RESULTS.md keeps the two apart.
# ===========================================================================
SEARCH_LANGUAGES: tuple[str, ...] = ("en", "ta", "te")

_HERE = Path(__file__).resolve().parent
_CORPUS = _HERE / "corpus"
_GOLDEN = _HERE / "golden.csv"
_OUT = _HERE / "results.json"

# document_id -> the language the document is written in. Declared by the
# curator, exactly like the law example's authority.csv: it is metadata about
# the source, not something the pipeline should have to guess.
DOC_LANGUAGE: dict[str, str] = {
    "01-en-leave-policy": "en",
    "02-en-notice-period-policy": "en",
    "03-en-probation-policy": "en",
    "04-en-confidentiality-policy": "en",
    "05-ta-chennai-leave-annexure": "ta",
    "06-ta-notice-buyout-annexure": "ta",
    "07-ta-maternity-creche-annexure": "ta",
    "08-ta-termination-appeal-annexure": "ta",
    "09-te-hyderabad-leave-annexure": "te",
    "10-te-probation-extension-annexure": "te",
    "11-te-confidentiality-annexure": "te",
    "12-te-shift-allowance-annexure": "te",
}

# Which probe classes make up each reported bucket.
_BUCKETS: dict[str, tuple[str, ...]] = {
    "Tamil-only": ("ta_only", "ta_only_exact_token", "ta_only_pdf"),
    "Telugu-only": ("te_only", "te_only_exact_token"),
    "English-answerable (control)": ("en",),
    "Ungroundable (must abstain)": ("none",),
}


def _require(*names: str) -> str:
    for name in names:
        val = os.environ.get(name)
        if val:
            return val
    raise SystemExit(f"Set one of these env vars (by name): {', '.join(names)}")


def _config() -> CiteNexusConfig:
    """Jina embeddings+rerank + Gemini generation. Keys read HERE, by the app."""
    jina = OpenAIHttpEndpoint(
        base_url=os.environ.get("CITENEXUS_EMBED_BASE_URL", "https://api.jina.ai/v1"),
        api_key=_require("JINA_API_KEY", "CITENEXUS_EMBED_API_KEY"),
    )
    gemini = GeminiHttpEndpoint(api_key=_require("GEMINI_API_KEY", "CITENEXUS_LLM_API_KEY"))
    base_uri = os.environ.get("CITENEXUS_BASE_URI", str(_HERE / ".citenexus-data"))
    return CiteNexusConfig(
        storage=StorageConfig(bucket=base_uri),
        # jina-embeddings-v3 and the v2 reranker are both multilingual and both
        # cover Tamil and Telugu. The gap this script measures is therefore NOT
        # "the model cannot read Tamil" -- it is that a single English query
        # vector has to reach Tamil prose unaided, with BM25 contributing zero.
        embedding=EmbeddingConfig(endpoint=jina, model="jina-embeddings-v3"),
        llm=LLMConfig(
            endpoint=gemini,
            model=os.environ.get("CITENEXUS_LLM_MODEL", "gemini-2.5-flash"),
            temperature=0.0,  # grounded answers are deterministic (spec 4b)
        ),
        reranker=RerankerConfig(
            enabled=True,
            endpoint=jina,  # one Jina connection serves embeddings AND rerank
            model="jina-reranker-v2-base-multilingual",
        ),
        # Answer in the query's language (§11a) -- so an English question gets an
        # English answer even when the only supporting passage is Tamil. The
        # citation itself stays verbatim in Tamil and is never translated in place.
        multilingual=MultilingualConfig(fallback_language="en"),
        # The fan-out needs a reformulator: a SMALL model rewrites the query into
        # each search language, the original is always retained, and the lists are
        # RRF-fused. Cached per (query, language), so N languages cost N-1 calls.
        reformulation=ReformulationConfig(
            enabled=True, endpoint=gemini, model="gemini-2.5-flash-lite"
        ),
        # Dense + sparse only. Keeping the surface to the two signals every RAG
        # has is what makes the cross-lingual gap legible rather than confounded.
        signals=(Signal.embedding, Signal.text),
    )


_ASK_TAKES_SEARCH_LANGUAGES = "search_languages" in inspect.signature(CiteNexus.ask).parameters


def _ask(rag: CiteNexus, question: str) -> Result:
    """Single ask site, so the fan-out is a one-constant change above."""
    if _ASK_TAKES_SEARCH_LANGUAGES:
        return rag.ask(question, search_languages=SEARCH_LANGUAGES)
    # The parameter does not exist yet in this build. That IS the baseline: the
    # question is searched only in the language it was asked in.
    return rag.ask(question)


def _cited_docs(result: Result) -> list[str]:
    seen: list[str] = []
    for s in result.sources:
        if s.document not in seen:
            seen.append(s.document)
    return seen


def _pct(n: int, d: int) -> str:
    return f"{(n / d * 100):.0f}%" if d else "n/a"


def main() -> None:
    rag = CiteNexus.from_config(_config())

    print("== Ingest ==")
    paths = sorted(p for p in _CORPUS.iterdir() if p.suffix in {".txt", ".pdf"})
    for path in paths:
        res = rag.ingest(path, document_id=path.stem)
        lang = DOC_LANGUAGE.get(path.stem, "?")
        print(f"   {path.stem:38} {path.suffix:5} lang={lang}  -> {res.status}")
    print(f"   {len(paths)} documents ingested")

    with _GOLDEN.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    per_q = []
    print(f"\n== Ask  (search_languages={SEARCH_LANGUAGES}) ==")
    for row in rows:
        q = row["question"]
        result = _ask(rag, q)
        decision = result.evidence.decision.value
        cited = _cited_docs(result)
        top = cited[0] if cited else None
        cited_langs = sorted({DOC_LANGUAGE.get(d, "?") for d in cited})
        passage_langs = sorted({s.passage_language for s in result.sources if s.passage_language})

        correct = [d for d in (row.get("correct_docs") or "").split("|") if d]
        expected = (row.get("expected") or "").strip()
        # Did the answer actually carry the number the question turns on? This is
        # the check that separates "answered" from "answered CORRECTLY", and it
        # matters most for the exact-token probes.
        token_ok = bool(expected) and expected in (result.answer or "")

        rec = {
            "question": q,
            "probe": row.get("probe") or "",
            "expect_decision": row.get("expect_decision"),
            "expected": expected,
            "decision": decision,
            "answer": result.answer,
            "answer_language": result.answer_language,
            "cited_docs": cited,
            "top_doc": top,
            "cited_doc_languages": cited_langs,
            "cited_passage_languages": passage_langs,
            "correct_docs": correct,
            "cited_correct_doc": bool(correct) and bool(top) and top in correct,
            "expected_token_in_answer": token_ok,
            "distinct_documents": result.evidence.distinct_documents,
            "supporting_sources": result.evidence.supporting_sources,
            "all_claims_verified": result.evidence.all_claims_verified,
            "unsupported_claims_removed": result.evidence.unsupported_claims_removed,
            "conflicts_detected": result.evidence.conflicts_detected,
            "languages_in_evidence": list(result.evidence.languages_in_evidence),
            "unsupported_scripts": list(result.evidence.unsupported_scripts),
            "missing_evidence": list(result.missing_evidence),
        }
        per_q.append(rec)

        wanted = row["expect_decision"] == "answer"
        verdict = "OK" if (decision == "answered") == wanted else "MISS"
        print(f"\n[{verdict}] {row.get('probe'):22} Q: {q[:88]}")
        print(f"   decision       : {decision}   answer_language={result.answer_language}")
        print(f"   answer         : {(result.answer or '')[:150]}")
        print(f"   cited doc      : {top}  (doc lang={cited_langs or '-'})")
        print(f"   passage langs  : {passage_langs or '-'}")
        if expected:
            print(f"   expected token : {expected!r} in answer -> {token_ok}")
        if result.missing_evidence:
            print(f"   missing        : {list(result.missing_evidence)[:2]}")

    # ---------------- the headline: the cross-lingual gap, quantified ----------
    print("\n" + "=" * 78)
    print(f"BASELINE  search_languages={SEARCH_LANGUAGES}  ({len(per_q)} questions)")
    print("=" * 78)
    print(f"\n{'bucket':32} {'n':>3} {'answered':>9} {'abstained':>10} {'correct-token':>14}")
    buckets_out = {}
    for name, probes in _BUCKETS.items():
        group = [r for r in per_q if r["probe"] in probes]
        ans = [r for r in group if r["decision"] == Decision.answered.value]
        abst = [r for r in group if r["decision"] != Decision.answered.value]
        tok = [r for r in ans if r["expected_token_in_answer"]]
        buckets_out[name] = {
            "n": len(group),
            "answered": len(ans),
            "abstained": len(abst),
            "correct_token": len(tok),
            "answered_rate": len(ans) / len(group) if group else None,
            "correct_token_rate": len(tok) / len(group) if group else None,
        }
        print(
            f"{name:32} {len(group):>3} {len(ans):>9} {len(abst):>10} {len(tok):>14}"
            f"   ({_pct(len(tok), len(group))} of the bucket)"
        )

    ta = buckets_out["Tamil-only"]
    te = buckets_out["Telugu-only"]
    en = buckets_out["English-answerable (control)"]
    nb = buckets_out["Ungroundable (must abstain)"]
    print(
        "\nRead it like this: the control bucket shows the pipeline is healthy when\n"
        "the question and the evidence share a language "
        f"({en['correct_token']}/{en['n']} answered with the right token).\n"
        "The Tamil-only and Telugu-only buckets are the SAME pipeline with only the\n"
        "evidence language changed -- "
        f"{ta['correct_token']}/{ta['n']} Tamil and {te['correct_token']}/{te['n']} Telugu.\n"
        f"Abstention on ungroundable questions: {nb['abstained']}/{nb['n']} "
        "(this is the number that must never regress)."
    )

    # ---------------- standard evidence-quality metrics ------------------------
    answered = [r for r in per_q if r["decision"] == Decision.answered.value]
    refused = [r for r in per_q if r["decision"] != Decision.answered.value]
    want_answer = [r for r in per_q if r["expect_decision"] == "answer"]
    want_abstain = [r for r in per_q if r["expect_decision"] == "abstain"]
    grounded = sum(1 for r in answered if r["all_claims_verified"])
    with_citation = sum(1 for r in answered if r["cited_docs"])
    right_doc = sum(1 for r in answered if r["cited_correct_doc"])
    answered_when_should = sum(1 for r in want_answer if r["decision"] == "answered")
    abstained_when_should = sum(1 for r in want_abstain if r["decision"] != "answered")

    na, nwa, nwb = len(answered), len(want_answer), len(want_abstain)
    print("\n== Evidence-quality metrics (same set as the law example) ==")
    print(f"   total questions          : {len(per_q)}")
    print(f"   answered / abstained     : {na} / {len(refused)}")
    print(f"   groundedness_rate        : {_pct(grounded, na)}  ({grounded}/{na})")
    print(f"   citation_rate            : {_pct(with_citation, na)}  ({with_citation}/{na})")
    print(f"   cited-the-right-document : {_pct(right_doc, na)}  ({right_doc}/{na})")
    print(f"   answer-when-groundable   : {_pct(answered_when_should, nwa)}"
          f"  ({answered_when_should}/{nwa})")
    print(f"   abstain-when-ungroundable: {_pct(abstained_when_should, nwb)}"
          f"  ({abstained_when_should}/{nwb})")

    # Which language actually supplied the evidence, across every answer given?
    lang_counter: Counter[str] = Counter()
    for r in answered:
        for lang in r["cited_doc_languages"]:
            lang_counter[lang] += 1
    print("\n== Evidence language across all answered questions ==")
    for lang, n in sorted(lang_counter.items()):
        print(f"   {lang}: {n}")
    if not lang_counter.get("ta") and not lang_counter.get("te"):
        print("   -> NO non-Latin document was cited even once. The Tamil and Telugu")
        print("      halves of the corpus were, for retrieval purposes, invisible.")

    # A wrong answer is worse than no answer: did any question get answered from
    # the WRONG document -- e.g. the English 10-day carry-forward rule offered for
    # a Hyderabad employee, whose Telugu annexure says 5?
    print("\n== Wrong-evidence audit (answered, but not from the authoritative doc) ==")
    wrong = [r for r in answered if r["correct_docs"] and not r["cited_correct_doc"]]
    for r in wrong:
        print(f"   cited={r['top_doc']} ; authoritative={r['correct_docs']}")
        print(f"        Q: {r['question'][:100]}")
        print(f"        A: {(r['answer'] or '')[:110]}")
    over = [r for r in per_q if r["expect_decision"] == "abstain" and r["decision"] == "answered"]
    for r in over:
        print(f"   SHOULD-ABSTAIN-BUT-ANSWERED  cited={r['top_doc']}")
        print(f"        Q: {r['question'][:100]}  ->  A: {(r['answer'] or '')[:90]}")
    if not wrong and not over:
        print("   none")

    # ---------------- library's own evaluate() front door ----------------------
    report = rag.evaluate(_GOLDEN)
    print("\n== Library evaluate() report ==")
    print(f"   total={report.total} answered={report.answered} refused={report.refused}")
    print(
        f"   groundedness_rate={report.groundedness_rate:.0%} "
        f"citation_rate={report.citation_rate:.0%} "
        f"expected_support_rate={report.expected_support_rate:.0%}"
    )

    _OUT.write_text(
        json.dumps(
            {
                "search_languages": list(SEARCH_LANGUAGES),
                "buckets": buckets_out,
                "metrics": {
                    "total": len(per_q),
                    "answered": len(answered),
                    "abstained": len(refused),
                    "groundedness_rate": grounded / len(answered) if answered else None,
                    "citation_rate": with_citation / len(answered) if answered else None,
                    "cited_right_document_rate": (
                        right_doc / len(answered) if answered else None
                    ),
                    "answer_when_groundable": (
                        answered_when_should / len(want_answer) if want_answer else None
                    ),
                    "abstain_when_ungroundable": (
                        abstained_when_should / len(want_abstain) if want_abstain else None
                    ),
                },
                "evidence_language_counts": dict(lang_counter),
                "library_evaluate": {
                    "total": report.total,
                    "answered": report.answered,
                    "refused": report.refused,
                    "groundedness_rate": report.groundedness_rate,
                    "citation_rate": report.citation_rate,
                    "expected_support_rate": report.expected_support_rate,
                },
                "per_question": per_q,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"\nwrote {_OUT}")


if __name__ == "__main__":
    main()
