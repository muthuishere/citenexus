// Deterministic conflict detection and near-duplicate collapse (ADR-0007),
// ported byte-for-byte from the Python reference
// python/src/citenexus/answer/conflict.py. ADR-0010 tier 1: implemented
// NATIVELY per port — no FFI, no native library — so the pure Go build keeps
// working with no build tags (see golang/ingest/ingest.go for why that purity is
// load-bearing).
//
// Two questions asked of the *same* post-fusion candidate set, by the same
// pairwise comparison:
//
//   - Do two grounded passages disagree? — surfaced, never resolved. Resolution
//     is a policy decision that belongs to the caller and to authority
//     (ADR-0004); a library that silently picks a winner is today's bug with
//     more machinery.
//   - Are two grounded passages the same passage twice? — collapsed, so
//     DistinctDocuments stops counting mirrors as independent corroboration.
//
// Both are pure, offline and model-free: set arithmetic plus one RE2-clean
// number pattern.
//
// The number that matters is the FALSE-CONFLICT RATE, not recall. In strict
// mode a detected conflict abstains, so a false conflict is a false refusal,
// while a missed conflict merely leaves today's behaviour in place. Every rule
// below is built to decline rather than decide, and the guard that actually
// holds the rate down is MaxResidual.
//
// Order is load-bearing. CONFLICT IS CHECKED BEFORE DUPLICATION. A one-word
// change is a duplicate only when that word is neither a value nor a polarity
// marker; getting this backwards would collapse a contradiction into a
// corroboration, which is the worst outcome this change could produce.
//
// The thresholds are NOT parameters. They come from the generated
// ConflictThresholds (conflict_tables.go), which is generated from the canonical
// conformance/conflict.json: SubjectOverlap 0.60, MaxSymdiff 3, MaxResidual 1,
// MinContent 3, DuplicateJaccard 0.80, DuplicateMaxLengthDelta 2, TopK 6. A
// conformance vector cannot pin a value the caller controls, and every one of
// them trades directly against false abstention.

package answer

import (
	"fmt"
	"regexp"
	"sort"
	"strings"
	"sync"
	"unicode/utf8"

	"github.com/muthuishere/citenexus/golang/gate"
	"github.com/muthuishere/citenexus/golang/tokenize"
)

// measurementRE mirrors Python's _MEASUREMENT_RE.
//
// A digit-LEADING token ("500mg", "2019") is a measured value and belongs to the
// numeric rule. A letter-leading token containing digits ("p50", "ipv4", "sec4")
// is an IDENTIFIER and must stay in the content set — it is frequently the only
// thing distinguishing two otherwise-identical passages. Getting this backwards
// produced the ADR-0007 spike's only false conflict ("The p50 latency budget is
// 200 ms" vs "The p99 latency budget is 900 ms"), because the digit filter ate
// the one word that told them apart.
var measurementRE = regexp.MustCompile(`^[0-9]+[a-z]*$`)

// isTokenizerDigitArtifact mirrors Python's _is_tokenizer_digit_artifact: a
// digit-bearing token that is not pure ASCII.
//
// The identifier exception above is ASCII, for the same reason the letter
// boundary below is. tokenize.TokenizeV2 emits CHARACTER BIGRAMS for CJK, so
// 「通知期間は30日です。」 tokenizes as は3 / 30 / 日, and its 60-day counterpart as
// は6 / 60 / 日. measurementRE correctly drops the bare 30 and 60, but は3 and は6
// are letter-leading-with-digit, so the identifier exception kept BOTH in the
// content set — a two-token divergence manufactured out of one number, which is
// above MaxResidual and kills the value rule that the number itself would have
// fired. A mixed-script token carrying an ASCII digit is a tokenizer artifact,
// never an identifier: the identifiers the exception exists for ("p50", "ipv4")
// are ASCII by construction.
func isTokenizerDigitArtifact(token string) bool {
	hasDigit, hasNonASCII := false, false
	for _, r := range token {
		if r >= '0' && r <= '9' {
			hasDigit = true
		}
		if r > 0x7f {
			hasNonASCII = true
		}
	}
	return hasDigit && hasNonASCII
}

// pythonSpace is Python's re \s for str, spelled out.
//
// The Python pattern is `([0-9][0-9,]*(?:\.[0-9]+)?)\s*([a-z]+|%)?` and is
// deliberately RE2-compatible — no lookaround, no backreferences — so it ports
// straight across. The ONE thing that does not port is the meaning of `\s`:
// Go's RE2 `\s` is [\t\n\f\r ] only, while Python's (and JavaScript's) is
// Unicode-aware. Copying the pattern literally would make Go the only port that
// fails to read the unit off "500 mg" — a non-breaking space between a
// number and its unit is ordinary typography, not an exotic input — and a
// dropped unit changes a value verdict. So the class is written out to Python's
// exact set (Py_UNICODE_ISSPACE): U+0009–U+000D, U+001C–U+001F, U+0020, U+0085,
// U+00A0, U+1680, U+2000–U+200A, U+2028, U+2029, U+202F, U+205F, U+3000. The
// pattern is otherwise unchanged.
const pythonSpace = `\x{09}-\x{0d}\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}`

// numberRE mirrors Python's _NUMBER_RE. The letter-boundary check that RE2 would
// need lookbehind for is done in CODE below, precisely so this pattern stays
// backtracking-free.
var numberRE = regexp.MustCompile(`([0-9][0-9,]*(?:\.[0-9]+)?)[` + pythonSpace + `]*([a-z]+|%)?`)

// isIdentifierPrefix mirrors Python's `_IDENTIFIER_PREFIX`. The letter-boundary
// guard is LATIN-ONLY, deliberately, and this is the one place the two facts
// have to be held together:
//
//   - the identifiers it protects are ASCII by construction — "p50", "p99",
//     "ipv4", "ipv6", "sec4", "http2". The text is already lowercased where the
//     check runs, so a–z covers every ASCII letter that can reach it, and the
//     digits it guards are the ASCII [0-9] the pattern itself matched;
//   - unicode.IsLetter (like Python's str.isalpha and JS's \p{L}) is also TRUE
//     for kana, kanji and Han. Japanese and Chinese do not put spaces around
//     numbers, so in 「通知期間は30日です。」 the kana は sits flush against the 3,
//     the number was discarded as an "identifier", numbers came back empty, and
//     the value rule never ran. The SAME sentence with a non-letter separator
//     (「通知期間: 30日」) did fire — measured. Two of the world's largest written
//     languages were inert for the one conflict rule that is otherwise
//     script-independent, which is exactly the one-sided-answer failure ADR-0007
//     exists to prevent.
//
// Narrowing to ASCII keeps every identifier case working (they are all ASCII)
// and lets CJK numbers parse. It also widens the value rule to any other script
// that writes a letter flush against a digit; that is the intended direction —
// the guard exists to protect ASCII identifiers, not to suppress non-Latin text.
func isIdentifierPrefix(r rune) bool {
	return (r >= 'a' && r <= 'z') || r == '_'
}

// ConflictFinding is why two passages were judged to disagree. It never says
// which one is right.
type ConflictFinding struct {
	Rule   string // "antonym" | "negation" | "value"
	Detail string
}

// ConflictPair is a detected conflict between two candidates, by position in the
// sequence.
type ConflictPair struct {
	Left    int
	Right   int
	Finding ConflictFinding
}

// Describe is the one-line form written to Result.Conflicts.
func (p ConflictPair) Describe(leftDocument, rightDocument string) string {
	return fmt.Sprintf("%s: %s vs %s (%s)", p.Finding.Rule, leftDocument, rightDocument, p.Finding.Detail)
}

// ConflictTopK is how many post-fusion candidates are compared pairwise. O(k²)
// on a small k.
func ConflictTopK() int { return LoadConflictTables().Thresholds.TopK }

// foldedTables caches the folded derivations of the canonical tables. The fold
// is applied to the tables once, exactly as Python computes _FOLDED_ANTONYMS and
// _FOLDED_SCOPE at import time.
var (
	foldedOnce     sync.Once
	foldedAntonyms map[[2]string]struct{}
	foldedScope    map[string]struct{}
	negationSet    map[string]struct{}
	reportBigrams  map[[2]string]struct{}
	unitSet        map[string]struct{}
)

func loadFolded() {
	foldedOnce.Do(func() {
		foldedAntonyms = make(map[[2]string]struct{})
		for pair := range ConflictAntonymSet() {
			foldedAntonyms[[2]string{foldConflictToken(pair[0]), foldConflictToken(pair[1])}] = struct{}{}
		}
		foldedScope = make(map[string]struct{})
		for marker := range ConflictScopeMarkerSet() {
			foldedScope[foldConflictToken(marker)] = struct{}{}
		}
		negationSet = ConflictNegationSet()
		reportBigrams = ConflictReportBigramSet()
		unitSet = MeasurementUnitSet()
	})
}

// foldConflictToken folds a regular English plural / third-person -s onto its
// base form.
//
// The pinned tokenizer (v2, ADR-0011) does NOT stem, and this does not change it:
// folding happens inside the comparison only, and no other gate sees it. Without
// it, morphology alone defeats the residual guard on true contradictions that
// are otherwise word-identical — "requires"/"require", "conserves"/"conserve",
// "attract"/"attracts" — each counting as a divergence that is not a divergence.
//
// Deliberately one rule, not a stemmer: a single trailing "s", never on short
// tokens and never after s/u/i ("class", "status", "analysis"). A stemmer would
// merge genuinely different words and every such merge is a false conflict.
func foldConflictToken(token string) string {
	runes := []rune(token)
	n := len(runes)
	if n >= 4 && runes[n-1] == 's' {
		switch runes[n-2] {
		case 's', 'u', 'i':
		default:
			return string(runes[:n-1])
		}
	}
	return token
}

// conflictFeatures is everything the pairwise rules need from one passage.
type conflictFeatures struct {
	tokens    []string
	content   map[string]struct{} // folded, meaning-bearing, non-numeric, non-polarity
	negations int
	numbers   map[string]struct{}
	units     map[string]struct{}
	reported  bool // carries a reported-speech bigram
}

func normalizeConflictNumber(raw string) string {
	value := strings.ReplaceAll(raw, ",", "")
	if strings.Contains(value, ".") {
		value = strings.TrimRight(value, "0")
		value = strings.TrimRight(value, ".")
	}
	if value == "" {
		return "0"
	}
	return value
}

func conflictFeaturesOf(text string) conflictFeatures {
	loadFolded()
	lowered := strings.ToLower(text)
	tokens := tokenize.TokenizeV2(lowered)

	numbers := map[string]struct{}{}
	units := map[string]struct{}{}
	for _, m := range numberRE.FindAllStringSubmatchIndex(lowered, -1) {
		start := m[2] // group 1 start
		if start > 0 {
			prev, _ := utf8.DecodeLastRuneInString(lowered[:start])
			if isIdentifierPrefix(prev) {
				continue // "p50", "ipv4": an identifier, not a measured value
			}
		}
		numbers[normalizeConflictNumber(lowered[m[2]:m[3]])] = struct{}{}
		if m[4] < 0 {
			continue
		}
		unit := lowered[m[4]:m[5]]
		if unit == "%" {
			units["%"] = struct{}{}
		} else if unit != "" {
			if _, ok := unitSet[unit]; ok {
				units[unit] = struct{}{}
			}
		}
	}

	// Stopwords and negations are matched on the RAW token, before folding: the
	// fold is a comparison aid, not a normalizer, and folding first would turn
	// "does" into "doe" and smuggle a stopword into the content set.
	content := map[string]struct{}{}
	negations := 0
	for _, token := range tokens {
		if _, isNegation := negationSet[token]; isNegation {
			negations++
		}
		if gate.IsStopword(token) {
			continue
		}
		if _, isNegation := negationSet[token]; isNegation {
			continue
		}
		if measurementRE.MatchString(token) {
			continue
		}
		if isTokenizerDigitArtifact(token) {
			continue
		}
		content[foldConflictToken(token)] = struct{}{}
	}

	reported := false
	for i := 0; i+1 < len(tokens); i++ {
		if _, ok := reportBigrams[[2]string{tokens[i], tokens[i+1]}]; ok {
			reported = true
			break
		}
	}

	return conflictFeatures{
		tokens:    tokens,
		content:   content,
		negations: negations,
		numbers:   numbers,
		units:     units,
		reported:  reported,
	}
}

// DetectConflict is the deterministic pairwise contradiction test. The second
// return is false when there is no conflict (Python's None).
//
// Pure and total: no model, no network, no I/O, no configuration. The GUARD
// ORDER is load-bearing and matches the reference exactly.
func DetectConflict(left, right string) (ConflictFinding, bool) {
	th := LoadConflictTables().Thresholds
	a, b := conflictFeaturesOf(left), conflictFeaturesOf(right)

	minContent := len(a.content)
	if len(b.content) < minContent {
		minContent = len(b.content)
	}
	if minContent < th.MinContent {
		return ConflictFinding{}, false // too short to compare honestly
	}

	shared := intersect(a.content, b.content)
	overlap := float64(len(shared)) / float64(minContent)
	if overlap < th.SubjectOverlap {
		return ConflictFinding{}, false // not the same subject
	}

	divergence := symmetricDifference(a.content, b.content)
	if len(divergence) > th.MaxSymdiff {
		return ConflictFinding{}, false
	}

	for token := range divergence {
		if _, ok := foldedScope[token]; ok {
			// differently scoped -> complementary, not contradictory
			return ConflictFinding{}, false
		}
	}

	if a.reported || b.reported {
		return ConflictFinding{}, false // a quoted negation belongs to a third party
	}

	// Sorted explicitly: Go map iteration is randomized, and the reference
	// returns the FIRST hit of sorted(a-b) x sorted(b-a). Without the sort this
	// detail string would be nondeterministic.
	onlyA := sortedKeys(difference(a.content, b.content))
	onlyB := sortedKeys(difference(b.content, a.content))
	for _, x := range onlyA {
		for _, y := range onlyB {
			if _, ok := foldedAntonyms[[2]string{x, y}]; !ok {
				continue
			}
			if residualExcluding(divergence, x, y) <= th.MaxResidual {
				return ConflictFinding{Rule: "antonym", Detail: fmt.Sprintf("%s vs %s", x, y)}, true
			}
		}
	}

	// Parity, not presence: two negations cancel.
	if (a.negations%2) != (b.negations%2) && len(divergence) <= th.MaxResidual {
		return ConflictFinding{
			Rule:   "negation",
			Detail: fmt.Sprintf("%d vs %d negations", a.negations, b.negations),
		}, true
	}

	if len(a.numbers) > 0 && len(b.numbers) > 0 && !setsEqual(a.numbers, b.numbers) {
		elaboration := isSubset(a.numbers, b.numbers) || isSubset(b.numbers, a.numbers)
		if !elaboration && setsEqual(a.units, b.units) && len(divergence) <= th.MaxResidual {
			return ConflictFinding{
				Rule: "value",
				Detail: fmt.Sprintf(
					"%s vs %s",
					strings.Join(sortedKeys(a.numbers), ", "),
					strings.Join(sortedKeys(b.numbers), ", "),
				),
			}, true
		}
	}

	return ConflictFinding{}, false
}

// IsNearDuplicate returns the collapse reason if the two are SURFACE CLONES; the
// second return is false otherwise.
//
// This claims one thing and not another. It detects the same passage appearing
// twice — identical token sequence, or a near-identical one of equal length,
// equal numbers and equal negation parity. It does NOT measure evidential
// independence, and cannot: "the same fact restated" and "the same source
// paraphrased" are both semantic equivalence with lexical divergence, so a
// textual detector sees one signal with two causes.
//
// So it is biased to UNDER-collapse. A word-order paraphrase is left standing.
// Under-collapsing leaves DistinctDocuments as inflated as it is today;
// over-collapsing would under-report real corroboration, a new wrong signal.
func IsNearDuplicate(left, right string) (string, bool) {
	th := LoadConflictTables().Thresholds
	if _, conflicting := DetectConflict(left, right); conflicting {
		// conflict first, always: a contradiction is never a clone
		return "", false
	}
	leftTokens, rightTokens := tokenize.TokenizeV2(left), tokenize.TokenizeV2(right)
	if slicesEqual(leftTokens, rightTokens) {
		return "exact", true // covers whitespace, punctuation and case variants
	}
	a, b := conflictFeaturesOf(left), conflictFeaturesOf(right)
	if !setsEqual(a.numbers, b.numbers) || a.negations%2 != b.negations%2 {
		return "", false
	}
	leftSet, rightSet := stringSet(leftTokens), stringSet(rightTokens)
	union := len(symmetricDifference(leftSet, rightSet)) + len(intersect(leftSet, rightSet))
	if union == 0 {
		return "", false
	}
	jaccard := float64(len(intersect(leftSet, rightSet))) / float64(union)
	delta := len(leftTokens) - len(rightTokens)
	if delta < 0 {
		delta = -delta
	}
	if jaccard >= th.DuplicateJaccard && delta <= th.DuplicateMaxLengthDelta {
		return fmt.Sprintf("near (%.2f)", jaccard), true
	}
	return "", false
}

// DescribeConflicts renders one line per conflict, naming both documents and
// neither as the winner.
func DescribeConflicts(pairs []ConflictPair, documents []string) []string {
	out := make([]string, 0, len(pairs))
	for _, pair := range pairs {
		out = append(out, pair.Describe(documents[pair.Left], documents[pair.Right]))
	}
	return out
}

// FindConflicts returns all conflicting pairs within the first ConflictTopK
// passages.
func FindConflicts(passages []string) []ConflictPair {
	return FindConflictsTopK(passages, ConflictTopK())
}

// FindConflictsTopK is FindConflicts with an explicit window (Python's keyword
// argument).
func FindConflictsTopK(passages []string, topK int) []ConflictPair {
	window := passages
	if topK < len(window) {
		window = window[:topK]
	}
	pairs := []ConflictPair{}
	for i := range window {
		for j := i + 1; j < len(window); j++ {
			if finding, ok := DetectConflict(window[i], window[j]); ok {
				pairs = append(pairs, ConflictPair{Left: i, Right: j, Finding: finding})
			}
		}
	}
	return pairs
}

// CollapseNearDuplicates returns the indices of the passages that survive
// surface-clone collapse, in order.
func CollapseNearDuplicates(passages []string) []int {
	kept := []int{}
	for index, text := range passages {
		duplicate := false
		for _, k := range kept {
			if _, ok := IsNearDuplicate(text, passages[k]); ok {
				duplicate = true
				break
			}
		}
		if duplicate {
			continue
		}
		kept = append(kept, index)
	}
	return kept
}

// ── set helpers ──────────────────────────────────────────────────────────────

func intersect(a, b map[string]struct{}) map[string]struct{} {
	out := map[string]struct{}{}
	for k := range a {
		if _, ok := b[k]; ok {
			out[k] = struct{}{}
		}
	}
	return out
}

func difference(a, b map[string]struct{}) map[string]struct{} {
	out := map[string]struct{}{}
	for k := range a {
		if _, ok := b[k]; !ok {
			out[k] = struct{}{}
		}
	}
	return out
}

// symmetricDifference is (a | b) - (a & b).
func symmetricDifference(a, b map[string]struct{}) map[string]struct{} {
	out := difference(a, b)
	for k := range difference(b, a) {
		out[k] = struct{}{}
	}
	return out
}

// residualExcluding is len(divergence - {x, y}).
func residualExcluding(divergence map[string]struct{}, x, y string) int {
	n := 0
	for k := range divergence {
		if k != x && k != y {
			n++
		}
	}
	return n
}

func isSubset(a, b map[string]struct{}) bool {
	for k := range a {
		if _, ok := b[k]; !ok {
			return false
		}
	}
	return true
}

func setsEqual(a, b map[string]struct{}) bool {
	return len(a) == len(b) && isSubset(a, b)
}

func sortedKeys(set map[string]struct{}) []string {
	out := make([]string, 0, len(set))
	for k := range set {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

func slicesEqual(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}
