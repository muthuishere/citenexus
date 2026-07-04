// Package answer is the hermetic cite-or-abstain ASK flow for the Go CiteNexus
// port (SPEC-PORTS-v1 §0/§7). It is the guarantee: an answer is emitted only
// when a retrieved passage is relevant to the question AND the generated answer
// is fully supported by that passage; otherwise the flow refuses. It mirrors the
// Python reference citenexus.smoke.pipeline.SmokePipeline.ask exactly, over the
// deterministic fakes.
package answer

import (
	"sort"

	"github.com/muthuishere/citenexus/golang/fakes"
	"github.com/muthuishere/citenexus/golang/gate"
	"github.com/muthuishere/citenexus/golang/result"
)

// Doc is one corpus document: a stable id and its text.
type Doc struct {
	DocumentID string `json:"document_id"`
	Text       string `json:"text"`
}

// DefaultTopK is the retrieval cutoff used by the hermetic flow.
const DefaultTopK = 5

// row is one indexed evidence unit: a document embedded as a single EU.
type row struct {
	euID       string
	documentID string
	text       string
	vector     []float64
	order      int // corpus insertion order, for stable tie-breaking.
}

// Ask answers the question grounded in the corpus, or refuses. It mirrors
// SmokePipeline.ask: embed every doc as one EU, rank by descending cosine to the
// question (stable by insertion order on ties), keep the top topK, filter to rows
// that share a content token with the question, then require the echoed answer to
// pass the faithfulness gate before answering.
func Ask(corpus []Doc, question string, topK int) result.Result {
	embedder := fakes.FakeEmbedding{}

	rows := make([]row, len(corpus))
	for i, doc := range corpus {
		rows[i] = row{
			euID:       doc.DocumentID + "::0",
			documentID: doc.DocumentID,
			text:       doc.Text,
			vector:     embedder.Embed(doc.Text),
			order:      i,
		}
	}

	qvec := embedder.Embed(question)
	scores := make([]float64, len(rows))
	for i := range rows {
		scores[i] = fakes.Cosine(qvec, rows[i].vector)
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
		return result.Refused(result.TrustModeStrict)
	}

	top := grounded[0]
	passage := top.text
	ans := fakes.FakeLLM{}.Answer(question, passage)

	// Faithfulness gate: never emit an ungrounded claim. This gate is the product.
	if !gate.IsSupported(ans, passage) {
		return result.Refused(result.TrustModeStrict)
	}

	distinct := make(map[string]struct{}, len(grounded))
	for _, r := range grounded {
		distinct[r.documentID] = struct{}{}
	}

	return result.Result{
		Answer:         ans,
		AnswerLanguage: "en",
		Mode:           result.TrustModeStrict,
		Evidence: result.EvidenceSignals{
			Decision:            result.DecisionAnswered,
			SupportingSources:   len(grounded),
			DistinctDocuments:   len(distinct),
			AllClaimsVerified:   true,
			LanguagesInEvidence: []string{"en"},
		},
		Claims: []result.Claim{
			{Claim: ans, Supported: true, Sources: []string{top.euID}},
		},
		Sources: []result.SourceRef{
			{Document: top.documentID, Passage: passage, PassageLanguage: "en"},
		},
		MissingEvidence: []string{},
		Conflicts:       []string{},
		Provenance:      []result.ProvenanceEntry{},
	}
}
