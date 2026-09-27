"""verify_answer unit tests — a port of the Go tests that pin behaviour beyond
the conformance vectors (``golang/answer/verify_answer_test.go``,
``verify_number_forms_test.go``, ``verify_union_reason_test.go``,
``verify_parties_binding_test.go``, ``verify_premise_invariance_test.go``)."""

from __future__ import annotations

import io
import json
import re
from dataclasses import replace

import pytest

from citenexus import SupportChecker, VerifyOptions, verify_answer
from citenexus.answer.glossary import (
    GlossaryEntry,
    GlossaryError,
    parse_glossary_tsv,
    prepare_glossary,
)
from citenexus.answer.result import Claim, Decision, Result
from citenexus.answer.verify import is_supported_v2
from citenexus.answer.verify_answer import (
    CONFLICT_REFUSAL_ANSWER,
    REASON_BELOW_FLOOR,
    REASON_CONTRADICTED,
    REASON_NOT_SUPPORTED,
    REASON_OUTRANKED,
    REASON_UNCITED,
    REASON_UNKNOWN_CITATION,
    REASON_UNRESOLVED_CLAIMS,
    CitedClaim,
    EvidenceUnit,
    Facet,
    InvalidEvidenceError,
    SupportCheckerError,
    parse_citations,
)
from citenexus.answer.verify_exclusions import exclusion_guard
from citenexus.answer.verify_guards import GuardConfig, names, number_guard
from citenexus.answer.verify_qualifier_pairs import DEFAULT_QUALIFIER_PAIRS, QualifierPair
from citenexus.answer.verify_roles import DEFAULT_ACTOR_LEXICON, ActorLexicon
from citenexus.answer.verify_verbpairs import DEFAULT_VERB_PAIRS, verb_pair_guard
from citenexus.domain.authority import AuthorityPolicy

NOTICE30 = EvidenceUnit(
    id="hr-1#0", document_id="hr-1", text="The notice period is 30 days.", language="en"
)
NOTICE60 = EvidenceUnit(
    id="hr-2#0", document_id="hr-2", text="The notice period is 60 days.", language="en"
)
LEAVE = EvidenceUnit(
    id="hr-3#0",
    document_id="hr-3",
    text="Employees receive 25 days of annual leave.",
    language="en",
)
DUTCH_LEAVE = EvidenceUnit(
    id="nl-1#0",
    document_id="nl-1",
    text="Werknemers krijgen 25 vakantiedagen per jaar.",
    language="nl",
)


class FakeChecker:
    """Answers from a table keyed by passage; unknown passages score (0, 0)."""

    def __init__(
        self, scores: dict[str, tuple[float, float]] | None = None, error: Exception | None = None
    ) -> None:
        self.scores = scores or {}
        self.error = error
        self.calls = 0

    def check(self, claim: str, passage: str) -> tuple[float, float]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.scores.get(passage, (0.0, 0.0))


class AdmitAll:
    def check(self, claim: str, passage: str) -> tuple[float, float]:
        return 0.999, 0.0


class LowChecker:
    def check(self, claim: str, passage: str) -> tuple[float, float]:
        return 0.1, 0.02


def verify(answer: str, evidence: list[EvidenceUnit], opts: VerifyOptions | None = None) -> Result:
    return verify_answer(answer, evidence, opts or VerifyOptions())


def test_checkers_satisfy_the_published_contract() -> None:
    assert isinstance(FakeChecker(), SupportChecker)
    assert isinstance(AdmitAll(), SupportChecker)


@pytest.mark.parametrize(
    ("answer", "want"),
    [
        (
            "One fact [eu:a]. Two fact [eu:b].",
            [CitedClaim("One fact.", ["a"]), CitedClaim("Two fact.", ["b"])],
        ),
        (
            "One fact. [eu:a] Two fact. [eu:b]",
            [CitedClaim("One fact.", ["a"]), CitedClaim("Two fact.", ["b"])],
        ),
        ("One fact [eu:doc.pdf#3].", [CitedClaim("One fact.", ["doc.pdf#3"])]),
        ("One fact [eu:a, eu:b][eu:c, a].", [CitedClaim("One fact.", ["a", "b", "c"])]),
        ("One fact.", [CitedClaim("One fact.")]),
        (
            "One fact [eu:a][q:cost]. Two fact [q:when, q:who][eu:b].",
            [
                CitedClaim("One fact.", ["a"], ["cost"]),
                CitedClaim("Two fact.", ["b"], ["when", "who"]),
            ],
        ),
    ],
    ids=[
        "marker before period",
        "marker after period attaches backwards",
        "dotted id does not split",
        "comma list and repeated groups",
        "uncited",
        "facet markers are separate from citations",
    ],
)
def test_parse_citations(answer: str, want: list[CitedClaim]) -> None:
    assert parse_citations(answer) == want


def test_keeps_the_true_half() -> None:
    res = verify(
        "The notice period is 30 days [eu:hr-1#0]. The notice period is 90 days [eu:hr-1#0].",
        [NOTICE30, LEAVE],
    )
    assert res.evidence.decision == Decision.partial
    assert res.answer == "The notice period is 30 days."
    assert not res.evidence.all_claims_verified
    assert res.evidence.unsupported_claims_removed == 1
    assert res.claims[0].verified_by == "gate"
    assert res.claims[1].reason == REASON_NOT_SUPPORTED
    assert len(res.sources) == 1
    assert res.sources[0].document == "hr-1"


def test_citation_rules() -> None:
    ev = [NOTICE30, LEAVE]
    res = verify("The notice period is 30 days [eu:nope].", ev)
    assert res.evidence.decision == Decision.refused
    assert res.claims[0].reason == REASON_UNKNOWN_CITATION
    # A wrong citation is not rescued by another unit.
    assert verify("The notice period is 30 days [eu:hr-3#0].", ev).evidence.decision == (
        Decision.refused
    )
    # Uncited is searched by default.
    res = verify("The notice period is 30 days.", ev)
    assert res.evidence.decision == Decision.answered
    assert res.claims[0].sources[0] == "hr-1#0"
    # Uncited is dropped when citations are required.
    res = verify("The notice period is 30 days.", ev, VerifyOptions(require_citations=True))
    assert res.evidence.decision == Decision.refused
    assert res.claims[0].reason == REASON_UNCITED
    # An empty answer refuses.
    assert verify("  ", ev).evidence.decision == Decision.refused


@pytest.mark.parametrize("evidence", [[NOTICE30, NOTICE30], [EvidenceUnit(id="", text="x")]])
def test_invalid_evidence_is_an_error(evidence: list[EvidenceUnit]) -> None:
    with pytest.raises(InvalidEvidenceError):
        verify("x", evidence)


def test_support_checker_vetoes_a_gate_admitted_claim() -> None:
    checker = FakeChecker({NOTICE30.text: (0.1, 0.8)})
    res = verify(
        "The notice period is 30 days [eu:hr-1#0].", [NOTICE30], VerifyOptions(checker=checker)
    )
    assert res.evidence.decision == Decision.refused
    assert res.claims[0].reason == REASON_CONTRADICTED


def test_support_checker_admits_only_cross_language_claims() -> None:
    checker = FakeChecker({DUTCH_LEAVE.text: (0.97, 0.01), LEAVE.text: (0.97, 0.01)})
    opts = VerifyOptions(checker=checker, checker_name="mdeberta", answer_language="en")
    res = verify("Employees get 25 vacation days a year [eu:nl-1#0].", [DUTCH_LEAVE], opts)
    assert res.evidence.decision == Decision.answered
    assert res.claims[0].verified_by == "model:mdeberta"
    assert res.evidence.model_verified_claims == 1
    # Same language: the checker's entailment must NOT rescue a gate failure.
    res = verify("Staff get 25 vacation days a year [eu:hr-3#0].", [LEAVE], opts)
    assert res.evidence.decision == Decision.refused
    # Undeclared answer language: no admission either.
    res = verify(
        "Employees get 25 vacation days a year [eu:nl-1#0].",
        [DUTCH_LEAVE],
        replace(opts, answer_language=""),
    )
    assert res.evidence.decision == Decision.refused


def test_support_checker_below_threshold_does_not_admit() -> None:
    checker = FakeChecker({DUTCH_LEAVE.text: (0.85, 0.01)})
    res = verify(
        "Employees get 25 vacation days a year [eu:nl-1#0].",
        [DUTCH_LEAVE],
        VerifyOptions(checker=checker, answer_language="en-GB"),
    )
    assert res.evidence.decision == Decision.refused


def test_support_checker_error_is_an_error() -> None:
    checker = FakeChecker(error=RuntimeError("onnx: boom"))
    with pytest.raises(SupportCheckerError, match="boom"):
        verify(
            "The notice period is 30 days [eu:hr-1#0].", [NOTICE30], VerifyOptions(checker=checker)
        )


def test_equal_authority_conflict_abstains_citing_both_sides() -> None:
    res = verify("The notice period is 30 days [eu:hr-1#0].", [NOTICE30, NOTICE60])
    assert res.answer == CONFLICT_REFUSAL_ANSWER
    assert res.evidence.conflicts_detected == 1
    assert len(res.sources) == 2
    assert res.claims[0].reason == REASON_UNRESOLVED_CLAIMS


def test_higher_authority_resolves_the_conflict() -> None:
    adopted = replace(NOTICE30, authority={"authority_tier": "adopted"})
    proposal = replace(NOTICE60, authority={"authority_tier": "proposal"})
    policy = AuthorityPolicy.ordered(("proposal", "adopted"))
    ev = [proposal, adopted]
    res = verify("The notice period is 30 days [eu:hr-1#0].", ev, VerifyOptions(authority=policy))
    assert res.evidence.decision == Decision.answered
    assert res.evidence.authority_tier == "adopted"
    assert len(res.conflicts) == 1
    assert "resolved by authority" in res.conflicts[0]
    res = verify("The notice period is 60 days [eu:hr-2#0].", ev, VerifyOptions(authority=policy))
    assert res.evidence.decision == Decision.refused
    assert res.claims[0].reason == REASON_OUTRANKED


def test_authority_floor_excludes_cited_evidence() -> None:
    note = replace(LEAVE, authority={"authority_tier": "note"})
    policy = AuthorityPolicy.ordered(("note", "adopted"), minimum_tier="adopted")
    res = verify(
        "Employees receive 25 days of annual leave [eu:hr-3#0].",
        [note],
        VerifyOptions(authority=policy),
    )
    assert res.evidence.decision == Decision.refused
    assert res.evidence.authority_floor_applied
    assert res.claims[0].reason == REASON_BELOW_FLOOR
    assert res.missing_evidence[0] == "no evidence at or above the required authority tier"


def test_new_result_fields_are_omitted_when_empty() -> None:
    raw = Claim(claim="x", supported=False).model_dump_json()
    assert "verified_by" not in raw
    assert "reason" not in raw
    res = verify("The notice period is 30 days [eu:hr-1#0].", [NOTICE30])
    signals = json.loads(res.model_dump_json())["evidence"]
    assert "model_verified_claims" not in signals
    assert "missing_facets" not in signals
    # And a populated Result round-trips.
    assert Result.model_validate_json(res.model_dump_json()) == res


@pytest.mark.parametrize(
    ("guard", "claim"),
    [
        ("number", "Employees get 30 vacation days a year [eu:nl-1#0]."),
        ("negation", "Employees do not get 25 vacation days a year [eu:nl-1#0]."),
        ("name", "Employees at Acme get 25 vacation days a year [eu:nl-1#0]."),
    ],
)
def test_guards_cannot_be_overridden_by_the_model(guard: str, claim: str) -> None:
    sure = FakeChecker({DUTCH_LEAVE.text: (0.99, 0.0)})
    res = verify(claim, [DUTCH_LEAVE], VerifyOptions(checker=sure, answer_language="en"))
    assert res.evidence.decision == Decision.refused
    assert res.claims[0].reason.startswith(guard + " guard")


@pytest.mark.parametrize(
    ("claim", "claim_lang", "passage", "passage_lang", "passes"),
    [
        ("The fee is €25.50.", "en", "De vergoeding is € 25,50.", "nl", True),
        ("The budget is €1,500.", "en", "Het budget is € 1.500.", "nl", True),
        ("De vergoeding is € 25,-.", "nl", "De vergoeding is € 25,00.", "nl", True),
        ("The fee is €25.05.", "en", "De vergoeding is € 25,50.", "nl", False),
        # ADR-0015 amendment 2026-09-27: copied verbatim, the claim's "1.500"
        # keeps the passage's (Dutch) reading — this was a refusal.
        ("The budget is €1.500.", "en", "Het budget is € 1.500.", "nl", True),
        ("The budget is €1.500.", "en", "Het budget is € 1500.", "nl", False),  # not copied
        ("Het budget is € 1.500.", "", "Het budget is € 1500.", "nl", False),  # ambiguous
    ],
)
def test_number_guard_reads_each_side_in_its_language(
    claim: str, claim_lang: str, passage: str, passage_lang: str, passes: bool
) -> None:
    assert (number_guard(claim, claim_lang, passage, passage_lang) == "") == passes


def test_names() -> None:
    got = names("Employees at Acme get the CAO bonus per R-119. Then Payroll pays.")
    assert got == ["Acme", "CAO", "R-119", "Payroll"]


def test_quote_path_anchors_the_content() -> None:
    fee = EvidenceUnit(
        id="faq#7",
        document_id="faq",
        language="nl",
        text="Voor thuiswerken geldt een vergoeding van € 25 exclusief btw per maand.",
    )
    checker = FakeChecker({fee.text: (0.95, 0.01)})
    opts = VerifyOptions(checker=checker, checker_name="nli", answer_language="nl")
    res = verify(
        'Bij thuiswerk geldt "een vergoeding van € 25 exclusief btw" [eu:faq#7].', [fee], opts
    )
    assert res.claims[0].verified_by == "quote+model:nli"
    # A quote that is not in the passage anchors nothing.
    res = verify('Er geldt "een vergoeding van € 25 inclusief btw" [eu:faq#7].', [fee], opts)
    assert res.evidence.decision == Decision.refused
    # Without a checker the quote alone admits nothing.
    res = verify(
        'Bij thuiswerk geldt "een vergoeding van € 25 exclusief btw" [eu:faq#7].',
        [fee],
        VerifyOptions(answer_language="nl"),
    )
    assert res.evidence.decision == Decision.refused


def test_admit_paraphrase_is_opt_in() -> None:
    checker = FakeChecker({LEAVE.text: (0.97, 0.01)})
    claim = "Staff get 25 days of annual leave [eu:hr-3#0]."
    opts = VerifyOptions(checker=checker, checker_name="nli", answer_language="en")
    assert verify(claim, [LEAVE], opts).evidence.decision == Decision.refused
    res = verify(claim, [LEAVE], replace(opts, admit_paraphrase=True))
    assert res.evidence.decision == Decision.answered
    assert res.claims[0].verified_by == "model:nli"


def test_missing_facets_are_named() -> None:
    opts = VerifyOptions(
        facets=(Facet("notice", "the notice period"), Facet("leave", "annual leave"))
    )
    ev = [NOTICE30, LEAVE]
    res = verify(
        "The notice period is 30 days [eu:hr-1#0][q:notice]. "
        "Employees receive 40 days of annual leave [eu:hr-3#0][q:leave].",
        ev,
        opts,
    )
    assert res.evidence.decision == Decision.partial
    assert res.evidence.missing_facets == ("leave",)
    assert "no verified answer for: annual leave" in "|".join(res.missing_evidence)
    res = verify(
        "The notice period is 30 days [eu:hr-1#0][q:notice]. "
        "Employees receive 25 days of annual leave [eu:hr-3#0][q:leave].",
        ev,
        opts,
    )
    assert res.evidence.decision == Decision.answered
    assert res.evidence.missing_facets == ()


def test_clause_final_negation_is_not_dropped() -> None:
    parking = EvidenceUnit(
        id="p#1",
        document_id="p",
        language="nl",
        text="De werkgever vergoedt de parkeerkosten niet. Reiskosten worden wel vergoed.",
    )
    # The shared predicate accepts the dropped negation — the hole this closes.
    assert is_supported_v2("De werkgever vergoedt de parkeerkosten.", parking.text)
    sure = FakeChecker({parking.text: (0.99, 0.0)})
    for opts in (
        VerifyOptions(),
        VerifyOptions(checker=sure, admit_paraphrase=True, answer_language="nl"),
    ):
        res = verify("De werkgever vergoedt de parkeerkosten [eu:p#1].", [parking], opts)
        assert res.evidence.decision == Decision.refused
        assert res.claims[0].reason.startswith("negation guard")
    # The negated claim itself, and a claim from the next clause, still pass.
    res = verify(
        "De werkgever vergoedt de parkeerkosten niet [eu:p#1]. Reiskosten worden vergoed [eu:p#1].",
        [parking],
    )
    assert res.evidence.decision == Decision.answered


def test_next_clause_negation_does_not_refuse() -> None:
    ev = EvidenceUnit(
        id="c#1",
        document_id="c",
        language="nl",
        text="De werkgever vergoedt de parkeerkosten, maar niet de reiskosten.",
    )
    res = verify("De werkgever vergoedt de parkeerkosten [eu:c#1].", [ev])
    assert res.evidence.decision == Decision.answered


def test_r119_r120_incl_excl_btw() -> None:
    faq = EvidenceUnit(
        id="R-119",
        document_id="hr-faq",
        language="nl",
        text="Voor thuiswerken geldt een vergoeding van € 25 exclusief btw per maand.",
        authority={"source_layer": "adopted"},
    )
    note = EvidenceUnit(
        id="R-120",
        document_id="voorgesteld-beleid",
        language="nl",
        text="Voor thuiswerken geldt een vergoeding van € 25 inclusief btw per maand.",
        authority={"source_layer": "proposal"},
    )
    claim = "Voor thuiswerken geldt een vergoeding van € 25 exclusief btw per maand [eu:R-119]."
    res = verify(claim, [faq, note], VerifyOptions(answer_language="nl"))
    assert res.answer == CONFLICT_REFUSAL_ANSWER
    assert len(res.sources) == 2
    assert res.conflicts[0].startswith("inclusion:")
    policy = AuthorityPolicy.ordered(("proposal", "adopted"), key="source_layer")
    res = verify(claim, [faq, note], VerifyOptions(answer_language="nl", authority=policy))
    assert res.evidence.decision == Decision.answered
    assert "resolved by authority" in res.conflicts[0]


def test_lead_in_frames_empty_disables_the_rule() -> None:
    ev = [
        EvidenceUnit(
            id="a",
            document_id="a",
            language="nl",
            text="De werknemer heeft recht op 25 vakantiedagen per kalenderjaar.",
        )
    ]
    answer = "Zo zit het:\n- De werknemer heeft recht op 25 vakantiedagen per kalenderjaar [eu:a]"
    res = verify(answer, ev, VerifyOptions(answer_language="nl", lead_in_frames=()))
    assert len(res.claims) == 1
    assert not res.claims[0].supported
    assert res.claims[0].claim.startswith("Zo zit het")


def test_role_guard_lexicon_replaces_the_default() -> None:
    ev = [
        EvidenceUnit(
            id="a",
            document_id="a",
            language="nl",
            text="De werkgever betaalt de rest; je betaalt 4,5%.",
        )
    ]
    answer = "De werkgever betaalt 4,5% [eu:a]."
    assert not verify(answer, ev, VerifyOptions(answer_language="nl")).claims[0].supported
    res = verify(answer, ev, VerifyOptions(answer_language="nl", actors=ActorLexicon()))
    assert res.claims[0].supported


def test_qualifier_pairs_are_host_extensible() -> None:
    ev = [
        EvidenceUnit(
            id="a",
            document_id="a",
            language="nl",
            text="De daluren-toeslag bedraagt 15% tijdens de daluren.",
        )
    ]
    answer = "The peak-hours supplement is 15% [eu:a]."
    chk = FakeChecker({ev[0].text: (0.999, 0.0)})
    base = VerifyOptions(answer_language="en", checker=chk, checker_name="fake")
    assert verify(answer, ev, base).claims[0].supported
    with_pair = replace(
        base,
        qualifier_pairs=(
            *DEFAULT_QUALIFIER_PAIRS,
            QualifierPair(a=("peak-hours", "spits"), b=("daluren", "off-peak")),
        ),
    )
    assert not verify(answer, ev, with_pair).claims[0].supported


def test_exclusion_guard_has_no_verdict_across_languages_without_a_glossary() -> None:
    claim = (
        "Teachers who work from home at least one day a week receive €2.35 per day worked "
        "from home."
    )
    unit = EvidenceUnit(
        id="S1",
        document_id="thuiswerkregeling Stichting Openbaar Onderwijs Duinrand",
        language="nl",
        text=(
            "Thuiswerkvergoeding. Medewerkers van het bestuursbureau die op grond van een "
            "thuiswerkafspraak ten minste één dag per week thuiswerken, ontvangen een "
            "vergoeding van € 2,35 per thuiswerkdag. Voor leraren en onderwijsondersteunend "
            "personeel geldt deze vergoeding niet."
        ),
    )
    assert exclusion_guard(claim, "en", unit, GuardConfig(actors=DEFAULT_ACTOR_LEXICON)) == ""
    cfg = GuardConfig(
        actors=DEFAULT_ACTOR_LEXICON,
        gloss=prepare_glossary([("leraren", "teachers"), ("leraar", "teacher")], None),
    )
    assert exclusion_guard(claim, "en", unit, cfg).startswith("exclusion guard")


def test_verb_pair_guard_has_no_verdict_across_languages_without_a_glossary() -> None:
    unit = EvidenceUnit(
        id="a",
        language="nl",
        text=(
            "De werknemer vraagt het aanvullend verlof ten minste vier weken van tevoren aan "
            "bij de leidinggevende."
        ),
    )
    claim = "You take the additional leave at least four weeks in advance."
    cfg = GuardConfig(actors=DEFAULT_ACTOR_LEXICON)
    assert verb_pair_guard(claim, "en", unit, DEFAULT_VERB_PAIRS, cfg) == ""
    cfg = GuardConfig(
        actors=DEFAULT_ACTOR_LEXICON,
        gloss=prepare_glossary([("verlof", "leave"), ("aanvullend", "additional")], None),
    )
    assert verb_pair_guard(claim, "en", unit, DEFAULT_VERB_PAIRS, cfg).startswith("verb guard")


def test_disable_definitions() -> None:
    ev = [
        EvidenceUnit(
            id="a",
            document_id="a",
            language="nl",
            text=(
                "Een werknemer kan onbetaald verlof (hierna: het Verlof) opnemen. Tijdens het "
                "Verlof bouwt de werknemer geen vakantiedagen op."
            ),
        )
    ]
    answer = "Tijdens verlof bouw je geen vakantiedagen op [eu:a]."
    chk = FakeChecker({ev[0].text: (0.999, 0.0)})
    on = VerifyOptions(
        answer_language="nl", admit_paraphrase=True, checker=chk, checker_name="fake"
    )
    assert not verify(answer, ev, on).claims[0].supported
    assert verify(answer, ev, replace(on, disable_definitions=True)).claims[0].supported


def test_parse_glossary_tsv() -> None:
    tsv = (
        "nl\ten\tpos\tclass\tlemma_nl\tlemma_en\tsep\n"
        "sluit\tclose\tverb\tverb\tafsluiten\tclose\taf\n"
        "Controller\tController\tnoun\tparty\tcontroller\tcontroller\t\n"
        "\tempty\tnoun\tparty\t\t\t\n"
    )
    assert parse_glossary_tsv(io.StringIO(tsv)) == [
        GlossaryEntry(
            nl="sluit", en="close", lemma_nl="afsluiten", lemma_en="close", sep="af", class_="verb"
        ),
        GlossaryEntry(
            nl="controller",
            en="controller",
            lemma_nl="controller",
            lemma_en="controller",
            class_="party",
        ),
    ]
    with pytest.raises(GlossaryError):
        parse_glossary_tsv(io.StringIO("a\tb\nx\ty\n"))


# ─── verify_number_forms_test.go ─────────────────────────────────────────────


def _nl_unit(f: str) -> str:
    return (
        "Huur. De maandhuur van de bedrijfsruimte bedraagt "
        + f
        + " per maand. De huur wordt jaarlijks geïndexeerd."
    )


def _nl_claim(f: str) -> str:
    return "De maandhuur van de bedrijfsruimte bedraagt " + f + " per maand."


def _en_unit(f: str) -> str:
    return (
        "Rent. The monthly rent of the business premises is "
        + f
        + " per month. The rent is indexed yearly."
    )


def _en_claim(f: str) -> str:
    return "The monthly rent of the business premises is " + f + " per month."


def _number_form_cases() -> list[tuple[str, str, str, str, str, bool]]:
    cases = []
    for f in ("4.000", "4.000,00", "€ 4.000", "€ 4 000", "€4.000,-"):
        cases.append(("nl claim " + f, "nl", "nl", _nl_unit("€ 4.000"), _nl_claim(f), False))
        cases.append(("nl unit " + f, "nl", "nl", _nl_unit(f), _nl_claim("€ 4.000"), False))
    for f in ("4,000", "4,000.00", "€ 4,000"):
        cases.append(("en claim " + f, "en", "en", _en_unit("€ 4,000"), _en_claim(f), False))
        cases.append(("en unit " + f, "en", "en", _en_unit(f), _en_claim("€ 4,000"), False))
    # Narrow no-break (U+202F) and no-break (U+00A0) space grouping.
    for sp in ("\u202f", "\u00a0", " "):
        grouped = "€" + sp + "1" + sp + "012"
        cases.append(
            ("nl claim grouped", "nl", "nl", _nl_unit("€ 1.012"), _nl_claim(grouped), False)
        )
        cases.append(
            ("nl unit grouped", "nl", "nl", _nl_unit(grouped), _nl_claim("€ 1.012"), False)
        )
        cases.append(
            (
                "nl grouped is not 1.021",
                "nl",
                "nl",
                _nl_unit("€ 1.021"),
                _nl_claim("€ 1" + sp + "012"),
                True,
            )
        )
    cases += [
        ("nl € 0,23 = 0,23 euro", "nl", "nl", _nl_unit("€ 0,23"), _nl_claim("0,23 euro"), False),
        ("nl € 0,23 = 23 cent", "nl", "nl", _nl_unit("€ 0,23"), _nl_claim("23 cent"), False),
        ("en € 0.23 = nl € 0,23", "nl", "en", _nl_unit("€ 0,23"), _en_claim("€ 0.23"), False),
        ("nl € 0,23 is not € 23", "nl", "nl", _nl_unit("€ 0,23"), _nl_claim("€ 23"), True),
        ("nl € 0,23 is not € 0,32", "nl", "nl", _nl_unit("€ 0,23"), _nl_claim("€ 0,32"), True),
        # ADR-0015 amendment 2026-09-27: a number copied verbatim from the unit
        # keeps the unit's locale — admitted (these were refusals).
        (
            "en copies the dutch amount",
            "nl",
            "en",
            _nl_unit("€ 4.000"),
            _en_claim("€ 4.000"),
            False,
        ),
        (
            "en copies the dutch amount before euro",
            "nl",
            "en",
            _nl_unit("€ 4.000"),
            _en_claim("4.000 euro"),
            False,
        ),
        (
            "en copies 4.000,00",
            "nl",
            "en",
            _nl_unit("€ 4.000,00"),
            _en_claim("€ 4.000,00"),
            False,
        ),
        ("en copies €4.000,-", "nl", "en", _nl_unit("€4.000,-"), _en_claim("€4.000,-"), False),
        (
            "nl copies the english amount",
            "en",
            "nl",
            _en_unit("€ 4,000"),
            _nl_claim("€ 4,000"),
            False,
        ),
        # A number the writer formats itself follows the claim's language.
        ("en 4.000 not in the unit", "nl", "en", _nl_unit("€ 4000"), _en_claim("€ 4.000"), True),
        (
            "en 4.000 over 4.000,50",
            "nl",
            "en",
            _nl_unit("€ 4.000,50"),
            _en_claim("€ 4.000"),
            True,
        ),
        ("en 4.000 over 14.000", "nl", "en", _nl_unit("€ 14.000"), _en_claim("€ 4.000"), True),
        # The whole-number bound.
        ("en € 23 over nl € 0,23", "nl", "en", _nl_unit("€ 0,23"), _en_claim("€ 23"), True),
        ("en 12 over en 12.75", "en", "en", _en_unit("€ 12.75"), _en_claim("€ 12"), True),
        ("en 12 over nl 0,12", "nl", "en", _nl_unit("€ 0,12"), _en_claim("€ 12"), True),
        (
            "en format over the dutch unit",
            "nl",
            "en",
            _nl_unit("€ 4.000"),
            _en_claim("€ 4,000"),
            False,
        ),
        (
            "nl format over the english unit",
            "en",
            "nl",
            _en_unit("€ 4,000"),
            _nl_claim("€ 4.000"),
            False,
        ),
        ("4.000 is not 40.000", "nl", "nl", _nl_unit("€ 40.000"), _nl_claim("€ 4.000"), True),
        ("4.000 is not 4,5", "nl", "nl", _nl_unit("€ 4,5"), _nl_claim("€ 4.000"), True),
        ("en 4,000 is not 40,000", "en", "en", _en_unit("€ 40,000"), _en_claim("€ 4,000"), True),
        (
            "4.000 is not the count 4",
            "nl",
            "nl",
            "Parkeren. De huurder krijgt 4 parkeerplaatsen bij de bedrijfsruimte. "
            "De huur wordt jaarlijks geïndexeerd.",
            "De huurder krijgt 4.000 parkeerplaatsen bij de bedrijfsruimte.",
            True,
        ),
        # ADR-0015 amendment: copied verbatim outside money too, "4.000" keeps
        # the Dutch unit's reading (4000) — admitted; this was a refusal.
        (
            "en-declared 4.000 copied from a dutch unit outside money",
            "nl",
            "en",
            "Personeel. Het bedrijf heeft 4.000 medewerkers in dienst. "
            "Zij werken in drie vestigingen.",
            "The company employs 4.000 staff.",
            False,
        ),
        (
            "en-declared 4.000 outside money not in the unit",
            "nl",
            "en",
            "Personeel. Het bedrijf heeft 4000 medewerkers in dienst. "
            "Zij werken in drie vestigingen.",
            "The company employs 4.000 staff.",
            True,
        ),
    ]
    return cases


@pytest.mark.parametrize(
    ("unit_lang", "claim_lang", "unit", "claim", "refuse"),
    [pytest.param(*c[1:], id=c[0]) for c in _number_form_cases()],
)
def test_number_forms_in_running_text(
    unit_lang: str, claim_lang: str, unit: str, claim: str, refuse: bool
) -> None:
    res = verify(
        claim + " [eu:a]",
        [EvidenceUnit(id="a", document_id="d", language=unit_lang, text=unit)],
        VerifyOptions(
            answer_language=claim_lang,
            admit_paraphrase=True,
            checker=AdmitAll(),
            checker_name="admit",
        ),
    )
    assert res.claims[0].supported != refuse, res.claims[0].reason


# ─── verify_union_reason_test.go ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("lead", "guard"),
    [
        ("Volgens artikel 7:13 BW [eu:a2][eu:a1]:", False),
        ("Volgens artikel 7:13 BW [eu:a1][eu:a2]:", False),
        ("Volgens artikel 7:13 BW [eu:a2][eu:a3]:", True),
    ],
    ids=[
        "guard-refused pair first, model-refused pair second",
        "model-refused pair first, guard-refused pair second",
        "every pair guard-refused",
    ],
)
def test_union_reason_names_a_guard_only_when_every_pair_failed_one(lead: str, guard: bool) -> None:
    def article(unit_id: str, number: str) -> EvidenceUnit:
        return EvidenceUnit(
            id=unit_id,
            document_id=unit_id,
            language="nl",
            text=f"Artikel {number} BW regelt wanneer de werkgever een bedrag op het loon "
            "mag inhouden.",
        )

    evidence = [
        article("a1", "7:13"),
        article("a2", "7:14"),
        article("a3", "7:15"),
        EvidenceUnit(
            id="b",
            document_id="b",
            language="nl",
            text="De werkgever mag loon inhouden als de werknemer schade veroorzaakt.",
        ),
    ]
    item = "\n- De werkgever mag loon inhouden als de werknemer schade veroorzaakt [eu:b]"
    res = verify(
        lead + item,
        evidence,
        VerifyOptions(
            answer_language="nl", admit_paraphrase=True, checker=LowChecker(), checker_name="low"
        ),
    )
    reasons = [c.reason for c in res.claims if "schade" in c.claim]
    assert reasons, res.claims
    is_guard = " guard" in reasons[-1] and "(model:" not in reasons[-1]
    assert is_guard == guard, reasons[-1]


# ─── verify_parties_binding_test.go ──────────────────────────────────────────

_ONE_NL = "Fietsregeling. De minimumprijs van een fiets is € 500 en de maximumprijs is € 4.000."
_ONE_EN = "Bike scheme. The minimum price of a bike is € 500 and the maximum price is € 4,000."
_TWO_NL = "Toeslag. De ondergrens van de toeslag is € 100. De bovengrens van de toeslag is € 300."
_TWO_EN = (
    "Allowance. The lower limit of the allowance is € 100. "
    "The upper limit of the allowance is € 300."
)


@pytest.mark.parametrize(
    ("lang", "unit", "claim", "refuse"),
    [
        ("nl", _ONE_NL, "De maximumprijs van een fiets is € 4.000.", False),
        ("nl", _ONE_NL, "De minimumprijs van een fiets is € 500.", False),
        ("nl", _ONE_NL, "De minimumprijs van een fiets is € 4.000.", True),
        ("nl", _ONE_NL, "De maximumprijs van een fiets is € 500.", True),
        ("en", _ONE_EN, "The maximum price of a bike is € 4,000.", False),
        ("en", _ONE_EN, "The minimum price of a bike is € 4,000.", True),
        ("nl", _TWO_NL, "De bovengrens van de toeslag is € 300.", False),
        ("nl", _TWO_NL, "De ondergrens van de toeslag is € 300.", True),
        ("en", _TWO_EN, "The upper limit of the allowance is € 300.", False),
        ("en", _TWO_EN, "The lower limit of the allowance is € 300.", True),
    ],
)
def test_party_swap_binds_the_value_to_its_word(
    lang: str, unit: str, claim: str, refuse: bool
) -> None:
    res = verify(
        claim + " [eu:a]",
        [EvidenceUnit(id="a", document_id="d", language=lang, text=unit)],
        VerifyOptions(
            answer_language=lang, admit_paraphrase=True, checker=AdmitAll(), checker_name="admit"
        ),
    )
    assert len(res.claims) == 1
    assert res.claims[0].supported != refuse, res.claims[0].reason


# ─── verify_premise_invariance_test.go ───────────────────────────────────────

_PREMISE_HIGH = (
    "Veiligheid. De directie beschermt een medewerker die een incident te goeder trouw en "
    "naar behoren meldt."
)
_BEST_ON = re.compile(r"best entailment ([0-9.]+), contradiction ([0-9.]+) on (\S+?)[;)]")


class RecordingChecker:
    """Scores every passage low and records what it was asked."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def check(self, claim: str, passage: str) -> tuple[float, float]:
        self.calls.append(passage)
        if passage == _PREMISE_HIGH:
            return 0.75, 0.01
        return 0.018, 0.02


@pytest.mark.parametrize("eager", [True, False])
@pytest.mark.parametrize(
    "claim",
    [
        # conjunct_presence refuses unit a (a conjunct dropped); off, no guard fires.
        "Management protects an employee who reports an incident in good faith [eu:a][eu:b].",
        # No guard fires in either mode.
        "Management protects an employee who reports an incident in good faith and properly "
        "[eu:a][eu:b].",
    ],
    ids=["a guard verdict differs between the modes", "no guard fires"],
)
def test_options_never_move_premise_selection(claim: str, eager: bool) -> None:
    gloss = [
        ("directie", "management"),
        ("beschermt", "protects"),
        ("medewerker", "employee"),
        ("incident", "incident"),
        ("goeder", "good"),
        ("trouw", "faith"),
        ("meldt", "reports"),
    ]
    evidence = [
        EvidenceUnit(id="a", document_id="d", language="nl", text=_PREMISE_HIGH),
        EvidenceUnit(
            id="b",
            document_id="d",
            language="nl",
            text="Meldingen. Meldingen gaan naar de veiligheidskundige van de directie.",
        ),
    ]
    calls: list[list[str]] = []
    reported: list[str] = []
    supported: list[bool] = []
    for on in (False, True):
        rec = RecordingChecker()
        res = verify(
            claim,
            evidence,
            VerifyOptions(
                answer_language="en",
                glossary=gloss,
                conjunct_presence=on,
                checker=rec,
                checker_name="rec",
                eager_scoring=eager,
            ),
        )
        calls.append(rec.calls)
        supported.append(res.claims[0].supported)
        m = _BEST_ON.search(res.claims[0].reason)
        reported.append("/".join(m.groups()) if m else "")
    assert reported[0] == reported[1]
    if not eager:
        if supported[0] != supported[1]:
            return
        calls = [sorted(c) for c in calls]
    assert calls[0] == calls[1]
