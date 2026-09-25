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
	"sync"
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
	plain := map[string]bool{} // forms that are also a verb on their own
	for _, e := range entries {
		pairs = append(pairs, [2]string{e.NL, e.EN})
		if e.Sep != "" {
			sep[e.NL] = e.Sep
		} else {
			plain[e.NL] = true
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
	// "stuurt" is sturen as well as the split form of opsturen: a form that
	// is also a plain verb needs no particle.
	for form := range plain {
		delete(sep, form)
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

// PreparedGlossary is a glossary indexed once: built by PrepareGlossary,
// immutable, safe for concurrent use. Pass it in VerifyOptions.Glossary-
// Prepared; expanding a 100k-row glossary on every VerifyAnswer call cost
// the consumer 81 ms and 49 MB per call.
type PreparedGlossary struct {
	index   map[string][][]string // a single-token term -> its translations
	sepOf   map[string]string     // a split separable form -> its particle
	classOf map[string]string     // an NL form or lemma -> its class
	sepKeys map[string][]sepKey   // particle -> joined separable forms under it
}

type sepKey struct {
	rest string // the key after the particle: "sluiten" in "afsluiten"
	trs  [][]string
}

// PrepareGlossary indexes term pairs and glossary entries once.
func PrepareGlossary(pairs [][2]string, entries []GlossaryEntry) *PreparedGlossary {
	entryPairs, sep, class := expandGlossary(entries)
	all := append(append([][2]string{}, pairs...), entryPairs...)
	g := &PreparedGlossary{index: glossaryIndex(all), sepOf: sep, classOf: class, sepKeys: map[string][]sepKey{}}
	for key, trs := range g.index {
		for p := range separableParticles {
			if strings.HasPrefix(key, p) && len(key) > len(p)+2 {
				g.sepKeys[p] = append(g.sepKeys[p], sepKey{rest: key[len(p):], trs: trs})
			}
		}
	}
	return g
}

func (g *PreparedGlossary) empty() bool { return g == nil || len(g.index) == 0 }

// Nil-safe readers: a nil *PreparedGlossary is the empty glossary.
func (g *PreparedGlossary) idx() map[string][][]string {
	if g == nil {
		return nil
	}
	return g.index
}
func (g *PreparedGlossary) sep() map[string]string {
	if g == nil {
		return nil
	}
	return g.sepOf
}
func (g *PreparedGlossary) class() map[string]string {
	if g == nil {
		return nil
	}
	return g.classOf
}
func (g *PreparedGlossary) seps() map[string][]sepKey {
	if g == nil {
		return nil
	}
	return g.sepKeys
}

var (
	preparedMu    sync.Mutex
	preparedCache = map[preparedKey]*PreparedGlossary{}
)

type preparedKey struct {
	pairs   *[2]string
	nPairs  int
	entries *GlossaryEntry
	nEntr   int
}

// preparedFor returns opts' prepared glossary: GlossaryPrepared when given,
// else the Glossary and GlossaryEntries slices prepared once and cached by
// their identity (backing array and length), so a host that passes the same
// slices on every call pays for the index once.
func preparedFor(opts VerifyOptions) *PreparedGlossary {
	if opts.GlossaryPrepared != nil {
		return opts.GlossaryPrepared
	}
	if len(opts.Glossary) == 0 && len(opts.GlossaryEntries) == 0 {
		return &PreparedGlossary{}
	}
	key := preparedKey{nPairs: len(opts.Glossary), nEntr: len(opts.GlossaryEntries)}
	if len(opts.Glossary) > 0 {
		key.pairs = &opts.Glossary[0]
	}
	if len(opts.GlossaryEntries) > 0 {
		key.entries = &opts.GlossaryEntries[0]
	}
	preparedMu.Lock()
	defer preparedMu.Unlock()
	if g, ok := preparedCache[key]; ok {
		return g
	}
	if len(preparedCache) >= 16 {
		preparedCache = map[preparedKey]*PreparedGlossary{}
	}
	g := PrepareGlossary(opts.Glossary, opts.GlossaryEntries)
	preparedCache[key] = g
	return g
}
