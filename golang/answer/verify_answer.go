// VerifyAnswer — cite-or-abstain for an answer the CALLER already generated.
//
// AskWith owns the whole flow: it retrieves, generates from ONE passage and gates
// every claim against that passage. A caller that runs its own retrieval and a
// writer that synthesises across many passages cannot use it. VerifyAnswer is
// the retrieval-free half: it takes the answer and the evidence the writer saw,
// and returns the same Result AskWith would — only verified claims survive,
// every claim keeps its verdict, and an answer with nothing verified abstains.
//
// Go-first: the Python reference has no equivalent yet.
//
// # The citation contract
//
// The writer ends each claim with the evidence-unit ids it rests on:
//
//	De vergoeding is € 25 inclusief btw [eu:hr-12#3]. Aanvragen gaan via HR [eu:hr-12#4, eu:hr-09#1].
//
// A marker belongs to the claim it follows. `[eu:a][eu:b]`, `[eu:a, b]` and
// `[eu:a, eu:b]` are all accepted. Markers are removed from the claim text
// before it is checked, and never appear in Result.Answer: the citations live
// in Result.Claims[i].Sources.
//
// A writer may also tag the part of the question a claim answers with
// `[q:<facet-id>]` (see VerifyOptions.Facets): a declared facet no verified
// claim answers is NAMED in the Result instead of silently missing.
//
// # What admits a claim, in order
//
//  1. GATE — the deterministic predicate (gate.IsSupportedV2) against a cited
//     unit — or, for an uncited claim when RequireCitations is false, against
//     any selected unit, most authoritative first. VerifiedBy "gate".
//  2. QUOTE — the claim carries a verbatim quote ("…", “…”, „…”, «…», at least
//     MinQuoteTokens tokens) that passes the gate against a cited unit, AND the
//     checker entails the whole claim from that unit. The quote anchors the
//     content deterministically; the model only vouches for the words around
//     it (a translation, a framing). VerifiedBy "quote+model:<name>".
//  3. MODEL — the checker entails the claim from a cited unit whose declared
//     language differs from the answer language, or from any cited unit when
//     AdmitParaphrase is set. VerifiedBy "model:<name>".
//
// Steps 2 and 3 need an injected SupportChecker, and every admission they make
// must also pass the deterministic guards (numbers, negation, names —
// verify_guards.go), which the model cannot override. Model-admitted claims are
// counted in Evidence.ModelVerifiedClaims.
//
// And what removes one again — every rule below can only ADD abstention:
//
//   - a checker contradiction on the unit that supported the claim (veto);
//   - a conflict with a MORE authoritative unit (resolved by authority);
//   - a conflict with an EQUALLY authoritative unit (unresolved — both sides are
//     reported, the claim is dropped; if nothing survives, the Result is the
//     conflict abstention citing both sides, exactly as AskWith's).
package answer

import (
	"context"
	"errors"
	"fmt"
	"regexp"
	"strings"

	"github.com/muthuishere/citenexus/golang/authority"
	"github.com/muthuishere/citenexus/golang/contracts"
	"github.com/muthuishere/citenexus/golang/gate"
	"github.com/muthuishere/citenexus/golang/lang"
	"github.com/muthuishere/citenexus/golang/result"
	"github.com/muthuishere/citenexus/golang/tokenize"
)

// EvidenceUnit is one citable passage the writer saw.
type EvidenceUnit struct {
	// ID is what the writer cites in `[eu:<id>]`. Required, unique.
	ID         string
	DocumentID string
	Text       string
	// Language is the DECLARED language ("nl", "en", "nl-NL"). Never detected
	// here. Empty means undeclared, which disables model admission for this unit
	// (a cross-language check needs both languages known).
	Language string
	// Authority is caller-supplied metadata read ONLY by VerifyOptions.Authority
	// (ADR-0004) — e.g. {"authority_tier": "adopted"}.
	Authority map[string]string
}

// VerifyOptions configures VerifyAnswer. The zero value is deterministic-only,
// unranked, citations optional.
type VerifyOptions struct {
	// AnswerLanguage is the language the answer was written in — rung 1 of
	// lang.ResolveAnswerLanguage. Model admission requires it to be declared.
	AnswerLanguage string
	// Authority ranks units and, with a floor, excludes them. The zero Policy
	// ranks everything equal.
	Authority authority.Policy
	// RequireCitations drops every claim that carries no `[eu:...]` marker
	// instead of searching the evidence for it.
	RequireCitations bool
	// Checker is the optional injected support checker (see contracts).
	Checker contracts.SupportChecker
	// CheckerName labels model-admitted claims: VerifiedBy = "model:"+CheckerName.
	CheckerName string
	// AdmitParaphrase lets the checker admit SAME-language claims the gate
	// rejected (a paraphrase), still behind the deterministic guards. Off by
	// default: it trades the gate's guarantee for coverage, and the caller should
	// choose that knowingly. Claims it admits are labelled like any model
	// admission.
	AdmitParaphrase bool
	// Facets are the parts of the question the answer must cover, referenced by
	// the writer as `[q:<ID>]`. A facet with no verified claim is reported in
	// Evidence.MissingFacets and MissingEvidence, and makes the decision
	// "partial" (or "refused" when nothing at all was verified).
	Facets []Facet
	// EntailThreshold is the minimum entailment for a model or quote admission.
	// Zero means DefaultEntailThreshold.
	EntailThreshold float64
	// ContradictThreshold is the contradiction score at which the checker vetoes,
	// and above which it may not admit. Zero means DefaultContradictThreshold.
	ContradictThreshold float64
}

// Facet is one part of the question an answer must cover.
type Facet struct {
	ID    string // what the writer cites in `[q:<ID>]`
	Label string // what MissingEvidence names; ID when empty
}

// Default checker thresholds. Deliberately conservative: a wrongly admitted
// claim costs more than a wrongly dropped one.
const (
	DefaultEntailThreshold     = 0.9
	DefaultContradictThreshold = 0.5
)

// Claim.Reason values for a dropped claim.
const (
	ReasonUncited          = "uncited"
	ReasonUnknownCitation  = "cites unknown evidence unit"
	ReasonBelowFloor       = "cited evidence is below the authority floor"
	ReasonNotSupported     = "not supported by the cited evidence"
	ReasonContradicted     = "contradicted by the cited evidence"
	ReasonOutranked        = "contradicted by a more authoritative source"
	ReasonUnresolvedClaims = "cited sources disagree and the conflict is unresolved"
)

// ErrInvalidEvidence is wrapped by every evidence-validation error.
var ErrInvalidEvidence = errors.New("answer: invalid evidence")

// citationMarker matches one `[eu:...]` or `[q:...]` group; the body is a comma
// list.
var citationMarker = regexp.MustCompile(`\s*\[\s*(eu|q)\s*:([^\]]*)\]`)

type citedClaim struct {
	text   string
	cited  []string
	facets []string
}

// parseCitations splits the answer into claims and attaches each marker to the
// claim it follows. Markers (with the whitespace before them) are removed first,
// so an id containing "." cannot split a sentence.
func parseCitations(answer string) []citedClaim {
	type mark struct {
		at    int // byte offset in the cleaned text
		facet bool
		ids   []string
	}
	var clean strings.Builder
	marks := []mark{}
	last := 0
	for _, loc := range citationMarker.FindAllStringSubmatchIndex(answer, -1) {
		clean.WriteString(answer[last:loc[0]])
		kind := answer[loc[2]:loc[3]]
		ids := []string{}
		for _, part := range strings.Split(answer[loc[4]:loc[5]], ",") {
			id := strings.TrimSpace(part)
			id = strings.TrimSpace(strings.TrimPrefix(id, kind+":"))
			if id != "" {
				ids = append(ids, id)
			}
		}
		marks = append(marks, mark{at: clean.Len(), facet: kind == "q", ids: ids})
		last = loc[1]
	}
	clean.WriteString(answer[last:])
	text := clean.String()

	texts := SplitClaims(text)
	claims := make([]citedClaim, len(texts))
	starts := make([]int, len(texts))
	cursor := 0
	for i, t := range texts {
		claims[i].text = t
		if at := strings.Index(text[cursor:], t); at >= 0 {
			cursor += at
		}
		starts[i] = cursor
		cursor += len(t)
	}
	for _, m := range marks {
		owner := 0
		for i, s := range starts {
			if s <= m.at {
				owner = i
			}
		}
		switch {
		case len(claims) == 0:
		case m.facet:
			claims[owner].facets = appendUnique(claims[owner].facets, m.ids...)
		default:
			claims[owner].cited = appendUnique(claims[owner].cited, m.ids...)
		}
	}
	return claims
}

func appendUnique(list []string, items ...string) []string {
	for _, item := range items {
		dup := false
		for _, have := range list {
			if have == item {
				dup = true
				break
			}
		}
		if !dup {
			list = append(list, item)
		}
	}
	return list
}

// primaryLanguage is the lowercase primary subtag: "nl-NL" -> "nl".
func primaryLanguage(code string) string {
	code = strings.ToLower(strings.TrimSpace(code))
	if i := strings.IndexAny(code, "-_"); i >= 0 {
		code = code[:i]
	}
	return code
}

type verdict struct {
	facets     []string
	text       string
	supported  bool
	sources    []string // unit ids that support it
	verifiedBy string
	reason     string
}

// VerifyAnswer gates a caller-generated answer against the evidence it cites.
//
// FAILURE IS AN ERROR, NOT A REFUSAL — as in AskWith. Invalid evidence or a
// checker error returns a zero Result and an error; a refusal is only ever a
// finding about the evidence.
func VerifyAnswer(ctx context.Context, answer string, evidence []EvidenceUnit, opts VerifyOptions) (result.Result, error) {
	byID := make(map[string]int, len(evidence))
	for i, eu := range evidence {
		if eu.ID == "" {
			return result.Result{}, fmt.Errorf("%w: unit %d has an empty ID", ErrInvalidEvidence, i)
		}
		if _, dup := byID[eu.ID]; dup {
			return result.Result{}, fmt.Errorf("%w: duplicate ID %q", ErrInvalidEvidence, eu.ID)
		}
		byID[eu.ID] = i
	}
	entailAt := opts.EntailThreshold
	if entailAt == 0 {
		entailAt = DefaultEntailThreshold
	}
	contradictAt := opts.ContradictThreshold
	if contradictAt == 0 {
		contradictAt = DefaultContradictThreshold
	}
	modelLabel := "model"
	if opts.CheckerName != "" {
		modelLabel = "model:" + opts.CheckerName
	}

	// Observed languages and unreadable scripts, reported, never inputs.
	languages := []string{}
	seenLanguage := map[string]struct{}{}
	scriptLists := [][]string{tokenize.UnsupportedScripts(answer)}
	for _, eu := range evidence {
		if eu.Language != "" {
			if _, ok := seenLanguage[eu.Language]; !ok {
				seenLanguage[eu.Language] = struct{}{}
				languages = append(languages, eu.Language)
			}
		}
		scriptLists = append(scriptLists, tokenize.UnsupportedScripts(eu.Text))
	}
	unsupported := sortedUnique(scriptLists...)
	answerLanguage := lang.ResolveAnswerLanguage(nil, opts.AnswerLanguage, "", languages, defaultAnswerLanguage)
	claimLanguage := primaryLanguage(opts.AnswerLanguage)

	// Authority: after grounding in spirit — it only ever narrows what may be cited.
	selection := authority.Select(evidence, func(eu EvidenceUnit) map[string]string { return eu.Authority }, opts.Authority)
	selected := selection.Candidates
	excluded := make(map[string]struct{}, len(selection.Excluded))
	for _, eu := range selection.Excluded {
		excluded[eu.ID] = struct{}{}
	}
	tierOf := func(eu EvidenceUnit) authority.Tier { return opts.Authority.TierOf(eu.Authority) }

	// Checker scores, cached per (claim, unit): the veto and the admission ask
	// the same question.
	type key struct{ claim, id string }
	type scores struct{ entailed, contradicted float64 }
	cache := map[key]scores{}
	check := func(claim string, eu EvidenceUnit) (scores, error) {
		k := key{claim, eu.ID}
		if s, ok := cache[k]; ok {
			return s, nil
		}
		e, c, err := opts.Checker.Check(ctx, claim, eu.Text)
		if err != nil {
			return scores{}, fmt.Errorf("answer: support checker on %q: %w", eu.ID, err)
		}
		cache[k] = scores{e, c}
		return cache[k], nil
	}

	parsed := parseCitations(answer)
	verdicts := make([]verdict, 0, len(parsed))
	for _, pc := range parsed {
		v := verdict{text: pc.text, facets: pc.facets}

		// The units this claim may be checked against.
		candidates := []EvidenceUnit{}
		switch {
		case len(pc.cited) > 0:
			unknown, belowFloor := false, false
			for _, id := range pc.cited {
				i, ok := byID[id]
				if !ok {
					unknown = true
					continue
				}
				if _, out := excluded[id]; out {
					belowFloor = true
					continue
				}
				candidates = append(candidates, evidence[i])
			}
			if len(candidates) == 0 {
				v.reason = ReasonUnknownCitation
				if belowFloor {
					v.reason = ReasonBelowFloor
				} else if !unknown {
					v.reason = ReasonNotSupported
				}
			}
		case opts.RequireCitations:
			v.reason = ReasonUncited
		default:
			candidates = selected
		}

		// 1. The deterministic gate. Cited: every cited unit that passes supports
		// it. Uncited: the first (most authoritative) unit that passes.
		for _, eu := range candidates {
			if gate.IsSupportedV2(pc.text, eu.Text) {
				v.sources = append(v.sources, eu.ID)
				if len(pc.cited) == 0 {
					break
				}
			}
		}
		if len(v.sources) > 0 {
			v.supported, v.verifiedBy = true, "gate"
		}

		// Veto: a gate-admitted source the checker says contradicts the claim.
		if v.supported && opts.Checker != nil {
			kept := v.sources[:0:0]
			for _, id := range v.sources {
				s, err := check(pc.text, evidence[byID[id]])
				if err != nil {
					return result.Result{}, err
				}
				if s.contradicted < contradictAt {
					kept = append(kept, id)
				}
			}
			v.sources = kept
			if len(kept) == 0 {
				v.supported, v.verifiedBy, v.reason = false, "", ReasonContradicted
			}
		}

		// 2 + 3. Model-backed admission: cited claims only, checker required,
		// every admission behind the deterministic guards.
		if !v.supported && v.reason != ReasonContradicted && opts.Checker != nil && len(pc.cited) > 0 {
			guardReason := ""
			admit := func(eu EvidenceUnit) (bool, error) {
				if reason := guards(pc.text, eu.Text); reason != "" {
					guardReason = reason
					return false, nil
				}
				s, err := check(pc.text, eu)
				if err != nil {
					return false, err
				}
				return s.entailed >= entailAt && s.contradicted < contradictAt, nil
			}

			// 2. QUOTE: every quote in the claim passes the gate against the unit.
			if qs := quotes(pc.text); len(qs) > 0 {
				for _, eu := range candidates {
					anchored := true
					for _, q := range qs {
						if !gate.IsSupportedV2(q, eu.Text) {
							anchored = false
							break
						}
					}
					if !anchored {
						continue
					}
					ok, err := admit(eu)
					if err != nil {
						return result.Result{}, err
					}
					if ok {
						v.sources = append(v.sources, eu.ID)
					}
				}
				if len(v.sources) > 0 {
					v.supported, v.verifiedBy, v.reason = true, "quote+"+modelLabel, ""
				}
			}

			// 3. MODEL: cross-language, or any language under AdmitParaphrase.
			if !v.supported {
				for _, eu := range candidates {
					pl := primaryLanguage(eu.Language)
					crossLanguage := claimLanguage != "" && pl != "" && pl != claimLanguage
					if !crossLanguage && !opts.AdmitParaphrase {
						continue
					}
					ok, err := admit(eu)
					if err != nil {
						return result.Result{}, err
					}
					if ok {
						v.sources = append(v.sources, eu.ID)
					}
				}
				if len(v.sources) > 0 {
					v.supported, v.verifiedBy, v.reason = true, modelLabel, ""
				}
			}
			if !v.supported && guardReason != "" {
				v.reason = guardReason
			}
		}

		if !v.supported && v.reason == "" {
			v.reason = ReasonNotSupported
		}
		verdicts = append(verdicts, v)
	}

	// Conflicts: every unit supporting a surviving claim against every other
	// selected unit (ADR-0007 detector — it reports, and authority resolves).
	type conflict struct {
		supporting, other EvidenceUnit
		finding           ConflictFinding
	}
	conflicts := []conflict{}
	checked := map[[2]string]bool{}
	for _, v := range verdicts {
		for _, id := range v.sources {
			s := evidence[byID[id]]
			for _, o := range selected {
				if o.ID == s.ID || checked[[2]string{s.ID, o.ID}] {
					continue
				}
				checked[[2]string{s.ID, o.ID}], checked[[2]string{o.ID, s.ID}] = true, true
				if f, ok := DetectConflict(s.Text, o.Text); ok {
					conflicts = append(conflicts, conflict{s, o, f})
				}
			}
		}
	}
	// A unit loses when something at least as authoritative contradicts it:
	// strictly more => resolved against it; equal => unresolved, both lose.
	outranked := map[string]bool{}
	unresolved := map[string]bool{}
	var conflictNotes []string
	unresolvedSides := []EvidenceUnit{}
	for _, c := range conflicts {
		ts, to := tierOf(c.supporting), tierOf(c.other)
		note := fmt.Sprintf("%s: %s vs %s (%s)", c.finding.Rule, c.supporting.DocumentID, c.other.DocumentID, c.finding.Detail)
		switch {
		case to.Outranks(ts):
			outranked[c.supporting.ID] = true
			note += fmt.Sprintf(" — resolved by authority: %s outranks %s", c.other.ID, c.supporting.ID)
		case ts.Outranks(to):
			outranked[c.other.ID] = true
			note += fmt.Sprintf(" — resolved by authority: %s outranks %s", c.supporting.ID, c.other.ID)
		default:
			unresolved[c.supporting.ID], unresolved[c.other.ID] = true, true
			unresolvedSides = append(unresolvedSides, c.supporting, c.other)
		}
		conflictNotes = append(conflictNotes, note)
	}
	conflictDropped := 0
	for i := range verdicts {
		v := &verdicts[i]
		if !v.supported {
			continue
		}
		kept := v.sources[:0:0]
		reason := ""
		for _, id := range v.sources {
			switch {
			case outranked[id]:
				reason = ReasonOutranked
			case unresolved[id]:
				if reason == "" {
					reason = ReasonUnresolvedClaims
				}
			default:
				kept = append(kept, id)
			}
		}
		v.sources = kept
		if len(kept) == 0 {
			v.supported, v.verifiedBy, v.reason = false, "", reason
			conflictDropped++
		}
	}

	// Assemble.
	answered := []string{}
	claims := make([]result.Claim, 0, len(verdicts))
	sources := []result.SourceRef{}
	cited := map[string]struct{}{}
	supportingTexts := []string{}
	var top *EvidenceUnit
	modelVerified := 0
	for _, v := range verdicts {
		claimSources := []string{}
		if v.supported {
			answered = append(answered, v.text)
			claimSources = v.sources
			if strings.HasPrefix(v.verifiedBy, "model") {
				modelVerified++
			}
			for _, id := range v.sources {
				if _, ok := cited[id]; ok {
					continue
				}
				cited[id] = struct{}{}
				eu := evidence[byID[id]]
				supportingTexts = append(supportingTexts, eu.Text)
				sources = append(sources, sourceRefOf(eu))
				if top == nil || tierOf(eu).Outranks(tierOf(*top)) {
					euCopy := eu
					top = &euCopy
				}
			}
		}
		claims = append(claims, result.Claim{
			Claim: v.text, Supported: v.supported, Sources: claimSources,
			VerifiedBy: v.verifiedBy, Reason: v.reason,
		})
	}
	if conflictNotes == nil {
		conflictNotes = []string{}
	}
	removed := len(verdicts) - len(answered)

	// Facets no verified claim answers are NAMED, never silently missing.
	covered := map[string]bool{}
	for _, v := range verdicts {
		if v.supported {
			for _, f := range v.facets {
				covered[f] = true
			}
		}
	}
	var missingFacets, missingFacetNotes []string
	for _, f := range opts.Facets {
		if covered[f.ID] {
			continue
		}
		label := f.Label
		if label == "" {
			label = f.ID
		}
		missingFacets = append(missingFacets, f.ID)
		missingFacetNotes = append(missingFacetNotes, "no verified answer for: "+label)
	}

	if len(answered) == 0 {
		refused := refusal(answerLanguage, "generated answer failed the faithfulness gate", unsupported, nil)
		switch {
		case len(verdicts) == 0:
			refused.MissingEvidence = []string{"the answer contains no claims"}
		case conflictDropped > 0 && len(unresolvedSides) > 0:
			// The evidence is there and it disagrees with itself: cite both sides.
			refused.Answer = result.ConflictRefusalAnswer
			refused.MissingEvidence = []string{ReasonUnresolvedClaims}
			seen := map[string]struct{}{}
			for _, eu := range unresolvedSides {
				if _, ok := seen[eu.ID]; !ok {
					seen[eu.ID] = struct{}{}
					refused.Sources = append(refused.Sources, sourceRefOf(eu))
				}
			}
		case selection.FloorApplied() && len(selected) == 0:
			refused.MissingEvidence = []string{authority.InsufficientAuthority}
		}
		refused.Claims = claims
		refused.Conflicts = conflictNotes
		refused.Evidence.ConflictsDetected = len(conflicts)
		refused.Evidence.UnsupportedClaimsRemoved = removed
		refused.Evidence.LanguagesInEvidence = languages
		refused.Evidence.AuthorityFloorApplied = selection.FloorApplied()
		refused.Evidence.MissingFacets = missingFacets
		refused.MissingEvidence = append(refused.MissingEvidence, missingFacetNotes...)
		return refused, nil
	}

	distinct := map[string]struct{}{}
	for _, s := range sources {
		distinct[s.Document] = struct{}{}
	}
	// Anything dropped or uncovered makes the answer PARTIAL — the verified part
	// is kept, and what is missing is named rather than lost. (AskWith's strict
	// flow never emits partial; this verb does, because a caller-generated
	// multi-claim answer is exactly where incompleteness needs a name.)
	missing := []string{}
	if len(unresolvedSides) > 0 {
		missing = append(missing, ReasonUnresolvedClaims)
	}
	for _, v := range verdicts {
		if !v.supported {
			missing = append(missing, fmt.Sprintf("dropped: %s (%s)", v.text, v.reason))
		}
	}
	missing = append(missing, missingFacetNotes...)
	decision := result.DecisionAnswered
	if removed > 0 || len(missingFacets) > 0 {
		decision = result.DecisionPartial
	}
	tierName := ""
	if top != nil {
		tierName = tierOf(*top).Name
	}
	return result.Result{
		Answer:         strings.Join(answered, " "),
		AnswerLanguage: answerLanguage,
		Mode:           result.TrustModeStrict,
		Evidence: result.EvidenceSignals{
			Decision:                 decision,
			SupportingSources:        len(CollapseNearDuplicates(supportingTexts)),
			DistinctDocuments:        len(distinct),
			AllClaimsVerified:        removed == 0,
			UnsupportedClaimsRemoved: removed,
			ConflictsDetected:        len(conflicts),
			LanguagesInEvidence:      languages,
			UnsupportedScripts:       unsupported,
			AuthorityTier:            tierName,
			AuthorityFloorApplied:    selection.FloorApplied(),
			ModelVerifiedClaims:      modelVerified,
			MissingFacets:            missingFacets,
		},
		Claims:          claims,
		Sources:         sources,
		MissingEvidence: missing,
		Conflicts:       conflictNotes,
		Provenance:      []result.ProvenanceEntry{},
	}, nil
}

func sourceRefOf(eu EvidenceUnit) result.SourceRef {
	language := eu.Language
	if language == "" {
		language = undeclaredLanguage
	}
	return result.SourceRef{Document: eu.DocumentID, Passage: eu.Text, PassageLanguage: language}
}
