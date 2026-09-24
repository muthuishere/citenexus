// Guards for the MODEL path: swaps an NLI model admits with P(entailment)
// ≈ 0.999 that no threshold stops (measured by rag_go on its fine-tuned
// checker, 2026-09-24). Each is deterministic, table-driven, and can only
// refuse. They run inside guards() on every quote and model admission; a gate
// admission is verbatim and never reaches them.

package answer

import (
	"fmt"
	"regexp"
	"strings"

	"github.com/muthuishere/citenexus/golang/gate"
	"github.com/muthuishere/citenexus/golang/tokenize"
)

// ─── unit guard ──────────────────────────────────────────────────────────────

// timeUnits maps a unit word (NL + EN, with abbreviations) to its class. Work
// days and calendar days are different classes on purpose: they are different
// periods in law.
var timeUnits = map[string]string{
	"day": "day", "days": "day", "dag": "day", "dagen": "day",
	"kalenderdag": "day", "kalenderdagen": "day",
	"werkdag": "workday", "werkdagen": "workday",
	"week": "week", "weeks": "week", "weken": "week", "wk": "week", "wkn": "week",
	"month": "month", "months": "month", "maand": "month", "maanden": "month", "mnd": "month",
	"year": "year", "years": "year", "jaar": "year", "jaren": "year", "jr": "year", "yr": "year", "yrs": "year",
	"hour": "hour", "hours": "hour", "uur": "hour", "uren": "hour", "hr": "hour", "hrs": "hour",
	"minute": "minute", "minutes": "minute", "minuut": "minute", "minuten": "minute", "min": "minute",
}

// unitModifiers precede "day(s)" in English and change its class.
var unitModifiers = map[string]string{"working": "workday", "business": "workday", "calendar": "day"}

// numberWords are the spelled-out values a policy writes before a unit
// ("twee (2) maanden", "four weeks"). "een"/"één" count only when a unit
// follows, which is the only place a value is read.
var numberWords = map[string]string{
	"zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
	"seven": "7", "eight": "8", "nine": "9", "ten": "10", "eleven": "11", "twelve": "12",
	"thirteen": "13", "fourteen": "14", "fifteen": "15", "sixteen": "16", "seventeen": "17",
	"eighteen": "18", "nineteen": "19", "twenty": "20", "thirty": "30", "forty": "40",
	"fifty": "50", "sixty": "60",
	"nul": "0", "een": "1", "één": "1", "twee": "2", "drie": "3", "vier": "4", "vijf": "5",
	"zes": "6", "zeven": "7", "acht": "8", "negen": "9", "tien": "10", "elf": "11",
	"twaalf": "12", "dertien": "13", "veertien": "14", "vijftien": "15", "zestien": "16",
	"zeventien": "17", "achttien": "18", "negentien": "19", "twintig": "20", "dertig": "30",
	"veertig": "40", "vijftig": "50", "zestig": "60",
}

var unitScan = regexp.MustCompile(`[0-9]+(?:[.,][0-9]+)*|½|\p{L}+`)

// quantities are the (value key, unit class) pairs in text: a number — digits
// read by ADR-0015 key, or a number word — directly followed by a time unit.
// A parenthesised digit restating a number word ("twee (2) maanden") is
// skipped, so it is read once.
func quantities(text, language string) map[[2]string]struct{} {
	tokens := unitScan.FindAllString(strings.ToLower(text), -1)
	out := map[[2]string]struct{}{}
	for i := 0; i < len(tokens); i++ {
		value, isNumber := "", false
		switch t := tokens[i]; {
		case t == "½":
			value, isNumber = "0.5", true
		case t[0] >= '0' && t[0] <= '9':
			value, isNumber = ReadNumber(t, false, language).Key, true
		default:
			value, isNumber = numberWords[t]
		}
		if !isNumber {
			continue
		}
		j := i + 1
		if j < len(tokens) && tokens[j][0] >= '0' && tokens[j][0] <= '9' &&
			ReadNumber(tokens[j], false, language).Key == value {
			j++ // "twee (2) maanden"
		}
		if j >= len(tokens) {
			continue
		}
		class, ok := timeUnits[tokens[j]]
		if mod, isMod := unitModifiers[tokens[j]]; isMod && j+1 < len(tokens) {
			if c := timeUnits[tokens[j+1]]; c == "day" {
				class, ok = mod, true
			}
		}
		if ok {
			out[[2]string{value, class}] = struct{}{}
		}
	}
	return out
}

// unitGuard refuses a SWAP of a quantity: the claim's number-with-a-time-unit
// is absent from the passage while the passage has the same number with a
// different unit ("2 weeks" over "twee (2) maanden" — admitted by the model at
// P(E) 0.999; the number guard sees the 2 and passes it), or the same unit with
// a different number ("four weeks" over "twee weken" — no digits, so the number
// guard never looks). Numbers and units are read across NL/EN, each side in its
// own declared language.
//
// A quantity the passage does not express at all is NOT refused here: a table
// cell ("12,5 ✓" under a "Jaren in dienst" header) carries the number without
// its unit, and the number guard already requires the digits to be present.
func unitGuard(claim, claimLanguage, passage, passageLanguage string) string {
	have := quantities(passage, passageLanguage)
	for q := range quantities(claim, claimLanguage) {
		if _, ok := have[q]; ok {
			continue
		}
		var sameValue, sameUnit []string
		for p := range have {
			if p[0] == q[0] {
				sameValue = append(sameValue, p[1])
			}
			if p[1] == q[1] {
				sameUnit = append(sameUnit, p[0])
			}
		}
		switch {
		case len(sameValue) > 0:
			return fmt.Sprintf("unit guard: %s %s where the passage says %s %s",
				q[0], q[1], q[0], strings.Join(sortedStrings(sameValue), "/"))
		case len(sameUnit) > 0:
			return fmt.Sprintf("unit guard: %s %s where the passage says %s %s",
				q[0], q[1], strings.Join(sortedStrings(sameUnit), "/"), q[1])
		}
	}
	return ""
}

func sortedStrings(in []string) []string {
	set := map[string]struct{}{}
	for _, s := range in {
		set[s] = struct{}{}
	}
	return sortedKeys(set)
}

// ─── qualifier / role guard ──────────────────────────────────────────────────

// qualifierSide is one side of a closed pair, with its forms per language.
type qualifierSide struct{ nl, en []string }

// qualifierPairs are closed pairs whose swap flips legal meaning. A form of 5+
// letters also matches inside a compound ("brutoloon", "werkgeversbijdrage");
// a shorter one only as a whole token ("na", "net"). Plain "voor" is
// deliberately absent: it means "for".
var qualifierPairs = [][2]qualifierSide{
	{{nl: []string{"bruto"}, en: []string{"gross"}}, {nl: []string{"netto"}, en: []string{"net"}}},
	{{nl: []string{"werkgever"}, en: []string{"employer"}}, {nl: []string{"werknemer"}, en: []string{"employee"}}},
	{{nl: []string{"vóór", "voordat"}, en: []string{"before"}}, {nl: []string{"na", "nadat"}, en: []string{"after"}}},
	{{nl: []string{"eerder"}, en: []string{"earlier"}}, {nl: []string{"later"}, en: []string{"later"}}},
	{{nl: []string{"minimaal"}, en: []string{"minimum"}}, {nl: []string{"maximaal"}, en: []string{"maximum"}}},
	{{nl: []string{"schriftelijk", "schriftelijke"}, en: []string{"written", "writing"}},
		{nl: []string{"mondeling", "mondelinge"}, en: []string{"oral", "orally", "verbally"}}},
}

func matchesForm(token, form string) bool {
	if len([]rune(form)) >= 5 {
		return strings.Contains(token, form)
	}
	return token == form
}

func anyForm(token string, forms []string) bool {
	for _, form := range forms {
		if matchesForm(token, form) {
			return true
		}
	}
	return false
}

// formsIn is the side's forms in one language ("nl" or "en").
func (q qualifierSide) formsIn(language string) []string {
	if language == "nl" {
		return q.nl
	}
	return q.en
}

// contextStop are function words that carry no locating signal, NL + EN.
var contextStop = map[string]struct{}{
	"de": {}, "het": {}, "een": {}, "en": {}, "van": {}, "in": {}, "op": {}, "te": {}, "dat": {},
	"die": {}, "is": {}, "zijn": {}, "voor": {}, "met": {}, "aan": {}, "bij": {}, "of": {},
	"als": {}, "ook": {}, "om": {}, "naar": {}, "door": {}, "over": {}, "tot": {}, "uit": {},
	"je": {}, "jouw": {}, "uw": {}, "wordt": {}, "worden": {},
}

const qualifierWindow = 5

// clauseTokens tokenizes text clause by clause, so a context window never
// borrows words from a neighbouring sentence: "De werkgever betaalt de premie.
// De werknemer ontvangt …" must not give "werknemer" the context "premie".
func clauseTokens(text string) [][]string {
	out := [][]string{}
	for _, clause := range clauseBreak.Split(text, -1) {
		if tokens := tokenize.TokenizeV2(clause); len(tokens) > 0 {
			out = append(out, tokens)
		}
	}
	return out
}

// window is the content tokens within qualifierWindow of index i in the same
// clause, minus any form of the pair.
func window(tokens []string, i int, pair [2]qualifierSide) map[string]struct{} {
	out := map[string]struct{}{}
	for k := i - qualifierWindow; k <= i+qualifierWindow; k++ {
		if k < 0 || k >= len(tokens) || k == i {
			continue
		}
		t := tokens[k]
		if gate.IsStopword(t) || isPairForm(t, pair) {
			continue
		}
		if _, stop := contextStop[t]; stop {
			continue
		}
		out[t] = struct{}{}
	}
	return out
}

func isPairForm(t string, pair [2]qualifierSide) bool {
	for _, side := range pair {
		if anyForm(t, side.nl) || anyForm(t, side.en) {
			return true
		}
	}
	return false
}

// qualifierGuard refuses a claim that carries one side of a closed pair where
// the passage, at the matching place, carries the other: "het nettoloon in
// geld" over "het brutoloon in geld" — although the passage mentions
// "nettoloon" elsewhere (rag_go R-123; R-119 the same in a table).
//
// SAME LANGUAGE ONLY: a claim form is compared with passage forms of its own
// language. Neighbouring words cannot be compared across languages, and a role
// is often written without the pair word at all ("je", a company name), so a
// cross-language verdict would be a guess; those claims stay with the checker
// and the other guards.
//
// Within a language, "the matching place" is decided by context: for each
// occurrence of the pair in the passage, count how many of the claim's
// neighbouring content tokens sit in its neighbourhood. Refused when the
// passage has only the other side, or when the other side's best occurrence
// matches STRICTLY better than any occurrence of the claim's side. A tie is not
// refused.
func qualifierGuard(claim, passage string) string {
	passageClauses := clauseTokens(passage)
	for _, pair := range qualifierPairs {
		for _, claimTokens := range clauseTokens(claim) {
			for i, t := range claimTokens {
				for s := 0; s < 2; s++ {
					for _, lang := range []string{"nl", "en"} {
						same, other := pair[s].formsIn(lang), pair[1-s].formsIn(lang)
						if !anyForm(t, same) || anyForm(t, other) {
							continue
						}
						context := window(claimTokens, i, pair)
						bestSame, bestOther, sawSame, sawOther := -1, -1, false, false
						for _, passageTokens := range passageClauses {
							for j, p := range passageTokens {
								isSame, isOther := anyForm(p, same), anyForm(p, other)
								if isSame == isOther {
									continue
								}
								score := 0
								for w := range window(passageTokens, j, pair) {
									if _, ok := context[w]; ok {
										score++
									}
								}
								if isSame {
									sawSame = true
									if score > bestSame {
										bestSame = score
									}
								} else {
									sawOther = true
									if score > bestOther {
										bestOther = score
									}
								}
							}
						}
						if sawOther && (!sawSame || bestOther > bestSame) {
							return fmt.Sprintf("qualifier guard: the claim says %q where the passage says %s",
								t, strings.Join(other, "/"))
						}
					}
				}
			}
		}
	}
	return ""
}

// ─── scope guard ─────────────────────────────────────────────────────────────

// duringWords open a temporal scope ("tijdens aanvullend geboorteverlof").
var duringWords = map[string]struct{}{
	"during": {}, "throughout": {}, "tijdens": {}, "gedurende": {},
}

// universals widen a scope to every case. "enig(e)" is deliberately absent: in
// Dutch it also means "only".
var universals = map[string]struct{}{
	"any": {}, "all": {}, "every": {}, "each": {},
	"alle": {}, "elk": {}, "elke": {}, "ieder": {}, "iedere": {},
}

// duringScopes lists, for each temporal scope in text, whether it is universal:
// a during-word followed (directly, or after one article) by a universal.
func duringScopes(text string) (universal, specific bool) {
	tokens := tokenize.TokenizeV2(text)
	for i, t := range tokens {
		if _, ok := duringWords[t]; !ok || i+1 >= len(tokens) {
			continue
		}
		next := tokens[i+1]
		if (next == "the" || next == "de" || next == "het") && i+2 < len(tokens) {
			next = tokens[i+2]
		}
		if _, ok := universals[next]; ok {
			universal = true
		} else {
			specific = true
		}
	}
	return universal, specific
}

// scopeGuard refuses the widening rag_go measured as a real false admission
// (L-R23): the passage attaches a fact to a SPECIFIC period ("tijdens
// aanvullend geboorteverlof") and the claim widens it to every period ("during
// any leave"). Fires only on that shape — a during-word followed by a
// universal in the claim, a during-word followed by something specific in the
// passage, and no universal during-scope in the passage. Deliberately narrow:
// "whether any …", "that's all", distributive "each" and other uses of these
// words are not scope widening, and a broad rule refused ~4% of correct claims.
// Dropping a condition WITHOUT a universal ("the allowance applies") is not
// detected here (ADR-0012 is still open).
func scopeGuard(claim, passage string) string {
	claimUniversal, _ := duringScopes(claim)
	if !claimUniversal {
		return ""
	}
	passageUniversal, passageSpecific := duringScopes(passage)
	if passageSpecific && !passageUniversal {
		return "scope guard: the claim widens a specific period in the passage to every period"
	}
	return ""
}
