// Language and Script — the named code sets (change: language-enums).
//
// Both are DEFINED STRING TYPES, not iota enums. That is the whole point: an
// untyped constant converts implicitly, so
//
//	var l Language = "ta"          // still compiles
//	SearchLanguageByCode("ta")     // still works
//
// while `func f(l Language)` documents the domain and readers get a named set to
// autocomplete. An iota enum would have needed a lookup table at every boundary
// and would not round-trip through the shared JSON fixtures.
//
// The set is pinned to <repo>/conformance/cases/languages.json (see
// codes_test.go), which the Python reference generates — so Python, Go and JS
// cannot drift apart by review error, exactly as the script claim is pinned.

package lang

// Language is a language code (ISO 639-1), plus the one non-language sentinel.
type Language string

// Script is a writing system, as classified by the tokenizer's script table.
type Script string

// The languages CiteNexus can NAME. That deliberately includes the ones it
// REFUSES to search: a language must be nameable to be refused by name.
const (
	English    Language = "en"
	French     Language = "fr"
	German     Language = "de"
	Spanish    Language = "es"
	Portuguese Language = "pt"
	Italian    Language = "it"
	Dutch      Language = "nl"
	Polish     Language = "pl"
	Turkish    Language = "tr"
	Vietnamese Language = "vi"
	Indonesian Language = "id"
	Swahili    Language = "sw"
	Russian    Language = "ru"
	Ukrainian  Language = "uk"
	Greek      Language = "el"
	Hebrew     Language = "he"
	Arabic     Language = "ar"
	Persian    Language = "fa"
	Urdu       Language = "ur"
	Hindi      Language = "hi"
	Marathi    Language = "mr"
	Nepali     Language = "ne"
	Bengali    Language = "bn"
	Assamese   Language = "as"
	Tamil      Language = "ta"
	Thai       Language = "th"
	Korean     Language = "ko"
	Chinese    Language = "zh"
	Japanese   Language = "ja"
	Telugu     Language = "te"
	Kannada    Language = "kn"
	Malayalam  Language = "ml"
	Gujarati   Language = "gu"
	Punjabi    Language = "pa"
	Odia       Language = "or"
	Sinhala    Language = "si"
	Khmer      Language = "km"
	Lao        Language = "lo"
	Burmese    Language = "my"
	Georgian   Language = "ka"
	Armenian   Language = "hy"

	// Auto is "detect it from my question" — a sentinel, not a language. It is
	// deliberately absent from SearchLanguages(), so asking to SEARCH "auto"
	// still fails as an unknown code. Equal to AutoAnswerLanguage.
	Auto Language = AutoAnswerLanguage
)

// The writing systems the tokenizer's range table classifies. Three tiers per
// ADR-0011: fixture-backed and claimed, named-but-unclaimed, and ScriptUnknown
// (outside the table entirely, so it produces no tokens at all).
const (
	ScriptArabic     Script = "arabic"
	ScriptArmenian   Script = "armenian"
	ScriptBengali    Script = "bengali"
	ScriptCommon     Script = "common"
	ScriptCyrillic   Script = "cyrillic"
	ScriptDevanagari Script = "devanagari"
	ScriptGeorgian   Script = "georgian"
	ScriptGreek      Script = "greek"
	ScriptGujarati   Script = "gujarati"
	ScriptGurmukhi   Script = "gurmukhi"
	ScriptHan        Script = "han"
	ScriptHangul     Script = "hangul"
	ScriptHebrew     Script = "hebrew"
	ScriptHiragana   Script = "hiragana"
	ScriptKannada    Script = "kannada"
	ScriptKatakana   Script = "katakana"
	ScriptKhmer      Script = "khmer"
	ScriptLao        Script = "lao"
	ScriptLatin      Script = "latin"
	ScriptMalayalam  Script = "malayalam"
	ScriptMyanmar    Script = "myanmar"
	ScriptOriya      Script = "oriya"
	ScriptSinhala    Script = "sinhala"
	ScriptTamil      Script = "tamil"
	ScriptTelugu     Script = "telugu"
	ScriptThai       Script = "thai"
	ScriptUnknown    Script = "unknown"
)

// SearchLanguage is one entry of the search-language table: its code, its
// prompt-facing name, the script(s) it is written in, and whether every one of
// those scripts carries an ADR-0011 golden fixture.
type SearchLanguage struct {
	Code      Language
	Name      string
	Scripts   []Script
	Supported bool
}

// searchLanguages is the table, in the canonical order of the conformance
// fixture. Unsupported entries are present ON PURPOSE — dropping them would turn
// a precise "kannada is not claimed" into a vague "unknown language code".
var searchLanguages = []SearchLanguage{
	{Code: English, Name: "English", Scripts: []Script{ScriptLatin}, Supported: true},
	{Code: French, Name: "French", Scripts: []Script{ScriptLatin}, Supported: true},
	{Code: German, Name: "German", Scripts: []Script{ScriptLatin}, Supported: true},
	{Code: Spanish, Name: "Spanish", Scripts: []Script{ScriptLatin}, Supported: true},
	{Code: Portuguese, Name: "Portuguese", Scripts: []Script{ScriptLatin}, Supported: true},
	{Code: Italian, Name: "Italian", Scripts: []Script{ScriptLatin}, Supported: true},
	{Code: Dutch, Name: "Dutch", Scripts: []Script{ScriptLatin}, Supported: true},
	{Code: Polish, Name: "Polish", Scripts: []Script{ScriptLatin}, Supported: true},
	{Code: Turkish, Name: "Turkish", Scripts: []Script{ScriptLatin}, Supported: true},
	{Code: Vietnamese, Name: "Vietnamese", Scripts: []Script{ScriptLatin}, Supported: true},
	{Code: Indonesian, Name: "Indonesian", Scripts: []Script{ScriptLatin}, Supported: true},
	{Code: Swahili, Name: "Swahili", Scripts: []Script{ScriptLatin}, Supported: true},
	{Code: Russian, Name: "Russian", Scripts: []Script{ScriptCyrillic}, Supported: true},
	{Code: Ukrainian, Name: "Ukrainian", Scripts: []Script{ScriptCyrillic}, Supported: true},
	{Code: Greek, Name: "Greek", Scripts: []Script{ScriptGreek}, Supported: true},
	{Code: Hebrew, Name: "Hebrew", Scripts: []Script{ScriptHebrew}, Supported: true},
	{Code: Arabic, Name: "Arabic", Scripts: []Script{ScriptArabic}, Supported: true},
	{Code: Persian, Name: "Persian", Scripts: []Script{ScriptArabic}, Supported: true},
	{Code: Urdu, Name: "Urdu", Scripts: []Script{ScriptArabic}, Supported: true},
	{Code: Hindi, Name: "Hindi", Scripts: []Script{ScriptDevanagari}, Supported: true},
	{Code: Marathi, Name: "Marathi", Scripts: []Script{ScriptDevanagari}, Supported: true},
	{Code: Nepali, Name: "Nepali", Scripts: []Script{ScriptDevanagari}, Supported: true},
	{Code: Bengali, Name: "Bengali", Scripts: []Script{ScriptBengali}, Supported: true},
	{Code: Assamese, Name: "Assamese", Scripts: []Script{ScriptBengali}, Supported: true},
	{Code: Tamil, Name: "Tamil", Scripts: []Script{ScriptTamil}, Supported: true},
	{Code: Thai, Name: "Thai", Scripts: []Script{ScriptThai}, Supported: true},
	{Code: Korean, Name: "Korean", Scripts: []Script{ScriptHangul}, Supported: true},
	{Code: Chinese, Name: "Chinese", Scripts: []Script{ScriptHan}, Supported: true},
	{Code: Japanese, Name: "Japanese", Scripts: []Script{ScriptHan, ScriptHiragana, ScriptKatakana}, Supported: true},
	{Code: Telugu, Name: "Telugu", Scripts: []Script{ScriptTelugu}, Supported: true},
	{Code: Kannada, Name: "Kannada", Scripts: []Script{ScriptKannada}, Supported: false},
	{Code: Malayalam, Name: "Malayalam", Scripts: []Script{ScriptMalayalam}, Supported: false},
	{Code: Gujarati, Name: "Gujarati", Scripts: []Script{ScriptGujarati}, Supported: false},
	{Code: Punjabi, Name: "Punjabi", Scripts: []Script{ScriptGurmukhi}, Supported: false},
	{Code: Odia, Name: "Odia", Scripts: []Script{ScriptOriya}, Supported: false},
	{Code: Sinhala, Name: "Sinhala", Scripts: []Script{ScriptSinhala}, Supported: false},
	{Code: Khmer, Name: "Khmer", Scripts: []Script{ScriptKhmer}, Supported: false},
	{Code: Lao, Name: "Lao", Scripts: []Script{ScriptLao}, Supported: false},
	{Code: Burmese, Name: "Burmese", Scripts: []Script{ScriptMyanmar}, Supported: false},
	{Code: Georgian, Name: "Georgian", Scripts: []Script{ScriptGeorgian}, Supported: false},
	{Code: Armenian, Name: "Armenian", Scripts: []Script{ScriptArmenian}, Supported: false},
}

// SearchLanguages returns the table in canonical order. The slice is copied, so
// a caller cannot mutate the shared set.
func SearchLanguages() []SearchLanguage {
	out := make([]SearchLanguage, len(searchLanguages))
	copy(out, searchLanguages)
	return out
}

// SearchLanguageByCode looks a language up by its code. A plain string converts
// implicitly, so SearchLanguageByCode("ta") is as valid as
// SearchLanguageByCode(Tamil). Codes are NEVER guessed: an unknown code reports
// ok=false rather than inferring a script from its shape.
func SearchLanguageByCode(code Language) (SearchLanguage, bool) {
	for _, l := range searchLanguages {
		if l.Code == code {
			return l, true
		}
	}
	return SearchLanguage{}, false
}
