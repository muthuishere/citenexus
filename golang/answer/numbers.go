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
	"fmt"
	"math/big"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"unicode"
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

// lakhForm: 1-2 leading digits, one or more two-digit groups, a final
// three-digit group, and an optional point decimal.
var lakhForm = regexp.MustCompile(`^([1-9][0-9]?(?:,[0-9]{2})+,[0-9]{3})(?:\.([0-9]+))?$`)

// localeTags: the declared tag normalised ("de_CH" -> "de-ch") and its primary
// language subtag.
func localeTags(language string) (string, string) {
	full := strings.ReplaceAll(strings.ToLower(strings.TrimSpace(language)), "_", "-")
	return full, primaryLanguageTag(full)
}

// decimalMarkOf is the decimal mark of a declared language: "," or ".", or ""
// when the language is undeclared or unknown. A region tag in the tables
// ("de-ch", "es-mx") wins over its language (CLDR, ADR-0015 amendment).
func decimalMarkOf(language string) string {
	tables := LoadConflictTables()
	full, primary := localeTags(language)
	for _, code := range []string{full, primary} {
		switch {
		case code == "":
		case inTable(tables.DecimalCommaLanguages, code):
			return ","
		case inTable(tables.DecimalPointLanguages, code):
			return "."
		}
	}
	return ""
}

// readsLakh: the declared language writes Indian lakh grouping.
func readsLakh(language string) bool {
	tables := LoadConflictTables()
	full, primary := localeTags(language)
	return full != "" && (inTable(tables.LakhGroupingLanguages, full) || inTable(tables.LakhGroupingLanguages, primary))
}

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
	// Indian lakh grouping ("1,00,000", "12,34,567.89"): a two-digit group
	// can be nothing else, but only a language that writes it reads it.
	if m := lakhForm.FindStringSubmatch(raw); m != nil && readsLakh(language) {
		return known(strings.ReplaceAll(m[1], ",", ""), m[2])
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

	var isThousands bool
	switch decimalMarkOf(language) {
	case ",":
		isThousands = mark == "."
	case ".":
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
	// attached is true when the unit follows the digits with no space ("1st",
	// "2de") — required to read it as an ordinal suffix: "4 de werkgever" is
	// a 4 and an article.
	attached bool
}

// verbatimNumbers maps a number's spelling (numberMatch.raw) in a cited unit to
// the unit's own reading of it. ADR-0015 amendment (2026-09-27): a number the
// claim copies VERBATIM from its unit keeps the unit's locale — an English
// claim writing the Dutch "€ 4.000" is 4000 over that unit. The match is on
// the whole matched number (numberRE takes every digit group), so "12" never
// takes the reading of "12.75" or "0,12". A spelling the unit reads two ways
// (a dashed and a plain "4.000" in an English unit) is dropped: ambiguity
// falls back to the claim's own language.
type verbatimNumbers map[string]NumberReading

func verbatimIn(text, language string) verbatimNumbers {
	out := verbatimNumbers{}
	clash := map[string]bool{}
	for _, m := range numbersIn(text, language) {
		if r, seen := out[m.raw]; seen && r.Key != m.reading.Key {
			clash[m.raw] = true
		}
		out[m.raw] = m.reading
	}
	for raw := range clash {
		delete(out, raw)
	}
	return out
}

// readWith reads a claim number: the unit's reading when the claim copies the
// unit's spelling, else ReadNumber in the claim's own language. A dashed
// amount ("4.000,-") reads the same in every locale.
func readWith(raw string, dash bool, language string, vb []verbatimNumbers) NumberReading {
	if !dash {
		for _, v := range vb {
			if r, ok := v[raw]; ok {
				return r
			}
		}
	}
	return ReadNumber(raw, dash, language)
}

// numbersIn finds every measured number in text, skipping identifiers such as
// "p50" / "ipv4" (a digit run flush against an ASCII letter). vb, when given,
// is the cited unit's verbatim readings (claim side only).
func numbersIn(text, language string, vb ...verbatimNumbers) []numberMatch {
	lowered := joinSpacedThousands(strings.ToLower(text), language)
	out := []numberMatch{}
	for _, m := range numberRE.FindAllStringSubmatchIndex(lowered, -1) {
		start := m[2]
		if start > 0 {
			prev, _ := utf8.DecodeLastRuneInString(lowered[:start])
			if isIdentifierPrefix(prev) {
				continue
			}
		}
		match := numberMatch{raw: lowered[m[2]:m[3]], reading: readWith(lowered[m[2]:m[3]], m[4] >= 0, language, vb)}
		if m[6] >= 0 {
			match.unit = lowered[m[6]:m[7]]
			match.attached = m[6] == m[3]
		}
		out = append(out, match)
	}
	return out
}

// Clock times are times of day, never durations or amounts: "09:00" =
// "9:00" = "9.00 uur" = "9am". clockTimes returns their keys ("clock:9:00",
// 24-hour) and the text with them blanked out, so the number and unit guards
// never read "9.00 uur" as nine hours or "09:00" as the numbers 9 and 0.
var (
	clockColon = regexp.MustCompile(`\b([01]?[0-9]|2[0-3]):([0-5][0-9])\b`)
	clockDot   = regexp.MustCompile(`\b([01]?[0-9]|2[0-3])\.([0-5][0-9])(\s*(?:uur|u)\b)`)
	clockAmPm  = regexp.MustCompile(`\b(1[0-2]|0?[1-9])(?:[:.]([0-5][0-9]))?\s*(am|pm|a\.m\.|p\.m\.)`)
)

func clockTimes(text string) (map[string]struct{}, string) {
	keys := map[string]struct{}{}
	lowered := strings.ToLower(text)
	blank := []byte(lowered)
	mark := func(start, end int, hour, minute string) {
		h := strings.TrimLeft(hour, "0")
		if h == "" {
			h = "0"
		}
		if minute == "" {
			minute = "00"
		}
		keys["clock:"+h+":"+minute] = struct{}{}
		for i := start; i < end; i++ {
			blank[i] = ' '
		}
	}
	for _, m := range clockAmPm.FindAllStringSubmatchIndex(lowered, -1) {
		hour, minute := lowered[m[2]:m[3]], ""
		if m[4] >= 0 {
			minute = lowered[m[4]:m[5]]
		}
		h := 0
		for _, r := range hour {
			h = h*10 + int(r-'0')
		}
		pm := strings.HasPrefix(lowered[m[6]:m[7]], "p")
		switch {
		case pm && h < 12:
			h += 12
		case !pm && h == 12:
			h = 0
		}
		mark(m[0], m[1], strconv.Itoa(h), minute)
	}
	for _, re := range []*regexp.Regexp{clockColon, clockDot} {
		for _, m := range re.FindAllStringSubmatchIndex(string(blank), -1) {
			mark(m[0], m[5], string(blank[m[2]:m[3]]), string(blank[m[4]:m[5]]))
		}
	}
	return keys, string(blank)
}

// Money is never a duration: "€ 150 per maand" is a price with a period, not
// 150 months. moneyRates returns the rates in text — (amount key, period
// class) for an amount followed by per/a/each/"/" and a time unit ("€ 2,35
// per thuiswerkdag" = (2.35, day)) — and the text with every money amount
// blanked, so quantities() never reads one as a duration.
var (
	moneyBefore = regexp.MustCompile(`(?:€|\beur\b|\$|£)\s*([0-9][0-9.,]*)(?:,-)?`)
	moneyAfter  = regexp.MustCompile(`\b([0-9][0-9.,]*)\s*(?:euro|eur)\b`)
	ratePeriod  = regexp.MustCompile(`^(?:\s+\p{L}+)?\s*(?:per|a|an|each|/)\s*(\p{L}+)`)
)

func moneyRates(text, language string, vb ...verbatimNumbers) (map[[2]string]struct{}, string) {
	rates := map[[2]string]struct{}{}
	lowered := strings.ToLower(text)
	blank := []byte(lowered)
	for _, re := range []*regexp.Regexp{moneyBefore, moneyAfter} {
		for _, m := range re.FindAllStringSubmatchIndex(lowered, -1) {
			raw := strings.TrimRight(lowered[m[2]:m[3]], ".,")
			if raw == "" {
				continue
			}
			key := readWith(raw, false, language, vb).Key
			if p := ratePeriod.FindStringSubmatch(lowered[m[1]:]); p != nil {
				if class, _, ok := unitOf(p[1]); ok {
					rates[[2]string{key, class}] = struct{}{}
				}
			}
			for i := m[2]; i < m[3]; i++ {
				blank[i] = ' '
			}
		}
	}
	return rates, string(blank)
}

// spacedThousands is a money amount grouped by spaces — a plain, no-break or
// narrow no-break space — "€ 4 000" = "€ 4.000" = 4000, including between
// the sign and the amount (Go's \s is ASCII-only). Only after a currency
// sign or code, and only with exact three-digit groups: elsewhere "4 000" may
// be two numbers.
var spacedThousands = regexp.MustCompile(`((?:€|\beur\b|\$|£)[\s\x{00A0}\x{202F}]*)([1-9][0-9]*)[ \x{00A0}\x{202F}]([0-9]{3})\b`)

// groupedDigits are digits grouped by a space (plain, no-break or narrow
// no-break: "1 234,56") or an apostrophe (Swiss "1'234.50" / "1’234.50"):
// 1-3 leading digits, then exact three-digit groups.
var (
	spaceGrouped      = regexp.MustCompile(`[1-9][0-9]{0,2}(?:[ \x{00A0}\x{202F}][0-9]{3})+`)
	apostropheGrouped = regexp.MustCompile(`[1-9][0-9]{0,2}(?:['’][0-9]{3})+`)
	groupSeparators   = regexp.MustCompile(`[ \x{00A0}\x{202F}'’]`)
)

// joinGrouped removes the separators of each whole grouped run. A run that
// touches another digit, letter or number mark on either side, or is followed
// by another separator and digit ("1 234 56"), is left as written: it may be
// several numbers, and ambiguity is never guessed.
func joinGrouped(text string, re *regexp.Regexp) string {
	var b strings.Builder
	last := 0
	for _, m := range re.FindAllStringIndex(text, -1) {
		if m[0] > 0 {
			prev, _ := utf8.DecodeLastRuneInString(text[:m[0]])
			if unicode.IsDigit(prev) || unicode.IsLetter(prev) || strings.ContainsRune(".,'’", prev) {
				continue
			}
		}
		if m[1] < len(text) {
			next, size := utf8.DecodeRuneInString(text[m[1]:])
			if unicode.IsDigit(next) || unicode.IsLetter(next) {
				continue
			}
			if groupSeparators.MatchString(string(next)) && m[1]+size < len(text) {
				if after, _ := utf8.DecodeRuneInString(text[m[1]+size:]); unicode.IsDigit(after) {
					continue
				}
			}
		}
		b.WriteString(text[last:m[0]])
		b.WriteString(groupSeparators.ReplaceAllString(text[m[0]:m[1]], ""))
		last = m[1]
	}
	b.WriteString(text[last:])
	return b.String()
}

// joinSpacedThousands joins grouped digits before numbers are read: a money
// amount grouped by spaces in every language (a currency sign or code marks
// it as one number); any space-grouped run only in a decimal-comma language,
// which writes "1 234,56" (CLDR fr, de, …); and apostrophe grouping in every
// language — an apostrophe is a decimal mark nowhere.
func joinSpacedThousands(text, language string) string {
	for i := 0; i < 4; i++ { // "€ 1 250 000": one group per pass
		next := spacedThousands.ReplaceAllString(text, "$1$2$3")
		if next == text {
			break
		}
		text = next
	}
	if decimalMarkOf(language) == "," {
		text = joinGrouped(text, spaceGrouped)
	}
	return joinGrouped(text, apostropheGrouped)
}

// Dates, numeric or written, are read as (day, month, year?) and compared as
// dates: "01-06-2026" = "1 juni 2026" = "June 1, 2026". A numeric d-m(-y)
// date is read day-first under a Dutch declaration; in any other language a
// numeric date whose day and month could both be either ("01/06") is
// AMBIGUOUS and matches only its own spelling — ambiguity refuses, it never
// guesses (ADR-0015's rule for numbers). Months come from the same NL/EN
// table the name guard folds.
var (
	numericDate = regexp.MustCompile(`\b([0-3]?[0-9])[-/.]([01]?[0-9])(?:[-/.]((?:19|20)[0-9]{2}))?\b`)
	monthNames  = func() string {
		names := make([]string, 0, len(monthNumber))
		for n := range monthNumber {
			names = append(names, n)
		}
		sort.Slice(names, func(i, j int) bool { return len(names[i]) > len(names[j]) })
		return strings.Join(names, "|")
	}()
	dayMonth = regexp.MustCompile(`\b([0-3]?[0-9])(?:st|nd|rd|th|e|ste|de)?\s+(` + monthNames + `)\b(?:\s+((?:19|20)[0-9]{2}))?`)
	monthDay = regexp.MustCompile(`\b(` + monthNames + `)\s+([0-3]?[0-9])(?:st|nd|rd|th)?\b(?:,?\s+((?:19|20)[0-9]{2}))?`)
)

var monthNumber = map[string]int{
	"januari": 1, "februari": 2, "maart": 3, "april": 4, "mei": 5, "juni": 6, "juli": 7, "augustus": 8,
	"september": 9, "oktober": 10, "november": 11, "december": 12,
	"january": 1, "february": 2, "march": 3, "may": 5, "june": 6, "july": 7, "august": 8,
	"october": 10,
}

type dateKey struct {
	day, month, year int // year 0: not stated
	ambiguous        string
}

func (d dateKey) String() string {
	if d.ambiguous != "" {
		return d.ambiguous
	}
	if d.year == 0 {
		return fmt.Sprintf("%02d-%02d", d.day, d.month)
	}
	return fmt.Sprintf("%02d-%02d-%d", d.day, d.month, d.year)
}

// sameDate: equal day and month, and equal years when both state one.
func sameDate(a, b dateKey) bool {
	if a.ambiguous != "" || b.ambiguous != "" {
		return a.ambiguous != "" && a.ambiguous == b.ambiguous
	}
	return a.day == b.day && a.month == b.month && (a.year == 0 || b.year == 0 || a.year == b.year)
}

func atoi(s string) int {
	n := 0
	for _, r := range s {
		n = n*10 + int(r-'0')
	}
	return n
}

type dateSpan struct {
	start, end int
	key        dateKey
}

// datesIn returns the dates in text and the text with them blanked.
func datesIn(text, language string) ([]dateKey, string) {
	lowered := strings.ToLower(text)
	blank := []byte(lowered)
	var out []dateKey
	for _, sp := range dateSpans(lowered, language) {
		out = append(out, sp.key)
		for i := sp.start; i < sp.end; i++ {
			blank[i] = ' '
		}
	}
	return out, string(blank)
}

// dateSpans finds the dates in lowered text, in text order.
func dateSpans(lowered, language string) []dateSpan {
	blank := []byte(lowered)
	var spans []dateSpan
	valid := func(d, m int) bool { return d >= 1 && d <= 31 && m >= 1 && m <= 12 }
	var k dateKey
	mark := func(start, end int) {
		spans = append(spans, dateSpan{start, end, k})
		for i := start; i < end; i++ {
			blank[i] = ' '
		}
	}
	for _, m := range dayMonth.FindAllStringSubmatchIndex(lowered, -1) {
		d, mo := atoi(lowered[m[2]:m[3]]), monthNumber[lowered[m[4]:m[5]]]
		if !valid(d, mo) {
			continue
		}
		k = dateKey{day: d, month: mo}
		if m[6] >= 0 {
			k.year = atoi(lowered[m[6]:m[7]])
		}
		mark(m[0], m[1])
	}
	for _, m := range monthDay.FindAllStringSubmatchIndex(string(blank), -1) {
		mo, d := monthNumber[string(blank[m[2]:m[3]])], atoi(string(blank[m[4]:m[5]]))
		if !valid(d, mo) {
			continue
		}
		k = dateKey{day: d, month: mo}
		if m[6] >= 0 {
			k.year = atoi(string(blank[m[6]:m[7]]))
		}
		mark(m[0], m[1])
	}
	dutch := primaryLanguageTag(language) == "nl"
	for _, m := range numericDate.FindAllStringSubmatchIndex(string(blank), -1) {
		raw := string(blank[m[0]:m[1]])
		a, b := atoi(string(blank[m[2]:m[3]])), atoi(string(blank[m[4]:m[5]]))
		year := 0
		if m[6] >= 0 {
			year = atoi(string(blank[m[6]:m[7]]))
		} else if !strings.Contains(raw, "-") {
			continue // "1.5" or "3/4" without a year is a number or a fraction
		}
		switch {
		case dutch && valid(a, b):
			k = dateKey{day: a, month: b, year: year}
		case !dutch && valid(a, b) && valid(b, a) && a != b:
			k = dateKey{ambiguous: "date?" + raw}
		case valid(a, b):
			k = dateKey{day: a, month: b, year: year}
		case valid(b, a):
			k = dateKey{day: b, month: a, year: year} // month-first, unambiguous
		default:
			continue
		}
		mark(m[0], m[1])
	}
	sort.Slice(spans, func(i, j int) bool { return spans[i].start < spans[j].start })
	return spans
}
