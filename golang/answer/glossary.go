// Glossary entries with lemmas, separable particles and classes.
//
// VerifyOptions.Glossary is a list of term pairs. A pair matches only the
// surface forms it names, so "werkt" over a claim's "work" was no match, and a
// party noun could not be told from any other noun. GlossaryEntry adds what a
// matcher needs to read a form through its lemma:
//
//   - LemmaNL / LemmaEN: every NL form of a lemma translates to every EN form
//     of it (and to the EN lemma) — an inflection matches through its lemma;
//   - Sep: the particle of a Dutch separable verb; a split finite form ("sluit",
//     "keert") matches as that verb only with its particle later in the clause;
//   - Class: party | group | verb | hedge | qualifier. The reader's pronoun is
//     compared with a third party only when that party's class says it is one.
//
// ParseGlossaryTSV reads such a file by its header (nl, en, lemma_nl,
// lemma_en, sep, class); unknown columns are ignored and a file with only nl
// and en loads as plain pairs.

package answer

import (
	"bufio"
	"fmt"
	"io"
	"strings"
)

// GlossaryEntry is one NL/EN surface pair with its lemmas, particle and class.
type GlossaryEntry struct {
	NL, EN           string
	LemmaNL, LemmaEN string
	Sep              string
	Class            string
}

// ParseGlossaryTSV reads a tab-separated glossary with a header row.
func ParseGlossaryTSV(r io.Reader) ([]GlossaryEntry, error) {
	sc := bufio.NewScanner(r)
	sc.Buffer(make([]byte, 1<<20), 1<<24)
	var col map[string]int
	var out []GlossaryEntry
	for sc.Scan() {
		f := strings.Split(sc.Text(), "\t")
		if col == nil {
			col = map[string]int{}
			for i, h := range f {
				col[strings.ToLower(strings.TrimSpace(h))] = i
			}
			if _, ok := col["nl"]; !ok {
				return nil, fmt.Errorf("answer: glossary header has no nl column")
			}
			if _, ok := col["en"]; !ok {
				return nil, fmt.Errorf("answer: glossary header has no en column")
			}
			continue
		}
		get := func(name string) string {
			if i, ok := col[name]; ok && i < len(f) {
				return strings.ToLower(strings.TrimSpace(f[i]))
			}
			return ""
		}
		e := GlossaryEntry{NL: get("nl"), EN: get("en"), LemmaNL: get("lemma_nl"), LemmaEN: get("lemma_en"), Sep: get("sep"), Class: get("class")}
		if e.NL != "" && e.EN != "" {
			out = append(out, e)
		}
	}
	return out, sc.Err()
}

// expandGlossary turns entries into term pairs — each NL form paired with
// every EN form and EN lemma of its lemma — and returns the particle and
// class of each NL form.
func expandGlossary(entries []GlossaryEntry) (pairs [][2]string, sep, class map[string]string) {
	sep, class = map[string]string{}, map[string]string{}
	nlForms, enForms := map[string][]string{}, map[string][]string{}
	for _, e := range entries {
		pairs = append(pairs, [2]string{e.NL, e.EN})
		if e.Sep != "" {
			sep[e.NL] = e.Sep
		}
		if e.Class != "" {
			class[e.NL] = e.Class
		}
		if e.LemmaNL == "" {
			continue
		}
		nlForms[e.LemmaNL] = appendUnique(nlForms[e.LemmaNL], e.NL, e.LemmaNL)
		enForms[e.LemmaNL] = appendUnique(enForms[e.LemmaNL], e.EN)
		if e.LemmaEN != "" {
			enForms[e.LemmaNL] = appendUnique(enForms[e.LemmaNL], e.LemmaEN)
		}
		if e.Class != "" {
			class[e.LemmaNL] = e.Class
		}
	}
	for lemma, nls := range nlForms {
		for _, n := range nls {
			for _, en := range enForms[lemma] {
				pairs = append(pairs, [2]string{n, en})
			}
		}
	}
	return pairs, sep, class
}
