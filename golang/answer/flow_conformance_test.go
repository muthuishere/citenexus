package answer

import (
	"reflect"
	"strings"
	"testing"

	"github.com/muthuishere/citenexus/golang/internal/conform"
)

// Flow-level conformance for the three answer-path signals this port used to
// hardcode (2026-08-17). Each suite reads its expectations from a COMMITTED
// fixture and pins the vector count exactly — a `> 0` floor would let a shrunken
// file pass, which is the hole these suites exist to close.
//
// The fixtures are deliberately the ones that already pin the PRIMITIVES:
//
//   - language.json      → lang.ResolveAnswerLanguage (the §11a chain)
//   - tokenize_v2.json   → tokenize.UnsupportedScripts (ADR-0011)
//   - faithful_v2.json   → gate.IsSupportedV2 (ADR-0009)
//
// Each primitive shipped in this port with ZERO callers on the answer path, so
// every one of these signals was a constant wearing the primitive's name. These
// suites bind the FLOW to them, which is the thing a caller actually observes;
// binding the predicate alone is what let the 0.10.0 regression through.

// ---------------------------------------------------------------------------
// GAP 1 — the answer language comes from the chain; the evidence languages are
// observed. Both were the literal "en" before.
// ---------------------------------------------------------------------------

type languageVector struct {
	Name      string `json:"name"`
	Detection *struct {
		IsReliable bool `json:"is_reliable"`
	} `json:"detection"`
	AnswerLanguage        *string  `json:"answer_language"`
	ConversationLanguage  *string  `json:"conversation_language"`
	LanguagesInEvidence   []string `json:"languages_in_evidence"`
	DefaultAnswerLanguage string   `json:"default_answer_language"`
	Expected              string   `json:"expected"`
}

// expectedLanguageVectors pins conformance/cases/language.json, and
// expectedFlowDrivableLanguageVectors pins how many of them this port's flow can
// EXPRESS. The port has no detector and no conversation state, and its rung-4
// default is fixed at "en", so a case that turns on any of those three is not
// reproducible here — but the count of reproducible ones is pinned so the subset
// cannot silently shrink to nothing.
const (
	expectedLanguageVectors             = 6
	expectedFlowDrivableLanguageVectors = 4
)

// flowDrivable reports whether this port's flow can reproduce the committed
// case, i.e. whether the committed `expected` is still the right answer when the
// only input the flow accepts is the caller's answer-language request.
func (v languageVector) flowDrivable() bool {
	if v.DefaultAnswerLanguage != defaultAnswerLanguage {
		return false
	}
	if v.AnswerLanguage != nil && *v.AnswerLanguage != "" {
		return true // rung 1 wins outright; the rungs below cannot matter.
	}
	return v.ConversationLanguage == nil && (v.Detection == nil || !v.Detection.IsReliable)
}

func TestFlowResolvesTheAnswerLanguageThroughTheChain(t *testing.T) {
	var vectors []languageVector
	conform.Case(t, "language.json", &vectors)
	if len(vectors) != expectedLanguageVectors {
		t.Fatalf("language.json: got %d vectors, want %d", len(vectors), expectedLanguageVectors)
	}

	const passage = "The employee shall not disclose confidential information."
	drivable := 0
	for _, v := range vectors {
		if !v.flowDrivable() {
			continue
		}
		drivable++
		request := ""
		if v.AnswerLanguage != nil {
			request = *v.AnswerLanguage
		}
		got, err := AskWith(
			[]Doc{{DocumentID: "doc", Text: passage}}, passage, DefaultTopK,
			Providers{AnswerLanguage: request},
		)
		if err != nil {
			t.Fatalf("%s: %v", v.Name, err)
		}
		// The committed expectation, read from the fixture — never re-derived by
		// calling ResolveAnswerLanguage here.
		if got.AnswerLanguage != v.Expected {
			t.Errorf("%s: answer_language = %q, want %q", v.Name, got.AnswerLanguage, v.Expected)
		}
	}
	if drivable != expectedFlowDrivableLanguageVectors {
		t.Fatalf("flow-drivable language vectors = %d, want %d", drivable, expectedFlowDrivableLanguageVectors)
	}
}

func TestFlowReportsObservedEvidenceLanguagesNotTheAnswerLanguage(t *testing.T) {
	var vectors []languageVector
	conform.Case(t, "language.json", &vectors)
	if len(vectors) != expectedLanguageVectors {
		t.Fatalf("language.json: got %d vectors, want %d", len(vectors), expectedLanguageVectors)
	}

	const passage = "The employee shall not disclose confidential information."
	for _, v := range vectors {
		// Stamp the committed evidence languages onto real documents. They are an
		// OBSERVATION to report, never an input to the chain — so whatever they
		// are, they must come back out on languages_in_evidence, distinct and in
		// pool order, and they must NOT move answer_language.
		corpus := make([]Doc, 0, len(v.LanguagesInEvidence)+1)
		want := []string{}
		seen := map[string]bool{}
		for i, language := range v.LanguagesInEvidence {
			corpus = append(corpus, Doc{
				DocumentID: string(rune('a' + i)), Text: passage, Language: language,
			})
			if !seen[language] {
				seen[language] = true
				want = append(want, language)
			}
		}
		if len(corpus) == 0 {
			corpus = append(corpus, Doc{DocumentID: "a", Text: passage})
		}
		got, err := AskWith(corpus, passage, DefaultTopK, Providers{})
		if err != nil {
			t.Fatalf("%s: %v", v.Name, err)
		}
		if !reflect.DeepEqual(got.Evidence.LanguagesInEvidence, want) {
			t.Errorf("%s: languages_in_evidence = %q, want %q",
				v.Name, got.Evidence.LanguagesInEvidence, want)
		}
		// The cited passage reports the DOCUMENT's declared language, or the
		// pinned "und" — never the answer language. This is the assertion that
		// fails if anyone reintroduces the `passageLanguage: answerLanguage`
		// shortcut.
		wantPassageLanguage := undeclaredLanguage
		if len(v.LanguagesInEvidence) > 0 {
			wantPassageLanguage = v.LanguagesInEvidence[0]
		}
		if len(got.Sources) != 1 || got.Sources[0].PassageLanguage != wantPassageLanguage {
			t.Errorf("%s: passage_language = %+v, want %q",
				v.Name, got.Sources, wantPassageLanguage)
		}
	}
}

// ---------------------------------------------------------------------------
// GAP 2 — unsupported_scripts is populated from the tokenizer, so "I cannot read
// this script" is distinguishable from "I have no evidence". It was always [].
// ---------------------------------------------------------------------------

type scriptVector struct {
	Script             string   `json:"script"`
	Text               string   `json:"text"`
	UnsupportedScripts []string `json:"unsupported_scripts"`
}

// The bucket sizes of conformance/cases/tokenize_v2.json.
const (
	expectedClaimedScriptVectors   = 14
	expectedUnclaimedScriptVectors = 11
)

func loadScriptVectors(t *testing.T) (claimed, unclaimed []scriptVector) {
	t.Helper()
	var fixture struct {
		Supported []scriptVector `json:"supported"`
		Unclaimed []scriptVector `json:"unclaimed"`
	}
	conform.Case(t, "tokenize_v2.json", &fixture)
	if len(fixture.Supported) != expectedClaimedScriptVectors {
		t.Fatalf("tokenize_v2.json supported: got %d, want %d",
			len(fixture.Supported), expectedClaimedScriptVectors)
	}
	if len(fixture.Unclaimed) != expectedUnclaimedScriptVectors {
		t.Fatalf("tokenize_v2.json unclaimed: got %d, want %d",
			len(fixture.Unclaimed), expectedUnclaimedScriptVectors)
	}
	return fixture.Supported, fixture.Unclaimed
}

func TestFlowRefusesAnUnreadableQuestionAsACapabilityGap(t *testing.T) {
	_, unclaimed := loadScriptVectors(t)
	for _, v := range unclaimed {
		got, err := AskWith([]Doc{{DocumentID: "doc", Text: v.Text}}, v.Text, DefaultTopK, Providers{})
		if err != nil {
			t.Fatalf("%s: %v", v.Script, err)
		}
		if got.Evidence.Decision != "refused" {
			t.Errorf("%s: decision = %q, want refused", v.Script, got.Evidence.Decision)
		}
		// The committed capability signal, read from the fixture. Before this
		// wiring the flow returned [] here and the caller could not tell an
		// unreadable script from an empty corpus.
		if !reflect.DeepEqual(got.Evidence.UnsupportedScripts, v.UnsupportedScripts) {
			t.Errorf("%s: unsupported_scripts = %q, want %q",
				v.Script, got.Evidence.UnsupportedScripts, v.UnsupportedScripts)
		}
		wantReason := "unsupported script: " + strings.Join(v.UnsupportedScripts, ", ")
		if len(got.MissingEvidence) == 0 || got.MissingEvidence[0] != wantReason {
			t.Errorf("%s: missing_evidence = %q, want first %q",
				v.Script, got.MissingEvidence, wantReason)
		}
	}
}

func TestFlowReportsNoScriptGapForEveryClaimedScript(t *testing.T) {
	claimed, _ := loadScriptVectors(t)
	for _, v := range claimed {
		got, err := AskWith([]Doc{{DocumentID: "doc", Text: v.Text}}, v.Text, DefaultTopK, Providers{})
		if err != nil {
			t.Fatalf("%s: %v", v.Script, err)
		}
		if !reflect.DeepEqual(got.Evidence.UnsupportedScripts, v.UnsupportedScripts) {
			t.Errorf("%s: unsupported_scripts = %q, want %q (committed)",
				v.Script, got.Evidence.UnsupportedScripts, v.UnsupportedScripts)
		}
		if got.Evidence.Decision != "answered" {
			t.Errorf("%s: decision = %q, want answered", v.Script, got.Evidence.Decision)
		}
	}
}

// ---------------------------------------------------------------------------
// GAP 3 — verification is per ATOMIC CLAIM with drop-not-fail. The port used to
// gate the whole answer string as one claim, so it passed or refused WHOLE.
// ---------------------------------------------------------------------------

type faithfulVector struct {
	Name      string `json:"name"`
	Passage   string `json:"passage"`
	Answer    string `json:"answer"`
	Supported bool   `json:"supported"`
}

// The bucket sizes of conformance/cases/faithful_v2.json.
const (
	expectedFaithfulAttacks  = 9
	expectedFaithfulControls = 30
)

func loadFaithfulVectors(t *testing.T) (attacks, controls []faithfulVector) {
	t.Helper()
	var fixture struct {
		Attacks  []faithfulVector `json:"attacks"`
		Controls []faithfulVector `json:"controls"`
	}
	conform.Case(t, "faithful_v2.json", &fixture)
	if len(fixture.Attacks) != expectedFaithfulAttacks {
		t.Fatalf("faithful_v2.json attacks: got %d, want %d",
			len(fixture.Attacks), expectedFaithfulAttacks)
	}
	if len(fixture.Controls) != expectedFaithfulControls {
		t.Fatalf("faithful_v2.json controls: got %d, want %d",
			len(fixture.Controls), expectedFaithfulControls)
	}
	return fixture.Attacks, fixture.Controls
}

type fixedGenerator struct{ out string }

func (g fixedGenerator) Answer(_, _, _ string) (string, error) { return g.out, nil }

// The drop-not-fail contract, over the committed adversarial vectors: a
// generation that is one VERBATIM sentence followed by the committed FALSE one
// must return the verbatim half and drop the lie — with both verdicts recorded.
// Before this change the port refused BOTH halves and the caller lost a true,
// cited sentence to its neighbour.
func TestFlowDropsAnUnsupportedClaimAndKeepsTheSupportedOne(t *testing.T) {
	attacks, _ := loadFaithfulVectors(t)
	for _, v := range attacks {
		if v.Supported {
			t.Fatalf("%s: attack vector is committed as supported", v.Name)
		}
		generated := v.Passage + " " + v.Answer
		got, err := AskWith(
			[]Doc{{DocumentID: "doc", Text: v.Passage}}, v.Passage, DefaultTopK,
			Providers{Generator: fixedGenerator{out: generated}},
		)
		if err != nil {
			t.Fatalf("%s: %v", v.Name, err)
		}
		if got.Evidence.Decision != "answered" {
			t.Errorf("%s: decision = %q, want answered (the verbatim half survives)",
				v.Name, got.Evidence.Decision)
		}
		if got.Answer != v.Passage {
			t.Errorf("%s: answer = %q, want the verbatim half %q", v.Name, got.Answer, v.Passage)
		}
		if got.Evidence.AllClaimsVerified {
			t.Errorf("%s: all_claims_verified = true, want false", v.Name)
		}
		if got.Evidence.UnsupportedClaimsRemoved != 1 {
			t.Errorf("%s: unsupported_claims_removed = %d, want 1",
				v.Name, got.Evidence.UnsupportedClaimsRemoved)
		}
		want := []struct {
			text      string
			supported bool
		}{{v.Passage, true}, {v.Answer, false}}
		if len(got.Claims) != len(want) {
			t.Fatalf("%s: %d claims, want %d: %+v", v.Name, len(got.Claims), len(want), got.Claims)
		}
		for i, w := range want {
			if got.Claims[i].Claim != w.text || got.Claims[i].Supported != w.supported {
				t.Errorf("%s: claim %d = %+v, want %q supported=%v",
					v.Name, i, got.Claims[i], w.text, w.supported)
			}
		}
		// The dropped claim cites nothing: an unsupported claim must never carry
		// an evidence-unit id, or a caller could follow the citation and find the
		// lie "sourced".
		if len(got.Claims[1].Sources) != 0 {
			t.Errorf("%s: dropped claim cites %q, want none", v.Name, got.Claims[1].Sources)
		}
	}
}

// An answer with NO surviving claim is still a whole refusal, and it is the
// GATE's refusal — not the evidence-absent one. Over the committed attacks.
func TestFlowRefusesWhenNoClaimSurvives(t *testing.T) {
	attacks, _ := loadFaithfulVectors(t)
	for _, v := range attacks {
		got, err := AskWith(
			[]Doc{{DocumentID: "doc", Text: v.Passage}}, v.Passage, DefaultTopK,
			Providers{Generator: fixedGenerator{out: v.Answer}},
		)
		if err != nil {
			t.Fatalf("%s: %v", v.Name, err)
		}
		if got.Evidence.Decision != "refused" {
			t.Errorf("%s: decision = %q, want refused", v.Name, got.Evidence.Decision)
		}
		const wantReason = "generated answer failed the faithfulness gate"
		if len(got.MissingEvidence) == 0 || got.MissingEvidence[0] != wantReason {
			t.Errorf("%s: missing_evidence = %q, want first %q",
				v.Name, got.MissingEvidence, wantReason)
		}
	}
}

// Every committed CONTROL answers whole, with nothing dropped.
func TestFlowKeepsEveryControlAnswerWhole(t *testing.T) {
	_, controls := loadFaithfulVectors(t)
	for _, v := range controls {
		if !v.Supported {
			t.Fatalf("%s: control vector is committed as unsupported", v.Name)
		}
		got, err := AskWith(
			[]Doc{{DocumentID: "doc", Text: v.Passage}}, v.Passage, DefaultTopK,
			Providers{Generator: fixedGenerator{out: v.Answer}},
		)
		if err != nil {
			t.Fatalf("%s: %v", v.Name, err)
		}
		if got.Evidence.Decision != "answered" {
			t.Errorf("%s: decision = %q, want answered", v.Name, got.Evidence.Decision)
		}
		if !got.Evidence.AllClaimsVerified || got.Evidence.UnsupportedClaimsRemoved != 0 {
			t.Errorf("%s: all_claims_verified=%v removed=%d, want true/0",
				v.Name, got.Evidence.AllClaimsVerified, got.Evidence.UnsupportedClaimsRemoved)
		}
		if got.Answer != strings.Join(SplitClaims(v.Answer), " ") {
			t.Errorf("%s: answer = %q, want the whole committed answer", v.Name, got.Answer)
		}
	}
}
