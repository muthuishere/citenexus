// Locale-aware number reading for conflict detection (ADR-0015), ported from
// python/src/citenexus/answer/numbers.py and pinned by the number_readings
// bucket of conformance/cases/conflict.json.
//
// Two passages quoting the same amount must compare EQUAL, and two different
// amounts must never compare equal. The second rule dominates: a false "equal"
// hides a real conflict (fails open), a false "different" only costs an
// abstention (fails closed). So a number is read to a single value only when its
// FORM, or the passage's declared language, leaves one reading; otherwise its
// key is its raw spelling prefixed "?", equal to nothing but the same spelling.

package answer

import (
	"math/big"
	"regexp"
	"strings"
	"unicode/utf8"
)

// NumberReading is a number's comparison key and, when it has exactly one
// reading, its exact value. Value is nil for an ambiguous or unreadable number.
type NumberReading struct {
	Key   string
	Value *big.Rat
}

// numberRE mirrors Python's numbers.NUMBER_RE: digit groups joined by single
// "."/",", an optional Dutch ",-", then an optional unit. Applied to LOWERED
// text; the letter-boundary check is done in code (see isIdentifierPrefix).
var numberRE = regexp.MustCompile(`([0-9]+(?:[.,][0-9]+)*)(,-)?[` + pythonSpace + `]*([a-z]+|%)?`)

var (
	leadGroup  = regexp.MustCompile(`^[1-9][0-9]{0,2}$`)
	threeGroup = regexp.MustCompile(`^[0-9]{3}$`)
)

// thousands is a valid thousands grouping: 1-3 leading digits (no leading
// zero), then groups of exactly three.
func thousands(groups []string) bool {
	if !leadGroup.MatchString(groups[0]) {
		return false
	}
	for _, g := range groups[1:] {
		if !threeGroup.MatchString(g) {
			return false
		}
	}
	return true
}

func primaryLanguageTag(language string) string {
	language = strings.ToLower(strings.TrimSpace(language))
	if i := strings.IndexAny(language, "-_"); i >= 0 {
		language = language[:i]
	}
	return language
}

// known builds the reading of integer digits plus decimal digits. The key is the
// canonical decimal string with no leading or trailing zeros: 1500, 25.5, 0.05.
func known(whole, decimals string) NumberReading {
	w := strings.TrimLeft(whole, "0")
	if w == "" {
		w = "0"
	}
	d := strings.TrimRight(decimals, "0")
	key := w
	if d != "" {
		key = w + "." + d
	}
	value, _ := new(big.Rat).SetString(key)
	return NumberReading{Key: key, Value: value}
}

func unread(raw string) NumberReading { return NumberReading{Key: "?" + raw} }

func inTable(values []string, code string) bool {
	for _, v := range values {
		if v == code {
			return true
		}
	}
	return false
}

// ReadNumber reads one matched number to its comparison key. dash is true when
// the Dutch ",-" suffix followed it; language is the passage's DECLARED
// language ("" = undeclared), which only decides "1.500" / "1,500".
func ReadNumber(raw string, dash bool, language string) NumberReading {
	if dash {
		if strings.Contains(raw, ",") {
			return unread(raw + ",-") // "25,50,-" is not a form
		}
		groups := strings.Split(raw, ".")
		if len(groups) > 1 && !thousands(groups) {
			return unread(raw + ",-")
		}
		return known(strings.Join(groups, ""), "")
	}

	hasDot, hasComma := strings.Contains(raw, "."), strings.Contains(raw, ",")
	if !hasDot && !hasComma {
		return known(raw, "")
	}

	if hasDot && hasComma {
		decimalMark, thousandsMark := ",", "."
		if strings.LastIndex(raw, ".") > strings.LastIndex(raw, ",") {
			decimalMark, thousandsMark = ".", ","
		}
		cut := strings.LastIndex(raw, decimalMark)
		whole, decimals := raw[:cut], raw[cut+1:]
		if strings.Contains(whole, decimalMark) {
			return unread(raw)
		}
		groups := strings.Split(whole, thousandsMark)
		if !thousands(groups) {
			return unread(raw)
		}
		return known(strings.Join(groups, ""), decimals)
	}

	mark := ","
	if hasDot {
		mark = "."
	}
	parts := strings.Split(raw, mark)
	if len(parts) > 2 {
		if thousands(parts) {
			return known(strings.Join(parts, ""), "")
		}
		return unread(raw)
	}

	whole, tail := parts[0], parts[1]
	if len(tail) != 3 || !thousands(parts) {
		return known(whole, tail) // a decimal mark in every locale
	}

	tables := LoadConflictTables()
	var isThousands bool
	switch code := primaryLanguageTag(language); {
	case inTable(tables.DecimalCommaLanguages, code):
		isThousands = mark == "."
	case inTable(tables.DecimalPointLanguages, code):
		isThousands = mark == ","
	default:
		return unread(raw) // 1.500 / 1,500 with no declared locale
	}
	if isThousands {
		return known(whole+tail, "")
	}
	return known(whole, tail)
}

// numberMatch is one number found in lowered text, with its unit (if any).
type numberMatch struct {
	raw     string // the matched digits and separators, as written
	reading NumberReading
	unit    string
}

// numbersIn finds every measured number in text, skipping identifiers such as
// "p50" / "ipv4" (a digit run flush against an ASCII letter).
func numbersIn(text, language string) []numberMatch {
	lowered := strings.ToLower(text)
	out := []numberMatch{}
	for _, m := range numberRE.FindAllStringSubmatchIndex(lowered, -1) {
		start := m[2]
		if start > 0 {
			prev, _ := utf8.DecodeLastRuneInString(lowered[:start])
			if isIdentifierPrefix(prev) {
				continue
			}
		}
		match := numberMatch{raw: lowered[m[2]:m[3]], reading: ReadNumber(lowered[m[2]:m[3]], m[4] >= 0, language)}
		if m[6] >= 0 {
			match.unit = lowered[m[6]:m[7]]
		}
		out = append(out, match)
	}
	return out
}
