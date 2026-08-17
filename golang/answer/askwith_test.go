package answer

import (
	"errors"
	"strings"
	"testing"

	"github.com/muthuishere/citenexus/golang/internal/conform"
	"github.com/muthuishere/citenexus/golang/result"
)

// ---------------------------------------------------------------------------
// Test doubles written from OUTSIDE: they name only golang/contracts' shapes.
// ---------------------------------------------------------------------------

// tokenVec is a tiny deterministic vectorizer: one slot per letter of the
// alphabet, counting occurrences. Enough for relative ranking, and completely
// independent of the library's own fakes.
func tokenVec(text string) []float64 {
	vec := make([]float64, 26)
	for _, r := range strings.ToLower(text) {
		if r >= 'a' && r <= 'z' {
			vec[r-'a'] += 1
		}
	}
	return vec
}

type stubEmbedding struct {
	batches [][]string
	fail    error
	vector  func(text string) []float64
}

func (e *stubEmbedding) Embed(texts []string) ([][]float64, error) {
	e.batches = append(e.batches, append([]string(nil), texts...))
	if e.fail != nil {
		return nil, e.fail
	}
	fn := e.vector
	if fn == nil {
		fn = tokenVec
	}
	out := make([][]float64, len(texts))
	for i, t := range texts {
		out[i] = fn(t)
	}
	return out, nil
}

type stubGenerator struct {
	calls []string
	langs []string
	fail  error
	// reply, when set, replaces the extractive default — used to prove the
	// faithfulness gate still runs on INJECTED output.
	reply string
}

func (g *stubGenerator) Answer(question, passage, answerLanguage string) (string, error) {
	g.calls = append(g.calls, question)
	g.langs = append(g.langs, answerLanguage)
	if g.fail != nil {
		return "", g.fail
	}
	if g.reply != "" {
		return g.reply, nil
	}
	return passage, nil // extractive: quote the evidence
}

var errModelDown = errors.New("model call timed out after 30s")

var miniCorpus = []Doc{
	{DocumentID: "nda", Text: "The employee shall not disclose confidential information to any third party."},
	{DocumentID: "lease", Text: "The tenant shall give the landlord thirty days written notice."},
}

// ---------------------------------------------------------------------------
// 1. The pinned entry point is unchanged — Ask IS AskWith with no providers
// ---------------------------------------------------------------------------

func TestAskWithNoProvidersIsIdenticalToAsk(t *testing.T) {
	var fixture struct {
		Corpus []Doc `json:"corpus"`
		TopK   int   `json:"top_k"`
		Cases  []struct {
			Question string `json:"question"`
		} `json:"cases"`
	}
	conform.Case(t, "e2e_hermetic.json", &fixture)
	if len(fixture.Cases) != expectedE2ECounts["cases"] {
		t.Fatalf("e2e_hermetic.json: got %d cases, want %d", len(fixture.Cases), expectedE2ECounts["cases"])
	}
	if len(fixture.Corpus) != expectedE2ECounts["corpus"] {
		t.Fatalf("e2e_hermetic.json: got %d corpus docs, want %d", len(fixture.Corpus), expectedE2ECounts["corpus"])
	}
	if fixture.TopK != expectedE2ECounts["top_k"] {
		t.Fatalf("e2e_hermetic.json: top_k = %d, want %d", fixture.TopK, expectedE2ECounts["top_k"])
	}

	for _, c := range fixture.Cases {
		want := Ask(fixture.Corpus, c.Question, fixture.TopK)
		got, err := AskWith(fixture.Corpus, c.Question, fixture.TopK, Providers{})
		if err != nil {
			t.Fatalf("%q: AskWith with an empty provider set errored: %v", c.Question, err)
		}
		if got.Answer != want.Answer || got.Evidence.Decision != want.Evidence.Decision {
			t.Errorf("%q: AskWith diverged from Ask: %+v vs %+v", c.Question, got, want)
		}
		if len(got.Sources) != len(want.Sources) {
			t.Errorf("%q: source count diverged: %d vs %d", c.Question, len(got.Sources), len(want.Sources))
		}
		for i := range got.Sources {
			if got.Sources[i] != want.Sources[i] {
				t.Errorf("%q: source %d diverged", c.Question, i)
			}
		}
	}
}

// ---------------------------------------------------------------------------
// 2. Injected providers actually drive the flow
// ---------------------------------------------------------------------------

func TestInjectedProvidersProduceACitedAnswer(t *testing.T) {
	emb, gen := &stubEmbedding{}, &stubGenerator{}
	res, err := AskWith(miniCorpus, "Can the employee disclose confidential information?", 5,
		Providers{Embedding: emb, Generator: gen})
	if err != nil {
		t.Fatalf("AskWith: %v", err)
	}
	if res.Evidence.Decision != result.DecisionAnswered {
		t.Fatalf("decision = %q, want answered (%+v)", res.Evidence.Decision, res)
	}
	if len(res.Sources) == 0 {
		t.Fatal("an answer must cite")
	}
	if res.Sources[0].Document != "nda" {
		t.Errorf("cited %q, want nda", res.Sources[0].Document)
	}
	if !strings.Contains(miniCorpus[0].Text, res.Answer) {
		t.Errorf("answer is not verbatim from the cited passage: %q", res.Answer)
	}
	if len(gen.calls) != 1 {
		t.Errorf("the injected generator was called %d times, want 1", len(gen.calls))
	}
	if len(gen.langs) != 1 || gen.langs[0] != "en" {
		t.Errorf("the answer language was not passed through: %v", gen.langs)
	}
}

func TestTheBatchContractIsThePathActuallyTaken(t *testing.T) {
	emb := &stubEmbedding{}
	if _, err := AskWith(miniCorpus, "Can the employee disclose confidential information?", 5,
		Providers{Embedding: emb}); err != nil {
		t.Fatalf("AskWith: %v", err)
	}
	if len(emb.batches) != 2 {
		t.Fatalf("want two batch calls (corpus, then question), got %d: %v", len(emb.batches), emb.batches)
	}
	if len(emb.batches[0]) != len(miniCorpus) {
		t.Errorf("the corpus was not embedded in ONE batch: %v", emb.batches[0])
	}
	if len(emb.batches[1]) != 1 {
		t.Errorf("the question must be a batch of one, got %v", emb.batches[1])
	}
}

func TestAPartialProviderSetIsValid(t *testing.T) {
	q := "Can the employee disclose confidential information?"

	genOnly, err := AskWith(miniCorpus, q, 5, Providers{Generator: &stubGenerator{}})
	if err != nil {
		t.Fatalf("generator-only: %v", err)
	}
	if genOnly.Evidence.Decision != result.DecisionAnswered {
		t.Errorf("generator-only refused: %+v", genOnly)
	}

	embOnly, err := AskWith(miniCorpus, q, 5, Providers{Embedding: &stubEmbedding{}})
	if err != nil {
		t.Fatalf("embedding-only: %v", err)
	}
	if embOnly.Evidence.Decision != result.DecisionAnswered {
		t.Errorf("embedding-only refused: %+v", embOnly)
	}
}

// ---------------------------------------------------------------------------
// 3. A provider failure is an ERROR, never a refusal
// ---------------------------------------------------------------------------

func TestAnEmbeddingFailureIsAnErrorNotARefusal(t *testing.T) {
	res, err := AskWith(miniCorpus, "anything at all", 5,
		Providers{Embedding: &stubEmbedding{fail: errModelDown}})
	if !errors.Is(err, errModelDown) {
		t.Fatalf("the provider failure did not surface: %v", err)
	}
	// A refusal is a FINDING about the evidence. A dead model is not one.
	if res.Evidence.Decision == result.DecisionRefused {
		t.Error("a model failure was dressed up as an abstention")
	}
}

func TestAGeneratorFailureIsAnErrorNotARefusal(t *testing.T) {
	res, err := AskWith(miniCorpus, "Can the employee disclose confidential information?", 5,
		Providers{Generator: &stubGenerator{fail: errModelDown}})
	if !errors.Is(err, errModelDown) {
		t.Fatalf("the provider failure did not surface: %v", err)
	}
	if res.Evidence.Decision == result.DecisionRefused {
		t.Error("a model failure was dressed up as an abstention")
	}
}

// ---------------------------------------------------------------------------
// 4. Degenerate vectors from a NON-failing provider are still refused
// ---------------------------------------------------------------------------

func TestDegenerateVectorsFromAnInjectedProviderAreRefused(t *testing.T) {
	for _, c := range []struct {
		name string
		fn   func(string) []float64
		want string
	}{
		{"zero", func(string) []float64 { return make([]float64, 26) }, "zero vector"},
		{"empty", func(string) []float64 { return nil }, "empty vector"},
	} {
		_, err := AskWith(miniCorpus, "Can the employee disclose confidential information?", 5,
			Providers{Embedding: &stubEmbedding{vector: c.fn}})
		if err == nil {
			t.Errorf("%s: a degenerate vector was scored as if it carried signal", c.name)
			continue
		}
		if !strings.Contains(err.Error(), c.want) {
			t.Errorf("%s: error should name the problem, got %v", c.name, err)
		}
	}
}

func TestAnInconsistentDimensionIsRefused(t *testing.T) {
	n := 0
	ragged := func(text string) []float64 {
		n++
		return make2(n * 4)
	}
	_, err := AskWith(miniCorpus, "Can the employee disclose confidential information?", 5,
		Providers{Embedding: &stubEmbedding{vector: ragged}})
	if err == nil || !strings.Contains(err.Error(), "-dim vector") {
		t.Fatalf("a dimension-inconsistent run was accepted: %v", err)
	}
}

// make2 returns a non-zero vector of length n.
func make2(n int) []float64 {
	v := make([]float64, n)
	for i := range v {
		v[i] = 1
	}
	return v
}

// fakes.Cosine indexes b[i] for every i in a and PANICS on a shorter b. The
// dimension guard should make that unreachable through AskWith, but "unreachable"
// is not a memory-safety argument, so the scorer is length-guarded too.
func TestTheScorerIsLengthGuarded(t *testing.T) {
	defer func() {
		if r := recover(); r != nil {
			t.Fatalf("the scorer panicked on mismatched lengths: %v", r)
		}
	}()
	if got := dot([]float64{1, 1, 1}, []float64{1, 1}); got != 2 {
		t.Errorf("dot over the shared prefix = %v, want 2", got)
	}
	if got := dot([]float64{1, 1}, []float64{1, 1, 1}); got != 2 {
		t.Errorf("dot over the shared prefix = %v, want 2", got)
	}
}

// A provider whose vectors are far shorter than the hermetic fake's 64 must
// still work end to end — the flow must not assume a dimensionality.
func TestASmallDimensionProviderStillAnswers(t *testing.T) {
	res, err := AskWith(miniCorpus, "Can the employee disclose confidential information?", 5,
		Providers{Embedding: &stubEmbedding{vector: func(text string) []float64 {
			v := tokenVec(text)
			return []float64{v['e'-'a'] + 1, v['d'-'a'] + 1}
		}}})
	if err != nil {
		t.Fatalf("AskWith: %v", err)
	}
	if res.Evidence.Decision != result.DecisionAnswered {
		t.Errorf("a 2-dim provider was refused: %+v", res)
	}
}

// ---------------------------------------------------------------------------
// 5. The gate still runs on injected output — this is the product
// ---------------------------------------------------------------------------

func TestAnInjectedGeneratorThatParaphrasesIsRefused(t *testing.T) {
	res, err := AskWith(miniCorpus, "Can the employee disclose confidential information?", 5,
		Providers{Generator: &stubGenerator{reply: "Yes, the employee may freely share everything."}})
	if err != nil {
		t.Fatalf("AskWith: %v", err)
	}
	if res.Evidence.Decision != result.DecisionRefused {
		t.Fatalf("an ungrounded injected answer was emitted: %q", res.Answer)
	}
}

func TestAnInjectedGeneratorThatAddsAnUnsourcedWordIsRefused(t *testing.T) {
	// One word the passage does not contain is enough — this is the whole
	// guarantee, and it does not weaken because the model was injected.
	//
	// NOTE: the gate on this path is the FROZEN §4 v1 predicate, which is known
	// to accept negation-deletion and role-inversion attacks (that is what
	// spikes/library-stress measures and what verify-v2 fixes). AskWith
	// deliberately does not swap the gate: `Ask` is pinned by
	// conformance/cases/e2e_hermetic.json and the two must stay one flow.
	res, err := AskWith(miniCorpus, "Can the employee disclose confidential information?", 5,
		Providers{Generator: &stubGenerator{
			reply: "The employee shall not disclose confidential information to any competitor.",
		}})
	if err != nil {
		t.Fatalf("AskWith: %v", err)
	}
	if res.Evidence.Decision != result.DecisionRefused {
		t.Fatalf("an answer containing an unsourced word was emitted: %q", res.Answer)
	}
}

func TestAskWithRefusesWhenNothingIsRelevant(t *testing.T) {
	res, err := AskWith(miniCorpus, "zzzz qqqq", 5,
		Providers{Embedding: &stubEmbedding{}, Generator: &stubGenerator{}})
	if err != nil {
		t.Fatalf("AskWith: %v", err)
	}
	if res.Evidence.Decision != result.DecisionRefused {
		t.Fatalf("answered an unanswerable question: %+v", res)
	}
}
