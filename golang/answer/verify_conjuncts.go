// The conjunct-token guard: a claim that drops a conjunct of the unit's
// condition which holds a LANGUAGE-FREE token — a number or a proper name.
//
// "Een zager krijgt een ploegentoeslag, mits hij in de nachtploeg werkt en
// ten minste 3 jaar in dienst is" under "A sawyer gets a shift allowance if he
// works in the night shift": the condition guard judges a word missing across
// languages only through the caller's glossary, and a glossary lists some
// translations, not every rendering, so it cannot say "3 jaar in dienst" was
// dropped. The number can: "3" reads the same in both languages. A name does
// too ("instructeur Verhoef", "Stichting Bijenlint").
//
// Two separate questions:
//
//   - WHICH SENTENCE the claim follows: one holding a number or name the claim
//     carries that no other unit sentence holds (language-free); otherwise the
//     sentence sharing the most content words with the claim (directly, or
//     through the glossary across languages), at least two, with no tie.
//   - WHETHER A CONJUNCT IS MISSING: the sentence's condition (after mits,
//     indien, tenzij, zolang, op voorwaarde dat, alleen als, provided, unless,
//     only if, as long as) split into conjuncts at en/and/list commas; a
//     conjunct with numbers or names the claim does not carry in any form
//     (digits, or the number spelled out) — none of its tokens — is missing. Only language-free
//     tokens decide — a conjunct without one gives no verdict, whatever the
//     glossary knows.
//
// A compressed claim that keeps every conjunct ("a sawyer with at least 3
// years of service who works nights") carries the token and is not refused.
// Can only refuse.

package answer

import (
	"fmt"
	"regexp"
	"strings"
	"unicode"

	"github.com/muthuishere/citenexus/golang/tokenize"
)

var conjunctOpener = regexp.MustCompile(`(?i)\b(mits|indien|tenzij|zolang|op voorwaarde dat|alleen als|provided that|provided|unless|only if|as long as)\b`)

var conjunctSplit = regexp.MustCompile(`(?i),|\b(?:en|and)\b`)

var conjunctCoordinator = regexp.MustCompile(`(?i)\b(?:en|and)\b`)

var totEnMetWords = regexp.MustCompile(`(?i)\btot en met\b|\bup to and including\b`)

// languageFree: the number keys (ADR-0015, read in the text's language) and
// the proper names (a capitalised word not opening the text) of a text.
func languageFree(text, language string) map[string]bool {
	out := map[string]bool{}
	for _, m := range numbersIn(text, language) {
		out["#"+m.reading.Key] = true
	}
	words := strings.Fields(text)
	for i, w := range words {
		w = strings.Trim(w, ".,;:()\"'!?")
		r := []rune(w)
		if i == 0 || len(r) < 3 || !unicode.IsUpper(r[0]) {
			continue
		}
		if prev := words[i-1]; strings.HasSuffix(prev, ".") || strings.HasSuffix(prev, ":") {
			continue // a sentence start inside the text
		}
		out["@"+strings.ToLower(w)] = true
	}
	return out
}

// claimCarriesToken: the claim holds the token — the same number key, the
// number spelled out ("three" for 3), or the same name.
func claimCarriesToken(tok string, claimFree map[string]bool, claimTokens []string) bool {
	if claimFree[tok] {
		return true
	}
	if strings.HasPrefix(tok, "@") {
		name := tok[1:]
		for _, t := range claimTokens {
			if t == name {
				return true
			}
		}
		return false
	}
	for _, t := range claimTokens {
		if v, ok := numberWordValue(t); ok && "#"+v == tok {
			return true
		}
	}
	return false
}

// conditionConjuncts: the conjuncts of a sentence's condition, each with its
// language-free tokens; nil when the sentence has none, or only one.
func conditionConjuncts(sentence, language string) []map[string]bool {
	loc := conjunctOpener.FindStringIndex(sentence)
	if loc == nil {
		return nil
	}
	span := totEnMetWords.ReplaceAllString(sentence[loc[1]:], "tot_en_met")
	// Final comma segments without a coordinator are the main clause or
	// trailing material, not conjuncts; "mits A, B en C, krijgt X" keeps
	// "A, B en C".
	segs := strings.Split(span, ",")
	for len(segs) > 1 && !conjunctCoordinator.MatchString(segs[len(segs)-1]) {
		segs = segs[:len(segs)-1]
	}
	var out []map[string]bool
	parts := 0
	for _, p := range conjunctSplit.Split(strings.Join(segs, ","), -1) {
		if strings.TrimSpace(p) == "" {
			continue
		}
		parts++
		out = append(out, languageFree(p, language))
	}
	if parts < 2 {
		return nil
	}
	return out
}

// conjunctTokenGuard: see the file comment.
func conjunctTokenGuard(claim, claimLanguage string, eu EvidenceUnit, cfg guardConfig) string {
	if cfg.fragment {
		return ""
	}
	sentences := sentenceBreak.Split(softJoin(eu.Text), -1)
	claimTokens := tokenize.TokenizeV2(claim)
	claimFree := languageFree(claim, claimLanguage)

	// Which sentence the claim follows. Language-free first.
	best := -1
	for i, s := range sentences {
		sFree := languageFree(s, eu.Language)
		for tok := range claimFree {
			if !sFree[tok] {
				continue
			}
			unique := true
			for j, o := range sentences {
				if j != i && languageFree(o, eu.Language)[tok] {
					unique = false
					break
				}
			}
			if unique {
				if best >= 0 && best != i {
					return "" // anchored to two sentences: no verdict
				}
				best = i
			}
		}
	}
	if best < 0 {
		// Shared content words (through the glossary across languages).
		cross := claimLanguage != "" && eu.Language != "" && primaryLanguage(claimLanguage) != primaryLanguage(eu.Language)
		c := carrier{claim: map[string]bool{}, crossLang: cross, translations: cfg.gloss.idx()}
		for _, t := range claimTokens {
			c.claim[t] = true
		}
		bestN, tie := 0, false
		for i, s := range sentences {
			n := 0
			seen := map[string]bool{}
			for _, t := range tokenize.TokenizeV2(s) {
				if has, _ := c.carried(t); has && conditionContent(t) && !seen[t] {
					seen[t] = true
					n++
				}
			}
			switch {
			case n > bestN:
				best, bestN, tie = i, n, false
			case n == bestN && n > 0:
				tie = true
			}
		}
		if bestN < 2 || tie {
			return ""
		}
	}
	for _, conj := range conditionConjuncts(sentences[best], eu.Language) {
		if len(conj) == 0 {
			continue // no language-free token: no verdict on this conjunct
		}
		missing := ""
		for tok := range conj {
			if claimCarriesToken(tok, claimFree, claimTokens) {
				missing = ""
				break
			}
			if missing == "" || tok < missing {
				missing = tok
			}
		}
		if missing != "" {
			return fmt.Sprintf("condition guard: the passage's condition includes %q and the claim drops that part", strings.TrimLeft(missing, "#@"))
		}
	}
	return ""
}
