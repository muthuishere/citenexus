"""ADR-0007 validation spike — deterministic conflict detection + near-duplicate
collapse over grounded candidates.

Throwaway prototype. Nothing here imports from or mutates citenexus internals
beyond the pinned tokenizer, because the whole question is whether the *rule set*
can hold, not whether it can be wired in.

The number that decides ADR-0007 is the FALSE POSITIVE RATE on hard negatives.
In strict mode a detected conflict abstains, so a false conflict is a false
refusal. A detector with 100% recall and 20% FP is useless; a detector with 60%
recall and ~0% FP is shippable.

Run:  cd python && uv run python ../spikes/adr-0007-conflict/spike.py
Exit: 0 if the FP rate on hard negatives is <= FP_BUDGET, else 1.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "python" / "src"))

from citenexus.tokenize import tokenize  # noqa: E402

HERE = Path(__file__).resolve().parent
FP_BUDGET = 0.05  # >5% false conflicts on hard negatives kills the design

# ─────────────────────────────────────────────────────────────────────────────
# Tier-2 data: the polarity table (drafted as conformance/polarity.json would be)
# ─────────────────────────────────────────────────────────────────────────────

_TABLE = json.loads((HERE / "polarity.draft.json").read_text())


@dataclass(frozen=True)
class Polarity:
    negations: frozenset[str]
    antonyms: frozenset[tuple[str, str]]
    report_markers: frozenset[str]
    scope_markers: frozenset[str]


def load_polarity(lang: str = "en") -> Polarity:
    d = _TABLE["languages"][lang]
    pairs = set()
    for a, b in d["antonyms"]:
        pairs.add((a, b))
        pairs.add((b, a))
    return Polarity(
        negations=frozenset(d["negations"]),
        antonyms=frozenset(pairs),
        report_markers=frozenset(d["report_markers"]),
        scope_markers=frozenset(d["scope_markers"]),
    )


# The shipped English table deliberately drops "except"/"exempt" from negations:
# they are scope-restrictors, not polarity flips ("all employees except
# contractors" does not contradict "all employees"). The corruption experiment
# in PART 3 puts them back to measure what that costs.
_BASE = load_polarity("en")
EN = replace(_BASE, negations=_BASE.negations - {"except", "exempt"})

# Stopwords: mirrors conformance/stopwords.json (tier-2 data, read not copied).
_STOPWORDS = frozenset(json.loads((HERE / ".." / ".." / "conformance" / "stopwords.json").read_text()))

_UNITS = frozenset(
    """mg g kg mcg ug ml l cl dl mm cm m km mi mile miles inch inches ft
    bps bp percent pct days day months month years year weeks week hours hour
    minutes minute seconds second usd eur gbp million millions billion billions
    thousand k mph kmh degrees degree celsius fahrenheit kelvin hz khz mhz ghz
    volts v amps a watts w kw n j pa psi bar mol members people units""".split()
)

# A digit-LEADING token is a measurement ("500mg", "2019") and is handled by the
# numeric rule. A letter-leading token containing digits ("p50", "ipv4", "sec4")
# is an identifier and MUST stay in the content set — it is often the only thing
# distinguishing two otherwise-identical passages.
_IS_MEASUREMENT_RE = re.compile(r"^[0-9]+[a-z]*$")
# RE2-compatible: no lookaround, no backreferences, no lazy-with-backtracking.
_NUM_UNIT_RE = re.compile(r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*([a-z]+|%)?")


# ─────────────────────────────────────────────────────────────────────────────
# Passage features (pure, portable — every operation is available in Go/JS)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Features:
    tokens: tuple[str, ...]
    content: frozenset[str]  # meaning-bearing, non-numeric, non-polarity
    negations: int
    numbers: frozenset[str]
    units: frozenset[str]
    has_report_marker: bool


def _norm_number(raw: str) -> str:
    v = raw.replace(",", "")
    if "." in v:
        v = v.rstrip("0").rstrip(".")
    return v or "0"


def features(text: str, pol: Polarity = EN) -> Features:
    low = text.lower()
    toks = tuple(tokenize(low))
    numbers, units = set(), set()
    for m in _NUM_UNIT_RE.finditer(low):
        # A digit run glued to letters ("p50", "ipv4", "covid19") is an
        # identifier, not a measured value. RE2 has no lookbehind, so the
        # boundary check is done in code — trivially portable to Go/JS.
        start = m.start(1)
        if start > 0 and (low[start - 1].isalpha() or low[start - 1] == "_"):
            continue
        numbers.add(_norm_number(m.group(1)))
        unit = m.group(2)
        if unit and (unit in _UNITS or unit == "%"):
            units.add("%" if unit == "%" else unit)
    content = {
        t
        for t in toks
        if t not in _STOPWORDS
        and t not in pol.negations
        and not _IS_MEASUREMENT_RE.match(t)
    }
    return Features(
        tokens=toks,
        content=frozenset(content),
        negations=sum(1 for t in toks if t in pol.negations),
        numbers=frozenset(numbers),
        units=frozenset(units),
        has_report_marker=any(t in pol.report_markers for t in toks),
    )


# ─────────────────────────────────────────────────────────────────────────────
# PART 1 — pairwise conflict scoring
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Thresholds:
    subject_overlap: float = 0.60  # overlap coefficient on content tokens
    max_symdiff: int = 3  # total content divergence allowed at all
    max_residual: int = 1  # divergence left AFTER removing the polarity signal
    min_content: int = 3  # too-short passages are not comparable


DEFAULT = Thresholds()


@dataclass(frozen=True)
class Conflict:
    rule: str
    detail: str


def detect_conflict(
    a: str, b: str, pol: Polarity = EN, th: Thresholds = DEFAULT
) -> Conflict | None:
    """Deterministic pairwise contradiction score. Returns None = no conflict."""
    fa, fb = features(a, pol), features(b, pol)
    ca, cb = fa.content, fb.content
    if min(len(ca), len(cb)) < th.min_content:
        return None

    inter = ca & cb
    overlap = len(inter) / min(len(ca), len(cb))
    if overlap < th.subject_overlap:
        return None  # not the same subject

    symdiff = (ca | cb) - inter
    if len(symdiff) > th.max_symdiff:
        return None

    # Guard: passages qualified to different scopes are complementary, not
    # contradictory ("dose for adults" vs "dose for children").
    if symdiff & pol.scope_markers:
        return None

    # Guard: reported/quoted assertions carry a negation that belongs to a
    # third party, not to the passage's own claim.
    meta = fa.has_report_marker or fb.has_report_marker

    # --- Rule A: antonym / comparator inversion --------------------------------
    for x in ca - cb:
        for y in cb - ca:
            if (x, y) in pol.antonyms:
                residual = symdiff - {x, y}
                if len(residual) <= th.max_residual and not meta:
                    return Conflict("antonym", f"{x} <> {y}")

    # --- Rule N: negation-marker asymmetry -------------------------------------
    if (fa.negations % 2) != (fb.negations % 2) and not meta:
        if len(symdiff) <= th.max_residual:
            return Conflict("negation", f"neg {fa.negations} vs {fb.negations}")

    # --- Rule V: numeric / date divergence -------------------------------------
    if fa.numbers and fb.numbers and fa.numbers != fb.numbers:
        subset = fa.numbers <= fb.numbers or fb.numbers <= fa.numbers
        same_units = fa.units == fb.units
        if not subset and same_units and len(symdiff) <= th.max_residual and not meta:
            return Conflict(
                "value", f"{sorted(fa.numbers)} vs {sorted(fb.numbers)}"
            )

    return None


# ─────────────────────────────────────────────────────────────────────────────
# PART 2 — near-duplicate collapse (same seam, same polarity)
# ─────────────────────────────────────────────────────────────────────────────


def is_near_duplicate(a: str, b: str, pol: Polarity = EN) -> str | None:
    """Returns the collapse reason, or None if the two are independent slots."""
    if detect_conflict(a, b, pol) is not None:
        return None  # a conflict is never a duplicate
    ta, tb = tokenize(a.lower()), tokenize(b.lower())
    if ta == tb:
        return "exact"  # covers whitespace/punctuation/case variants
    fa, fb = features(a, pol), features(b, pol)
    if fa.numbers != fb.numbers or fa.negations % 2 != fb.negations % 2:
        return None
    sa, sb = set(ta), set(tb)
    jaccard = len(sa & sb) / len(sa | sb) if (sa | sb) else 0.0
    if jaccard >= 0.80 and abs(len(ta) - len(tb)) <= 2:
        return f"near (jaccard={jaccard:.2f})"
    return None


def collapse(passages: list[tuple[str, str]], pol: Polarity = EN) -> list[str]:
    """passages = [(doc_id, text)] -> surviving doc_ids after clone collapse."""
    kept: list[tuple[str, str]] = []
    for doc, text in passages:
        if any(is_near_duplicate(text, t) for _, t in kept):
            continue
        kept.append((doc, text))
    return [d for d, _ in kept]


# ═════════════════════════════════════════════════════════════════════════════
# FIXTURES — 5 unrelated domains, 3 sets
# ═════════════════════════════════════════════════════════════════════════════

Pair = tuple[str, str, str, str]  # domain, attack/trap label, a, b

TRUE_CONFLICTS: list[Pair] = [
    # ── legal ──
    ("legal", "negation", "The employee shall disclose confidential information to third parties.",
     "The employee shall not disclose confidential information to third parties."),
    ("legal", "value", "The notice period is 30 days.", "The notice period is 60 days."),
    ("legal", "comparator", "The zoning variance was approved by the council.",
     "The zoning variance was rejected by the council."),
    ("legal", "superseded", "The confidentiality policy took effect in 2019.",
     "The confidentiality policy took effect in 2026."),
    ("legal", "negation", "Arbitration is required for contract matters under this agreement.",
     "Arbitration is not required for contract matters under this agreement."),
    ("legal", "comparator", "The injunction was upheld on appeal.",
     "The injunction was overturned on appeal."),
    ("legal", "negation-in-claim-language",
     "The claim for indemnity is valid under section four.",
     "The claim for indemnity is not valid under section four."),
    # ── finance ──
    ("finance", "comparator", "Revenue increased by 12 percent in the third quarter.",
     "Revenue decreased by 12 percent in the third quarter."),
    ("finance", "value", "The restated filing reports net income of 4.2 million.",
     "The restated filing reports net income of 6.8 million."),
    ("finance", "comparator", "The covenant requires the leverage ratio to stay above 2.5.",
     "The covenant requires the leverage ratio to stay below 2.5."),
    ("finance", "superseded", "The special dividend was paid in 2024.",
     "The special dividend was paid in 2025."),
    ("finance", "comparator", "The fund is eligible for the withholding exemption.",
     "The fund is ineligible for the withholding exemption."),
    # ── medical ──
    ("medical", "negation", "The vaccine is recommended for pregnant patients.",
     "The vaccine is not recommended for pregnant patients."),
    ("medical", "value", "The maximum daily dose is 4000 mg.",
     "The maximum daily dose is 3000 mg."),
    ("medical", "comparator", "Treatment increased survival in the trial cohort.",
     "Treatment decreased survival in the trial cohort."),
    ("medical", "superseded", "The prescribing guideline was withdrawn in 2021.",
     "The prescribing guideline was withdrawn in 2023."),
    ("medical", "negation", "Renal impairment is a contraindication for this drug.",
     "Renal impairment is not a contraindication for this drug."),
    # ── operations ──
    ("operations", "value", "The escalation threshold is 15 minutes.",
     "The escalation threshold is 45 minutes."),
    ("operations", "value", "Database backups are retained for 90 days.",
     "Database backups are retained for 30 days."),
    ("operations", "comparator", "Request tracing is enabled in the production cluster.",
     "Request tracing is disabled in the production cluster."),
    ("operations", "comparator", "Change requests are permitted during the freeze window.",
     "Change requests are prohibited during the freeze window."),
    ("operations", "comparator", "The rollback rehearsal is mandatory before deployment.",
     "The rollback rehearsal is optional before deployment."),
    # ── physics ──
    ("physics", "comparator", "Like charges attract each other.",
     "Like charges repel each other."),
    ("physics", "value", "The measured half life is 12 hours.",
     "The measured half life is 20 hours."),
    ("physics", "value", "Pure water boils at 100 degrees at sea level.",
     "Pure water boils at 90 degrees at sea level."),
    ("physics", "comparator", "The aluminium sample expands when heated.",
     "The aluminium sample contracts when heated."),
    ("physics", "negation-morphology", "The reaction conserves momentum in this frame.",
     "The reaction does not conserve momentum in this frame."),
]

HARD_NEGATIVES: list[Pair] = [
    # ── medical ──
    ("medical", "different-aspect (scope word)", "The recommended dose for adults is 500 mg.",
     "The recommended dose for children is 200 mg."),
    ("medical", "different-aspect (no scope word)", "The oral dose is 500 mg.",
     "The intravenous dose is 200 mg."),
    ("medical", "unit variant", "The single dose is 1 g.", "The single dose is 1000 mg."),
    ("medical", "range elaboration", "The maintenance dose is 500 mg.",
     "The maintenance dose is between 250 mg and 500 mg."),
    ("medical", "different-scope negation", "The vaccine is not recommended for pregnant patients.",
     "The vaccine is recommended for elderly patients."),
    ("medical", "complementary", "The drug is metabolised in the liver.",
     "The drug is excreted by the kidneys."),
    # ── legal ──
    ("legal", "strict elaboration", "The notice period is 30 days.",
     "The notice period is 30 days, calculated from the date of service."),
    ("legal", "quoted negation", "The claim that the device is not compliant was rejected.",
     "The device is compliant."),
    ("legal", "different aspect + date", "The confidentiality policy took effect in 2019.",
     "The confidentiality policy was amended in 2026."),
    ("legal", "scope-qualified", "The residential lease requires 30 days notice.",
     "The commercial lease requires 90 days notice."),
    ("legal", "double negation restatement",
     "The clause is not inapplicable to subcontractors.",
     "The clause is applicable to subcontractors."),
    ("legal", "restrictor not negation", "All employees except contractors receive the allowance.",
     "All employees receive the allowance."),
    ("legal", "negation different object", "The employee shall not disclose confidential information.",
     "The employee shall disclose conflicts of interest."),
    # ── finance ──
    ("finance", "elaboration with extra figure", "Net income was 4.2 million.",
     "Net income was 4.2 million, up from 3.1 million."),
    ("finance", "different subject same verb", "Revenue increased by 12 percent in the third quarter.",
     "Costs increased by 12 percent in the third quarter."),
    ("finance", "antonym across scopes", "Domestic revenue increased in the third quarter.",
     "International revenue decreased in the third quarter."),
    ("finance", "antonym across measures", "Gross margin increased in 2024.",
     "Net margin decreased in 2024."),
    ("finance", "antonym different quantity", "Unit sales increased in the third quarter.",
     "Unit prices decreased in the third quarter."),
    ("finance", "quoted negation", "The allegation that revenue was not restated proved false.",
     "Revenue was restated."),
    ("finance", "complementary", "The fee is payable in advance.",
     "The fee is refundable on cancellation."),
    # ── operations ──
    ("operations", "different artefact", "Database backups are retained for 90 days.",
     "Database snapshots are retained for 7 days."),
    ("operations", "different environment", "Request tracing is enabled in the staging cluster.",
     "Request tracing is disabled in the production cluster."),
    ("operations", "unit variant", "The escalation threshold is 2 hours.",
     "The escalation threshold is 120 minutes."),
    ("operations", "different metric", "The p50 latency budget is 200 ms.",
     "The p99 latency budget is 900 ms."),
    # ── physics ──
    ("physics", "different condition", "The aluminium sample expands when heated.",
     "The aluminium sample contracts when cooled."),
    ("physics", "unit variant", "The half life is 2 hours.", "The half life is 120 minutes."),
    ("physics", "different medium", "Sound travels at 343 metres per second in air.",
     "Sound travels at 1480 metres per second in water."),
]

# Written AFTER the thresholds were frozen, and never used to tune them. Three
# parameters (subject_overlap, the measurement-token rule, the dup jaccard) were
# adjusted in response to failures on the sets above, so those sets are training
# data. This is the honesty check.
HELDOUT_NEGATIVES: list[Pair] = [
    ("legal", "different party same duty", "The supplier shall maintain insurance of 5 million.",
     "The contractor shall maintain insurance of 2 million."),
    ("legal", "condition vs base rule", "Late fees apply after 30 days.",
     "Late fees apply after 30 days unless waived by the registrar."),
    ("finance", "different period", "Operating cash flow was 18 million in the first half.",
     "Operating cash flow was 24 million in the second half."),
    ("finance", "currency variant", "The penalty is 500 usd.", "The penalty is 460 eur."),
    ("medical", "different route timing", "The infusion runs over 30 minutes.",
     "The infusion runs over 30 minutes in a monitored setting."),
    ("medical", "different population", "Screening starts at 45 years for average risk.",
     "Screening starts at 40 years for high risk."),
    ("operations", "different tier", "The bronze tier response target is 8 hours.",
     "The gold tier response target is 1 hour."),
    ("operations", "negated different object", "The queue does not retry poison messages.",
     "The queue retries transient failures."),
    ("physics", "different material", "The rod conducts heat at 400 watts per metre kelvin.",
     "The rod conducts heat at 80 watts per metre kelvin in the alloy form."),
    ("physics", "reported hypothesis", "The hypothesis that the field is not conservative was refuted.",
     "The field is conservative."),
]

HELDOUT_CONFLICTS: list[Pair] = [
    ("legal", "value", "The liability cap is 5 million.", "The liability cap is 2 million."),
    ("finance", "negation", "The instrument is subject to withholding tax.",
     "The instrument is not subject to withholding tax."),
    ("medical", "superseded", "The recall was issued in 2022.", "The recall was issued in 2024."),
    ("operations", "comparator", "The failover drill is mandatory each quarter.",
     "The failover drill is optional each quarter."),
    ("physics", "value", "The lattice constant is 5.4 angstroms.",
     "The lattice constant is 4.1 angstroms."),
]

UNRELATED: list[Pair] = [
    ("legal", "shared 'policy'", "The retention policy applies to archived correspondence.",
     "The reactor purge policy requires a 30 second hold."),
    ("finance", "shared 'interest'", "Interest accrues monthly on the outstanding balance.",
     "The employee must declare any conflict of interest."),
    ("medical", "shared 'dose'", "The dose is measured in milligrams.",
     "A dose of radiation is measured in sieverts."),
    ("operations", "shared 'cluster'", "The cluster runs three availability zones.",
     "The galaxy cluster spans four megaparsecs."),
    ("physics", "shared 'charge'", "The charge on an electron is negative.",
     "A late payment charge is applied after 30 days."),
    ("legal", "shared 'period'", "The notice period is 30 days.",
     "The orbital period is 30 days."),
    ("finance", "shared 'margin'", "Gross margin improved in the third quarter.",
     "The margin of error is two percent."),
    ("medical", "shared 'trial'", "The trial enrolled 400 patients.",
     "The trial court dismissed the motion."),
    ("operations", "shared 'window'", "The freeze window closes on Friday.",
     "The transmission window is 30 minutes wide."),
    ("physics", "shared 'mass'", "The mass of the sample is 40 grams.",
     "A mass tort claim was filed in 2019."),
    ("legal", "shared 'service'", "Service of process must be personal.",
     "The service restarts nightly at midnight."),
    ("finance", "shared 'return'", "The annual return was 12 percent.",
     "The tax return is filed in April."),
    ("medical", "shared 'pressure'", "Blood pressure is measured twice daily.",
     "The vessel pressure is 4 bar."),
    ("operations", "shared 'load'", "The load balancer drains connections gracefully.",
     "The beam load is 400 newtons."),
    ("physics", "shared 'current'", "The current through the coil is 2 amps.",
     "The current policy took effect in 2026."),
    ("legal", "shared 'agreement'", "The agreement is governed by Dutch law.",
     "There is broad agreement on the measurement technique."),
    ("finance", "shared 'capital'", "Tier one capital exceeds 12 percent.",
     "The capital city hosts the registry office."),
    ("medical", "shared 'resistance'", "Antibiotic resistance rose after 2019.",
     "The resistance of the wire is 4 ohms."),
    ("operations", "shared 'incident'", "The incident was resolved in 45 minutes.",
     "An incident report must be filed within 30 days."),
    ("physics", "shared 'decay'", "The isotope decay constant is 0.05.",
     "Urban decay was cited in the zoning report."),
    ("legal", "shared 'term'", "The term of the lease is 60 months.",
     "The term is defined in the physics glossary."),
    ("finance", "shared 'exposure'", "Net exposure fell to 4.2 million.",
     "Radiation exposure is limited to 20 millisieverts."),
]


# ═════════════════════════════════════════════════════════════════════════════
# Measurement
# ═════════════════════════════════════════════════════════════════════════════


def evaluate(pol: Polarity = EN, th: Thresholds = DEFAULT) -> dict:
    tp = [p for p in TRUE_CONFLICTS if detect_conflict(p[2], p[3], pol, th)]
    fn = [p for p in TRUE_CONFLICTS if not detect_conflict(p[2], p[3], pol, th)]
    fp_hard = [p for p in HARD_NEGATIVES if detect_conflict(p[2], p[3], pol, th)]
    fp_unrel = [p for p in UNRELATED if detect_conflict(p[2], p[3], pol, th)]
    detected = len(tp) + len(fp_hard) + len(fp_unrel)
    return {
        "tp": tp, "fn": fn, "fp_hard": fp_hard, "fp_unrel": fp_unrel,
        "precision": len(tp) / detected if detected else 1.0,
        "recall": len(tp) / len(TRUE_CONFLICTS),
        "fp_hard_rate": len(fp_hard) / len(HARD_NEGATIVES),
        "fp_unrel_rate": len(fp_unrel) / len(UNRELATED),
    }


def rule(ch: str = "─", n: int = 78) -> None:
    print(ch * n)


def main() -> int:
    print("ADR-0007 conflict-detection spike")
    print(f"fixtures: {len(TRUE_CONFLICTS)} true / {len(HARD_NEGATIVES)} hard-neg "
          f"/ {len(UNRELATED)} unrelated, 5 domains")
    rule("═")

    # ── PART 1 ────────────────────────────────────────────────────────────────
    r = evaluate()
    print("\nPART 1 — pairwise conflict detection (default table + thresholds)\n")
    print(f"  precision            {r['precision']:.3f}")
    print(f"  recall               {r['recall']:.3f}  ({len(r['tp'])}/{len(TRUE_CONFLICTS)})")
    print(f"  FP rate HARD NEG     {r['fp_hard_rate']:.3f}  "
          f"({len(r['fp_hard'])}/{len(HARD_NEGATIVES)})   <- the number that decides this")
    print(f"  FP rate UNRELATED    {r['fp_unrel_rate']:.3f}  "
          f"({len(r['fp_unrel'])}/{len(UNRELATED)})")

    if r["fn"]:
        print("\n  MISSED true conflicts (false negatives — safe direction):")
        for d, k, a, _ in r["fn"]:
            print(f"    - [{d}/{k}] {a[:62]}")
    if r["fp_hard"]:
        print("\n  FALSE CONFLICTS on hard negatives (unsafe — false abstention):")
        for d, k, a, b in r["fp_hard"]:
            c = detect_conflict(a, b)
            print(f"    ! [{d}/{k}] rule={c.rule} {c.detail}")
            print(f"        A: {a}\n        B: {b}")
    if r["fp_unrel"]:
        print("\n  FALSE CONFLICTS on unrelated pairs:")
        for d, k, a, b in r["fp_unrel"]:
            print(f"    ! [{d}/{k}] {detect_conflict(a, b)}")

    # per-domain FP on hard negatives
    print("\n  hard-negative FP by domain:")
    for dom in ("legal", "finance", "medical", "operations", "physics"):
        tot = [p for p in HARD_NEGATIVES if p[0] == dom]
        bad = [p for p in tot if detect_conflict(p[2], p[3])]
        print(f"    {dom:11s} {len(bad)}/{len(tot)}")

    # held-out generalisation check
    ho_fp = [p for p in HELDOUT_NEGATIVES if detect_conflict(p[2], p[3])]
    ho_tp = [p for p in HELDOUT_CONFLICTS if detect_conflict(p[2], p[3])]
    print("\n  HELD-OUT set (written after thresholds were frozen, never tuned on):")
    print(f"    FP rate on held-out hard negatives  "
          f"{len(ho_fp) / len(HELDOUT_NEGATIVES):.3f}  ({len(ho_fp)}/{len(HELDOUT_NEGATIVES)})")
    print(f"    recall on held-out true conflicts   "
          f"{len(ho_tp) / len(HELDOUT_CONFLICTS):.3f}  ({len(ho_tp)}/{len(HELDOUT_CONFLICTS)})")
    for d, k, a, b in ho_fp:
        c = detect_conflict(a, b)
        print(f"    ! [{d}/{k}] rule={c.rule} {c.detail}\n        A: {a}\n        B: {b}")

    # threshold sensitivity — is the result an artefact of one tuning?
    print("\n  threshold sensitivity (residual = divergence left after the signal):")
    print("    residual  recall  FP-hard  FP-unrel")
    for res in (0, 1, 2, 3):
        rr = evaluate(EN, replace(DEFAULT, max_residual=res))
        print(f"      {res}       {rr['recall']:.2f}    {rr['fp_hard_rate']:.2f}     "
              f"{rr['fp_unrel_rate']:.2f}")
    print("    subject_overlap  recall  FP-hard")
    for ov in (0.6, 0.7, 0.75, 0.85, 1.0):
        rr = evaluate(EN, replace(DEFAULT, subject_overlap=ov))
        print(f"      {ov:.2f}           {rr['recall']:.2f}    {rr['fp_hard_rate']:.2f}")

    rule("═")

    # ── PART 2 ────────────────────────────────────────────────────────────────
    print("\nPART 2 — near-duplicate collapse\n")
    base = "The vendor shall notify the customer within 30 days of a breach."
    dup_cases = [
        ("exact duplicate", base, base, True),
        ("whitespace variant", base, "The vendor shall notify the customer  within 30 days of a breach.", True),
        ("punctuation variant", base, "The vendor shall notify the customer, within 30 days, of a breach!", True),
        ("case variant", base, base.upper(), True),
        ("one word changed (synonym)", base,
         "The vendor must notify the customer within 30 days of a breach.", True),
        ("one word changed (VALUE)", base,
         "The vendor shall notify the customer within 60 days of a breach.", False),
        ("one word changed (NEGATION)", base,
         "The vendor shall not notify the customer within 30 days of a breach.", False),
        ("genuine independent restatement", base,
         "Breach notification to the affected customer is due inside one month.", False),
        ("paraphrase of the same source", base,
         "Within 30 days of a breach, the customer shall be notified by the vendor.", False),
    ]
    ok2 = True
    for label, a, b, expect in dup_cases:
        got = is_near_duplicate(a, b)
        good = bool(got) == expect
        ok2 &= good
        print(f"  [{'ok ' if good else 'FAIL'}] {label:34s} collapse={bool(got):<5} "
              f"expected={expect:<5} {got or ''}")

    print("\n  Probe-C scenario: one sentence under five document ids")
    mirrors = [(f"doc{i}", base) for i in range(1, 6)]
    print(f"    distinct_documents before collapse: {len(mirrors)}")
    print(f"    distinct_documents after  collapse: {len(collapse(mirrors))}")
    mixed = [("doc1", base), ("doc2", base + " "), ("doc3", dup_cases[7][2])]
    print(f"    mirrors + one genuine restatement:  {len(collapse(mixed))} (want 2)")

    rule("═")

    # ── PART 3 ────────────────────────────────────────────────────────────────
    print("\nPART 3 — what a bad polarity table costs\n")
    corruptions = {
        "clean (shipped table)": EN,
        "+ hedges as negations (except/unless/however/although)": replace(
            EN, negations=EN.negations | {"except", "exempt", "unless", "however", "although", "but"}
        ),
        "+ bogus antonym pairs (oral/iv, staging/prod, heated/cooled)": replace(
            EN, antonyms=EN.antonyms | {("oral", "intravenous"), ("intravenous", "oral"),
                                        ("staging", "production"), ("production", "staging"),
                                        ("heated", "cooled"), ("cooled", "heated"),
                                        ("backups", "snapshots"), ("snapshots", "backups")}
        ),
        "- scope markers removed (empty scope table)": replace(EN, scope_markers=frozenset()),
        "- report markers removed (no quoted-negation guard)": replace(EN, report_markers=frozenset()),
        "all of the above": replace(
            EN,
            negations=EN.negations | {"except", "exempt", "unless", "however", "although", "but"},
            antonyms=EN.antonyms | {("oral", "intravenous"), ("intravenous", "oral"),
                                    ("staging", "production"), ("production", "staging"),
                                    ("heated", "cooled"), ("cooled", "heated"),
                                    ("backups", "snapshots"), ("snapshots", "backups")},
            scope_markers=frozenset(),
            report_markers=frozenset(),
        ),
    }
    print(f"  {'table':56s} recall  FP-hard")
    for label, p in corruptions.items():
        rr = evaluate(p)
        print(f"  {label:56s}  {rr['recall']:.2f}    {rr['fp_hard_rate']:.2f}")
    print("\n  FP-hard is the false-abstention rate in strict mode: every point of")
    print("  it is a refusal on a pair of passages that do not actually disagree.")

    rule("═")
    verdict = r["fp_hard_rate"] <= FP_BUDGET
    print(f"\nVERDICT: hard-negative FP rate {r['fp_hard_rate']:.3f} "
          f"(budget {FP_BUDGET:.2f}) -> {'PASS' if verdict else 'FAIL'}")
    print(f"         recall {r['recall']:.3f}; near-duplicate cases "
          f"{'all pass' if ok2 else 'HAVE FAILURES'}")
    return 0 if (verdict and ok2) else 1


if __name__ == "__main__":
    raise SystemExit(main())
