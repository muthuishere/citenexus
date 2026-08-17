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
	// V2 (ADR-0011) tokenizes 14 scripts, not ASCII alone; under v1 a CJK or
	// Devanagari question and its own passage both tokenized to the empty set,
	// so this gate abstained before the faithfulness gate ever ran. Matches the
	// Python reference, which calls has_relevance_overlap_v2 here.
	grounded := make([]row, 0, len(ranked))
	for _, r := range ranked {
		if gate.HasRelevanceOverlapV2(question, r.text) {
			grounded = append(grounded, r)
		}
	}
	if len(grounded) == 0 {
		return result.Refused(result.TrustModeStrict), nil
	}

	// Conflict detection runs over the grounded candidates, BEFORE anything is
	// generated (ADR-0007), exactly as the Python reference does in
	// answer/flow.py. It reports and never resolves: picking a winner by rank,
	// recency or score is a policy decision belonging to the caller and to
	// authority (ADR-0004), and rank order deciding which of two contradictory
	// truths the caller sees is the defect this closes.
	window := grounded
	if k := ConflictTopK(); k < len(window) {
		window = window[:k]
	}
	conflictPairs := FindConflicts(textsOf(window))

	// Near-duplicate collapse feeds the corroboration signals only. The same
	// pairwise comparison that finds "same subject, opposite polarity" finds
	// "same subject, same text" — clones ingested under different document ids —
	// and those are one piece of evidence, not N.
	independent := make([]row, 0, len(grounded))
	for _, i := range CollapseNearDuplicates(textsOf(grounded)) {
		independent = append(independent, grounded[i])
	}

	top := grounded[0]
	const topIndex = 0 // this port generates from the first grounded candidate only
	passage := top.text
	ans, err := generator.Answer(question, passage, answerLanguage)
	if err != nil {
		return result.Result{}, fmt.Errorf("answer: generate: %w", err)
	}

	// Faithfulness gate: never emit an ungrounded claim. It runs on injected
	// output exactly as it runs on the fake's — this gate is the product, and it
	// does not soften because the caller supplied the model.
	//
	// V2 (ADR-0009), the predicate the Python reference uses at
	// answer/flow.py. The frozen v1 gate.IsSupported is SET CONTAINMENT, and a
	// set is closed under reordering and deletion: it accepted all nine
	// adversarial false answers (role inversion, negation deletion, value swap,
	// comparator inversion) because a lie built by permuting the passage's own
	// words has no token the passage lacks. V2 requires the claim's tokens to
	// appear IN ORDER within a bounded window and forbids a dropped polarity
	// marker. gate.IsSupported stays exported and frozen for the conformance
	// vectors; it is no longer what stands between a caller and a lie.
	if !gate.IsSupportedV2(ans, passage) {
		refusal := result.Refused(result.TrustModeStrict)
		// The gate owns this refusal, but the conflict count is a signal about
		// the evidence pool and it was already computed. Python carries it onto
		// the same refusal (flow.py's gate-failure Result).
		refusal.Evidence.ConflictsDetected = len(conflictPairs)
		return refusal, nil
	}

	// TrustMode coupling. An unresolved conflict touching the answer's own claim
	// — one whose two sides include the passage we are about to cite — is not
	// answerable in strict mode: the honest output is "these sources disagree,
	// here are both", not a coin flip on rank order. This can only ever produce
	// MORE abstention, so it cannot admit an ungrounded claim. Go is strict-only,
	// so unlike Python there is no normal/exploratory branch that surfaces the
	// conflict alongside an answer.
	touching := make([]ConflictPair, 0, len(conflictPairs))
	for _, pair := range conflictPairs {
		if pair.Left == topIndex || pair.Right == topIndex {
			touching = append(touching, pair)
		}
	}
	if len(touching) > 0 {
		return conflictAbstention(window, touching, len(conflictPairs), independent), nil
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

// textsOf is the citable text of each row, in order. The Python reference
// compares `citable_text` — the VERBATIM chunk — never the contextualized text;
// this port has no contextual-retrieval layer, so row.text IS the verbatim
// chunk.
func textsOf(rows []row) []string {
	out := make([]string, len(rows))
	for i, r := range rows {
		out[i] = r.text
	}
	return out
}

// conflictAbstention is the strict-mode abstention that CITES BOTH SIDES of the
// disagreement.
//
// A refusal that hides the evidence is only marginally better than a confident
// pick: the caller cannot check the library's reasoning or resolve the conflict
// themselves. Both passages are returned as sources, verbatim.
func conflictAbstention(window []row, touching []ConflictPair, totalConflicts int, independent []row) result.Result {
	documents := make([]string, len(window))
	for i, r := range window {
		documents[i] = r.documentID
	}

	cited := []result.SourceRef{}
	seen := map[string]struct{}{}
	for _, pair := range touching {
		for _, r := range [2]row{window[pair.Left], window[pair.Right]} {
			if _, ok := seen[r.euID]; ok {
				continue
			}
			seen[r.euID] = struct{}{}
			cited = append(cited, result.SourceRef{
				Document:        r.documentID,
				Passage:         r.text,
				PassageLanguage: answerLanguage,
			})
		}
	}

	distinct := map[string]struct{}{}
	for _, r := range independent {
		distinct[r.documentID] = struct{}{}
	}

	return result.Result{
		Answer:         result.ConflictRefusalAnswer,
		AnswerLanguage: answerLanguage,
		Mode:           result.TrustModeStrict,
		Evidence: result.EvidenceSignals{
			Decision:          result.DecisionRefused,
			SupportingSources: len(independent),
			DistinctDocuments: len(distinct),
			// RetrievalScoreSpread stays 0: this port's answered path does not
			// populate it either, and inventing a number on one path only would
			// make the two disagree about what the field means.
			ConflictsDetected:   totalConflicts,
			LanguagesInEvidence: []string{answerLanguage},
			UnsupportedScripts:  []string{},
		},
		Claims:          []result.Claim{},
		Sources:         cited,
		MissingEvidence: []string{"cited sources disagree and the conflict is unresolved"},
		Conflicts:       DescribeConflicts(touching, documents),
		Provenance:      []result.ProvenanceEntry{},
	}
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
