"""VerifyAnswer — cite-or-abstain for an answer the CALLER already generated.

Port of ``golang/answer/verify_answer.go`` (ADR-0016), pinned by
``conformance/cases/verify_answer.json``. ``AnswerFlow`` owns the whole flow:
it retrieves, generates from ONE passage and gates every claim against it. A
caller that runs its own retrieval and a writer that synthesises across many
passages cannot use it. :func:`verify_answer` is the retrieval-free half: it
takes the answer and the evidence the writer saw, and returns the same
:class:`Result` — only verified claims survive, every claim keeps its verdict,
and an answer with nothing verified abstains.

The citation contract: the writer ends each claim with the evidence-unit ids it
rests on — ``De vergoeding is € 25 [eu:hr-12#3].`` — and may tag the part of
the question a claim answers with ``[q:<facet-id>]``. Markers are removed from
the claim before it is checked and never appear in ``Result.answer``.

What admits a claim, in order:

1. GATE — the deterministic ADR-0009 predicate against a cited unit (or, for
   an uncited claim when citations are optional, the first selected unit that
   passes). ``verified_by="gate"``.
2. QUOTE — a verbatim quote of at least ``MIN_QUOTE_TOKENS`` tokens that passes
   the gate against a cited unit, AND the checker entails the whole claim.
   ``verified_by="quote+model:<name>"``.
3. MODEL — the checker entails the claim from a cited unit in another declared
   language, or any cited unit under ``admit_paraphrase``.
4. UNION — a list item joined to a content lead-in citing different units.

Steps 2 to 4 need an injected :class:`~citenexus.contracts.SupportChecker`, and
every admission must also pass the deterministic guards, which the model
cannot override. What removes a claim again — a checker contradiction (veto), a
conflict with a MORE or EQUALLY authoritative unit — can only ADD abstention.

FAILURE IS AN ERROR, NOT A REFUSAL: invalid evidence or a checker error raises.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from citenexus.answer import _gostr as go
from citenexus.answer import verify_union
from citenexus.answer.authority import INSUFFICIENT_AUTHORITY, select_by_authority
from citenexus.answer.conflict import (
    ConflictFinding,
    collapse_near_duplicates,
    detect_conflict,
)
from citenexus.answer.glossary import GlossaryEntry, PreparedGlossary, prepare_glossary
from citenexus.answer.numbers import numbers_in
from citenexus.answer.result import (
    Claim,
    Decision,
    EvidenceSignals,
    Result,
    SourceRef,
)
from citenexus.answer.segment import split_claims
from citenexus.answer.tables import POLARITY_MARKERS
from citenexus.answer.verify import is_stopword, is_supported_v2
from citenexus.answer.verify_definitions import document_definitions
from citenexus.answer.verify_guards import (
    GuardConfig,
    clause_negation_guard,
    guards,
    number_guard,
    quotes,
    truncation_guard,
)
from citenexus.answer.verify_guards_model import NUMBER_WORDS, unit_of
from citenexus.answer.verify_qualifier_pairs import DEFAULT_QUALIFIER_PAIRS, QualifierPair
from citenexus.answer.verify_roles import DEFAULT_ACTOR_LEXICON, ActorLexicon
from citenexus.answer.verify_subtypes import DEFAULT_SUBTYPE_HEADS, SubtypeHead
from citenexus.answer.verify_verbpairs import DEFAULT_VERB_PAIRS, VerbPair
from citenexus.domain.authority import AuthorityPolicy, AuthorityTier, encode_authority_meta
from citenexus.domain.trust import TrustMode
from citenexus.lang.fallback import resolve_answer_language
from citenexus.tokenize import tokenize_v2, unsupported_scripts

if TYPE_CHECKING:
    from citenexus.contracts import SupportChecker

__all__ = [
    "DEFAULT_CONTRADICT_THRESHOLD",
    "DEFAULT_ENTAIL_THRESHOLD",
    "DEFAULT_LEAD_IN_FRAMES",
    "REASON_BELOW_FLOOR",
    "REASON_CONTRADICTED",
    "REASON_NOT_SUPPORTED",
    "REASON_OUTRANKED",
    "REASON_UNCITED",
    "REASON_UNKNOWN_CITATION",
    "REASON_UNRESOLVED_CLAIMS",
    "EvidenceUnit",
    "Facet",
    "InvalidEvidenceError",
    "SupportCheckerError",
    "VerifyOptions",
    "verify_answer",
]


@dataclass(frozen=True)
class EvidenceUnit:
    """One citable passage the writer saw.

    Distinct from the ingested :class:`citenexus.evidence.EvidenceUnit`: this is
    the caller's own evidence, handed to :func:`verify_answer` directly.
    """

    #: What the writer cites in ``[eu:<id>]``. Required, unique.
    id: str
    document_id: str = ""
    text: str = ""
    #: The DECLARED language ("nl", "en", "nl-NL"); never detected here. Empty
    #: means undeclared, which disables model admission for this unit.
    language: str = ""
    #: Caller-supplied metadata read ONLY by ``VerifyOptions.authority``
    #: (ADR-0004) — e.g. ``{"authority_tier": "adopted"}``.
    authority: Mapping[str, str] = field(default_factory=dict)

    @property
    def authority_meta(self) -> str:
        """The metadata as the authority selector reads it (ADR-0004 seam)."""
        return encode_authority_meta(self.authority)


@dataclass(frozen=True)
class Facet:
    """One part of the question an answer must cover."""

    id: str  # what the writer cites in ``[q:<id>]``
    label: str = ""  # what missing_evidence names; the id when empty


@dataclass(frozen=True)
class VerifyOptions:
    """Configures :func:`verify_answer`. The default is deterministic-only,
    unranked, citations optional."""

    #: The language the answer was written in. Model admission requires it.
    answer_language: str = ""
    #: Ranks units and, with a floor, excludes them.
    authority: AuthorityPolicy = field(default_factory=AuthorityPolicy.unranked)
    #: Drop every claim without an ``[eu:...]`` marker instead of searching.
    require_citations: bool = False
    #: The optional injected support checker.
    checker: SupportChecker | None = None
    #: Labels model-admitted claims: ``verified_by = "model:" + checker_name``.
    checker_name: str = ""
    #: A closed, caller-owned alias list keyed by ONE lowercase name word:
    #: ``{"gdpr": ["avg"]}``. Nothing is guessed.
    name_aliases: Mapping[str, Sequence[str]] | None = None
    #: Content-free list lead-ins that are NOT joined to their items. None means
    #: DEFAULT_LEAD_IN_FRAMES; an empty sequence means none.
    lead_in_frames: Sequence[str] | None = None
    #: The role guard's lexicon. None means DEFAULT_ACTOR_LEXICON; a lexicon
    #: REPLACES the default (extend with ``DEFAULT_ACTOR_LEXICON.with_terms``);
    #: an empty ``ActorLexicon()`` switches the guard off.
    actors: ActorLexicon | None = None
    #: Opposite qualifiers compared across languages at a number. None means
    #: DEFAULT_QUALIFIER_PAIRS; a sequence REPLACES it; empty turns it off.
    qualifier_pairs: Sequence[QualifierPair] | None = None
    #: Distinct acts on the same object. None means DEFAULT_VERB_PAIRS.
    verb_pairs: Sequence[VerbPair] | None = None
    #: Turn off the definition guard.
    disable_definitions: bool = False
    #: Head nouns whose subtypes are different facts. None means the default.
    subtype_heads: Sequence[SubtypeHead] | None = None
    #: The caller's term pairs across languages, lowercase, either order.
    glossary: Sequence[tuple[str, str]] | None = None
    #: Glossary rows with lemmas, particle and class (added to ``glossary``).
    glossary_entries: Sequence[GlossaryEntry] | None = None
    #: ``glossary`` + ``glossary_entries`` indexed once (``prepare_glossary``).
    glossary_prepared: PreparedGlossary | None = None
    #: Let the checker admit SAME-language claims the gate rejected.
    admit_paraphrase: bool = False
    #: The parts of the question the answer must cover (``[q:<id>]``).
    facets: Sequence[Facet] = ()
    #: Minimum entailment for a model or quote admission. 0 = default.
    entail_threshold: float = 0.0
    #: Contradiction at which the checker vetoes. 0 = default.
    contradict_threshold: float = 0.0
    #: The cross-language condition reading (verify_conjunct_presence).
    conjunct_presence: bool = False
    #: Testing only: score every unit the model path reaches whatever the
    #: guards decide. The output is the same as the default lazy scoring.
    eager_scoring: bool = False


DEFAULT_ENTAIL_THRESHOLD = 0.9
DEFAULT_CONTRADICT_THRESHOLD = 0.5

REASON_UNCITED = "uncited"
REASON_UNKNOWN_CITATION = "cites unknown evidence unit"
REASON_BELOW_FLOOR = "cited evidence is below the authority floor"
REASON_NOT_SUPPORTED = "not supported by the cited evidence"
REASON_CONTRADICTED = "contradicted by the cited evidence"
REASON_OUTRANKED = "contradicted by a more authoritative source"
REASON_UNRESOLVED_CLAIMS = "cited sources disagree and the conflict is unresolved"

REFUSAL_ANSWER = "I can't answer that from the available evidence."
CONFLICT_REFUSAL_ANSWER = "The available evidence disagrees, so I can't answer that."

_DEFAULT_ANSWER_LANGUAGE = "en"
_UNDECLARED_LANGUAGE = "und"


class InvalidEvidenceError(ValueError):
    """Evidence that cannot be verified against (empty or duplicate ids)."""


class SupportCheckerError(RuntimeError):
    """The injected support checker failed (failure is an error, never a score)."""


#: One ``[eu:...]`` or ``[q:...]`` group; the body is a comma list.
CITATION_MARKER = re.compile(r"[\t\n\f\r ]*\[[\t\n\f\r ]*(eu|q)[\t\n\f\r ]*:([^\]]*)\]")


@dataclass
class CitedClaim:
    text: str
    cited: list[str] = field(default_factory=list)
    facets: list[str] = field(default_factory=list)
    # A list item joined to a content lead-in keeps its parts.
    lead: str = ""
    item: str = ""
    lead_cited: list[str] = field(default_factory=list)
    item_cited: list[str] = field(default_factory=list)


def _append_unique(items: list[str], *new: str) -> list[str]:
    for item in new:
        if item not in items:
            items.append(item)
    return items


def parse_citations(answer: str, frames: Sequence[str] | None = None) -> list[CitedClaim]:
    """Split the answer into claims and attach each marker to the claim it
    follows. Markers (with the whitespace before them) are removed first."""
    if frames is None:
        frames = DEFAULT_LEAD_IN_FRAMES
    marks: list[tuple[int, bool, list[str]]] = []
    clean: list[str] = []
    length = 0
    last = 0
    for m in CITATION_MARKER.finditer(answer):
        chunk = answer[last : m.start()]
        clean.append(chunk)
        length += len(chunk)
        kind = m.group(1)
        ids = []
        for part in m.group(2).split(","):
            cid = go.trim_space(go.trim_space(part).removeprefix(kind + ":"))
            if cid:
                ids.append(cid)
        marks.append((length, kind == "q", ids))
        last = m.end()
    clean.append(answer[last:])
    text = "".join(clean)

    texts = split_claims(text)
    claims = [CitedClaim(text=t) for t in texts]
    starts = []
    cursor = 0
    for t in texts:
        at = text.find(t, cursor)
        if at >= 0:
            cursor = at
        starts.append(cursor)
        cursor += len(t)
    for at, facet, ids in marks:
        owner = 0
        for i, s in enumerate(starts):
            if s <= at:
                owner = i
        if not claims:
            continue
        if facet:
            _append_unique(claims[owner].facets, *ids)
        else:
            _append_unique(claims[owner].cited, *ids)
    return join_list_items(claims, frames)


BARE_LIST_MARKER = re.compile(r"^(?:[-*•·]|[0-9]{1,3}[.)]|[a-z][.)])\Z")
LIST_ITEM_PREFIX = re.compile(r"^(?:[-*•·]|[0-9]{1,3}[.)]|[a-z][.)])[\t\n\f\r ]+")


def join_list_items(claims: list[CitedClaim], frames: Sequence[str]) -> list[CitedClaim]:
    """Make list items standalone claims (see the Go comment)."""
    merged: list[CitedClaim] = []
    i = 0
    while i < len(claims):
        c = claims[i]
        if BARE_LIST_MARKER.match(go.trim_space(c.text)) and i + 1 < len(claims):
            nxt = claims[i + 1]
            claims[i + 1] = CitedClaim(
                text=go.trim_space(c.text) + " " + nxt.text,
                cited=_append_unique(list(c.cited), *nxt.cited),
                facets=_append_unique(list(c.facets), *nxt.facets),
            )
            i += 1
            continue
        merged.append(c)
        i += 1

    out: list[CitedClaim] = []
    lead_in: CitedClaim | None = None
    join_text = ""
    own_claim = -1  # index in out of a verified exclusive/counted lead-in
    for i, c in enumerate(merged):
        loc = LIST_ITEM_PREFIX.match(c.text)
        if loc is None:
            lead_in, own_claim = None, -1
            if (
                go.trim_space(c.text).endswith(":")
                and i + 1 < len(merged)
                and LIST_ITEM_PREFIX.match(merged[i + 1].text)
            ):
                lead_in = c
                bare = go.trim_space(c.text).removesuffix(":")
                stripped, marked = strip_list_qualifiers(bare)
                join_text = stripped
                if not marked and content_free_lead_in(bare, frames):
                    # "Zo zit het:" says nothing: items are verified alone.
                    lead_in = CitedClaim(text="", cited=c.cited, facets=c.facets)
                    join_text = ""
                    continue
                if marked:
                    own_claim = len(out)
                    # A copy: the lead-in keeps its own citations for its items.
                    out.append(CitedClaim(text=c.text, cited=list(c.cited), facets=list(c.facets)))
                continue  # otherwise structural: carried into its items only
            out.append(c)
            continue
        item = go.trim_space(c.text[loc.end() :])
        if lead_in is None:
            out.append(CitedClaim(text=item, cited=c.cited, facets=c.facets))
            continue
        joined = CitedClaim(text=item, cited=list(c.cited), facets=list(c.facets))
        if join_text != "":
            joined.text = join_text + " " + lower_first(item)
            joined.lead, joined.item = join_text, lower_first(item)
            joined.lead_cited, joined.item_cited = lead_in.cited, c.cited
        joined.cited = _append_unique(list(c.cited), *lead_in.cited)
        joined.facets = _append_unique(list(c.facets), *lead_in.facets)
        if own_claim >= 0:
            _append_unique(out[own_claim].cited, *joined.cited)
            _append_unique(out[own_claim].facets, *joined.facets)
        out.append(joined)
    return out


#: A small, generic nl/en table of content-free list lead-ins.
DEFAULT_LEAD_IN_FRAMES: tuple[str, ...] = (
    "zo zit het",
    "zo werkt het",
    "het volgende",
    "als volgt",
    "hieronder",
    "samengevat",
    "kort samengevat",
    "in het kort",
    "een overzicht",
    "here's how",
    "here is how",
    "here's what",
    "here is what",
    "as follows",
    "the following",
    "below",
    "in short",
    "in summary",
    "an overview",
    "volg deze stappen",
    "volg de stappen",
    "volg de volgende stappen",
    "de volgende stappen",
    "deze stappen",
    "de stappen",
    "stappen",
    "hier zijn de stappen",
    "hier zijn de exacte stappen",
    "here are the steps",
    "here are the exact steps",
    "follow these steps",
    "follow the steps",
    "these steps",
    "the steps",
    "steps",
)


def content_free_lead_in(lead: str, frames: Sequence[str]) -> bool:
    """Every token of the lead-in is covered by a frame or is a stopword that
    is not a polarity marker, and there is at least one frame."""
    toks = tokenize_v2(lead)
    if not toks:
        return False
    covered = [False] * len(toks)
    matched = False
    for f in frames:
        ft = tokenize_v2(f)
        if not ft:
            continue
        for i in range(len(toks) - len(ft) + 1):
            if toks[i : i + len(ft)] == ft:
                matched = True
                for k in range(len(ft)):
                    covered[i + k] = True
    if not matched:
        return False
    for i, t in enumerate(toks):
        if covered[i]:
            continue
        if t in POLARITY_MARKERS or not is_stopword(t):
            return False
    return True


#: Make a lead-in exclusive: "mag alleen de volgende …".
LIST_EXCLUSIVES = frozenset(
    {"alleen", "uitsluitend", "enkel", "slechts", "only", "solely", "exclusively"}
)

#: Precede a number that names a provision, not a count: "volgens artikel 7".
LIST_REFERENCE_NOUNS = frozenset(
    {
        "artikel",
        "art",
        "lid",
        "hoofdstuk",
        "paragraaf",
        "bijlage",
        "article",
        "section",
        "chapter",
        "paragraph",
        "annex",
        "clause",
    }
)

#: RE2 ``\S+``.
LIST_LEAD_TOKEN = re.compile(go.NOT_WS + "+")


def strip_list_qualifiers(lead: str) -> tuple[str, bool]:
    """Remove a lead-in's exclusivity words and item count; report whether
    anything was removed."""
    words = LIST_LEAD_TOKEN.findall(lead)
    kept: list[str] = []
    marked = False
    for i, w in enumerate(words):
        bare = go.lower(w.strip(",;()\"'"))
        if bare in LIST_EXCLUSIVES or _is_list_count(bare, words, i):
            marked = True
            continue
        kept.append(w)
    return " ".join(kept), marked


_COUNTS = frozenset({"2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"})


def _is_list_count(bare: str, words: Sequence[str], i: int) -> bool:
    value = NUMBER_WORDS.get(bare)
    if value is None and bare and "0" <= bare[0] <= "9":
        value = bare
    if value is None or value not in _COUNTS:
        return False
    if i > 0 and go.lower(words[i - 1].strip(".,;()")) in LIST_REFERENCE_NOUNS:
        return False
    return not (i + 1 < len(words) and unit_of(go.lower(words[i + 1].strip(".,;()"))) is not None)


def lower_first(item: str) -> str:
    """Lowercase an item's first letter when joined mid-sentence — unless the
    word is an acronym or code ("CAO", "WW-uitkering")."""
    if (
        len(item) < 2
        or not go.is_upper(item[0])
        or go.is_upper(item[1])
        or not go.is_letter(item[1])
    ):
        return item
    return go.lower(item[0]) + item[1:]


_MD_LINK = re.compile(
    r"!?\[([^\[\]]*)\]\([^()\t\n\f\r ]*(?:\([^()\t\n\f\r ]*\)[^()\t\n\f\r ]*)*"
    r'(?:[\t\n\f\r ]+"[^"]*")?\)'
)
_MD_EMPHASIS = re.compile(
    r"(^|[\t\n\f\r (\[{\"'“‘])[*_]([^\t\n\f\r *_](?:[^*_\n]*[^\t\n\f\r *_])?)[*_]"  # noqa: RUF001
    r"(\Z|[\t\n\f\r )\]}\"'”’.,;:!?])"  # noqa: RUF001
)
_MD_STRONG = re.compile(r"\*\*|__|`")


def strip_markup(text: str) -> str:
    """Remove Markdown emphasis, code backticks and link markup from a claim,
    keeping every word it marks up."""
    out = _MD_STRONG.sub("", _MD_LINK.sub(r"\1", text))
    for _ in range(4):  # adjacent spans share a boundary character
        nxt = _MD_EMPHASIS.sub(r"\1\2\3", out)
        if nxt == out:
            break
        out = nxt
    return out


def primary_language(code: str | None) -> str:
    """The lowercase primary subtag: "nl-NL" -> "nl"."""
    code = go.lower(go.trim_space(code or ""))
    for i, ch in enumerate(code):
        if ch in "-_":
            return code[:i]
    return code


def cross_language(claim_language: str | None, unit_language: str | None) -> bool:
    """Both declared, and different primary languages."""
    return (
        bool(claim_language)
        and bool(unit_language)
        and primary_language(claim_language) != primary_language(unit_language)
    )


@dataclass(frozen=True)
class _Scores:
    entailed: float
    contradicted: float


@dataclass
class _Verdict:
    text: str
    facets: list[str]
    supported: bool = False
    sources: list[str] = field(default_factory=list)
    verified_by: str = ""
    reason: str = ""


@dataclass(frozen=True)
class _Conflict:
    supporting: EvidenceUnit
    other: EvidenceUnit
    finding: ConflictFinding


@dataclass(frozen=True)
class _Effect:
    outranked: bool  # False = unresolved
    conflict: _Conflict
    diff_runs: frozenset[str] | None  # value rule only: digit runs that differ


_DIGIT_RUN = re.compile(r"[0-9]+")


def _prepared_for(opts: VerifyOptions) -> PreparedGlossary:
    if opts.glossary_prepared is not None:
        return opts.glossary_prepared
    if not opts.glossary and not opts.glossary_entries:
        return PreparedGlossary()
    return prepare_glossary(opts.glossary, opts.glossary_entries)


def verify_answer(
    answer: str,
    evidence: Sequence[EvidenceUnit],
    options: VerifyOptions | None = None,
) -> Result:
    """Gate a caller-generated answer against the evidence it cites.

    Raises :class:`InvalidEvidenceError` for invalid evidence and
    :class:`SupportCheckerError` when the checker fails; a refusal is only ever
    a finding about the evidence.
    """
    opts = options if options is not None else VerifyOptions()
    by_id: dict[str, int] = {}
    for i, eu in enumerate(evidence):
        if eu.id == "":
            raise InvalidEvidenceError(f"answer: invalid evidence: unit {i} has an empty ID")
        if eu.id in by_id:
            raise InvalidEvidenceError(f"answer: invalid evidence: duplicate ID {go.quote(eu.id)}")
        by_id[eu.id] = i
    entail_at = opts.entail_threshold or DEFAULT_ENTAIL_THRESHOLD
    contradict_at = opts.contradict_threshold or DEFAULT_CONTRADICT_THRESHOLD
    model_label = "model:" + opts.checker_name if opts.checker_name else "model"

    # Observed languages and unreadable scripts, reported, never inputs.
    languages: list[str] = []
    scripts: set[str] = set(unsupported_scripts(answer))
    for eu in evidence:
        if eu.language and eu.language not in languages:
            languages.append(eu.language)
        scripts.update(unsupported_scripts(eu.text))
    unsupported = tuple(sorted(scripts))
    answer_language = resolve_answer_language(
        detection=None,
        answer_language=opts.answer_language or None,
        languages_in_evidence=languages,
        default_answer_language=_DEFAULT_ANSWER_LANGUAGE,
    )
    # "auto" is the detect-it sentinel, not a language.
    declared = opts.answer_language
    if go.lower(go.trim_space(declared)) == "auto":
        declared = ""
    claim_language = primary_language(declared)

    selection = select_by_authority(evidence, policy=opts.authority, mode=TrustMode.strict)
    selected = list(selection.candidates)
    excluded = {eu.id for eu in selection.excluded}

    def tier_of(eu: EvidenceUnit) -> AuthorityTier:
        return opts.authority.tier_of(dict(eu.authority))

    cache: dict[tuple[str, str], _Scores] = {}
    checker = opts.checker

    def check(claim: str, eu: EvidenceUnit) -> _Scores:
        key = (claim, eu.id)
        found = cache.get(key)
        if found is not None:
            return found
        assert checker is not None
        try:
            e, c = checker.check(claim, eu.text)
        except Exception as exc:
            raise SupportCheckerError(
                f"answer: support checker on {go.quote(eu.id)}: {exc}"
            ) from exc
        cache[key] = _Scores(float(e), float(c))
        return cache[key]

    cfg = GuardConfig(
        actors=opts.actors if opts.actors is not None else DEFAULT_ACTOR_LEXICON,
        aliases=opts.name_aliases,
        pairs=opts.qualifier_pairs if opts.qualifier_pairs is not None else DEFAULT_QUALIFIER_PAIRS,
        verbs=opts.verb_pairs if opts.verb_pairs is not None else DEFAULT_VERB_PAIRS,
        gloss=_prepared_for(opts),
        no_definitions=opts.disable_definitions,
        doc_defs=document_definitions(evidence),
        subtypes=opts.subtype_heads if opts.subtype_heads is not None else DEFAULT_SUBTYPE_HEADS,
        conjunct_presence=opts.conjunct_presence,
    )
    frames = opts.lead_in_frames if opts.lead_in_frames is not None else DEFAULT_LEAD_IN_FRAMES
    parsed = parse_citations(answer, frames)
    verdicts = [
        _verify_claim(
            pc,
            evidence=evidence,
            by_id=by_id,
            excluded=excluded,
            selected=selected,
            opts=opts,
            cfg=cfg,
            declared=declared,
            claim_language=claim_language,
            check=check,
            entail_at=entail_at,
            contradict_at=contradict_at,
            model_label=model_label,
        )
        for pc in parsed
    ]

    # Conflicts: every unit supporting a surviving claim against every other
    # selected unit (ADR-0007 — it reports, and authority resolves).
    conflicts: list[_Conflict] = []
    checked: set[tuple[str, str]] = set()
    for v in verdicts:
        for sid in v.sources:
            s = evidence[by_id[sid]]
            for o in selected:
                if o.id == s.id or (s.id, o.id) in checked:
                    continue
                checked.add((s.id, o.id))
                checked.add((o.id, s.id))
                finding = detect_conflict(
                    s.text, o.text, left_language=s.language, right_language=o.language
                )
                if finding is not None:
                    conflicts.append(_Conflict(s, o, finding))
    effects: dict[str, list[_Effect]] = {}
    conflict_notes: list[str] = []
    for c in conflicts:
        ts, to = tier_of(c.supporting), tier_of(c.other)
        note = (
            f"{c.finding.rule}: {c.supporting.document_id} vs {c.other.document_id} "
            f"({c.finding.detail})"
        )
        runs = _differing_digit_runs(c.supporting, c.other) if c.finding.rule == "value" else None
        if to.outranks(ts):
            effects.setdefault(c.supporting.id, []).append(_Effect(True, c, runs))
            note += f" — resolved by authority: {c.other.id} outranks {c.supporting.id}"
        elif ts.outranks(to):
            effects.setdefault(c.other.id, []).append(_Effect(True, c, runs))
            note += f" — resolved by authority: {c.supporting.id} outranks {c.other.id}"
        else:
            e = _Effect(False, c, runs)
            effects.setdefault(c.supporting.id, []).append(e)
            effects.setdefault(c.other.id, []).append(e)
        conflict_notes.append(note)
    conflict_dropped = 0
    unresolved_sides: list[EvidenceUnit] = []
    for v in verdicts:
        if not v.supported:
            continue
        kept: list[str] = []
        reason = ""
        for sid in v.sources:
            applied = False
            for e in effects.get(sid, ()):
                if _spared(v, e.diff_runs):
                    continue
                applied = True
                if e.outranked:
                    reason = REASON_OUTRANKED
                else:
                    if reason == "":
                        reason = REASON_UNRESOLVED_CLAIMS
                    unresolved_sides.extend((e.conflict.supporting, e.conflict.other))
            if not applied:
                kept.append(sid)
        v.sources = kept
        if not kept:
            v.supported, v.verified_by, v.reason = False, "", reason
            conflict_dropped += 1

    # Assemble.
    answered: list[str] = []
    claims: list[Claim] = []
    sources: list[SourceRef] = []
    cited: set[str] = set()
    supporting_texts: list[str] = []
    supporting_languages: list[str | None] = []
    top: EvidenceUnit | None = None
    model_verified = 0
    for v in verdicts:
        claim_sources: list[str] = []
        if v.supported:
            answered.append(v.text)
            claim_sources = v.sources
            if v.verified_by.startswith("model"):
                model_verified += 1
            for sid in v.sources:
                if sid in cited:
                    continue
                cited.add(sid)
                eu = evidence[by_id[sid]]
                supporting_texts.append(eu.text)
                supporting_languages.append(eu.language)
                sources.append(_source_ref_of(eu))
                if top is None or tier_of(eu).outranks(tier_of(top)):
                    top = eu
        claims.append(
            Claim(
                claim=v.text,
                supported=v.supported,
                sources=tuple(claim_sources),
                verified_by=v.verified_by,
                reason=v.reason,
            )
        )
    removed = len(verdicts) - len(answered)

    # Facets no verified claim answers are NAMED, never silently missing.
    covered = {f for v in verdicts if v.supported for f in v.facets}
    missing_facets: list[str] = []
    missing_facet_notes: list[str] = []
    for f in opts.facets:
        if f.id in covered:
            continue
        missing_facets.append(f.id)
        missing_facet_notes.append("no verified answer for: " + (f.label or f.id))

    if not answered:
        answer_text = REFUSAL_ANSWER
        missing: list[str] = ["generated answer failed the faithfulness gate"]
        refused_sources: list[SourceRef] = []
        if not verdicts:
            missing = ["the answer contains no claims"]
        elif conflict_dropped > 0 and unresolved_sides:
            # The evidence is there and it disagrees with itself: cite both sides.
            answer_text = CONFLICT_REFUSAL_ANSWER
            missing = [REASON_UNRESOLVED_CLAIMS]
            seen: set[str] = set()
            for eu in unresolved_sides:
                if eu.id not in seen:
                    seen.add(eu.id)
                    refused_sources.append(_source_ref_of(eu))
        elif selection.floor_applied and not selected:
            missing = [INSUFFICIENT_AUTHORITY]
        return Result(
            answer=answer_text,
            answer_language=answer_language,
            mode=TrustMode.strict,
            evidence=EvidenceSignals(
                decision=Decision.refused,
                unsupported_claims_removed=removed,
                conflicts_detected=len(conflicts),
                languages_in_evidence=tuple(languages),
                unsupported_scripts=unsupported,
                authority_floor_applied=selection.floor_applied,
                missing_facets=tuple(missing_facets),
            ),
            claims=tuple(claims),
            sources=tuple(refused_sources),
            missing_evidence=(*missing, *missing_facet_notes),
            conflicts=tuple(conflict_notes),
        )

    # Anything dropped or uncovered makes the answer PARTIAL — the verified
    # part is kept, and what is missing is named rather than lost.
    missing = []
    if unresolved_sides:
        missing.append(REASON_UNRESOLVED_CLAIMS)
    for v in verdicts:
        if not v.supported:
            missing.append(f"dropped: {v.text} ({v.reason})")
    missing.extend(missing_facet_notes)
    decision = Decision.partial if removed > 0 or missing_facets else Decision.answered
    return Result(
        answer=" ".join(answered),
        answer_language=answer_language,
        mode=TrustMode.strict,
        evidence=EvidenceSignals(
            decision=decision,
            supporting_sources=len(
                collapse_near_duplicates(supporting_texts, languages=supporting_languages)
            ),
            distinct_documents=len({s.document for s in sources}),
            all_claims_verified=removed == 0,
            unsupported_claims_removed=removed,
            conflicts_detected=len(conflicts),
            languages_in_evidence=tuple(languages),
            unsupported_scripts=unsupported,
            authority_tier=tier_of(top).name if top is not None else "",
            authority_floor_applied=selection.floor_applied,
            model_verified_claims=model_verified,
            missing_facets=tuple(missing_facets),
        ),
        claims=tuple(claims),
        sources=tuple(sources),
        missing_evidence=tuple(missing),
        conflicts=tuple(conflict_notes),
    )


def _verify_claim(
    pc: CitedClaim,
    *,
    evidence: Sequence[EvidenceUnit],
    by_id: Mapping[str, int],
    excluded: set[str],
    selected: list[EvidenceUnit],
    opts: VerifyOptions,
    cfg: GuardConfig,
    declared: str,
    claim_language: str,
    check: Callable[[str, EvidenceUnit], _Scores],
    entail_at: float,
    contradict_at: float,
    model_label: str,
) -> _Verdict:
    """The verdict on one claim: the gate, the veto, the model paths and the
    honest reason (F0)."""
    # Reported as written; checked with its markup removed.
    v = _Verdict(text=pc.text, facets=list(pc.facets))
    text = strip_markup(pc.text)

    # The units this claim may be checked against.
    candidates: list[EvidenceUnit] = []
    if pc.cited:
        unknown = below_floor = False
        for cid in pc.cited:
            i = by_id.get(cid)
            if i is None:
                unknown = True
                continue
            if cid in excluded:
                below_floor = True
                continue
            candidates.append(evidence[i])
        if not candidates:
            v.reason = REASON_UNKNOWN_CITATION
            if below_floor:
                v.reason = REASON_BELOW_FLOOR
            elif not unknown:
                v.reason = REASON_NOT_SUPPORTED
    elif opts.require_citations:
        v.reason = REASON_UNCITED
    else:
        candidates = list(selected)

    # 1. The deterministic gate.
    gate_reason = ""
    reason_units: list[EvidenceUnit] = candidates
    guard_of: dict[str, str] = {}
    scored_of: dict[str, _Scores] = {}
    scored_order: list[str] = []
    considered: set[str] = set()
    deferred: dict[str, EvidenceUnit] = {}
    for eu in candidates:
        if not is_supported_v2(text, eu.text):
            continue
        reason = _gate_guards(text, pc, declared, eu, cfg)
        if reason:
            if gate_reason == "":
                gate_reason = reason  # the FIRST cited unit refused, not the last
            guard_of.setdefault(eu.id, reason)
            continue
        v.sources.append(eu.id)
        if not pc.cited:
            break
    if v.sources:
        v.supported, v.verified_by = True, "gate"
    elif gate_reason:
        v.reason = gate_reason

    # Veto: a gate-admitted source the checker says contradicts the claim.
    if v.supported and opts.checker is not None:
        kept = [
            sid
            for sid in v.sources
            if check(text, evidence[by_id[sid]]).contradicted < contradict_at
        ]
        v.sources = kept
        if not kept:
            v.supported, v.verified_by, v.reason = False, "", REASON_CONTRADICTED

    # 2 + 3 + 4. Model-backed admission: cited claims only, checker required,
    # every admission behind the deterministic guards.
    if (
        not v.supported
        and v.reason != REASON_CONTRADICTED
        and opts.checker is not None
        and pc.cited
    ):
        eager = opts.eager_scoring

        def admit(eu: EvidenceUnit) -> bool:
            # The checker scores the unit whatever the guards decide: which
            # premises the model is asked about never depends on a guard.
            if eu.id not in considered:
                considered.add(eu.id)
                scored_order.append(eu.id)

            def score() -> _Scores:
                s = check(text, eu)
                scored_of[eu.id] = s
                return s

            if eager:
                score()
            reason = guards(text, declared, eu, cfg)
            if reason == "" and pc.item != "":
                # A joined item is also a cut span on its own words.
                reason = truncation_guard(strip_markup(pc.item), eu.text)
            if reason:
                guard_of.setdefault(eu.id, reason)
                if not eager:
                    deferred[eu.id] = eu
                return False
            s = scored_of.get(eu.id)
            if not eager or s is None:
                s = score()
            return s.entailed >= entail_at and s.contradicted < contradict_at

        # 2. QUOTE: every quote in the claim passes the gate against the unit.
        qs = quotes(text)
        if qs:
            for eu in candidates:
                anchored = all(
                    is_supported_v2(q, eu.text) and clause_negation_guard(q, eu.text) == ""
                    for q in qs
                )
                if not anchored:
                    continue
                if admit(eu):
                    v.sources.append(eu.id)
            if v.sources:
                v.supported, v.verified_by, v.reason = True, "quote+" + model_label, ""

        # 3. MODEL: cross-language, or any language under admit_paraphrase.
        if not v.supported:
            for eu in candidates:
                pl = primary_language(eu.language)
                cross = claim_language != "" and pl != "" and pl != claim_language
                if not cross and not opts.admit_paraphrase:
                    continue
                if admit(eu):
                    v.sources.append(eu.id)
            if v.sources:
                v.supported, v.verified_by, v.reason = True, model_label, ""

        # 4. UNION: a list item joined to a content lead-in citing another unit.
        union_reason, union_guard, union_all_guarded = "", "", True
        union_pairs = 0
        union_scored: dict[str, _Scores] = {}
        deferred_pairs: list[tuple[EvidenceUnit, EvidenceUnit]] = []
        if not v.supported and pc.lead != "" and pc.item_cited:
            lead, item = strip_markup(pc.lead), strip_markup(pc.item)
            in_item = set(pc.item_cited)
            in_lead = {cid: cid not in in_item for cid in pc.lead_cited}

            def allowed(eu: EvidenceUnit) -> bool:
                pl = primary_language(eu.language)
                return opts.admit_paraphrase or (
                    claim_language != "" and pl != "" and pl != claim_language
                )

            for b in candidates:
                if b.id not in in_item or not allowed(b):
                    continue
                for a in candidates:
                    if not in_lead.get(a.id, False) or not allowed(a):
                        continue
                    union_pairs += 1
                    reason = verify_union.union_refusal(text, lead, item, declared, a, b, cfg)
                    if reason and not opts.eager_scoring:
                        if union_guard == "":
                            union_guard = reason  # the FIRST guard-refused pair
                        deferred_pairs.append((a, b))
                        continue
                    model_reason = ""
                    premise = verify_union.union_premise(a, b)
                    for p in (a, b, premise):
                        s = check(text, p)
                        if p.id == premise.id:
                            union_scored[a.id + "+" + b.id] = s
                        if model_reason:
                            continue
                        if s.contradicted >= contradict_at:
                            model_reason = REASON_CONTRADICTED
                        elif p.id == premise.id and s.entailed < entail_at:
                            model_reason = REASON_NOT_SUPPORTED
                    if reason:
                        if union_guard == "":
                            union_guard = reason
                        continue
                    union_all_guarded = False
                    if model_reason:
                        if union_reason == "":
                            union_reason = model_reason  # the FIRST model-refused pair
                        continue
                    _append_unique(v.sources, a.id, b.id)
            if v.sources:
                v.supported, v.verified_by, v.reason = True, model_label, ""
        if not v.supported and union_reason == REASON_CONTRADICTED:
            v.reason = REASON_CONTRADICTED
        # A joined claim checked as a union is decided by its pairs.
        if not v.supported and union_pairs > 0 and v.reason != REASON_CONTRADICTED:
            guard_of, scored_of, scored_order = {}, {}, []
            reason_units = [EvidenceUnit(id="union")]
            if union_all_guarded:
                guard_of["union"] = union_guard  # every pair refused by a guard
            else:
                # The model's reason reports the best union premise over every
                # pair, guard-refused ones included: score those now.
                for a, b in deferred_pairs:
                    union_scored[a.id + "+" + b.id] = check(text, verify_union.union_premise(a, b))
                for label, sc in union_scored.items():
                    scored_of[label] = sc
                    scored_order.append(label)
                scored_order.sort()

    # F0 — an honest reason. A guard is named only when EVERY cited unit failed
    # a guard; otherwise the MODEL refused, with the best scores over every
    # scored unit. Reporting only: nothing is admitted or refused here.
    if not v.supported and v.reason != REASON_CONTRADICTED and reason_units:
        all_guarded = all(eu.id in guard_of for eu in reason_units)
        if not all_guarded and deferred and reason_units[0].id != "union":
            for sid in scored_order:
                deferred_eu = deferred.get(sid)
                if deferred_eu is None or sid in scored_of:
                    continue
                scored_of[sid] = check(text, deferred_eu)
        if all_guarded:
            v.reason = guard_of[reason_units[0].id]  # the first cited unit's guard
        elif scored_of:
            order = [sid for sid in scored_order if sid in scored_of]
            best = order[0]
            for sid in order[1:]:
                bs, s = scored_of[best], scored_of[sid]
                if s.entailed > bs.entailed or (
                    s.entailed == bs.entailed and s.contradicted < bs.contradicted
                ):
                    best = sid
            bs = scored_of[best]
            note = f"; {best} refused by {guard_of[best]}" if best in guard_of else ""
            v.reason = (
                f"{REASON_NOT_SUPPORTED} (model: best entailment {bs.entailed:.3f}, "
                f"contradiction {bs.contradicted:.3f} on {best}{note})"
            )
        else:
            v.reason = REASON_NOT_SUPPORTED

    if not v.supported and v.reason == "":
        v.reason = REASON_NOT_SUPPORTED
    return v


def _gate_guards(
    text: str, pc: CitedClaim, declared: str, eu: EvidenceUnit, cfg: GuardConfig
) -> str:
    """The guards that run after a gate admission, in the Go order."""
    from citenexus.answer import (
        verify_conditions,
        verify_conjuncts,
        verify_definitions,
        verify_exclusions,
        verify_hedges,
        verify_parties,
        verify_relations,
        verify_roles,
        verify_subtypes,
    )

    checks: tuple[Callable[[], str], ...] = (
        # The tokenizer splits "0,23" into 0 and 23: numbers compare as values.
        lambda: number_guard(text, declared, eu.text, eu.language),
        lambda: clause_negation_guard(text, eu.text),
        lambda: truncation_guard(text, eu.text),
        lambda: truncation_guard(strip_markup(pc.item), eu.text) if pc.item != "" else "",
        lambda: verify_exclusions.exclusion_guard(text, declared, eu, cfg),
        lambda: verify_definitions.definition_guard(text, declared, eu, cfg),
        lambda: verify_subtypes.subtype_guard(text, eu, cfg),
        lambda: verify_conditions.condition_guard(text, declared, eu, cfg),
        lambda: verify_conjuncts.conjunct_token_guard(text, declared, eu, cfg),
        # The gate's alignment may skip a hedge inside a gap.
        lambda: verify_hedges.hedge_guard(text, declared, eu, cfg),
        # The gate matches tokens, not who does what.
        lambda: verify_roles.role_guard(text, declared, eu, cfg.actors),
        lambda: verify_relations.relation_guard(text, declared, eu, cfg.actors),
        # The gate aligns tokens, not which word of a pair a value belongs to.
        lambda: verify_parties.pair_value_guard(text, declared, eu),
    )
    for guard in checks:
        reason = guard()
        if reason:
            return reason
    return ""


def _differing_digit_runs(a: EvidenceUnit, b: EvidenceUnit) -> frozenset[str]:
    """The digit runs of every number one unit carries and the other does not
    (by ADR-0015 key), from both sides."""
    runs: set[str] = set()
    for x, y in ((a, b), (b, a)):
        have = {m.reading.key for m in numbers_in(y.text, y.language)}
        for m in numbers_in(x.text, x.language):
            if m.reading.key in have:
                continue
            runs.update(_DIGIT_RUN.findall(m.raw))
    return frozenset(runs)


def _spared(v: _Verdict, diff_runs: frozenset[str] | None) -> bool:
    """A VALUE conflict provably does not touch this claim: verified on its own
    words (gate, or a gate-checked quote) and carrying none of the differing
    digit runs."""
    if diff_runs is None:
        return False
    if v.verified_by != "gate" and not v.verified_by.startswith("quote+"):
        return False
    return not any(run in diff_runs for run in _DIGIT_RUN.findall(v.text))


def _source_ref_of(eu: EvidenceUnit) -> SourceRef:
    return SourceRef(
        document=eu.document_id,
        passage=eu.text,
        passage_language=eu.language or _UNDECLARED_LANGUAGE,
    )
