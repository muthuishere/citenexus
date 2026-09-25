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
//  4. UNION — a list item joined to a content lead-in, where the lead-in and
//     the item cite different units: the checker entails the joined claim
//     from both units together, behind provenance-split guards and a scope
//     rule (verify_union.go). VerifiedBy "model:<name>", citing both units.
//
// Steps 2 to 4 need an injected SupportChecker, and every admission they make
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
	"sort"
	"strings"
	"unicode"

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
	// NameAliases lets the name guard accept a claim name through a caller-owned,
	// closed alias list keyed by ONE lowercase name word, as the guard extracts
	// them: "gdpr" -> ["avg"], "civil" -> ["burgerlijk"]. A name is present when
	// all tokens of any one alias are in the passage. Nothing is guessed: without
	// an entry a name must appear as written.
	NameAliases map[string][]string
	// LeadInFrames are the content-free list lead-ins ("Zo zit het:", "Here's
	// how:") that are NOT joined to their items: an item under such a lead-in is
	// verified alone and the lead-in is exempt. nil means DefaultLeadInFrames; a
	// non-nil empty slice means none (every ":" lead-in is joined). A lead-in is
	// content-free only when every token is inside a frame or is a stopword — any
	// other word, number, polarity marker, exclusivity word or count means JOIN.
	LeadInFrames []string
	// Actors is the role guard's lexicon (verify_roles.go): actor ids with
	// their terms in any language, the reader's pronouns, and the slot words.
	// nil means DefaultActorLexicon. A non-nil lexicon REPLACES the default —
	// extend it with DefaultActorLexicon.With("employer", "<organisation>");
	// an empty ActorLexicon switches the guard off.
	Actors *ActorLexicon
	// QualifierPairs are the opposite qualifiers compared across languages at
	// a number (verify_qualifier_pairs.go). nil means DefaultQualifierPairs; a
	// non-nil slice REPLACES it — extend with
	// append(DefaultQualifierPairs, QualifierPair{...}); empty turns it off.
	QualifierPairs []QualifierPair
	// VerbPairs are distinct acts on the same object — apply for vs take
	// (verify_verbpairs.go). nil means DefaultVerbPairs; a non-nil slice
	// REPLACES it (append to DefaultVerbPairs to extend); empty turns it off.
	VerbPairs []VerbPair
	// DisableDefinitions turns off the definition guard (verify_definitions.go),
	// which by default refuses a claim using the generic noun for a subtype the
	// unit defines explicitly ("onbetaald verlof (hierna: het Verlof)").
	DisableDefinitions bool
	// SubtypeHeads are the head nouns whose subtypes are different facts
	// (verlof / leave, …): a claim using the bare head over a unit that
	// only has compounds or qualified forms of it is refused
	// (verify_subtypes.go). nil means DefaultSubtypeHeads; a non-nil slice
	// REPLACES it; empty turns it off.
	SubtypeHeads []SubtypeHead
	// Glossary is the caller's term pairs across languages ({"toestemming",
	// "permission"}), lowercase, either order. It is read ONLY by the
	// condition guard, to tell whether a claim in another language carries a
	// unit's condition word. nil: that guard gives no verdict across languages.
	Glossary [][2]string
	// GlossaryEntries are glossary rows with lemmas, a separable particle and
	// a class (glossary.go; ParseGlossaryTSV reads them from a file). They add
	// to Glossary: inflections match through their lemma, a split separable
	// verb only with its particle, and the reader is compared with a third
	// party only when a party's class says it is one.
	GlossaryEntries []GlossaryEntry
	// GlossaryPrepared is Glossary + GlossaryEntries indexed ONCE by
	// PrepareGlossary; safe to share across calls and goroutines. When set it
	// is used instead of the two slices. Without it the slices are prepared
	// once per distinct slice (backing array + length) and cached, so editing a
	// slice IN PLACE after its first use is not seen: pass a new slice, or
	// prefer PrepareGlossary.
	GlossaryPrepared *PreparedGlossary
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
	// A list item joined to a content lead-in keeps its parts: lead is the
	// lead-in as joined (qualifiers stripped), item the item alone, and
	// leadCited / itemCited the units each part cited itself. Empty otherwise.
	lead, item           string
	leadCited, itemCited []string
}

// parseCitations splits the answer into claims and attaches each marker to the
// claim it follows. Markers (with the whitespace before them) are removed first,
// so an id containing "." cannot split a sentence.
func parseCitations(answer string) []citedClaim {
	return parseCitationsWith(answer, DefaultLeadInFrames)
}

func parseCitationsWith(answer string, frames []string) []citedClaim {
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
	return joinListItems(claims, frames)
}

var (
	bareListMarker = regexp.MustCompile(`^([-*•·]|[0-9]{1,3}[.)]|[a-z][.)])$`)
	listItemPrefix = regexp.MustCompile(`^([-*•·]|[0-9]{1,3}[.)]|[a-z][.)])\s+`)
)

// joinListItems makes list items standalone claims.
//
// SplitClaims ends a claim at every line break, so a list arrives as a lead-in
// ("De werknemer heeft recht op:") and items ("- vakantiegeld") — fragments
// that pass or fail the gate on their own words and mean nothing alone (rag_go
// measured 596 of 5,836 pieces fragment-shaped). Here:
//
//   - a bare marker piece ("1.", "-") is merged into the item it introduces;
//   - an item following a lead-in that ends in ":" is verified, and reported,
//     as the joined sentence "De werknemer heeft recht op vakantiegeld";
//   - such a lead-in is not a claim of its own; its citations and facets pass
//     to each item;
//   - an item with no lead-in is verified with its marker removed.
//
// A lead-in that is EXCLUSIVE or COUNTED ("mag alleen de volgende gegevens
// vragen:", "op drie manieren melden:") is the exception: joined to one item it
// says something the source does not ("mag alleen … vragen: naam" when the
// source lists six; "drie manieren: via HR"). So such a lead-in IS verified as a
// claim of its own, carrying its items' citations, which is where a wrong count
// is refused, and each item is joined to the lead-in with the exclusivity word
// and the count removed ("De werkgever mag de volgende gegevens vragen naam").
// The answer may list a subset; each item must still be in the source.
func joinListItems(claims []citedClaim, frames []string) []citedClaim {
	merged := make([]citedClaim, 0, len(claims))
	for i := 0; i < len(claims); i++ {
		c := claims[i]
		if bareListMarker.MatchString(strings.TrimSpace(c.text)) && i+1 < len(claims) {
			next := claims[i+1]
			next.text = strings.TrimSpace(c.text) + " " + next.text
			next.cited = appendUnique(append([]string{}, c.cited...), next.cited...)
			next.facets = appendUnique(append([]string{}, c.facets...), next.facets...)
			claims[i+1] = next
			continue
		}
		merged = append(merged, c)
	}

	out := make([]citedClaim, 0, len(merged))
	var leadIn *citedClaim
	joinText := ""
	ownClaim := -1 // index in out of a verified exclusive/counted lead-in
	for i := range merged {
		c := merged[i]
		loc := listItemPrefix.FindStringIndex(c.text)
		if loc == nil {
			leadIn, ownClaim = nil, -1
			if strings.HasSuffix(strings.TrimSpace(c.text), ":") && i+1 < len(merged) &&
				listItemPrefix.MatchString(merged[i+1].text) {
				lead := c
				leadIn = &lead
				bare := strings.TrimSuffix(strings.TrimSpace(c.text), ":")
				stripped, marked := stripListQualifiers(bare)
				joinText = stripped
				if !marked && contentFreeLeadIn(bare, frames) {
					// "Zo zit het:" says nothing: joined, its words would only make
					// a true item fail. Items are verified alone, as without a lead-in.
					leadIn = &citedClaim{text: "", cited: c.cited, facets: c.facets}
					joinText = ""
					continue
				}
				if marked {
					ownClaim = len(out)
					out = append(out, c)
				}
				continue // otherwise structural: carried into its items only
			}
			out = append(out, c)
			continue
		}
		item := strings.TrimSpace(c.text[loc[1]:])
		if leadIn == nil {
			c.text = item
			out = append(out, c)
			continue
		}
		if joinText == "" {
			c.text = item
		} else {
			c.text = joinText + " " + lowerFirst(item)
			c.lead, c.item = joinText, lowerFirst(item)
			c.leadCited, c.itemCited = leadIn.cited, c.cited
		}
		c.cited = appendUnique(append([]string{}, c.cited...), leadIn.cited...)
		c.facets = appendUnique(append([]string{}, c.facets...), leadIn.facets...)
		if ownClaim >= 0 {
			out[ownClaim].cited = appendUnique(out[ownClaim].cited, c.cited...)
			out[ownClaim].facets = appendUnique(out[ownClaim].facets, c.facets...)
		}
		out = append(out, c)
	}
	return out
}

// DefaultLeadInFrames is a small, generic nl/en table of content-free list
// lead-ins. Hosts supply their own through VerifyOptions.LeadInFrames.
//
// Step introducers ("Volg deze stappen:", "Here are the exact steps:") are
// whole phrases on purpose: "exact", "volg" and "deze" are not stopwords, so a
// frame must cover them, and a lead-in with any word outside a frame — "Volg
// deze stappen bij ziekte:" — is still joined. rag_go measured 12 step items
// left uncited under exactly these two lead-ins.
var DefaultLeadInFrames = []string{
	"zo zit het", "zo werkt het", "het volgende", "als volgt", "hieronder",
	"samengevat", "kort samengevat", "in het kort", "een overzicht",
	"here's how", "here is how", "here's what", "here is what", "as follows",
	"the following", "below", "in short", "in summary", "an overview",
	"volg deze stappen", "volg de stappen", "volg de volgende stappen",
	"de volgende stappen", "deze stappen", "de stappen", "stappen",
	"hier zijn de stappen", "hier zijn de exacte stappen",
	"here are the steps", "here are the exact steps", "follow these steps",
	"follow the steps", "these steps", "the steps", "steps",
}

// contentFreeLeadIn: every token of the lead-in is covered by a frame or is a
// stopword that is not a polarity marker, and there is at least one frame.
// Numbers never count as free.
func contentFreeLeadIn(lead string, frames []string) bool {
	toks := tokenize.TokenizeV2(lead)
	if len(toks) == 0 {
		return false
	}
	covered := make([]bool, len(toks))
	matched := false
	for _, f := range frames {
		ft := tokenize.TokenizeV2(f)
		if len(ft) == 0 {
			continue
		}
		for i := 0; i+len(ft) <= len(toks); i++ {
			same := true
			for k := range ft {
				if toks[i+k] != ft[k] {
					same = false
					break
				}
			}
			if same {
				matched = true
				for k := range ft {
					covered[i+k] = true
				}
			}
		}
	}
	if !matched {
		return false
	}
	polarity := gate.PolarityMarkers()
	for i, t := range toks {
		if covered[i] {
			continue
		}
		if _, neg := polarity[t]; neg || !gate.IsStopword(t) {
			return false
		}
	}
	return true
}

// listExclusives make a lead-in exclusive: "mag alleen de volgende …".
var listExclusives = map[string]struct{}{
	"alleen": {}, "uitsluitend": {}, "enkel": {}, "slechts": {},
	"only": {}, "solely": {}, "exclusively": {},
}

// listReferenceNouns precede a number that names a provision, not a count:
// "volgens artikel 7 geldt:".
var listReferenceNouns = map[string]struct{}{
	"artikel": {}, "art": {}, "lid": {}, "hoofdstuk": {}, "paragraaf": {}, "bijlage": {},
	"article": {}, "section": {}, "chapter": {}, "paragraph": {}, "annex": {}, "clause": {},
}

var listLeadToken = regexp.MustCompile(`\S+`)

// stripListQualifiers removes a lead-in's exclusivity words and item count, and
// reports whether it removed anything. A count is a cardinal 2–12 (a word or
// digits) that is not a period ("binnen 2 weken:") and does not name a
// provision ("artikel 7"). "een"/"one" are never a count: they are also the
// article.
func stripListQualifiers(lead string) (string, bool) {
	words := listLeadToken.FindAllString(lead, -1)
	kept := make([]string, 0, len(words))
	marked := false
	for i, w := range words {
		bare := strings.ToLower(strings.Trim(w, ",;()\"'"))
		if _, ok := listExclusives[bare]; ok {
			marked = true
			continue
		}
		if isListCount(bare, words, i) {
			marked = true
			continue
		}
		kept = append(kept, w)
	}
	return strings.Join(kept, " "), marked
}

func isListCount(bare string, words []string, i int) bool {
	value, ok := numberWords[bare]
	if !ok && bare != "" && bare[0] >= '0' && bare[0] <= '9' {
		value, ok = bare, true
	}
	if !ok {
		return false
	}
	switch value {
	case "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12":
	default:
		return false
	}
	if i > 0 {
		if _, ref := listReferenceNouns[strings.ToLower(strings.Trim(words[i-1], ".,;()"))]; ref {
			return false
		}
	}
	if i+1 < len(words) {
		if _, _, unit := unitOf(strings.ToLower(strings.Trim(words[i+1], ".,;()"))); unit {
			return false
		}
	}
	return true
}

// lowerFirst lowercases an item's first letter when joined mid-sentence —
// unless the word is an acronym or code ("CAO", "WW-uitkering"), where the case
// carries meaning.
func lowerFirst(item string) string {
	runes := []rune(item)
	if len(runes) < 2 || !unicode.IsUpper(runes[0]) || unicode.IsUpper(runes[1]) || !unicode.IsLetter(runes[1]) {
		return item
	}
	runes[0] = unicode.ToLower(runes[0])
	return string(runes)
}

var (
	// mdLink is an inline link or image: [text](url) / ![alt](url "title").
	mdLink = regexp.MustCompile(`!?\[([^\[\]]*)\]\([^()\s]*(?:\([^()\s]*\)[^()\s]*)*(?:\s+"[^"]*")?\)`)
	// mdEmphasis is single-character emphasis, *x* or _x_, opened at a word
	// boundary and closed before one: "snake_case" and "5 * 3" are not emphasis.
	mdEmphasis = regexp.MustCompile(`(^|[\s(\[{"'“‘])[*_]([^\s*_](?:[^*_\n]*[^\s*_])?)[*_]($|[\s)\]}"'”’.,;:!?])`)
	mdStrong   = strings.NewReplacer("**", "", "__", "", "`", "")
)

// stripMarkup removes Markdown emphasis (**, __, *, _), code backticks and link
// markup ([text](url) -> text) from a claim, keeping every word it marks up —
// a label ("**Bedrag:** …") stays a label. The gate, the guards and the checker
// see the claim as a reader does. rag_go measured 31 true claims refused and 3
// admitted only because the markup was there, and single emphasis hid a name
// from the name guard ("via *Cobra*" reads no capital).
func stripMarkup(text string) string {
	out := mdStrong.Replace(mdLink.ReplaceAllString(text, "$1"))
	for i := 0; i < 4; i++ { // adjacent spans share a boundary character
		next := mdEmphasis.ReplaceAllString(out, "$1$2$3")
		if next == out {
			break
		}
		out = next
	}
	return out
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
	// "auto" is the detect-it sentinel, not a language: it must not count as
	// declared, or every unit with a declared language reads as cross-language
	// and the model admits same-language paraphrases without AdmitParaphrase.
	declared := opts.AnswerLanguage
	if strings.EqualFold(strings.TrimSpace(declared), lang.AutoAnswerLanguage) {
		declared = ""
	}
	claimLanguage := primaryLanguage(declared)

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

	actors := DefaultActorLexicon
	if opts.Actors != nil {
		actors = *opts.Actors
	}
	pairs := DefaultQualifierPairs
	if opts.QualifierPairs != nil {
		pairs = opts.QualifierPairs
	}
	verbs := DefaultVerbPairs
	if opts.VerbPairs != nil {
		verbs = opts.VerbPairs
	}
	subtypes := DefaultSubtypeHeads
	if opts.SubtypeHeads != nil {
		subtypes = opts.SubtypeHeads
	}
	cfg := guardConfig{aliases: opts.NameAliases, actors: actors, pairs: pairs, verbs: verbs,
		gloss: preparedFor(opts), noDefinitions: opts.DisableDefinitions,
		docDefs: documentDefinitions(evidence), subtypes: subtypes}
	frames := opts.LeadInFrames
	if frames == nil {
		frames = DefaultLeadInFrames
	}
	parsed := parseCitationsWith(answer, frames)
	verdicts := make([]verdict, 0, len(parsed))
	for _, pc := range parsed {
		// Reported as written (a host locates it in its own answer); checked with
		// its markup removed, so "**Bedrag:**" or a link's URL decides nothing.
		v := verdict{text: pc.text, facets: pc.facets}
		text := stripMarkup(pc.text)

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
		gateReason := ""
		reasonUnits := candidates // whose outcomes decide the refusal reason (F0)
		// Per cited unit: the first guard that refused it, or the checker's
		// scores when the model decided (F0: an honest reason, below).
		guardOf := map[string]string{}
		scoredOf := map[string]scores{}
		scoredOrder := []string{}
		for _, eu := range candidates {
			if gate.IsSupportedV2(text, eu.Text) {
				reason := clauseNegationGuard(text, eu.Text)
				if reason == "" {
					reason = truncationGuard(text, eu.Text)
				}
				if reason == "" && pc.item != "" {
					reason = truncationGuard(stripMarkup(pc.item), eu.Text)
				}
				if reason == "" {
					reason = exclusionGuard(text, declared, eu, cfg)
				}
				if reason == "" {
					reason = definitionGuard(text, declared, eu, cfg)
				}
				if reason == "" {
					reason = subtypeGuard(text, eu, cfg)
				}
				if reason == "" {
					reason = conditionGuard(text, declared, eu, cfg)
				}
				if reason == "" {
					// The gate matches tokens, not who does what: "De werkgever
					// betaalt 4,5%" can align across two clauses of the unit.
					reason = roleGuard(text, declared, eu, actors)
				}
				if reason == "" {
					reason = relationGuard(text, declared, eu, actors)
				}
				if reason != "" {
					if gateReason == "" {
						gateReason = reason // the FIRST cited unit refused, not the last
					}
					if _, seen := guardOf[eu.ID]; !seen {
						guardOf[eu.ID] = reason
					}
					continue
				}
				v.sources = append(v.sources, eu.ID)
				if len(pc.cited) == 0 {
					break
				}
			}
		}
		if len(v.sources) > 0 {
			v.supported, v.verifiedBy = true, "gate"
		} else if gateReason != "" {
			v.reason = gateReason
		}

		// Veto: a gate-admitted source the checker says contradicts the claim.
		if v.supported && opts.Checker != nil {
			kept := v.sources[:0:0]
			for _, id := range v.sources {
				s, err := check(text, evidence[byID[id]])
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
				reason := guards(text, declared, eu, cfg)
				if reason == "" && pc.item != "" {
					// A joined item is also a cut span on its own words:
					// "Overwerk wordt uitbetaald" under "Voor overwerk geldt:".
					reason = truncationGuard(stripMarkup(pc.item), eu.Text)
				}
				if reason != "" {
					if guardReason == "" {
						guardReason = reason // the FIRST cited unit refused, not the last
					}
					if _, seen := guardOf[eu.ID]; !seen {
						guardOf[eu.ID] = reason
					}
					return false, nil
				}
				s, err := check(text, eu)
				if err != nil {
					return false, err
				}
				if _, seen := scoredOf[eu.ID]; !seen {
					scoredOrder = append(scoredOrder, eu.ID)
				}
				scoredOf[eu.ID] = s
				return s.entailed >= entailAt && s.contradicted < contradictAt, nil
			}

			// 2. QUOTE: every quote in the claim passes the gate against the unit.
			if qs := quotes(text); len(qs) > 0 {
				for _, eu := range candidates {
					anchored := true
					for _, q := range qs {
						if !gate.IsSupportedV2(q, eu.Text) || clauseNegationGuard(q, eu.Text) != "" {
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
			// 4. UNION: a list item joined to a content lead-in, where the lead-in
			// and the item cite different units ("Volgens artikel 7:13 BW
			// [eu:a]:" / "- … [eu:b]"). Checked alone, each unit lacks the
			// other part's facts, and the guards refuse a true item for the
			// lead-in's article number. See unionRefusal for what it takes.
			unionReason := ""
			unionPairs, unionScored := 0, map[string]scores{}
			if !v.supported && pc.lead != "" && len(pc.itemCited) > 0 {
				lead, item := stripMarkup(pc.lead), stripMarkup(pc.item)
				inItem, inLead := map[string]bool{}, map[string]bool{}
				for _, id := range pc.itemCited {
					inItem[id] = true
				}
				for _, id := range pc.leadCited {
					inLead[id] = !inItem[id]
				}
				allowed := func(eu EvidenceUnit) bool {
					pl := primaryLanguage(eu.Language)
					return opts.AdmitParaphrase || (claimLanguage != "" && pl != "" && pl != claimLanguage)
				}
				for _, b := range candidates {
					if !inItem[b.ID] || !allowed(b) {
						continue
					}
					for _, a := range candidates {
						if !inLead[a.ID] || !allowed(a) {
							continue
						}
						unionPairs++
						reason := unionRefusal(text, lead, item, declared, a, b, cfg)
						if reason == "" {
							// The checker may veto from either unit, and must entail the
							// claim from both together.
							for _, p := range []EvidenceUnit{a, b, unionPremise(a, b)} {
								s, err := check(text, p)
								if err != nil {
									return result.Result{}, err
								}
								if p.ID == unionPremise(a, b).ID {
									unionScored[a.ID+"+"+b.ID] = s
								}
								switch {
								case s.contradicted >= contradictAt:
									reason = ReasonContradicted
								case p.ID == unionPremise(a, b).ID && s.entailed < entailAt:
									reason = ReasonNotSupported
								}
								if reason != "" {
									break
								}
							}
						}
						if reason != "" {
							if unionReason == "" {
								unionReason = reason // the FIRST pair refused, not the last
							}
							continue
						}
						v.sources = appendUnique(v.sources, a.ID, b.ID)
					}
				}
				if len(v.sources) > 0 {
					v.supported, v.verifiedBy, v.reason = true, modelLabel, ""
				}
			}
			if !v.supported && unionReason == ReasonContradicted {
				v.reason = ReasonContradicted
			}
			// A joined claim checked as a union is decided by its pairs, not by
			// its units one at a time: every pair refused by a guard names the
			// guard; a pair the checker scored makes it the model's refusal.
			if !v.supported && unionPairs > 0 && v.reason != ReasonContradicted {
				guardOf, scoredOf, scoredOrder = map[string]string{}, map[string]scores{}, nil
				reasonUnits = []EvidenceUnit{{ID: "union"}}
				if len(unionScored) == 0 {
					guardOf["union"] = unionReason
				} else {
					for label, sc := range unionScored {
						scoredOf[label] = sc
						scoredOrder = append(scoredOrder, label)
					}
					sort.Strings(scoredOrder)
				}
			}
		}

		// F0 — an honest reason. A guard is named only when EVERY cited unit
		// failed a guard; when any unit reached the checker and it would not
		// admit, the claim was refused by the MODEL, and the reason says so
		// with the best unit's scores. rag_go measured 932 of 1,354 "guard"
		// refusals (69%) where another cited unit passed every guard and the
		// model refused. Reporting only: nothing is admitted or refused here.
		if !v.supported && v.reason != ReasonContradicted && len(reasonUnits) > 0 {
			allGuarded := true
			for _, eu := range reasonUnits {
				if _, ok := guardOf[eu.ID]; !ok {
					allGuarded = false
					break
				}
			}
			switch {
			case allGuarded:
				v.reason = guardOf[reasonUnits[0].ID] // the first cited unit's guard
			case len(scoredOf) > 0:
				best := scoredOrder[0]
				for _, id := range scoredOrder[1:] {
					b, s := scoredOf[best], scoredOf[id]
					if s.entailed > b.entailed || (s.entailed == b.entailed && s.contradicted < b.contradicted) {
						best = id
					}
				}
				bs := scoredOf[best]
				v.reason = fmt.Sprintf("%s (model: best entailment %.3f, contradiction %.3f on %s)",
					ReasonNotSupported, bs.entailed, bs.contradicted, best)
			default:
				v.reason = ReasonNotSupported
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
				if f, ok := DetectConflictWithLanguages(s.Text, s.Language, o.Text, o.Language); ok {
					conflicts = append(conflicts, conflict{s, o, f})
				}
			}
		}
	}
	// A unit loses when something at least as authoritative contradicts it:
	// strictly more => resolved against it; equal => unresolved, both lose.
	// Effects are recorded per unit and applied per CLAIM below, because a value
	// conflict only touches the claims that carry the disputed value.
	type effect struct {
		outranked bool // false = unresolved
		c         conflict
		diffRuns  map[string]struct{} // value rule only: digit runs that differ
	}
	effects := map[string][]effect{}
	var conflictNotes []string
	for _, c := range conflicts {
		ts, to := tierOf(c.supporting), tierOf(c.other)
		note := fmt.Sprintf("%s: %s vs %s (%s)", c.finding.Rule, c.supporting.DocumentID, c.other.DocumentID, c.finding.Detail)
		var runs map[string]struct{}
		if c.finding.Rule == "value" {
			runs = differingDigitRuns(c.supporting, c.other)
		}
		switch {
		case to.Outranks(ts):
			effects[c.supporting.ID] = append(effects[c.supporting.ID], effect{outranked: true, c: c, diffRuns: runs})
			note += fmt.Sprintf(" — resolved by authority: %s outranks %s", c.other.ID, c.supporting.ID)
		case ts.Outranks(to):
			effects[c.other.ID] = append(effects[c.other.ID], effect{outranked: true, c: c, diffRuns: runs})
			note += fmt.Sprintf(" — resolved by authority: %s outranks %s", c.supporting.ID, c.other.ID)
		default:
			e := effect{c: c, diffRuns: runs}
			effects[c.supporting.ID] = append(effects[c.supporting.ID], e)
			effects[c.other.ID] = append(effects[c.other.ID], e)
		}
		conflictNotes = append(conflictNotes, note)
	}
	conflictDropped := 0
	unresolvedSides := []EvidenceUnit{}
	for i := range verdicts {
		v := &verdicts[i]
		if !v.supported {
			continue
		}
		kept := v.sources[:0:0]
		reason := ""
		for _, id := range v.sources {
			applied := false
			for _, e := range effects[id] {
				if spared(*v, e.diffRuns) {
					continue
				}
				applied = true
				if e.outranked {
					reason = ReasonOutranked
				} else {
					if reason == "" {
						reason = ReasonUnresolvedClaims
					}
					unresolvedSides = append(unresolvedSides, e.c.supporting, e.c.other)
				}
			}
			if !applied {
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
	supportingTexts, supportingLanguages := []string{}, []string{}
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
				supportingLanguages = append(supportingLanguages, eu.Language)
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
			SupportingSources:        len(CollapseNearDuplicatesWithLanguages(supportingTexts, supportingLanguages)),
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

// differingDigitRuns are the digit runs of every number one unit carries and
// the other does not (by ADR-0015 key), from both sides. A phone number that
// differs between two versions of a contact list yields its own runs; the
// shared "06" prefix does not.
func differingDigitRuns(a, b EvidenceUnit) map[string]struct{} {
	runs := map[string]struct{}{}
	collect := func(x, y EvidenceUnit) {
		have := map[string]struct{}{}
		for _, m := range numbersIn(y.Text, y.Language) {
			have[m.reading.Key] = struct{}{}
		}
		for _, m := range numbersIn(x.Text, x.Language) {
			if _, ok := have[m.reading.Key]; ok {
				continue
			}
			for _, run := range digitRun.FindAllString(m.raw, -1) {
				runs[run] = struct{}{}
			}
		}
	}
	collect(a, b)
	collect(b, a)
	return runs
}

var digitRun = regexp.MustCompile(`[0-9]+`)

// spared is true when a VALUE conflict provably does not touch this claim: the
// claim was verified on its own words (the gate, or a gate-checked quote) and
// carries none of the differing digit runs. A model-admitted paraphrase is
// never spared — it may restate the disputed value in words ("dertig dagen"),
// which no digit comparison can see. Any other conflict rule is never spared.
func spared(v verdict, diffRuns map[string]struct{}) bool {
	if diffRuns == nil {
		return false
	}
	if v.verifiedBy != "gate" && !strings.HasPrefix(v.verifiedBy, "quote+") {
		return false
	}
	for _, run := range digitRun.FindAllString(v.text, -1) {
		if _, ok := diffRuns[run]; ok {
			return false
		}
	}
	return true
}

func sourceRefOf(eu EvidenceUnit) result.SourceRef {
	language := eu.Language
	if language == "" {
		language = undeclaredLanguage
	}
	return result.SourceRef{Document: eu.DocumentID, Passage: eu.Text, PassageLanguage: language}
}
