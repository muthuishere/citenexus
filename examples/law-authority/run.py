"""CiteNexus LAW stress-test — cite-or-abstain + the AUTHORITY gap, on a real corpus.

Ingests a small real California landlord-tenant corpus (official statutes + a
binding Court of Appeal opinion + an older general statute + a non-binding blog +
an out-of-state statute), runs ask() on a golden set, and reports real numbers:
groundedness, citation rate, answered/refused, abstention accuracy, and — for the
authority-probe questions — WHICH source answered and at what authority tier.

Endpoints (the APPLICATION owns its environment; the library reads no env):
  embeddings + rerank -> Jina  (JINA_API_KEY)      model jina-embeddings-v3 / jina-reranker-v2-base-multilingual
  generation          -> Gemini (GEMINI_API_KEY)   model gemini-2.5-flash

Run:
  cd python && . .venv/bin/activate
  export JINA_API_KEY=...      # referenced by name; never printed
  export GEMINI_API_KEY=...
  python ../examples/law-authority/run.py
"""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path

from citenexus import CiteNexus, GeminiHttpEndpoint, OpenAIHttpEndpoint
from citenexus.answer.result import Decision, Result
from citenexus.config.schema import (
    CiteNexusConfig,
    EmbeddingConfig,
    LLMConfig,
    MultilingualConfig,
    RerankerConfig,
    StorageConfig,
)
from citenexus.config.signals import Signal

_HERE = Path(__file__).resolve().parent
_CORPUS = _HERE / "corpus"
_GOLDEN = _HERE / "golden.csv"
_AUTHORITY = _HERE / "authority.csv"
_OUT = _HERE / "results.json"


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
        multilingual=MultilingualConfig(fallback_language="en"),
        # Dense + sparse only: the authority gap is a RANKING question, so we keep
        # the retrieval surface to the two signals every RAG has (no graph/wiki).
        signals=(Signal.embedding, Signal.text),
    )


def _load_authority() -> dict[str, dict[str, str]]:
    with _AUTHORITY.open(newline="", encoding="utf-8") as fh:
        return {r["document_id"]: r for r in csv.DictReader(fh)}


def _cited_docs(result: Result) -> list[str]:
    # Preserve rank order; the first cited source is the top-ranked evidence.
    seen: list[str] = []
    for s in result.sources:
        if s.document not in seen:
            seen.append(s.document)
    return seen


def main() -> None:
    authority = _load_authority()
    rag = CiteNexus.from_config(_config())

    print("== Ingest ==")
    for path in sorted(_CORPUS.glob("*.txt")):
        res = rag.ingest(path, document_id=path.stem)
        print(f"   {path.stem:38} -> {res.status}")

    with _GOLDEN.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    per_q = []
    print("\n== Ask ==")
    for row in rows:
        q = row["question"]
        result = rag.ask(q)  # strict mode is the default
        decision = result.evidence.decision.value
        cited = _cited_docs(result)
        top = cited[0] if cited else None
        top_tier = authority.get(top, {}).get("authority_tier", "-") if top else "-"

        correct = [d for d in (row.get("correct_docs") or "").split("|") if d]
        traps = [d for d in (row.get("trap_docs") or "").split("|") if d]
        winner_class = "-"
        if row.get("probe") == "authority" and top:
            if top in correct:
                winner_class = "CORRECT-AUTHORITY"
            elif top in traps:
                winner_class = "WRONG-AUTHORITY(trap won)"
            else:
                winner_class = "other"

        rec = {
            "question": q,
            "expect_decision": row.get("expect_decision"),
            "probe": row.get("probe") or "",
            "decision": decision,
            "answer": result.answer,
            "cited_docs": cited,
            "top_doc": top,
            "top_authority_tier": top_tier,
            "distinct_documents": result.evidence.distinct_documents,
            "supporting_sources": result.evidence.supporting_sources,
            "conflicts_detected": result.evidence.conflicts_detected,
            "all_claims_verified": result.evidence.all_claims_verified,
            "expected": row.get("expected", ""),
            "correct_docs": correct,
            "trap_docs": traps,
            "winner_class": winner_class,
        }
        per_q.append(rec)

        flag = ""
        if row.get("probe") == "authority":
            flag = f"   [AUTHORITY PROBE -> {winner_class}]"
        print(f"\nQ: {q}")
        print(f"   decision : {decision}")
        print(f"   answer   : {result.answer[:160]}")
        print(f"   top cited: {top}  (tier={top_tier}){flag}")
        if len(cited) > 1:
            print(f"   also     : {cited[1:]}")

    # ---- headline metrics (computed here, honest + explicit) ----
    answered = [r for r in per_q if r["decision"] == Decision.answered.value]
    refused = [r for r in per_q if r["decision"] == Decision.refused.value]
    want_answer = [r for r in per_q if r["expect_decision"] == "answer"]
    want_abstain = [r for r in per_q if r["expect_decision"] == "abstain"]

    grounded = sum(1 for r in answered if r["all_claims_verified"])
    cited = sum(1 for r in answered if r["cited_docs"])
    answered_when_should = sum(1 for r in want_answer if r["decision"] == "answered")
    abstained_when_should = sum(1 for r in want_abstain if r["decision"] == "refused")

    def pct(n: int, d: int) -> str:
        return f"{(n / d * 100):.0f}%" if d else "n/a"

    print("\n== Metrics (this run) ==")
    print(f"   total questions        : {len(per_q)}")
    print(f"   answered / refused     : {len(answered)} / {len(refused)}")
    print(f"   groundedness_rate      : {pct(grounded, len(answered))}  ({grounded}/{len(answered)} answered fully verified)")
    print(f"   citation_rate          : {pct(cited, len(answered))}  ({cited}/{len(answered)} answered carry a citation)")
    print(f"   answer-when-grounded   : {pct(answered_when_should, len(want_answer))}  ({answered_when_should}/{len(want_answer)})")
    print(f"   abstain-when-no-evidence: {pct(abstained_when_should, len(want_abstain))}  ({abstained_when_should}/{len(want_abstain)})")

    probes = [r for r in per_q if r["probe"] == "authority"]
    print("\n== Authority probes (high-authority source should answer) ==")
    for r in probes:
        outcome = r["winner_class"]
        if r["decision"] == "refused":
            outcome = "REFUSED (high-authority passage suppressed in ranking)"
        print(f"   {outcome}")
        print(f"        Q: {r['question']}")
        print(f"        A: {r['answer'][:140]}")

    # Citation-authority audit across EVERY question: does the CITED source match
    # the authoritative one — and did a should-abstain question get answered?
    print("\n== Citation-authority audit ==")
    for r in per_q:
        if r["expect_decision"] == "abstain":
            if r["decision"] == "answered":
                print(f"   SHOULD-ABSTAIN-BUT-ANSWERED  cited={r['top_doc']} (tier={r['top_authority_tier']})")
                print(f"        Q: {r['question']}  ->  A: {r['answer'][:90]}")
            continue
        if r["decision"] != "answered":
            continue
        if r["correct_docs"] and r["top_doc"] not in r["correct_docs"]:
            print(f"   CITED-WRONG-AUTHORITY  cited={r['top_doc']} (tier={r['top_authority_tier']}); authoritative={r['correct_docs']}")
            print(f"        Q: {r['question']}  ->  A: {r['answer'][:90]}")

    # ---- library's own evaluate() report (uses question+expected only) ----
    report = rag.evaluate(_GOLDEN)
    print("\n== Library evaluate() report ==")
    print(f"   total={report.total} answered={report.answered} refused={report.refused}")
    print(f"   groundedness_rate={report.groundedness_rate:.0%} citation_rate={report.citation_rate:.0%} expected_support_rate={report.expected_support_rate:.0%}")

    _OUT.write_text(
        json.dumps(
            {
                "metrics": {
                    "total": len(per_q),
                    "answered": len(answered),
                    "refused": len(refused),
                    "groundedness_rate": grounded / len(answered) if answered else None,
                    "citation_rate": cited / len(answered) if answered else None,
                    "answer_when_grounded": answered_when_should / len(want_answer) if want_answer else None,
                    "abstain_when_no_evidence": abstained_when_should / len(want_abstain) if want_abstain else None,
                },
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
        ),
        encoding="utf-8",
    )
    print(f"\nwrote {_OUT}")


if __name__ == "__main__":
    main()
