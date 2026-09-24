// The union rule for a list item joined to a content lead-in.
//
// joinListItems verifies "Volgens artikel 7:13 BW:" / "- de werkgever mag …"
// as ONE claim, because an item cut loose from a lead-in that restricts it
// ("Alleen voor stagiairs:") would be admitted for a scope it does not have.
// But the writer often cites the lead-in to the unit that NAMES the provision
// and the item to the unit that STATES the fact. Checked against either unit
// alone, the joined claim then fails: rag_go measured 95 items admitted alone
// and refused once joined, mostly by the name and number guards, for the
// lead-in's article number, law name or count.
//
// The union rule admits such a claim against the lead-in's unit A and the
// item's unit B together — but only the lead-in's REFERENCES may come from A.
// Everything else the lead-in says is a condition on the item, and a condition
// must hold where the item's fact is stated. How the union applies, per path:
//
//   - GATE: never. The gate's guarantee is "verbatim in one unit"; a claim
//     spanning two units is verbatim nowhere, and gluing two texts together
//     would let an ordered match cross the seam. Without a checker a joined
//     claim is verified per unit, as before.
//   - GUARDS: split by provenance, and all of them must pass —
//     the lead-in's own facts against A (a lead-in's number or name must be in
//     a unit IT cites: not exempted, and not borrowed from the item's unit);
//     the item's facts against B (an item's number cannot come from A, so a
//     value A states and B contradicts is refused); and the whole claim against
//     A and B together (nothing in the claim is in neither).
//   - SCOPE (leadInScope): every lead-in word that is not a reference — a
//     name, a provision number after "artikel"/"lid"/…, the reference noun
//     itself, an attribution word ("volgens", "under"), a stopword — must be in
//     B. "voor stagiairs" over a werknemer passage is refused even when A is a
//     stagiair passage.
//   - MODEL: the checker must entail the joined claim from the premise A+B
//     (unionPremise), and neither A, B nor A+B may contradict it. Behind every
//     rule above, which the model cannot override.
//
// It applies only when the item cites a unit of its own and the lead-in cites
// a different one, and only where the model path itself is allowed (a
// cross-language unit, or AdmitParaphrase) for both units. A claim it admits is
// a model admission citing both units.

package answer

import (
	"fmt"
	"strings"

	"github.com/muthuishere/citenexus/golang/gate"
	"github.com/muthuishere/citenexus/golang/tokenize"
)

// unionPremise is the evidence a joined item is checked against: the lead-in's
// unit, then the item's. Two languages that differ leave it undeclared, so a
// number either could read ambiguously matches only as spelled.
func unionPremise(a, b EvidenceUnit) EvidenceUnit {
	language := a.Language
	if primaryLanguage(a.Language) != primaryLanguage(b.Language) {
		language = ""
	}
	return EvidenceUnit{
		ID:         a.ID + "\x00" + b.ID,
		DocumentID: a.DocumentID + "\n" + b.DocumentID,
		Text:       a.Text + "\n\n" + b.Text,
		Language:   language,
	}
}

// unionRefusal runs the deterministic part of the union rule for one pair —
// A (the lead-in's unit) and B (the item's) — and returns the first refusal,
// or "". claim is the joined claim; lead and item its parts.
func unionRefusal(claim, lead, item, claimLanguage string, a, b EvidenceUnit, cfg guardConfig) string {
	if reason := leadInScope(lead, b); reason != "" {
		return reason
	}
	leadCfg := cfg
	leadCfg.fragment = true
	if reason := guards(lead, claimLanguage, a, leadCfg); reason != "" {
		return reason
	}
	if reason := guards(item, claimLanguage, b, cfg); reason != "" {
		return reason
	}
	return guards(claim, claimLanguage, unionPremise(a, b), cfg)
}

// leadInAttribution attribute a lead-in to a source and restrict nothing:
// "Volgens artikel 7:13 BW:", "Under Article 7:13:", "… geldt:".
var leadInAttribution = map[string]struct{}{
	"volgens": {}, "krachtens": {}, "ingevolge": {}, "conform": {}, "onder": {},
	"geldt": {}, "gelden": {}, "bepaalt": {},
	"according": {}, "pursuant": {}, "under": {}, "applies": {}, "apply": {},
	"provides": {}, "states": {},
}

// leadInScope: every word of the lead-in that is not a reference must be in the
// item's unit B. References — names (as the name guard reads them), a reference
// noun and the provision number after it ("artikel 7:13", "art. 7:673 lid 7"),
// attribution words and stopwords — may come from the lead-in's own unit, where
// the guards check them. A polarity marker is never free: "Niet vergoed:"
// needs a negation in B.
func leadInScope(lead string, b EvidenceUnit) string {
	have := map[string]struct{}{}
	for _, tok := range tokenize.TokenizeV2(b.Text) {
		have[tok] = struct{}{}
	}
	named := map[string]struct{}{}
	for _, name := range names(lead) {
		for _, tok := range tokenize.TokenizeV2(name) {
			named[tok] = struct{}{}
		}
	}
	words := listLeadToken.FindAllString(lead, -1)
	reference := make([]bool, len(words))
	for i, w := range words {
		if _, ok := listReferenceNouns[strings.ToLower(strings.Trim(w, `.,;:()[]"'`))]; !ok {
			continue
		}
		reference[i] = true
		if i+1 < len(words) && strings.ContainsAny(words[i+1], "0123456789") {
			reference[i+1] = true
		}
	}
	polarity := gate.PolarityMarkers()
	for i, w := range words {
		if reference[i] {
			continue
		}
		for _, tok := range tokenize.TokenizeV2(w) {
			if _, ok := have[tok]; ok {
				continue
			}
			if _, negation := polarity[tok]; !negation && freeLeadInToken(tok, named) {
				continue
			}
			return fmt.Sprintf("lead-in guard: %q is not in the item's evidence", tok)
		}
	}
	return ""
}

func freeLeadInToken(tok string, named map[string]struct{}) bool {
	if gate.IsStopword(tok) {
		return true
	}
	for _, set := range []map[string]struct{}{contextStop, leadInAttribution, named} {
		if _, ok := set[tok]; ok {
			return true
		}
	}
	return false
}
