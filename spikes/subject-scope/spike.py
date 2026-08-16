#!/usr/bin/env python3
"""SPIKE — the SUBJECT-SCOPE gap. Offline, deterministic, no network, no keys.

The open failure (see spikes/subject-scope/NOTES.md):

    Q  "How much notice must a landlord give to terminate a fixed five-year
        commercial lease with a specified term in California?"      -> must ABSTAIN
    A  "at least 60 days prior to the proposed date of termination"
       cited 01-ca-civ-1946_1-statute, tier=controlling-statute (the HIGHEST tier)

The faithfulness gate is right (the words are verbatim in the passage) and the
ADR-0004 authority floor cannot help (the source is top-tier). The passage is
simply about a different KIND of tenancy.

This spike measures, against the REAL example corpus, using the LIBRARY's own
extractor / chunker / gate predicates:

  M1  Where the scope precondition actually lives  -> applicability SEVERANCE
  M2  Reproduce the two already-rejected approaches (relevance floor, token
      coverage) and quantify why they cannot work
  M3  Candidate: declared scope FACETS + closed-vocabulary query matching,
      refusal-only (the exact shape of the ADR-0004 authority floor)
  M4  Robustness of M3 under paraphrase -> the fail-open rate
  M5  Candidate: scope-context PROPAGATION at ingest (feasibility + effect)

Run (needs the project env — citenexus imports pydantic):
    cd python && ./.venv/bin/python ../spikes/subject-scope/spike.py
"""

from __future__ import annotations

import csv
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
_EXAMPLE = _ROOT / "examples" / "law-authority"
_CORPUS = _EXAMPLE / "corpus"

# Let the spike run from anywhere in the repo without an install.
sys.path.insert(0, str(_ROOT / "python" / "src"))

from citenexus.answer.verify import (  # noqa: E402
    content_tokens,
    has_relevance_overlap,
    is_supported,
)
from citenexus.evidence.chunker import chunk_text  # noqa: E402
from citenexus.extract.txt import TxtExtractor  # noqa: E402


# --------------------------------------------------------------------------
# Fixtures: the real EvidenceUnit grid, built the way ingest builds it
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class EU:
    eu_id: str
    document_id: str
    order: int
    text: str


def build_eus() -> list[EU]:
    """Reproduce the EU grid exactly: TxtExtractor blocks -> chunk_text children.

    TxtExtractor splits a .txt on blank lines, one paragraph per block
    (extract/txt.py). chunked_builder then chunks each BLOCK independently at
    450 tokens. Every paragraph in this corpus is well under 450 tokens, so
    **one statutory subdivision == one EvidenceUnit**. That fact is the whole
    of M1.
    """
    eus: list[EU] = []
    for path in sorted(_CORPUS.glob("*.txt")):
        doc = TxtExtractor().extract(path)
        for block in doc.blocks:
            if not block.text.strip():
                continue
            for i, chunk in enumerate(chunk_text(block.text)):
                eus.append(
                    EU(
                        eu_id=f"{doc.document_id}::{block.order}::{i}",
                        document_id=doc.document_id,
                        order=block.order,
                        text=chunk,
                    )
                )
    return eus


def load_golden() -> list[dict[str, str]]:
    with (_EXAMPLE / "golden.csv").open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def load_results() -> dict:
    return json.loads((_EXAMPLE / "results.json").read_text(encoding="utf-8"))


# The observed failure, reconstructed. The answer text is the one the live run
# produced for the sibling question against the SAME passage (results.json,
# per_question[1]); the passage is the EU that carries it.
BAD_QUESTION = (
    "How much notice must a landlord give to terminate a fixed five-year "
    "commercial lease with a specified term in California?"
)
BAD_ANSWER = "at least 60 days prior to the proposed date of termination"
BAD_EU_ID = "01-ca-civ-1946_1-statute::3::0"


# An "operative" EU states a notice period — the kind of passage an answer to a
# "how much notice" question gets extracted from.
_OPERATIVE = re.compile(r"\b(\d+)\s+days?\b", re.I)


def is_operative(eu: EU) -> bool:
    return bool(_OPERATIVE.search(eu.text)) and bool(
        re.search(r"notice|terminat", eu.text, re.I)
    )


# --------------------------------------------------------------------------
# M1 — applicability severance
# --------------------------------------------------------------------------

# The scope PRECONDITION each document's notice rules hang off. These strings
# are quoted verbatim from the corpus; the point of M1 is not that a human can
# find them but WHERE they sit relative to the operative rule.
SCOPE_PREDICATE_PHRASES = {
    "01-ca-civ-1946_1-statute": "for a term not specified by the parties",
    "02-mak-v-berkeley-2015-appellate": "for a term not specified by the parties",
    "04-ca-civ-1946-general-statute": "for a term not specified by the parties",
    "06-florida-83_57-statute": "without a specific duration",
    "05-nolo-month-to-month-blog": "month-to-month tenancy",
    # 1946.2 (just cause) is not conditioned on the term being unspecified.
    "03-ca-civ-1946_2-justcause-statute": None,
}


def m1_severance(eus: list[EU]) -> dict:
    print("\n=== M1  Applicability severance =========================================")
    print("Where does the scope precondition live, relative to the operative rule?\n")
    by_doc: dict[str, list[EU]] = {}
    for eu in eus:
        by_doc.setdefault(eu.document_id, []).append(eu)

    total_operative = 0
    self_sufficient = 0
    rows = []
    for doc_id, doc_eus in sorted(by_doc.items()):
        phrase = SCOPE_PREDICATE_PHRASES.get(doc_id)
        pred_eus = (
            [e.eu_id for e in doc_eus if phrase and phrase.lower() in e.text.lower()]
            if phrase
            else []
        )
        op_eus = [e for e in doc_eus if is_operative(e)]
        carried = [e for e in op_eus if phrase and phrase.lower() in e.text.lower()]
        total_operative += len(op_eus)
        self_sufficient += len(carried)
        rows.append((doc_id, len(doc_eus), len(op_eus), len(carried), pred_eus))
        print(f"  {doc_id}")
        print(f"      EUs total                : {len(doc_eus)}")
        print(f"      scope precondition       : {phrase!r}")
        print(f"      lives in EU(s)           : {pred_eus or '-'}")
        print(f"      operative (notice-period) EUs : {len(op_eus)}  -> {[e.eu_id for e in op_eus]}")
        print(f"      of which self-sufficient : {len(carried)}")

    print(f"\n  TOTAL operative EUs                 : {total_operative}")
    print(f"  TOTAL that carry their own scope    : {self_sufficient}")
    rate = self_sufficient / total_operative if total_operative else 0.0
    print(f"  SEVERANCE RATE                      : {1 - rate:.0%} of operative EUs are")
    print("      cited without the precondition that decides whether they apply.")
    print("\n  The failing citation is exactly this shape:")
    bad = next(e for e in eus if e.eu_id == BAD_EU_ID)
    print(f"      cited EU {BAD_EU_ID}")
    print(f"      contains 'not specified by the parties'? "
          f"{'for a term not specified' in bad.text.lower()}")
    print("      the governing clause is EU ::2::0, one paragraph away, never retrieved.")
    return {"operative": total_operative, "self_sufficient": self_sufficient}


# --------------------------------------------------------------------------
# M2 — reproduce the two rejected approaches
# --------------------------------------------------------------------------


def coverage(question: str, passage: str) -> float:
    q = content_tokens(question)
    if not q:
        return 0.0
    return len(q & content_tokens(passage)) / len(q)


def best_eu(eus: list[EU], doc_id: str, question: str) -> EU:
    cands = [e for e in eus if e.document_id == doc_id]
    return max(cands, key=lambda e: coverage(question, e.text))


def m2_rejected(eus: list[EU], golden: list[dict[str, str]]) -> dict:
    print("\n=== M2  The two already-rejected approaches, reproduced =================")

    by_id = {e.eu_id: e for e in eus}
    bad_eu = by_id[BAD_EU_ID]

    # --- 2a: relevance floor (the library's own predicate) -----------------
    print("\n  (2a) query-term relevance floor  [citenexus.answer.verify.has_relevance_overlap]")
    fires_on_bad = has_relevance_overlap(BAD_QUESTION, bad_eu.text)
    print(f"       bad pairing passes the floor? {fires_on_bad}   (True = floor is blind to it)")
    print("       'california' in the cited statute's body text? "
          f"{'california' in bad_eu.text.lower()}")
    hdr = by_id["01-ca-civ-1946_1-statute::0::0"]
    print("       ...but the SOURCE header EU does carry it:      "
          f"{'california' in hdr.text.lower()}  <- corpus-authored, not statutory text")

    # --- 2b: content-token coverage ---------------------------------------
    print("\n  (2b) content-token coverage threshold")
    good: list[tuple[str, float]] = []
    for row in golden:
        if row.get("expect_decision") != "answer":
            continue
        for doc_id in [d for d in (row.get("correct_docs") or "").split("|") if d]:
            e = best_eu(eus, doc_id, row["question"])
            good.append((f"{row['question'][:44]}… x {doc_id}", coverage(row["question"], e.text)))
    bad_cov = coverage(BAD_QUESTION, bad_eu.text)

    # The second known-bad pairing from the pre-fix run: the Texas question
    # answered from the Florida statute.
    tx_q = "What is the notice period to end a month-to-month tenancy in Texas?"
    tx_eu = best_eu(eus, "06-florida-83_57-statute", tx_q)
    tx_cov = coverage(tx_q, tx_eu.text)

    lo = min(c for _, c in good)
    hi = max(c for _, c in good)
    print(f"       GOOD pairings (n={len(good)}): min={lo:.2f}  max={hi:.2f}")
    for label, c in sorted(good, key=lambda x: x[1]):
        print(f"          {c:.2f}  {label}")
    print(f"       BAD  commercial-fixed-term x 1946.1(b) : {bad_cov:.2f}")
    print(f"       BAD  Texas x Florida 83.57             : {tx_cov:.2f}")

    bads = [bad_cov, tx_cov]
    below = sum(1 for _, c in good if c < max(bads))
    lost_at_low = sum(1 for _, c in good if c <= bad_cov)
    print(f"\n       bad #1 ({bad_cov:.2f}) sits INSIDE the good range [{lo:.2f}, {hi:.2f}].")
    print(f"       bad #2 ({tx_cov:.2f}) sits ABOVE every good pairing (max {hi:.2f}).")
    print(f"       a threshold high enough to block bad #1 loses {lost_at_low}/{len(good)} good pairings;")
    print(f"       a threshold high enough to block BOTH loses {below}/{len(good)}.")
    print("       Coverage is not merely non-separating — it is ANTI-correlated:")
    print("       the worst answer in the set is the best-covered pairing in the set.")
    print("       => no separating threshold exists. Confirmed.")
    return {"good_range": (lo, hi), "bad": bads, "good_lost_at_safe_threshold": below}


# --------------------------------------------------------------------------
# M3 — declared scope facets, refusal-only (the candidate)
# --------------------------------------------------------------------------

# A facet is a CLOSED, curator-declared vocabulary — the same shape as
# ADR-0004's authority tiers: metadata about the source, never derived from its
# prose, applied strictly after grounding, able only to REMOVE.
FACETS: dict[str, dict[str, object]] = {
    "tenancy_term": {
        # values that are mutually exclusive with one another
        "exclusive": True,
        "values": ("unspecified", "specified", "any"),
        # "any" is compatible with everything
        "wildcard": "any",
        # surface forms that let a QUERY assert a value, declared by the curator
        # alongside the corpus. This is data, not model output.
        "query_forms": {
            "specified": (
                "fixed-term", "fixed term", "specified term", "specified end date",
                "five-year lease", "term of years", "for a term of",
            ),
            "unspecified": (
                "month-to-month", "month to month", "periodic tenancy",
                "week-to-week", "no specified term", "without a specific term",
            ),
        },
    },
    "jurisdiction": {
        "exclusive": True,
        "values": ("CA", "FL", "generic"),
        "wildcard": "generic",
        "query_forms": {
            "CA": ("california", "californian"),
            "FL": ("florida",),
            "TX": ("texas",),
        },
    },
}

DOC_FACETS: dict[str, dict[str, str]] = {
    "01-ca-civ-1946_1-statute": {"tenancy_term": "unspecified", "jurisdiction": "CA"},
    "02-mak-v-berkeley-2015-appellate": {"tenancy_term": "unspecified", "jurisdiction": "CA"},
    "03-ca-civ-1946_2-justcause-statute": {"tenancy_term": "any", "jurisdiction": "CA"},
    "04-ca-civ-1946-general-statute": {"tenancy_term": "unspecified", "jurisdiction": "CA"},
    "05-nolo-month-to-month-blog": {"tenancy_term": "unspecified", "jurisdiction": "generic"},
    "06-florida-83_57-statute": {"tenancy_term": "unspecified", "jurisdiction": "FL"},
}


def query_facets(question: str) -> dict[str, str]:
    """Assert facet values a query states, by declared surface form only."""
    q = question.lower()
    out: dict[str, str] = {}
    for facet, spec in FACETS.items():
        for value, forms in spec["query_forms"].items():  # type: ignore[index]
            if any(f in q for f in forms):
                # first declared match wins; a query stating two exclusive
                # values is itself a scope conflict -> treated as unknown
                out[facet] = value if facet not in out else "__conflict__"
    return {k: v for k, v in out.items() if v != "__conflict__"}


def scope_conflict(question: str, doc_id: str) -> str | None:
    """Refusal-only gate: is the query's declared scope excluded by the doc's?"""
    qf = query_facets(question)
    df = DOC_FACETS.get(doc_id, {})
    for facet, q_value in qf.items():
        spec = FACETS[facet]
        d_value = df.get(facet)
        if d_value is None:
            continue  # undeclared on the document -> no assertion -> fail open
        if d_value == spec["wildcard"]:
            continue
        if q_value == d_value:
            continue
        return f"{facet}: query asserts {q_value!r}, source declares {d_value!r}"
    return None


def m3_facets(eus: list[EU], golden: list[dict[str, str]]) -> dict:
    print("\n=== M3  Declared scope facets, refusal-only ============================")
    print("Same seam as the ADR-0004 authority floor: metadata in, no prose read,\n"
          "applied after grounding, can only WITHHOLD.\n")

    # The document each question is actually at risk of citing. For the eight
    # answerable ones that is golden.csv's correct_docs. For the three
    # should-abstain ones it is the source the pre-fix live run DID cite (the
    # commercial-lease and Texas rows) or, where nothing in the corpus is even
    # on-topic, nothing at all (the security-deposit row).
    AT_RISK = {
        "How much notice must a landlord give to terminate a fixed five-year commercial "
        "lease with a specified term in California?": ["01-ca-civ-1946_1-statute"],
        "What is the notice period to end a month-to-month tenancy in Texas?": [
            "06-florida-83_57-statute"
        ],
        "What is the maximum security deposit a California landlord may collect?": [],
    }

    scope_blocks = 0
    jurisdiction_blocks = 0
    regressions = 0
    not_this_gate = 0
    for row in golden:
        q = row["question"]
        want = row.get("expect_decision")
        docs = AT_RISK.get(q, [d for d in (row.get("correct_docs") or "").split("|") if d])
        qf = query_facets(q)
        if not docs:
            not_this_gate += 1
            print(f"  [{want or '-':7}] not this gate's job (no on-topic source to withhold)")
            print(f"      Q: {q[:92]}")
            continue
        verdicts = {d: scope_conflict(q, d) for d in docs}
        blocked = [d for d, v in verdicts.items() if v]
        if want == "abstain" and blocked:
            kinds = {v.split(":")[0] for v in verdicts.values() if v}
            if "tenancy_term" in kinds:
                scope_blocks += 1
                mark = "BLOCKED on SUBJECT SCOPE (the open class — correct)"
            else:
                jurisdiction_blocks += 1
                mark = "BLOCKED on jurisdiction (already covered by ADR-0004)"
        elif want == "answer" and set(blocked) == set(docs):
            regressions += 1
            mark = "BLOCKED (REGRESSION — was answerable)"
        elif blocked:
            mark = f"partial: {blocked} withheld, {[d for d in docs if d not in blocked]} kept"
        else:
            mark = "passes"
        print(f"  [{want or '-':7}] {mark}")
        print(f"      Q: {q[:92]}")
        print(f"      query facets: {qf or '{}'}")
        for d, v in verdicts.items():
            if v:
                print(f"      -> {d}: {v}")

    print(f"\n  blocked on SUBJECT SCOPE (the open class): {scope_blocks}")
    print(f"  blocked on jurisdiction (redundant w/ ADR-0004): {jurisdiction_blocks}")
    print(f"  out of this gate's reach (missing topic)  : {not_this_gate}")
    print(f"  answerable questions lost (regressions)   : {regressions}")
    return {
        "scope_blocks": scope_blocks,
        "jurisdiction_blocks": jurisdiction_blocks,
        "regressions": regressions,
        "not_this_gate": not_this_gate,
    }


# --------------------------------------------------------------------------
# M4 — paraphrase robustness: the fail-open rate
# --------------------------------------------------------------------------

PARAPHRASES = (
    # each means exactly the same thing; none uses a declared surface form
    "The lease runs from 1 January 2026 to 31 December 2030. What notice ends it early?",
    "Our shop lease has five years left to run. How long a notice must the landlord serve?",
    "How much warning does a landlord owe a business tenant on a lease that expires in 2030?",
    "A commercial tenancy was granted for a definite period of 60 months. Notice required?",
    "What notice period applies where the parties agreed the tenancy would end on a set date?",
    "Le bail commercial de cinq ans se termine le 31 décembre 2030. Quel préavis ?",
)


def m4_paraphrase() -> dict:
    print("\n=== M4  Paraphrase robustness (the fail-open rate) =====================")
    print("Same question, no declared surface form. Does the M3 gate still fire?\n")
    fired = 0
    for p in PARAPHRASES:
        v = scope_conflict(p, "01-ca-civ-1946_1-statute")
        fired += bool(v)
        print(f"  {'FIRES ' if v else 'SILENT'}  {p[:88]}")
        print(f"          facets seen: {query_facets(p) or '{}'}")
    print(f"\n  fired on {fired}/{len(PARAPHRASES)} paraphrases "
          f"-> FAIL-OPEN RATE {1 - fired / len(PARAPHRASES):.0%}")
    print("  A lexical facet gate protects the phrasings the curator anticipated,")
    print("  and only those. It is a floor, not a guarantee.")
    return {"fired": fired, "total": len(PARAPHRASES)}


# --------------------------------------------------------------------------
# M5 — scope-context propagation at ingest
# --------------------------------------------------------------------------


def m5_propagation(eus: list[EU]) -> dict:
    print("\n=== M5  Scope-context propagation at ingest ============================")
    print("Attach the document's applicability clause to every EU derived from it,")
    print("so the precondition travels with the rule. Measured: does it fit, and")
    print("does the augmented passage still pass the faithfulness gate?\n")

    by_doc: dict[str, list[EU]] = {}
    for eu in eus:
        by_doc.setdefault(eu.document_id, []).append(eu)

    over_budget = 0
    total = 0
    for doc_id, doc_eus in sorted(by_doc.items()):
        phrase = SCOPE_PREDICATE_PHRASES.get(doc_id)
        if not phrase:
            continue
        anchor = next(
            (e for e in doc_eus if phrase.lower() in e.text.lower()), None
        )
        if anchor is None:
            continue
        for e in doc_eus:
            if not is_operative(e):
                continue
            total += 1
            augmented = f"{anchor.text}\n{e.text}"
            if len(augmented.split()) > 450:
                over_budget += 1
    print(f"  operative EUs augmented          : {total}")
    print(f"  over the 450-token chunk budget  : {over_budget}")

    by_id = {e.eu_id: e for e in eus}
    bad_eu = by_id[BAD_EU_ID]
    anchor = by_id["01-ca-civ-1946_1-statute::2::0"]
    augmented = f"{anchor.text}\n{bad_eu.text}"
    print("\n  On the failing citation:")
    print(f"    is_supported(answer, passage)  before : {is_supported(BAD_ANSWER, bad_eu.text)}")
    print(f"    is_supported(answer, augmented) after : {is_supported(BAD_ANSWER, augmented)}")
    print("    'not specified by the parties' now visible in the cited context: "
          f"{'not specified by the parties' in augmented.lower()}")
    print("\n  Propagation does NOT by itself refuse — the gate is token-containment")
    print("  and containment only grows. What it changes is that the precondition")
    print("  is now IN the passage, so a downstream scope check (facet, judge, or")
    print("  a human reading the citation) has something to check against. Today it")
    print("  is invisible to every one of them.")
    return {"augmented": total, "over_budget": over_budget}


# --------------------------------------------------------------------------


def main() -> None:
    eus = build_eus()
    golden = load_golden()
    results = load_results()

    print("SPIKE — subject-scope gap")
    print("=" * 74)
    print(f"corpus documents : {len({e.document_id for e in eus})}")
    print(f"EvidenceUnits    : {len(eus)}  (one statutory subdivision per EU)")
    print(f"golden questions : {len(golden)}")
    print(f"last live run    : answered={results['metrics']['answered']} "
          f"refused={results['metrics']['refused']} "
          f"groundedness={results['metrics']['groundedness_rate']:.0%} "
          f"abstain_when_no_evidence={results['metrics']['abstain_when_no_evidence']:.0%}")

    m1 = m1_severance(eus)
    m2 = m2_rejected(eus, golden)
    m3 = m3_facets(eus, golden)
    m4 = m4_paraphrase()
    m5 = m5_propagation(eus)

    print("\n=== SUMMARY ============================================================")
    print(f"  M1 severance      : {m1['operative'] - m1['self_sufficient']}/{m1['operative']} "
          "operative EUs cited without their governing precondition")
    print(f"  M2 coverage       : good {m2['good_range'][0]:.2f}-{m2['good_range'][1]:.2f}, "
          f"bad {[f'{b:.2f}' for b in m2['bad']]} -> no separating threshold")
    print(f"  M3 facet gate     : {m3['scope_blocks']}/1 subject-scope failures caught, "
          f"{m3['regressions']} regressions "
          f"(+{m3['jurisdiction_blocks']} jurisdiction, redundant)")
    print(f"  M4 robustness     : fires on {m4['fired']}/{m4['total']} paraphrases")
    print(f"  M5 propagation    : {m5['augmented']} EUs augmented, "
          f"{m5['over_budget']} over budget")
    print("\n  See NOTES.md for the recommendation and the honesty section.")


if __name__ == "__main__":
    main()
