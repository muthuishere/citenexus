"""ADR-0007: deterministic conflict detection and near-duplicate collapse.

The headline assertion in this file is ``test_hard_negatives_produce_no_conflict``.
In strict mode a detected conflict abstains, so a FALSE conflict is a FALSE
REFUSAL on two passages that do not disagree, while a missed conflict merely
leaves today's behaviour in place. Recall failures are free; precision failures
are not. Every fixture below is single-sentence, English and synthetic — enough
to reject a design, not enough to certify one.

Fixtures ported from ``spikes/adr-0007-conflict/`` and kept here so
``scripts/gen_conformance.py`` can generate the conformance vectors from one copy
of the data.
"""

from __future__ import annotations

import pytest

from citenexus.answer.conflict import (
    MAX_RESIDUAL,
    collapse_near_duplicates,
    detect_conflict,
    find_conflicts,
    is_near_duplicate,
)

# (domain, label, passage a, passage b)
Pair = tuple[str, str, str, str]

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

#: Pairs that LOOK like contradictions and are not. Each differs by one further
#: content word — the scope, the route, the environment, the metric — and that
#: word is exactly what makes the two passages complementary.
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
    ("legal", "negation different object",
     "The employee shall not disclose confidential information.",
     "The employee shall disclose conflicts of interest."),
    # ── finance ──
    ("finance", "elaboration with extra figure", "Net income was 4.2 million.",
     "Net income was 4.2 million, up from 3.1 million."),
    ("finance", "different subject same verb",
     "Revenue increased by 12 percent in the third quarter.",
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

#: Pairs sharing one polysemous word and nothing else.
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

#: Written after the spike's thresholds were frozen and never tuned against.
#: The main sets above are training data; this one is the generalisation check.
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
    ("physics", "reported hypothesis",
     "The hypothesis that the field is not conservative was refuted.",
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

_CLONE_BASE = "The vendor shall notify the customer within 30 days of a breach."

#: (label, a, b, collapses?)
DUPLICATE_CASES: list[tuple[str, str, str, bool]] = [
    ("exact duplicate", _CLONE_BASE, _CLONE_BASE, True),
    ("whitespace variant", _CLONE_BASE,
     "The vendor shall notify the customer  within 30 days of a breach.", True),
    ("punctuation variant", _CLONE_BASE,
     "The vendor shall notify the customer, within 30 days, of a breach!", True),
    ("case variant", _CLONE_BASE, _CLONE_BASE.upper(), True),
    ("one word changed (synonym)", _CLONE_BASE,
     "The vendor must notify the customer within 30 days of a breach.", True),
    ("one word changed (VALUE)", _CLONE_BASE,
     "The vendor shall notify the customer within 60 days of a breach.", False),
    ("one word changed (NEGATION)", _CLONE_BASE,
     "The vendor shall not notify the customer within 30 days of a breach.", False),
    ("genuine independent restatement", _CLONE_BASE,
     "Breach notification to the affected customer is due inside one month.", False),
    # Known miss, recorded rather than chased: "the same source paraphrased" and
    # "the same fact independently restated" are indistinguishable to any textual
    # detector. Under-collapsing leaves distinct_documents as inflated as it is
    # today; over-collapsing would under-report real corroboration.
    ("paraphrase of the same source", _CLONE_BASE,
     "Within 30 days of a breach, the customer shall be notified by the vendor.", False),
]


# ─────────────────────────────────────────────────────────────────────────────
# The measurement that decides the design
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("domain", "label", "left", "right"), HARD_NEGATIVES)
def test_hard_negatives_produce_no_conflict(
    domain: str, label: str, left: str, right: str
) -> None:
    """Zero false conflicts, because a false conflict is a false refusal."""
    assert detect_conflict(left, right) is None, f"{domain}/{label}"


@pytest.mark.parametrize(("domain", "label", "left", "right"), UNRELATED)
def test_unrelated_pairs_produce_no_conflict(
    domain: str, label: str, left: str, right: str
) -> None:
    assert detect_conflict(left, right) is None, f"{domain}/{label}"


@pytest.mark.parametrize(("domain", "label", "left", "right"), HELDOUT_NEGATIVES)
def test_heldout_negatives_produce_no_conflict(
    domain: str, label: str, left: str, right: str
) -> None:
    assert detect_conflict(left, right) is None, f"{domain}/{label}"


@pytest.mark.parametrize(("domain", "label", "left", "right"), TRUE_CONFLICTS)
def test_true_conflicts_are_detected(
    domain: str, label: str, left: str, right: str
) -> None:
    assert detect_conflict(left, right) is not None, f"{domain}/{label}"


def test_heldout_recall_is_recorded_not_asserted_perfect() -> None:
    """Held-out recall is 4/5 and the miss is named, not hidden.

    "The recall was issued in 2022/2024" has only two content tokens once the
    year is taken as a value, which is below the comparability floor. Very short
    passages are not comparable, and that failure is in the safe direction.
    """
    detected = [p for p in HELDOUT_CONFLICTS if detect_conflict(p[2], p[3])]
    assert len(detected) == 4
    missed = [p for p in HELDOUT_CONFLICTS if not detect_conflict(p[2], p[3])]
    assert [p[1] for p in missed] == ["superseded"]


# ─────────────────────────────────────────────────────────────────────────────
# The guards, each pinned by the failure it exists to prevent
# ─────────────────────────────────────────────────────────────────────────────


def test_max_residual_is_pinned_at_one() -> None:
    """Relaxing this to 2 buys 4pp recall and costs 15pp false abstention."""
    assert MAX_RESIDUAL == 1


def test_identifiers_containing_digits_stay_in_the_content_set() -> None:
    """The tokenization trap, with its own vector.

    A digit-LEADING token ("500mg", "2019") is a measured value. A letter-leading
    token containing digits ("p50", "ipv4") is an IDENTIFIER, and eating it as a
    number removes the only word distinguishing two passages — which produced the
    spike's single false conflict.
    """
    assert detect_conflict(
        "The p50 latency budget is 200 ms.", "The p99 latency budget is 900 ms."
    ) is None
    # Same shape, same subject, no distinguishing identifier: a real conflict.
    assert detect_conflict(
        "The latency budget is 200 ms.", "The latency budget is 900 ms."
    ) is not None


def test_report_markers_are_bigram_scoped() -> None:
    """"claim that" suppresses; a bare "claim" must not.

    As a unigram this guard silently disables conflict detection across most
    legal text, where "claim" is a noun of art.
    """
    assert detect_conflict(
        "The claim that the device is not compliant was rejected.",
        "The device is compliant.",
    ) is None
    assert detect_conflict(
        "The claim for indemnity is valid under section four.",
        "The claim for indemnity is not valid under section four.",
    ) is not None


def test_scope_restrictors_are_not_negations() -> None:
    """"except" restricts scope; treating it as polarity costs false refusals."""
    assert detect_conflict(
        "All employees except contractors receive the allowance.",
        "All employees receive the allowance.",
    ) is None


def test_equal_units_are_required_for_a_value_conflict() -> None:
    """Suppresses 1 g vs 1000 mg without knowing any conversion factor."""
    assert detect_conflict("The single dose is 1 g.", "The single dose is 1000 mg.") is None


def test_detection_is_symmetric() -> None:
    for _, _, left, right in TRUE_CONFLICTS + HARD_NEGATIVES:
        forward, backward = detect_conflict(left, right), detect_conflict(right, left)
        assert (forward is None) == (backward is None)
        if forward is not None and backward is not None:
            assert forward.rule == backward.rule


def test_detection_is_pure_and_repeatable() -> None:
    for _, _, left, right in TRUE_CONFLICTS:
        assert detect_conflict(left, right) == detect_conflict(left, right)


# ─────────────────────────────────────────────────────────────────────────────
# Near-duplicate collapse
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("label", "left", "right", "collapses"), DUPLICATE_CASES)
def test_near_duplicate_cases(label: str, left: str, right: str, collapses: bool) -> None:
    assert bool(is_near_duplicate(left, right)) is collapses, label


def test_conflict_is_checked_before_duplication() -> None:
    """A value or negation change must never collapse into corroboration."""
    valued = "The vendor shall notify the customer within 60 days of a breach."
    negated = "The vendor shall not notify the customer within 30 days of a breach."
    for other in (valued, negated):
        assert detect_conflict(_CLONE_BASE, other) is not None
        assert is_near_duplicate(_CLONE_BASE, other) is None
    assert len(collapse_near_duplicates([_CLONE_BASE, valued, negated])) == 3


def test_mirrors_collapse_to_one_slot() -> None:
    assert collapse_near_duplicates([_CLONE_BASE] * 5) == (0,)


def test_mirrors_plus_an_independent_restatement_collapse_to_two() -> None:
    restatement = "Breach notification to the affected customer is due inside one month."
    passages = [_CLONE_BASE, _CLONE_BASE + " ", _CLONE_BASE.upper(), restatement]
    assert collapse_near_duplicates(passages) == (0, 3)


def test_collapse_preserves_rank_order() -> None:
    passages = ["first unrelated passage about turbines", _CLONE_BASE, _CLONE_BASE]
    assert collapse_near_duplicates(passages) == (0, 1)


# ─────────────────────────────────────────────────────────────────────────────
# Pairwise scan
# ─────────────────────────────────────────────────────────────────────────────


def test_find_conflicts_reports_every_pair_by_index() -> None:
    pairs = find_conflicts(
        [
            "The notice period is 30 days.",
            "The turbine is inspected every spring.",
            "The notice period is 60 days.",
        ]
    )
    assert [(p.left, p.right) for p in pairs] == [(0, 2)]
    assert pairs[0].finding.rule == "value"


def test_find_conflicts_is_bounded_by_top_k() -> None:
    passages = ["The turbine is inspected every spring."] * 6
    passages += ["The notice period is 30 days.", "The notice period is 60 days."]
    assert find_conflicts(passages) == ()


def test_describe_names_both_documents_and_never_a_winner() -> None:
    pair = find_conflicts(["The notice period is 30 days.", "The notice period is 60 days."])[0]
    described = pair.describe("policy-2019", "policy-2026")
    assert "policy-2019" in described
    assert "policy-2026" in described
    assert "30" in described and "60" in described
