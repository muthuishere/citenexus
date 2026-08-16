// The injectable twin of Ask (ADR-0014 R4).
//
// golang/contracts publishes the model seam; this file is what makes that
// publication mean something. Before it, `Ask` constructed fakes.FakeEmbedding
// and fakes.FakeLLM INSIDE itself, so the port's only end-to-end path could not
// be reached by any provider a third party wrote — and a contract with no call
// site is decoration.
//
// `Ask` keeps its exact signature and behaviour: it is pinned byte-for-byte by
// conformance/cases/e2e_hermetic.json, which this change must not regenerate. It
// is now defined as AskWith with an empty provider set.

package answer

import (
	"fmt"
	"sort"

	"github.com/muthuishere/citenexus/golang/contracts"
	"github.com/muthuishere/citenexus/golang/fakes"
	"github.com/muthuishere/citenexus/golang/gate"
	"github.com/muthuishere/citenexus/golang/result"
)

// Providers are the models the flow runs on. A nil field falls back to this
// port's deterministic fake, so a PARTIAL set is valid — a caller with a real
// generator and no embedding model, or the reverse, is a supported shape (the
// Python reference proves the same case in
// test_a_third_party_provider_answers_without_an_embedding_model).
//
// Only the two seams the Go port consumes appear here. There is no Vision,
// Completion or Reranker field because there is nothing in this port that would
// call one; see golang/contracts.
type Providers struct {
	// Embedding ranks the corpus against the question. Batch is the primitive.
	Embedding contracts.EmbeddingProvider
	// Generator turns the selected passage into an answer. It is NOT trusted:
	// its output goes through the faithfulness gate below before it can be
	// emitted, which is why an extractive generator is the best kind.
	Generator contracts.GeneratorProvider
}

// answerLanguage is fixed at "en" in this port. Python resolves it from config
// (including the "auto" sentinel, which means "answer in the query's language");
// the Go port has no config layer and no ask() facade over one, so it does not
// pretend to. The parameter is still passed through the contract so a provider
// sees the same signature it sees in Python.
const answerLanguage = "en"

// AskWith answers question grounded in corpus using the injected providers, or
// refuses. Same flow as Ask — embed, rank by cosine, keep topK, require a shared
// content token, then require the generated answer to pass the faithfulness
// gate — with the models supplied by the caller.
//
// FAILURE IS AN ERROR, NOT A REFUSAL. A refusal is a finding: "we searched the
// evidence and it does not support an answer." A timed-out embedding model is
// not a finding about the evidence, and reporting it as one would be the same
// class of lie as the zero vector ADR-0014 R2 removed — a failure wearing the
// costume of a successful negative result. On error the returned Result is the
// zero value, deliberately NOT a refusal.
func AskWith(corpus []Doc, question string, topK int, providers Providers) (result.Result, error) {
	embedding, injectedEmbedding := providers.Embedding, providers.Embedding != nil
	if !injectedEmbedding {
		embedding = hermeticEmbedding{}
	}
	generator := providers.Generator
	if generator == nil {
		generator = hermeticGenerator{}
	}

	texts := make([]string, len(corpus))
	for i, doc := range corpus {
		texts[i] = doc.Text
	}

	// ONE batch call for the whole corpus — the contract's primitive.
	docVectors, err := contracts.EmbedTexts(embedding, texts)
	if err != nil {
		return result.Result{}, fmt.Errorf("answer: embed corpus: %w", err)
	}

	dim := 0
	rows := make([]row, len(corpus))
	for i, doc := range corpus {
		vec := docVectors[i]
		// The write-path guard, applied to the ask path. It runs only for an
		// INJECTED provider: the hermetic fake is this port's own reference
		// implementation, pinned by the conformance fixture, and validating our
		// own pinned output would only be able to disagree with the fixture.
		// (A token-less document legitimately embeds to zeros there, and must
		// still lead to a refusal rather than an error.)
		if injectedEmbedding {
			if err := contracts.CheckVector(doc.DocumentID, vec, dim); err != nil {
				return result.Result{}, fmt.Errorf("answer: %w", err)
			}
			dim = len(vec)
		}
		rows[i] = row{
			euID:       doc.DocumentID + "::0",
			documentID: doc.DocumentID,
			text:       doc.Text,
			vector:     vec,
			order:      i,
		}
	}

	// A single text is a batch of one — the contract has no second method.
	qvec, err := contracts.EmbedOne(embedding, question)
	if err != nil {
		return result.Result{}, fmt.Errorf("answer: embed question: %w", err)
	}
	if injectedEmbedding {
		if err := contracts.CheckVector("question", qvec, dim); err != nil {
			return result.Result{}, fmt.Errorf("answer: %w", err)
		}
	}

	scores := make([]float64, len(rows))
	for i := range rows {
		scores[i] = dot(qvec, rows[i].vector)
	}

	ranked := make([]row, len(rows))
	copy(ranked, rows)
	sort.SliceStable(ranked, func(i, j int) bool {
		return scores[ranked[i].order] > scores[ranked[j].order]
	})
	if topK < len(ranked) {
		ranked = ranked[:topK]
	}

	// Relevance gate: keep only rows sharing a content token with the question.
	grounded := make([]row, 0, len(ranked))
	for _, r := range ranked {
		if gate.HasRelevanceOverlap(question, r.text) {
			grounded = append(grounded, r)
		}
	}
	if len(grounded) == 0 {
		return result.Refused(result.TrustModeStrict), nil
	}

	top := grounded[0]
	passage := top.text
	ans, err := generator.Answer(question, passage, answerLanguage)
	if err != nil {
		return result.Result{}, fmt.Errorf("answer: generate: %w", err)
	}

	// Faithfulness gate: never emit an ungrounded claim. It runs on injected
	// output exactly as it runs on the fake's — this gate is the product, and it
	// does not soften because the caller supplied the model.
	if !gate.IsSupported(ans, passage) {
		return result.Refused(result.TrustModeStrict), nil
	}

	distinct := make(map[string]struct{}, len(grounded))
	for _, r := range grounded {
		distinct[r.documentID] = struct{}{}
	}

	return result.Result{
		Answer:         ans,
		AnswerLanguage: answerLanguage,
		Mode:           result.TrustModeStrict,
		Evidence: result.EvidenceSignals{
			Decision:            result.DecisionAnswered,
			SupportingSources:   len(grounded),
			DistinctDocuments:   len(distinct),
			AllClaimsVerified:   true,
			LanguagesInEvidence: []string{answerLanguage},
			UnsupportedScripts:  []string{},
		},
		Claims: []result.Claim{
			{Claim: ans, Supported: true, Sources: []string{top.euID}},
		},
		Sources: []result.SourceRef{
			{Document: top.documentID, Passage: passage, PassageLanguage: answerLanguage},
		},
		MissingEvidence: []string{},
		Conflicts:       []string{},
		Provenance:      []result.ProvenanceEntry{},
	}, nil
}

// dot is the cosine of two already-L2-normalized vectors, guarded against a
// length mismatch. fakes.Cosine indexes b[i] for every i in a and would panic on
// a shorter b; the dimension guard should make that unreachable, but
// "unreachable" is not a memory-safety argument when the vectors come from an
// arbitrary third-party provider.
func dot(a, b []float64) float64 {
	n := len(a)
	if len(b) < n {
		n = len(b)
	}
	var sum float64
	for i := 0; i < n; i++ {
		sum += a[i] * b[i]
	}
	return sum
}

// hermeticEmbedding wraps this port's deterministic fake in the published batch
// contract, so the fallback path and the injected path are ONE code path rather
// than two branches that can drift.
type hermeticEmbedding struct{}

func (hermeticEmbedding) Embed(texts []string) ([][]float64, error) {
	out := make([][]float64, len(texts))
	for i, text := range texts {
		out[i] = fakes.FakeEmbedding{}.Embed(text)
	}
	return out, nil
}

// hermeticGenerator wraps the evidence-echoing fake in the published contract.
// It cannot fail, which is why Ask can drop the error return.
type hermeticGenerator struct{}

func (hermeticGenerator) Answer(question, passage, _ string) (string, error) {
	return fakes.FakeLLM{}.Answer(question, passage), nil
}

// Compile-time proof that the fallbacks are the published contracts, not a
// private shortcut around them.
var (
	_ contracts.EmbeddingProvider = hermeticEmbedding{}
	_ contracts.GeneratorProvider = hermeticGenerator{}
)
