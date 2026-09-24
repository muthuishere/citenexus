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
	"math/big"
	"regexp"
	"sort"
	"strings"
	"sync"

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

// numberRE lives in numbers.go (ADR-0015). The letter-boundary check that RE2
// would need lookbehind for is done in CODE, precisely so the pattern stays
// backtracking-free.

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
	Rule   string // "inclusion" | "antonym" | "negation" | "value"
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
	// ADR-0015: (x, y) folded inclusion pairs in both orientations; true when x
	// is the INCLUSIVE word.
	inclusionPairs map[[2]string]bool
	vatMarkers     map[string]struct{}
	vatRates       []*big.Rat
	vatTolerance   = big.NewRat(1, 100) // one cent
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
		tables := LoadConflictTables()
		inclusionPairs = map[[2]string]bool{}
		for _, pair := range tables.InclusionPairs {
			incl, excl := foldConflictToken(pair[0]), foldConflictToken(pair[1])
			inclusionPairs[[2]string{incl, excl}] = true
			inclusionPairs[[2]string{excl, incl}] = false
		}
		vatMarkers = stringSet(tables.VATMarkers)
		for _, rate := range tables.VATRates {
			r, ok := new(big.Rat).SetString(rate)
			if !ok {
				panic("answer: vat rate is not a decimal: " + rate)
			}
			vatRates = append(vatRates, r)
		}
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
	numbers   map[string]struct{} // comparison keys (ReadNumber)
	values    map[string]*big.Rat // key -> exact value, nil when ambiguous
	units     map[string]struct{}
	reported  bool // carries a reported-speech bigram
}

func conflictFeaturesOf(text, language string) conflictFeatures {
	loadFolded()
	lowered := strings.ToLower(text)
	tokens := tokenize.TokenizeV2(lowered)

	numbers := map[string]struct{}{}
	values := map[string]*big.Rat{}
	units := map[string]struct{}{}
	for _, m := range numbersIn(lowered, language) {
		numbers[m.reading.Key] = struct{}{}
		values[m.reading.Key] = m.reading.Value
		if m.unit == "%" {
			units["%"] = struct{}{}
		} else if m.unit != "" {
			if _, ok := unitSet[m.unit]; ok {
				units[m.unit] = struct{}{}
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
		values:    values,
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
	return DetectConflictWithLanguages(left, "", right, "")
}

// DetectConflictWithLanguages is DetectConflict with each passage's DECLARED
// language ("" = undeclared) — Python's left_language / right_language. The
// languages only decide how a locale-ambiguous number such as "1.500" is read
// (ADR-0015); undeclared, it is ambiguous and equal to nothing but itself.
func DetectConflictWithLanguages(left, leftLanguage, right, rightLanguage string) (ConflictFinding, bool) {
	th := LoadConflictTables().Thresholds
	a, b := conflictFeaturesOf(left, leftLanguage), conflictFeaturesOf(right, rightLanguage)

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

	// Inclusion runs BEFORE the value rule and owns its verdict, including a
	// decline: a VAT-consistent excl/incl pair must not then be called a value
	// conflict for carrying two different amounts.
	for _, x := range sortedKeys(difference(a.content, b.content)) {
		for _, y := range sortedKeys(difference(b.content, a.content)) {
			leftInclusive, ok := inclusionPairs[[2]string{x, y}]
			if ok && residualExcluding(divergence, x, y) <= th.MaxResidual {
				return inclusionVerdict(a, b, x, y, leftInclusive)
			}
		}
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

// vatConsistent is true when the two amounts are one price quoted excl. and
// incl. VAT: exactly one amount differs on each side, both have a single
// reading, and exclusive*rate is within one cent of inclusive for a tabled rate.
// Anything else is NOT consistent, and the difference stays a conflict.
func vatConsistent(inclusive, exclusive conflictFeatures) bool {
	onlyIncl := sortedKeys(difference(inclusive.numbers, exclusive.numbers))
	onlyExcl := sortedKeys(difference(exclusive.numbers, inclusive.numbers))
	if len(onlyIncl) != 1 || len(onlyExcl) != 1 || !setsEqual(inclusive.units, exclusive.units) {
		return false
	}
	incl, excl := inclusive.values[onlyIncl[0]], exclusive.values[onlyExcl[0]]
	if incl == nil || excl == nil {
		return false
	}
	for _, rate := range vatRates {
		diff := new(big.Rat).Sub(new(big.Rat).Mul(excl, rate), incl)
		if diff.Abs(diff).Cmp(vatTolerance) <= 0 {
			return true
		}
	}
	return false
}

// inclusionVerdict is ADR-0015: one passage says incl, the other excl, on the
// same subject. Same amounts (or none) conflict; different amounts are declined
// only when a VAT marker is present and they are consistent under a tabled VAT
// rate; any other difference conflicts. There is deliberately no "numbers
// differ, so decline" branch: for a legal reader that would fail open.
func inclusionVerdict(a, b conflictFeatures, x, y string, leftInclusive bool) (ConflictFinding, bool) {
	inclusive, exclusive := a, b
	if !leftInclusive {
		inclusive, exclusive = b, a
	}
	if setsEqual(a.numbers, b.numbers) {
		detail := fmt.Sprintf("%s vs %s", x, y)
		if amounts := strings.Join(sortedKeys(a.numbers), ", "); amounts != "" {
			detail += " on " + amounts
		}
		return ConflictFinding{Rule: "inclusion", Detail: detail}, true
	}
	vat := false
	for _, tok := range append(append([]string{}, a.tokens...), b.tokens...) {
		if _, ok := vatMarkers[tok]; ok {
			vat = true
			break
		}
	}
	// The decline also requires equal negation parity: "€ 100 excl" vs "NOT
	// € 121 incl" is VAT-consistent in its amounts and still a disagreement, and
	// the negation rule cannot catch it afterwards (the incl/excl words already
	// use up the residual).
	samePolarity := a.negations%2 == b.negations%2
	if vat && samePolarity && vatConsistent(inclusive, exclusive) {
		return ConflictFinding{}, false
	}
	return ConflictFinding{Rule: "inclusion", Detail: inclusionSide(x, a) + " vs " + inclusionSide(y, b)}, true
}

// inclusionSide is "inclusief 121" — the marker plus its amounts, if any.
func inclusionSide(word string, f conflictFeatures) string {
	if amounts := strings.Join(sortedKeys(f.numbers), ", "); amounts != "" {
		return word + " " + amounts
	}
	return word
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
	return IsNearDuplicateWithLanguages(left, "", right, "")
}

// IsNearDuplicateWithLanguages is IsNearDuplicate with declared languages
// (ADR-0015).
func IsNearDuplicateWithLanguages(left, leftLanguage, right, rightLanguage string) (string, bool) {
	th := LoadConflictTables().Thresholds
	if _, conflicting := DetectConflictWithLanguages(left, leftLanguage, right, rightLanguage); conflicting {
		// conflict first, always: a contradiction is never a clone
		return "", false
	}
	leftTokens, rightTokens := tokenize.TokenizeV2(left), tokenize.TokenizeV2(right)
	if slicesEqual(leftTokens, rightTokens) {
		return "exact", true // covers whitespace, punctuation and case variants
	}
	a, b := conflictFeaturesOf(left, leftLanguage), conflictFeaturesOf(right, rightLanguage)
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
	return FindConflictsWithLanguages(passages, nil, topK)
}

// languageAt is languages[i], or "" (undeclared) past its end.
func languageAt(languages []string, i int) string {
	if i < len(languages) {
		return languages[i]
	}
	return ""
}

// FindConflictsWithLanguages is FindConflictsTopK with the passages' declared
// languages, index-aligned (ADR-0015). A nil slice means all undeclared.
func FindConflictsWithLanguages(passages, languages []string, topK int) []ConflictPair {
	window := passages
	if topK < len(window) {
		window = window[:topK]
	}
	pairs := []ConflictPair{}
	for i := range window {
		for j := i + 1; j < len(window); j++ {
			if finding, ok := DetectConflictWithLanguages(
				window[i], languageAt(languages, i), window[j], languageAt(languages, j),
			); ok {
				pairs = append(pairs, ConflictPair{Left: i, Right: j, Finding: finding})
			}
		}
	}
	return pairs
}

// CollapseNearDuplicates returns the indices of the passages that survive
// surface-clone collapse, in order.
func CollapseNearDuplicates(passages []string) []int {
	return CollapseNearDuplicatesWithLanguages(passages, nil)
}

// CollapseNearDuplicatesWithLanguages is CollapseNearDuplicates with the
// passages' declared languages, index-aligned (ADR-0015).
func CollapseNearDuplicatesWithLanguages(passages, languages []string) []int {
	kept := []int{}
	for index, text := range passages {
		duplicate := false
		for _, k := range kept {
			if _, ok := IsNearDuplicateWithLanguages(
				text, languageAt(languages, index), passages[k], languageAt(languages, k),
			); ok {
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
