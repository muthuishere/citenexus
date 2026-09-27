// Bilingual qualifier pairs, bound to a number.
//
// The qualifier guard (verify_guards_model.go) compares bruto/netto,
// werkgever/werknemer, … within ONE language by their neighbouring words.
// Across languages the neighbours cannot be compared, and rag_go's checker
// admits "€150 gross per month" over "€ 150 netto per maand" at P(E) 0.997.
//
// Here a pair is a language-independent class: each side lists its forms in
// every language (bruto/gross ⇄ netto/net). A number anchors the comparison:
// the claim's number binds to the nearest qualifier form within
// qualifierNumberWindow words in its clause; each unit clause holding the same
// number (ADR-0015 key) binds its own the same way. Refused when no such unit
// clause carries the claim's side and at least one carries the other side.
// Without a number nothing is compared (the same-language guard still runs).
//
// Hosts extend or replace the classes with VerifyOptions.QualifierPairs.

package answer

import (
	"fmt"
	"strings"
)

// QualifierPair is two opposite qualifiers, each with its forms in any
// language (lowercase). A form of 5+ letters also matches inside a compound
// ("brutosalaris"); a shorter one only as a whole word ("net").
type QualifierPair struct {
	A, B []string
}

// DefaultQualifierPairs: gross/net, permanent/temporary contract, full/part
// time. "fixed" is deliberately absent: "fixed-term" means temporary.
var DefaultQualifierPairs = []QualifierPair{
	{A: []string{"bruto", "gross"}, B: []string{"netto", "net"}},
	{A: []string{"vast", "vaste", "permanent", "indefinite"}, B: []string{"tijdelijk", "tijdelijke", "temporary"}},
	{A: []string{"voltijd", "voltijds", "fulltime", "full-time"}, B: []string{"deeltijd", "deeltijds", "parttime", "part-time"}},
}

const qualifierNumberWindow = 3

// sideNear: which side of pair (0 = A, 1 = B, -1 none) the nearest qualifier
// form within the window of word i carries, and the form.
func sideNear(words []string, i int, pair QualifierPair) (int, string) {
	for d := 0; d <= qualifierNumberWindow; d++ {
		for _, j := range []int{i - d, i + d} {
			if j < 0 || j >= len(words) {
				continue
			}
			w := words[j]
			a, b := anyForm(w, pair.A), anyForm(w, pair.B)
			switch {
			case a && !b:
				return 0, w
			case b && !a:
				return 1, w
			}
		}
	}
	return -1, ""
}

func lowerWords(clause string) []string {
	words := listLeadToken.FindAllString(clause, -1)
	for i, w := range words {
		words[i] = strings.ToLower(strings.Trim(w, roleTrim))
	}
	return words
}

// numberWordKeys: per word index, the ADR-0015 keys of its numbers.
func numberWordKeys(clause, language string, vb ...verbatimNumbers) map[int][]string {
	out := map[int][]string{}
	for i, w := range listLeadToken.FindAllString(clause, -1) {
		for _, m := range numbersIn(w, language, vb...) {
			out[i] = append(out[i], m.reading.Key)
		}
	}
	return out
}

// qualifierPairGuard: see the file comment.
func qualifierPairGuard(claim, claimLanguage string, eu EvidenceUnit, pairs []QualifierPair) string {
	type unitClause struct {
		words []string
		keys  map[int][]string
	}
	var unit []unitClause
	vb := verbatimIn(eu.Text, eu.Language)
	for _, c := range roleClauses(eu.Text) {
		unit = append(unit, unitClause{lowerWords(c), numberWordKeys(c, eu.Language)})
	}
	for _, c := range roleClauses(claim) {
		words := lowerWords(c)
		for i, keys := range numberWordKeys(c, claimLanguage, vb) {
			for _, pair := range pairs {
				side, form := sideNear(words, i, pair)
				if side < 0 {
					continue
				}
				agrees, other := false, ""
				for _, uc := range unit {
					for j, ukeys := range uc.keys {
						if !sharesKey(keys, ukeys) {
							continue
						}
						// The claim's side anywhere in a clause holding the number
						// agrees ("60 jaar of ouder met een voltijds dienstverband");
						// the other side counts only right at the number.
						if clauseHasSide(uc.words, side, pair) {
							agrees = true
							continue
						}
						if us, uform := sideNear(uc.words, j, pair); us >= 0 && us != side && other == "" {
							other = uform
						}
					}
				}
				if !agrees && other != "" {
					return fmt.Sprintf("qualifier guard: the claim says %q where the passage says %q", form, other)
				}
			}
		}
	}
	return ""
}

func sharesKey(a, b []string) bool {
	for _, x := range a {
		for _, y := range b {
			if x == y {
				return true
			}
		}
	}
	return false
}

func clauseHasSide(words []string, side int, pair QualifierPair) bool {
	forms := pair.A
	if side == 1 {
		forms = pair.B
	}
	for _, w := range words {
		if anyForm(w, forms) {
			return true
		}
	}
	return false
}
