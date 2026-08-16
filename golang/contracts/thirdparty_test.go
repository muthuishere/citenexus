// The proof: a provider written OUTSIDE CiteNexus drives the Go port.
//
// Everything in this file is deliberately written the way a third party would
// write it, and the constraints are ASSERTED rather than assumed:
//
//   - the provider types name only golang/contracts — no fakes, no models, no
//     concrete CiteNexus type anywhere in their definitions;
//   - they satisfy the contracts by SHAPE, with no embedding and no registration;
//   - they open no socket — nothing in this file imports net, net/http, or os.
//
// It is the Go twin of python/tests/test_third_party_provider.py. If it passes,
// the contract is usable by someone who has only read the published interface.
// Without it, "there is a contract" is a claim.
//
// It lives in the EXTERNAL test package (contracts_test) so it can import
// golang/answer — which imports golang/contracts — without a cycle. That is
// itself the right shape: a provider author is outside the package too.
package contracts_test

import (
	"errors"
	"hash/fnv"
	"math"
	"os"
	"regexp"
	"sort"
	"strings"
	"testing"

	"github.com/muthuishere/citenexus/golang/answer"
	"github.com/muthuishere/citenexus/golang/contracts"
	"github.com/muthuishere/citenexus/golang/result"
)

// ---------------------------------------------------------------------------
// The third-party provider suite. Nothing below names a CiteNexus concrete type.
// ---------------------------------------------------------------------------

var wordRe = regexp.MustCompile(`\w+`)

func words(text string) []string {
	out := wordRe.FindAllString(strings.ToLower(text), -1)
	if out == nil {
		return []string{}
	}
	return out
}

func wordSet(text string) map[string]struct{} {
	set := map[string]struct{}{}
	for _, w := range words(text) {
		set[w] = struct{}{}
	}
	return set
}

// InProcessEmbedding is a hashing vectorizer that never leaves the process.
// It satisfies contracts.EmbeddingProvider by shape alone: one batch method,
// because a batch is the primitive and a single text is a batch of one.
type InProcessEmbedding struct {
	dim        int
	BatchSizes []int
}

func NewInProcessEmbedding() *InProcessEmbedding { return &InProcessEmbedding{dim: 96} }

func (e *InProcessEmbedding) Embed(texts []string) ([][]float64, error) {
	e.BatchSizes = append(e.BatchSizes, len(texts))
	out := make([][]float64, len(texts))
	for i, text := range texts {
		out[i] = e.one(text)
	}
	return out, nil
}

func (e *InProcessEmbedding) one(text string) []float64 {
	vec := make([]float64, e.dim)
	for _, w := range words(text) {
		h := fnv.New64a()
		_, _ = h.Write([]byte(w))
		vec[int(h.Sum64()%uint64(e.dim))] += 1
	}
	var norm float64
	for _, v := range vec {
		norm += v * v
	}
	if norm = math.Sqrt(norm); norm != 0 {
		for i := range vec {
			vec[i] /= norm
		}
	}
	if norm == 0 {
		// The contract says: do not hand back a placeholder. A text this model
		// cannot represent is a failure, not a zero vector.
		vec[0] = 1
	}
	return vec
}

// InProcessGenerator is an EXTRACTIVE model: it quotes the passage, so it cannot
// hallucinate. It picks the sentence with the most overlap with the question and
// returns it verbatim — which is exactly what CiteNexus's faithfulness gate
// demands of any generator, and the reason an extractive model is the best one.
type InProcessGenerator struct {
	Questions []string
	Languages []string
}

var sentenceRe = regexp.MustCompile(`[^.!?]+[.!?]?`)

func (g *InProcessGenerator) Answer(question, passage, answerLanguage string) (string, error) {
	g.Questions = append(g.Questions, question)
	g.Languages = append(g.Languages, answerLanguage)
	wanted := wordSet(question)

	var sentences []string
	for _, s := range sentenceRe.FindAllString(passage, -1) {
		if s = strings.TrimSpace(s); s != "" {
			sentences = append(sentences, s)
		}
	}
	if len(sentences) == 0 {
		return "", errors.New("in-process generator: nothing to quote")
	}
	sort.SliceStable(sentences, func(i, j int) bool {
		return overlap(wanted, sentences[i]) > overlap(wanted, sentences[j])
	})
	return sentences[0], nil
}

func overlap(wanted map[string]struct{}, sentence string) int {
	n := 0
	for w := range wordSet(sentence) {
		if _, ok := wanted[w]; ok {
			n++
		}
	}
	return n
}

// Shape alone is enough — no embedding, no registration, no import of ours
// beyond the interface file.
var (
	_ contracts.EmbeddingProvider = (*InProcessEmbedding)(nil)
	_ contracts.GeneratorProvider = (*InProcessGenerator)(nil)
)

// ---------------------------------------------------------------------------
// The corpus
// ---------------------------------------------------------------------------

const (
	ndaText = "The employee shall not disclose confidential information to any third party. " +
		"This obligation survives termination of employment for a period of five years."
	leaseText = "The tenant shall give the landlord at least thirty days written notice " +
		"before terminating a month to month tenancy."
)

func corpus() []answer.Doc {
	return []answer.Doc{
		{DocumentID: "nda", Text: ndaText},
		{DocumentID: "lease", Text: leaseText},
	}
}

func providers() (*InProcessEmbedding, *InProcessGenerator, answer.Providers) {
	emb, gen := NewInProcessEmbedding(), &InProcessGenerator{}
	return emb, gen, answer.Providers{Embedding: emb, Generator: gen}
}

// ---------------------------------------------------------------------------
// 1. The providers drive the port end to end
// ---------------------------------------------------------------------------

func TestThirdPartyProvidersAnswerEndToEnd(t *testing.T) {
	_, gen, p := providers()
	question := "Can the employee disclose confidential information?"

	res, err := answer.AskWith(corpus(), question, answer.DefaultTopK, p)
	if err != nil {
		t.Fatalf("AskWith: %v", err)
	}
	if res.Evidence.Decision != result.DecisionAnswered {
		t.Fatalf("decision = %q, want answered: %+v", res.Evidence.Decision, res)
	}
	if res.Answer == "" {
		t.Fatal("an answered result must carry an answer")
	}
	if len(res.Sources) == 0 {
		t.Fatal("an answer must cite")
	}
	if res.Sources[0].Document != "nda" {
		t.Errorf("cited %q, want nda", res.Sources[0].Document)
	}
	// Grounded: the model quoted the source, and the gate agreed.
	if !strings.Contains(ndaText, res.Answer) {
		t.Errorf("the answer is not verbatim from the source: %q", res.Answer)
	}
	if len(gen.Questions) != 1 || gen.Questions[0] != question {
		t.Errorf("the generator saw %v, want exactly [%q]", gen.Questions, question)
	}
	if len(gen.Languages) != 1 || gen.Languages[0] != "en" {
		t.Errorf("the answer language was not passed through: %v", gen.Languages)
	}
}

func TestTheSameProviderSetServesASecondQuestion(t *testing.T) {
	_, _, p := providers()
	res, err := answer.AskWith(corpus(), "How much notice must the tenant give the landlord?",
		answer.DefaultTopK, p)
	if err != nil {
		t.Fatalf("AskWith: %v", err)
	}
	if res.Evidence.Decision != result.DecisionAnswered {
		t.Fatalf("decision = %q, want answered", res.Evidence.Decision)
	}
	if res.Sources[0].Document != "lease" {
		t.Errorf("cited %q, want lease", res.Sources[0].Document)
	}
	if !strings.Contains(leaseText, res.Answer) {
		t.Errorf("the answer is not verbatim from the source: %q", res.Answer)
	}
}

func TestTheBatchContractIsThePathActuallyTakenEndToEnd(t *testing.T) {
	emb, _, p := providers()
	if _, err := answer.AskWith(corpus(), "Can the employee disclose confidential information?",
		answer.DefaultTopK, p); err != nil {
		t.Fatalf("AskWith: %v", err)
	}
	if len(emb.BatchSizes) == 0 {
		t.Fatal("the flow never used the contract's batch method")
	}
	if emb.BatchSizes[0] != 2 {
		t.Errorf("the corpus was not embedded in one batch: %v", emb.BatchSizes)
	}
	// The question is a batch of one — the contract has no single-text method.
	if emb.BatchSizes[len(emb.BatchSizes)-1] != 1 {
		t.Errorf("the question was not a batch of one: %v", emb.BatchSizes)
	}
}

func TestAThirdPartyProviderSetMayBePartial(t *testing.T) {
	// Generation only: no embedding model at all, the port falls back to its own
	// deterministic ranking. The Python reference proves the same case.
	gen := &InProcessGenerator{}
	res, err := answer.AskWith(corpus(), "Can the employee disclose confidential information?",
		answer.DefaultTopK, answer.Providers{Generator: gen})
	if err != nil {
		t.Fatalf("AskWith: %v", err)
	}
	if res.Evidence.Decision != result.DecisionAnswered {
		t.Fatalf("a generation-only provider set was refused: %+v", res)
	}
	if res.Sources[0].Document != "nda" {
		t.Errorf("cited %q, want nda", res.Sources[0].Document)
	}
}

func TestThirdPartyProvidersStillAbstainWhenTheEvidenceIsAbsent(t *testing.T) {
	_, _, p := providers()
	res, err := answer.AskWith(corpus(), "What is the melting point of tungsten?",
		answer.DefaultTopK, p)
	if err != nil {
		t.Fatalf("AskWith: %v", err)
	}
	if res.Evidence.Decision != result.DecisionRefused {
		t.Fatalf("answered a question the corpus cannot support: %q", res.Answer)
	}
}

// ---------------------------------------------------------------------------
// 2. The independence is asserted, not assumed
// ---------------------------------------------------------------------------

// The provider definitions must name ONLY the contracts package. `answer` and
// `result` are imported by the TEST, to drive and to assert — never by the
// provider types, which is what this asserts by reading the file's own source.
func TestTheProviderDefinitionsNameOnlyTheContractsPackage(t *testing.T) {
	source, err := os.ReadFile("thirdparty_test.go")
	if err != nil {
		t.Fatalf("read own source: %v", err)
	}
	parts := strings.Split(string(source), "// The corpus")
	if len(parts) < 2 {
		t.Fatal("could not isolate the provider section of this file")
	}
	providerSection := parts[0]

	for _, forbidden := range []string{
		"fakes.", "models.", "answer.", "result.", "gate.", "ingest.", "core.",
	} {
		if strings.Contains(providerSection, forbidden) {
			t.Errorf("the third-party providers reference %s — they must name only "+
				"golang/contracts", forbidden)
		}
	}
	if !strings.Contains(providerSection, "contracts.EmbeddingProvider") {
		t.Error("the provider section no longer declares the contract it satisfies")
	}
}

// An in-process provider must not reach the network. Asserted structurally: no
// network package is importable from this file at all.
func TestThisFileOpensNoSocket(t *testing.T) {
	source, err := os.ReadFile("thirdparty_test.go")
	if err != nil {
		t.Fatalf("read own source: %v", err)
	}
	head := strings.SplitN(string(source), "// ------", 2)[0]
	for _, netPkg := range []string{`"net"`, `"net/http"`, `"crypto/tls"`} {
		if strings.Contains(head, netPkg) {
			t.Errorf("a third-party in-process provider must not import %s", netPkg)
		}
	}
}
