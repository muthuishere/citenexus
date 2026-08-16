"""Library-level adversarial stress test for the CiteNexus guarantees.

Deliberately NOT built around any one corpus or customer document. Every probe
runs over synthetic fixtures spanning five unrelated domains (legal, finance,
medical, operations, physics) so a failure is a property of the library, not of
a document set. Fully offline: deterministic fakes, no network, no model.

It probes the three claims CiteNexus makes about itself:

  A. "No ungrounded claim"  -> is the faithfulness gate actually sound?
  B. "Conflicts are surfaced" -> does anything detect contradiction?
  C. "distinct_documents"   -> does corroboration mean what it says?

Run:  uv run python spikes/library-stress/stress.py
Exit: 0 if every probe behaves as the contract promises, 1 if any hole is found.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from citenexus import CiteNexus
from citenexus.answer.verify import is_supported, is_supported_v2
from citenexus.testing.fakes import FakeEmbedding, FakeLLM

# ─────────────────────────────────────────────────────────────────────────────
# Probe A — is the faithfulness gate sound, or only vocabulary-sound?
#
# is_supported() is `set(answer) <= set(passage)`. Set containment is closed
# under (1) reordering and (2) deletion. Both operations change meaning. Each
# fixture below is an answer that a careless model could produce, is FALSE with
# respect to its passage, and that the gate should reject.
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GateCase:
    domain: str
    attack: str
    passage: str
    answer: str  # false w.r.t. passage


GATE_CASES = [
    # --- role inversion: identical token set, opposite meaning ---
    GateCase(
        "legal",
        "role inversion",
        "The tenant shall indemnify the landlord for damage to the property.",
        "The landlord shall indemnify the tenant for damage to the property.",
    ),
    GateCase(
        "finance",
        "role inversion",
        "The borrower pays the lender a fee of 400 basis points.",
        "The lender pays the borrower a fee of 400 basis points.",
    ),
    GateCase(
        "medical",
        "role inversion",
        "Ibuprofen increases the effect of warfarin in adult patients.",
        "Warfarin increases the effect of ibuprofen in adult patients.",
    ),
    # --- negation deletion: a strict subset, opposite meaning ---
    GateCase(
        "legal",
        "negation deletion",
        "The employee shall not disclose confidential information.",
        "The employee shall disclose confidential information.",
    ),
    GateCase(
        "operations",
        "negation deletion",
        "The reactor must not be restarted without a signed safety review.",
        "The reactor must be restarted without a signed safety review.",
    ),
    GateCase(
        "medical",
        "negation deletion",
        "This medication is not approved for patients under twelve years.",
        "This medication is approved for patients under twelve years.",
    ),
    # --- value swap across a shared token pool ---
    GateCase(
        "finance",
        "value swap",
        "Region A reported 40 million in revenue and region B reported 12 million.",
        "Region A reported 12 million in revenue and region B reported 40 million.",
    ),
    GateCase(
        "physics",
        "value swap",
        "The sample melts at 240 kelvin and boils at 610 kelvin.",
        "The sample melts at 610 kelvin and boils at 240 kelvin.",
    ),
    # --- comparator inversion ---
    GateCase(
        "physics",
        "comparator inversion",
        "Pressure in chamber one is greater than pressure in chamber two.",
        "Pressure in chamber two is greater than pressure in chamber one.",
    ),
]


def probe_a_gate_soundness() -> list[str]:
    print("\n=== Probe A — faithfulness gate soundness ===")
    print("Each answer below is FALSE w.r.t. its passage. The gate should reject all.")
    print("v1 = the frozen SPEC-PORTS-v1 predicate (kept for conformance; known unsound).")
    print("v2 = the shipped gate on the answer path (ADR-0009).\n")
    holes: list[str] = []
    v1_holes = 0
    for c in GATE_CASES:
        v1 = is_supported(c.answer, c.passage)
        v2 = is_supported_v2(c.answer, c.passage)
        v1_holes += v1
        verdict = "ACCEPTED (hole)" if v2 else "rejected  (ok)"
        print(f"  [{c.domain:<10}] {c.attack:<19} v1={'accept' if v1 else 'reject'} -> v2 {verdict}")
        if v2:
            holes.append(f"{c.domain}/{c.attack}")
    total = len(GATE_CASES)
    print(f"\n  frozen v1: {v1_holes}/{total} false answers accepted (unchanged, by design).")
    print(f"  shipped v2: {len(holes)}/{total} false answers accepted.")
    return holes


# ─────────────────────────────────────────────────────────────────────────────
# Probe B — contradiction. Two documents assert opposite facts about the same
# subject. Both are real, both are cited, both are retrievable. What happens?
# ─────────────────────────────────────────────────────────────────────────────

CONTRADICTIONS = [
    (
        "legal",
        ("policy-2019", "Remote work requires prior written approval from a director."),
        ("policy-2026", "Remote work does not require prior written approval."),
        "Does remote work require prior written approval?",
    ),
    (
        "finance",
        ("filing-q1", "The dividend for the period was 12 cents per share."),
        ("filing-q1-restated", "The dividend for the period was 30 cents per share."),
        "What was the dividend per share for the period?",
    ),
    (
        "medical",
        ("guideline-eu", "The recommended dose for adults is 500 milligrams daily."),
        ("guideline-us", "The recommended dose for adults is 800 milligrams daily."),
        "What is the recommended daily dose for adults?",
    ),
]


def probe_b_contradiction() -> list[str]:
    print("\n=== Probe B — contradiction detection ===")
    print("Two mutually exclusive answers are indexed. Both are grounded.\n")
    holes: list[str] = []
    for domain, doc_a, doc_b, question in CONTRADICTIONS:
        with tempfile.TemporaryDirectory() as tmp:
            rag = CiteNexus(Path(tmp), embedder=FakeEmbedding(), generator=FakeLLM())
            rag.ingest(text=doc_a[1], document_id=doc_a[0])
            rag.ingest(text=doc_b[1], document_id=doc_b[0])
            r = rag.ask(question)

            sig = r.evidence
            cited = {s.document for s in r.sources} if r.sources else set()
            print(f"  [{domain}] {question}")
            print(f"      decision           : {sig.decision}")
            print(f"      answer             : {r.answer[:72]}")
            print(f"      cited documents    : {sorted(cited) or '-'}")
            print(f"      conflicts_detected : {sig.conflicts_detected}")
            print(f"      Result.conflicts   : {r.conflicts}")
            print(f"      distinct_documents : {sig.distinct_documents}")

            answered = str(sig.decision).endswith("answered")
            if answered and sig.conflicts_detected == 0:
                holes.append(f"{domain}: answered one side, reported 0 conflicts")
            print()
    return holes


# ─────────────────────────────────────────────────────────────────────────────
# Probe C — corroboration inflation. One fact, cloned under N document IDs.
# distinct_documents is the signal a caller uses to judge independent support.
# ─────────────────────────────────────────────────────────────────────────────

CLONES = [
    ("operations", "The maintenance window opens at 02:00 UTC on Sunday.",
     "When does the maintenance window open?"),
    ("physics", "The detector threshold is calibrated to 4.5 gigaelectronvolts.",
     "What is the detector threshold calibrated to?"),
]


def probe_c_corroboration() -> list[str]:
    print("\n=== Probe C — corroboration inflation ===")
    print("One sentence, ingested under 5 different document IDs. One real source.\n")
    holes: list[str] = []
    for domain, text, question in CLONES:
        with tempfile.TemporaryDirectory() as tmp:
            rag = CiteNexus(Path(tmp), embedder=FakeEmbedding(), generator=FakeLLM())
            for i in range(5):
                rag.ingest(text=text, document_id=f"mirror-{i}")
            r = rag.ask(question)
            sig = r.evidence
            print(f"  [{domain}] independent facts indexed : 1")
            print(f"      distinct_documents reported : {sig.distinct_documents}")
            print(f"      supporting_sources reported : {sig.supporting_sources}")
            if sig.distinct_documents > 1:
                holes.append(
                    f"{domain}: 1 fact reported as {sig.distinct_documents} distinct documents"
                )
            print()
    return holes


# ─────────────────────────────────────────────────────────────────────────────
# Probe D — claim granularity. An answer that is half supported.
# ─────────────────────────────────────────────────────────────────────────────


class HalfTrueGenerator:
    """Appends one unsupported sentence to a faithful extract."""

    def answer(self, question: str, passage: str, answer_language: str = "en") -> str:
        return f"{passage} This obligation expires after twelve months."


def probe_d_claim_granularity() -> list[str]:
    print("\n=== Probe D — claim granularity ===")
    print("Answer = one supported sentence + one fabricated sentence.\n")
    holes: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        rag = CiteNexus(
            Path(tmp), embedder=FakeEmbedding(), generator=HalfTrueGenerator()
        )
        rag.ingest(
            text="The contractor shall maintain liability insurance at all times.",
            document_id="msa",
        )
        r = rag.ask("Must the contractor maintain liability insurance?")
        sig = r.evidence
        print(f"      decision                  : {sig.decision}")
        print(f"      answer                    : {r.answer[:88]}")
        print(f"      claims recorded           : {len(r.claims)}")
        print(f"      unsupported_claims_removed: {sig.unsupported_claims_removed}")
        if len(r.claims) <= 1:
            holes.append(
                f"answer carried {len(r.claims)} claim(s); per-claim verdicts unrepresentable"
            )
        print()
    return holes


def main() -> int:
    print("CiteNexus — library-level adversarial stress test")
    print("=" * 78)
    print("Synthetic fixtures across legal / finance / medical / operations / physics.")
    print("No customer corpus, no network, no model. Deterministic fakes only.")

    findings: dict[str, list[str]] = {
        "A. faithfulness gate soundness": probe_a_gate_soundness(),
        "B. contradiction detection": probe_b_contradiction(),
        "C. corroboration inflation": probe_c_corroboration(),
        "D. claim granularity": probe_d_claim_granularity(),
    }

    print("=" * 78)
    print("SUMMARY\n")
    failed = False
    for name, holes in findings.items():
        if holes:
            failed = True
            print(f"  FAIL  {name}")
            for h in holes:
                print(f"          - {h}")
        else:
            print(f"  PASS  {name}")
    print()
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
