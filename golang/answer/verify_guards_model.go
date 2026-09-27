// Guards for the MODEL path: swaps an NLI model admits with P(entailment)
// ≈ 0.999 that no threshold stops (measured by rag_go on its fine-tuned
// checker, 2026-09-24). Each is deterministic, table-driven, and can only
// refuse. They run inside guards() on every quote and model admission; a gate
// admission is verbatim and never reaches them.

package answer

import (
	"fmt"
	"math/big"
	"regexp"
	"sort"
	"strconv"
	"strings"

	"github.com/muthuishere/citenexus/golang/gate"
	"github.com/muthuishere/citenexus/golang/tokenize"
)

// ─── polarity-swap guard ─────────────────────────────────────────────────────

// polaritySwaps are single-word substitutions that flip a claim's polarity,
// both directions, NL + EN.
var polaritySwaps = map[string][]string{
	"een": {"geen"}, "geen": {"een"},
	"wel": {"niet"}, "niet": {"wel"},
	"altijd": {"nooit"}, "nooit": {"altijd"},
	"always": {"never"}, "never": {"always"},
	"a": {"no"}, "an": {"no"}, "no": {"a", "an"},
	"toegestaan": {"verboden"}, "verboden": {"toegestaan"},
	"allowed": {"forbidden", "prohibited"}, "forbidden": {"allowed"}, "prohibited": {"allowed"},
	"permitted": {"prohibited"}, "verplicht": {"optioneel"}, "optioneel": {"verplicht"},
	"required": {"optional"}, "optional": {"required"},
}

// polaritySwapGuard refuses a claim that is the passage with ONE polarity word
// swapped: "Er bestaat een recht op thuiswerken" over "Er bestaat geen recht op
// thuiswerken", "worden wel opgebouwd" over "worden niet opgebouwd". rag_go's
// checker admits both at its recommended τ (P(E) 0.197 / 0.21 against τ 0.154).
//
// Test: the claim does not align with the passage (the gate's ordered,
// gap-bounded alignment), but after swapping one word for its polar
// counterpart it does. A claim that aligns as written is never refused here — so
// "niet alleen … maar ook", double negation and every verbatim claim pass.
// Near-verbatim wording is required, which makes the guard same-language by
// construction; a translated claim is left to the checker and the other guards.
func polaritySwapGuard(claim, passage string) string {
	claimTokens := tokenize.TokenizeV2(claim)
	// The whole passage, not clause by clause: a claim may span a comma ("…
	// opgebouwd, wel naar rato …"), and the gate's gap budget already keeps the
	// alignment local.
	passageTokens := tokenize.TokenizeV2(passage)
	aligns := func(tokens []string) bool {
		_, ok := gate.Align(tokens, passageTokens)
		return ok
	}
	if len(claimTokens) == 0 || aligns(claimTokens) {
		return ""
	}
	for i, t := range claimTokens {
		for _, swap := range polaritySwaps[t] {
			variant := append(append(append([]string{}, claimTokens[:i]...), swap), claimTokens[i+1:]...)
			if aligns(variant) {
				return fmt.Sprintf("negation guard: the claim says %q where the passage says %q", t, swap)
			}
		}
	}
	return ""
}

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
	// Adjective forms after a number: "25-jarig", "32-urige", "5-daagse".
	"jarig": "year", "jarige": "year", "urig": "hour", "urige": "hour", "daags": "day", "daagse": "day",
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

// unitSuffixes read a time unit inside a Dutch compound ("vakantiedagen",
// "levensjaar"), longest first. Only for tokens of 6+ letters, and never a
// weekday: "maandag" ends in "dag" but is not a quantity of days.
var unitSuffixes = []struct{ suffix, class string }{
	{"werkdagen", "workday"}, {"werkdag", "workday"},
	{"maanden", "month"}, {"dagen", "day"}, {"weken", "week"}, {"jaren", "year"},
	{"maand", "month"}, {"jaar", "year"}, {"uren", "hour"}, {"dag", "day"}, {"uur", "hour"},
}

var weekdays = map[string]struct{}{
	"maandag": {}, "dinsdag": {}, "woensdag": {}, "donderdag": {}, "vrijdag": {}, "zaterdag": {}, "zondag": {},
}

// unitOf is a token's time-unit class: a unit word, or a Dutch compound ending
// in one. compound is true for the latter.
func unitOf(token string) (class string, compound bool, ok bool) {
	if c, found := timeUnits[token]; found {
		return c, false, true
	}
	if len([]rune(token)) < 6 {
		return "", false, false
	}
	if _, isWeekday := weekdays[token]; isWeekday {
		return "", false, false
	}
	for _, u := range unitSuffixes {
		if strings.HasSuffix(token, u.suffix) && token != u.suffix {
			return u.class, true, true
		}
	}
	return "", false, false
}

// quantityLinks may sit between a number and its unit when several numbers
// share one ("2 respectievelijk 3 werkdagen", "1 of 2 dagen").
var quantityLinks = map[string]struct{}{
	"respectievelijk": {}, "resp": {}, "en": {}, "of": {}, "tot": {}, "à": {},
	"and": {}, "or": {}, "to": {},
}

func numberValue(token, language string, vb ...verbatimNumbers) (string, bool) {
	switch {
	case token == "½":
		return "0.5", true
	case token[0] >= '0' && token[0] <= '9':
		return readWith(token, false, language, vb).Key, true
	default:
		return numberWordValue(token)
	}
}

// quantities are the (value key, unit class) pairs in text: a number — digits
// read by ADR-0015 key, or a number word — followed by a time unit, looking
// past a parenthesised restatement ("twee (2) maanden") and past other numbers
// and links that share the unit ("2 respectievelijk 3 werkdagen"). The unit may
// sit in a compound ("dertig (30) vakantiedagen"). Also read: "half jaar" /
// "halfjaar" / "half (a) year" as 6 months, and an ordinal before a year
// compound ("eerste levensjaar") as 1 year.
func quantities(text, language string, vb ...verbatimNumbers) map[[2]string]struct{} {
	_, text = clockTimes(text)                  // "7.30 uur" is a time of day, not 7.3 hours
	_, text = moneyRates(text, language, vb...) // "€ 150 per maand" is a price, not 150 months
	tokens := unitScan.FindAllString(strings.ToLower(text), -1)
	out := map[[2]string]struct{}{}
	for i := 0; i < len(tokens); i++ {
		t := tokens[i]
		if t == "halfjaar" {
			out[[2]string{"6", "month"}] = struct{}{}
			continue
		}
		if t == "half" {
			j := i + 1
			if j < len(tokens) && tokens[j] == "a" {
				j++
			}
			if j < len(tokens) && (tokens[j] == "jaar" || tokens[j] == "year") {
				out[[2]string{"6", "month"}] = struct{}{}
			}
			continue
		}
		if ord, isOrdinal := ordinalWords[t]; isOrdinal && i+1 < len(tokens) {
			if class, compound, ok := unitOf(tokens[i+1]); ok && compound && class == "year" {
				out[[2]string{ord, "year"}] = struct{}{}
			}
			continue
		}
		value, isNumber := numberValue(t, language, vb...)
		if !isNumber {
			continue
		}
		// Look past a restatement of the SAME value ("twee (2) maanden") and
		// past "link number" pairs sharing the unit ("2 respectievelijk 3
		// werkdagen"). A bare second number stops the scan: in a table row
		// "12,5 ✓ 1 dag" the 1 belongs to "dag", the 12,5 does not.
		j := i + 1
		if j < len(tokens) {
			if v, n := numberValue(tokens[j], language, vb...); n && v == value {
				j++
			}
		}
		for j+1 < len(tokens) && j-i <= 6 {
			if _, link := quantityLinks[tokens[j]]; !link {
				break
			}
			// "minimaal één en maximaal drie maanden": a bound word may sit
			// between the link and the next number.
			skip := 0
			if _, bound := rangeBoundWords[tokens[j+1]]; bound && j+2 < len(tokens) {
				skip = 1
			}
			if _, n := numberValue(tokens[j+1+skip], language, vb...); !n {
				break
			}
			linked, _ := numberValue(tokens[j+1+skip], language, vb...)
			j += 2 + skip
			if j < len(tokens) {
				if v, n := numberValue(tokens[j], language, vb...); n && v == linked {
					j++ // "drie (3)" after the link
				}
			}
		}
		if j >= len(tokens) {
			continue
		}
		class, _, ok := unitOf(tokens[j])
		if mod, isMod := unitModifiers[tokens[j]]; isMod && j+1 < len(tokens) {
			if c, _, _ := unitOf(tokens[j+1]); c == "day" {
				class, ok = mod, true
			}
		}
		// English puts one modifier between the number and a plain unit word
		// ("30 vacation days", "1 extra day"). Only a unit WORD may follow it,
		// never a compound, and only one modifier: "2 employees per day" is not a
		// quantity of days.
		if !ok && j+1 < len(tokens) {
			if _, n := numberValue(tokens[j], language, vb...); !n {
				if c, found := timeUnits[tokens[j+1]]; found {
					class, ok = c, true
					// "een halve maand" is half a month, not one month.
					if tokens[j] == "half" || tokens[j] == "halve" {
						if v, parsed := new(big.Rat).SetString(value); parsed {
							value = ratKey(v.Mul(v, big.NewRat(1, 2)))
						}
					}
				}
			}
		}
		if ok {
			out[[2]string{value, class}] = struct{}{}
		}
	}
	return out
}

// equivalentQuantity is the same period in the other unit, when exact: v years
// <-> 12v months. "een half jaar" (6 months) then matches "0.5 year" and a
// claim of "1 year" matches "12 maanden".
func equivalentQuantity(q [2]string) ([2]string, bool) {
	v, ok := new(big.Rat).SetString(q[0])
	if !ok {
		return q, false
	}
	switch q[1] {
	case "year":
		return [2]string{ratKey(new(big.Rat).Mul(v, big.NewRat(12, 1))), "month"}, true
	case "month":
		r := new(big.Rat).Quo(v, big.NewRat(12, 1))
		return [2]string{ratKey(r), "year"}, true
	}
	return q, false
}

func ratKey(r *big.Rat) string {
	if r.IsInt() {
		return r.Num().String()
	}
	s := r.FloatString(6)
	return strings.TrimRight(strings.TrimRight(s, "0"), ".")
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
	_, claim = clockTimes(claim) // a clock time is never a duration
	_, passage = clockTimes(passage)
	// A rate conflicts only with the SAME amount at another period: "€ 150 per
	// jaar" over "€ 150 per maand". Another amount's period decides nothing.
	// A number the claim copies from the passage keeps the passage's reading
	// (ADR-0015 amendment).
	vb := verbatimIn(passage, passageLanguage)
	claimRates, _ := moneyRates(claim, claimLanguage, vb)
	passageRates, _ := moneyRates(passage, passageLanguage)
	for _, r := range sortedPairs(claimRates) {
		if _, ok := passageRates[r]; ok {
			continue
		}
		for _, p := range sortedPairs(passageRates) {
			if p[0] == r[0] && p[1] != r[1] && !samePeriodFamily(p[1], r[1]) {
				return fmt.Sprintf("unit guard: %s per %s where the passage says %s per %s", r[0], r[1], p[0], p[1])
			}
		}
	}
	have := quantities(passage, passageLanguage)
	claimed := make([][2]string, 0)
	for q := range quantities(claim, claimLanguage, vb) {
		claimed = append(claimed, q)
	}
	// Sorted by (value, unit), so the reason names the same quantity on every run.
	sort.Slice(claimed, func(i, j int) bool {
		if claimed[i][0] != claimed[j][0] {
			return claimed[i][0] < claimed[j][0]
		}
		return claimed[i][1] < claimed[j][1]
	})
	for _, q := range claimed {
		if _, ok := have[q]; ok {
			continue
		}
		if sameQuantityIn(q, have) {
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
	{{nl: []string{"vóór", "voordat"}, en: []string{"before"}}, {nl: []string{"na", "ná", "nadat"}, en: []string{"after"}}},
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
	for _, clause := range clauseBreak.Split(softJoin(text), -1) {
		if tokens := tokenize.TokenizeV2(clause); len(tokens) > 0 {
			out = append(out, tokens)
		}
	}
	return out
}

// softLineBreak is a line break that does not end a sentence — a PDF wrap. It
// is joined so a pair word keeps the context it had before the wrap.
var softLineBreak = regexp.MustCompile(`([^.!?:;\n])[ \t]*\n[ \t]*([^\n\-*•·0-9])`)

func softJoin(text string) string { return softLineBreak.ReplaceAllString(text, "$1 $2") }

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
						// The claim names both sides itself ("werknemer en werkgever",
						// "voor/na"): it is not asserting one against the other.
						if namesBoth(claimTokens, i, other) {
							continue
						}
						// before/after and earlier/later are relational: swapped only when
						// the other side governs the SAME next word.
						if pair[0].en[0] == "before" || pair[0].en[0] == "earlier" {
							if relationalSwap(claimTokens, i, passageClauses, same, other) {
								return fmt.Sprintf("qualifier guard: the claim says %q where the passage says %s",
									t, strings.Join(other, "/"))
							}
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

// namesBoth is true when a form of the other side sits within the qualifier
// window of the claim's own occurrence.
func namesBoth(tokens []string, i int, other []string) bool {
	for k := i - qualifierWindow; k <= i+qualifierWindow; k++ {
		if k >= 0 && k < len(tokens) && k != i && anyForm(tokens[k], other) {
			return true
		}
	}
	return false
}

// nextContent is the first content token after index i, or "".
func nextContent(tokens []string, i int) string {
	for k := i + 1; k < len(tokens); k++ {
		if gate.IsStopword(tokens[k]) {
			continue
		}
		if _, stop := contextStop[tokens[k]]; stop {
			continue
		}
		return tokens[k]
	}
	return ""
}

// relationalSwap: the passage puts the OTHER side before the word that follows
// the claim's side ("na de proeftijd" vs a claim "voor de proeftijd"), and
// never the claim's own side before it. Nearby words alone decide nothing for
// a relation.
func relationalSwap(claimTokens []string, i int, passageClauses [][]string, same, other []string) bool {
	target := nextContent(claimTokens, i)
	if target == "" {
		return false
	}
	sawOther := false
	for _, tokens := range passageClauses {
		for j, p := range tokens {
			if nextContent(tokens, j) != target {
				continue
			}
			if anyForm(p, same) {
				return false
			}
			if anyForm(p, other) {
				sawOther = true
			}
		}
	}
	return sawOther
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

func sortedPairs(set map[[2]string]struct{}) [][2]string {
	out := make([][2]string, 0, len(set))
	for p := range set {
		out = append(out, p)
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i][0] != out[j][0] {
			return out[i][0] < out[j][0]
		}
		return out[i][1] < out[j][1]
	})
	return out
}

// sameQuantityIn: q, or the same period in another unit, is in have — years
// as months, and a whole number of years as 52-week years ("het eerste
// ziektejaar" = "de eerste 52 weken"), both directions.
func sameQuantityIn(q [2]string, have map[[2]string]struct{}) bool {
	if _, ok := have[q]; ok {
		return true
	}
	if eq, ok := equivalentQuantity(q); ok {
		if _, found := have[eq]; found {
			return true
		}
	}
	v, ok := new(big.Rat).SetString(q[0])
	if !ok {
		return false
	}
	switch q[1] {
	case "year":
		_, found := have[[2]string{ratKey(new(big.Rat).Mul(v, big.NewRat(52, 1))), "week"}]
		return found
	case "week":
		_, found := have[[2]string{ratKey(new(big.Rat).Quo(v, big.NewRat(52, 1))), "year"}]
		return found && new(big.Rat).Quo(v, big.NewRat(52, 1)).IsInt()
	}
	return false
}

// samePeriodFamily: day and workday are not told apart for a rate — "per
// thuiswerkdag" ends in "werkdag" but is a (home-working) day.
func samePeriodFamily(a, b string) bool {
	return (a == "day" || a == "workday") && (b == "day" || b == "workday")
}

// Dutch writes numbers as one word: "vijfentwintig" (25), "tweeëntwintig"
// (22), "honderdvijfentwintig" (125), "tweeduizend" (2000). numberWordValue
// reads the numberWords table first, then parses such compounds — a grammar,
// not a table: [units]en[tens] below 100, then honderd and duizend.
var (
	dutchUnits = map[string]int{"een": 1, "één": 1, "twee": 2, "drie": 3, "vier": 4, "vijf": 5, "zes": 6, "zeven": 7, "acht": 8, "negen": 9}
	dutchTeens = map[string]int{"tien": 10, "elf": 11, "twaalf": 12, "dertien": 13, "veertien": 14, "vijftien": 15,
		"zestien": 16, "zeventien": 17, "achttien": 18, "negentien": 19}
	dutchTens = map[string]int{"twintig": 20, "dertig": 30, "veertig": 40, "vijftig": 50, "zestig": 60,
		"zeventig": 70, "tachtig": 80, "negentig": 90}
)

func numberWordValue(word string) (string, bool) {
	if v, ok := numberWords[word]; ok {
		return v, true
	}
	if n, ok := parseDutchNumber(word); ok && n > 0 {
		return strconv.Itoa(n), true
	}
	return "", false
}

func parseDutchNumber(w string) (int, bool) {
	if w == "" {
		return 0, false
	}
	if head, tail, ok := strings.Cut(w, "duizend"); ok {
		mult := 1
		if head != "" {
			m, ok := parseDutchNumber(head)
			if !ok {
				return 0, false
			}
			mult = m
		}
		rest := 0
		if tail != "" {
			r, ok := parseDutchNumber(tail)
			if !ok {
				return 0, false
			}
			rest = r
		}
		return mult*1000 + rest, true
	}
	if head, tail, ok := strings.Cut(w, "honderd"); ok {
		mult := 1
		if head != "" {
			m, ok := dutchUnits[head]
			if !ok {
				return 0, false
			}
			mult = m
		}
		rest := 0
		if tail != "" {
			r, ok := parseDutchNumber(tail)
			if !ok || r >= 100 {
				return 0, false
			}
			rest = r
		}
		return mult*100 + rest, true
	}
	if v, ok := dutchUnits[w]; ok {
		return v, true
	}
	if v, ok := dutchTeens[w]; ok {
		return v, true
	}
	if v, ok := dutchTens[w]; ok {
		return v, true
	}
	for _, link := range []string{"ën", "en"} {
		for tens, tv := range dutchTens {
			if unit, ok := strings.CutSuffix(w, link+tens); ok {
				if uv, ok := dutchUnits[unit]; ok {
					return uv + tv, true
				}
			}
		}
	}
	return 0, false
}

// rangeBoundWords may precede the second number of a range.
var rangeBoundWords = map[string]struct{}{"maximaal": {}, "minimaal": {}, "hooguit": {}, "maximum": {}, "minimum": {}, "most": {}, "least": {}}
