// ADR-0011 — the Unicode tokenizer, v2.
//
// v1 (Tokenize, above) is the frozen SPEC-PORTS-v1 §4 tokenizer: lowercase then
// [a-z0-9]+. That is ASCII only, which turned out to be a false capability claim
// rather than a limitation — Japanese, Chinese, Arabic and Tamil each produced
// ZERO tokens, so the faithfulness gate rejected a verbatim quote of its own
// source and BM25 scored nothing. v2 fixes that without touching v1: v1 stays
// exported and byte-identical, because the shipped conformance vectors and every
// index already built pin it.
//
// v2 is a strict superset of v1 on pure-ASCII input, which is why moving BM25
// and the gate onto it left every existing vector unchanged.
//
// PLACEMENT — ADR-0011 §3: this is tier 3 for AUTHORSHIP (the Rust core is
// authoritative and generates the conformance vectors) but tier 1 for DELIVERY.
// Go keeps a NATIVE implementation that those vectors pin; the tokenizer is the
// hottest path there is, and ADR-0010 forbids handing it a mandatory native/FFI
// dependency (see golang/ingest/ingest.go:1).
//
// NO REGEX. This is a character scan over Unicode category and script tables,
// because Python re has no \p{L}, and Go RE2 and JS RegExp disagree on Unicode
// property escapes in ways no practical fixture set would catch.
//
// The one genuine port divergence is CASE FOLDING. Python uses str.casefold
// (full case folding: ß → ss); Go's strings.ToLower is simple 1:1 mapping and
// leaves ß alone. golang.org/x/text/cases.Fold is full case folding and is PURE
// GO — no cgo, no native dependency — so using it satisfies the tier-1 delivery
// rule. Same for golang.org/x/text/unicode/norm.NFKC.
package tokenize

import (
	_ "embed"
	"encoding/json"
	"sort"
	"sync"
	"unicode"

	"golang.org/x/text/cases"
	"golang.org/x/text/unicode/norm"
)

// TokenizerVersion is stamped on an index so a tokenizer/index mismatch is
// detectable rather than silent (ADR-0011). Bump it whenever TokenizeV2's output
// changes for any input.
const TokenizerVersion = 2

// scripts.json is ADR-0010 tier 2: shared data, per-port code. It is a copy of
// the supported_scripts / continuous_scripts claim in
// conformance/cases/tokenize_v2.json, EMBEDDED so this module is self-contained
// when consumed as a Go dependency (a filesystem read of the shared
// conformance/ dir would not exist in the module cache).
// TestScriptTableMatchesConformance pins the copy to the canonical file.
//
//go:embed scripts.json
var scriptsJSON []byte

var (
	scriptsOnce       sync.Once
	supportedScripts  map[string]struct{}
	continuousScripts map[string]struct{}
)

func loadScriptTable() {
	scriptsOnce.Do(func() {
		var table struct {
			Supported  []string `json:"supported_scripts"`
			Continuous []string `json:"continuous_scripts"`
		}
		if err := json.Unmarshal(scriptsJSON, &table); err != nil {
			panic("tokenize: unmarshal scripts.json: " + err.Error())
		}
		supportedScripts = make(map[string]struct{}, len(table.Supported))
		for _, s := range table.Supported {
			supportedScripts[s] = struct{}{}
		}
		continuousScripts = make(map[string]struct{}, len(table.Continuous))
		for _, s := range table.Continuous {
			continuousScripts[s] = struct{}{}
		}
	})
}

// SupportedScripts is the set of scripts CiteNexus CLAIMS. ADR-0011: a script
// enters this set only when a golden fixture proves it end-to-end. Everything
// else is reported by UnsupportedScripts so the caller gets a capability signal
// instead of the evidence-absent refusal.
func SupportedScripts() []string {
	loadScriptTable()
	return sortedKeys(supportedScripts)
}

// ContinuousScripts is the set of scripts written without spaces between words.
// These are character-bigram indexed; everything else is delimited by whitespace
// and punctuation. Korean is NOT here — Hangul writes spaces.
func ContinuousScripts() []string {
	loadScriptTable()
	return sortedKeys(continuousScripts)
}

func sortedKeys(m map[string]struct{}) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

// scriptRange is one (first, last, name) row of the script table. Python's
// stdlib has no Script property either, so the ranges are carried explicitly in
// both ports; the behavioral conformance vectors are what pin them. The table is
// deliberately partial: it covers the scripts CiteNexus makes a claim about plus
// the near neighbours it must be able to NAME when refusing.
//
// MUST stay sorted by first — binarySearch depends on it, and a mis-sorted table
// would silently mis-classify (TestScriptRangesAreSorted).
type scriptRange struct {
	first, last rune
	name        string
}

var scriptRanges = [...]scriptRange{
	{0x0041, 0x005A, "latin"},
	{0x0061, 0x007A, "latin"},
	{0x00AA, 0x00AA, "latin"},
	{0x00BA, 0x00BA, "latin"},
	{0x00C0, 0x02AF, "latin"},
	{0x0300, 0x036F, "common"}, // combining diacriticals — inherit their base
	{0x0370, 0x03FF, "greek"},
	{0x0400, 0x052F, "cyrillic"},
	{0x0531, 0x058F, "armenian"},
	{0x0591, 0x05F4, "hebrew"},
	{0x0600, 0x06FF, "arabic"},
	{0x0750, 0x077F, "arabic"},
	{0x0870, 0x08FF, "arabic"},
	{0x0900, 0x097F, "devanagari"},
	{0x0980, 0x09FF, "bengali"},
	{0x0B80, 0x0BFF, "tamil"},
	{0x0E00, 0x0E7F, "thai"},
	{0x0E80, 0x0EFF, "lao"},
	{0x1000, 0x109F, "myanmar"},
	{0x10A0, 0x10FF, "georgian"},
	{0x1100, 0x11FF, "hangul"},
	{0x1780, 0x17FF, "khmer"},
	{0x1E00, 0x1EFF, "latin"},
	{0x1F00, 0x1FFF, "greek"},
	{0x2C60, 0x2C7F, "latin"},
	{0x2DE0, 0x2DFF, "cyrillic"},
	{0x2E80, 0x2EFF, "han"},
	{0x3005, 0x3007, "han"},
	{0x3040, 0x309F, "hiragana"},
	{0x30A0, 0x30FF, "katakana"},
	{0x3130, 0x318F, "hangul"},
	{0x31F0, 0x31FF, "katakana"},
	{0x3400, 0x4DBF, "han"},
	{0x4E00, 0x9FFF, "han"},
	{0xA640, 0xA69F, "cyrillic"},
	{0xA720, 0xA7FF, "latin"},
	{0xA960, 0xA97F, "hangul"},
	{0xAC00, 0xD7A3, "hangul"},
	{0xF900, 0xFAFF, "han"},
	{0xFB1D, 0xFB4F, "hebrew"},
	{0xFB50, 0xFDFF, "arabic"},
	{0xFE70, 0xFEFF, "arabic"},
	{0xFF21, 0xFF3A, "latin"},
	{0xFF41, 0xFF5A, "latin"},
	{0x20000, 0x2A6DF, "han"},
}

// ScriptOf returns the script of one rune; "common" for script-neutral runes
// (digits, combining diacriticals) and "unknown" for anything the table does not
// cover. Binary search over the sorted range table — no regex, no property
// escapes.
func ScriptOf(r rune) string {
	if r >= '0' && r <= '9' {
		return "common"
	}
	lo, hi := 0, len(scriptRanges)-1
	for lo <= hi {
		mid := (lo + hi) / 2
		row := scriptRanges[mid]
		switch {
		case r < row.first:
			hi = mid - 1
		case r > row.last:
			lo = mid + 1
		default:
			return row.name
		}
	}
	return "unknown"
}

// isWordChar reports whether r is word-forming: Unicode letters, numbers and
// marks (categories L, N, M). Everything else separates.
func isWordChar(r rune) bool {
	return unicode.IsLetter(r) || unicode.IsNumber(r) || unicode.In(r, unicode.M)
}

var caseFolder = cases.Fold()

// emit flushes one same-script run into out.
func emit(run []rune, script string, out *[]string) {
	if len(run) == 0 {
		return
	}
	loadScriptTable()
	if _, continuous := continuousScripts[script]; continuous && len(run) > 1 {
		// Character bigrams (Lucene CJKBigramFilter semantics). Deterministic,
		// dictionary-free, and adequate for both lexical retrieval and ordered
		// containment. Bigrams never cross a script boundary, because a boundary
		// ends the run before this is called.
		for i := 0; i < len(run)-1; i++ {
			*out = append(*out, string(run[i:i+2]))
		}
		return
	}
	*out = append(*out, string(run))
}

// TokenizeV2 is Unicode-aware tokenization with bigram segmentation for
// spaceless scripts.
//
// NFKC-normalized and case-folded, then scanned into maximal same-script runs of
// word characters. Runs in a continuous script become character bigrams; all
// others become one token each. Parity with the Python reference
// citenexus.tokenize.tokenize_v2.
func TokenizeV2(text string) []string {
	// casefold can denormalize, so normalize once more afterwards. Idempotent
	// for the overwhelming majority of input.
	normalized := norm.NFKC.String(caseFolder.String(norm.NFKC.String(text)))

	out := []string{}
	var run []rune
	runScript := "common"
	// Scan RUNES, not bytes — a byte scan would split every multi-byte rune.
	for _, r := range normalized {
		if !isWordChar(r) {
			emit(run, runScript, &out)
			run, runScript = nil, "common"
			continue
		}
		script := ScriptOf(r)
		if len(run) > 0 && script != "common" && runScript != "common" && script != runScript {
			// A script boundary inside a run of word characters ("東京tokyo").
			emit(run, runScript, &out)
			run, runScript = nil, "common"
		}
		run = append(run, r)
		if runScript == "common" {
			runScript = script
		}
	}
	emit(run, runScript, &out)
	return out
}

// ScriptsIn returns every script present in text's word characters, sorted,
// without "common" — digits and punctuation carry no script claim.
func ScriptsIn(text string) []string {
	found := map[string]struct{}{}
	for _, r := range text {
		if isWordChar(r) {
			found[ScriptOf(r)] = struct{}{}
		}
	}
	delete(found, "common")
	return sortedKeys(found)
}

// UnsupportedScripts returns the scripts in text that CiteNexus does not claim
// to support.
//
// A non-empty result is a CAPABILITY signal, not an evidence judgement.
// Returning the evidence-absent refusal for a capability gap is the specific
// thing that let the ASCII-only tokenizer hide for as long as it did.
func UnsupportedScripts(text string) []string {
	loadScriptTable()
	out := []string{}
	for _, s := range ScriptsIn(text) {
		if _, ok := supportedScripts[s]; !ok {
			out = append(out, s)
		}
	}
	return out
}
