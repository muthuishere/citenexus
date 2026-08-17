// Package answer is the hermetic cite-or-abstain ASK flow for the Go CiteNexus
// port (SPEC-PORTS-v1 §0/§7). It is the guarantee: an answer is emitted only
// when a retrieved passage is relevant to the question AND the generated answer
// is fully supported by that passage; otherwise the flow refuses. It mirrors the
// Python reference citenexus.smoke.pipeline.SmokePipeline.ask exactly, over the
// deterministic fakes.
//
// Two entry points, one flow:
//
//   - Ask     — the pinned, hermetic one. Signature and behaviour frozen by
//     conformance/cases/e2e_hermetic.json.
//   - AskWith — the same flow with the model seam injected (askwith.go). This is
//     what gives golang/contracts a call site.
package answer

import "github.com/muthuishere/citenexus/golang/result"

// Doc is one corpus document: a stable id and its text.
type Doc struct {
	DocumentID string `json:"document_id"`
	Text       string `json:"text"`
	// Language is the document's declared language (a BCP-47-ish code such as
	// "te"). OPTIONAL and additive: it mirrors the Python reference's
	// Candidate.language, which is caller-supplied METADATA stamped at ingest —
	// it is never derived from the text here. Empty means "not declared", and
	// the cited SourceRef then reports the pinned "und" that Python emits for
	// `candidate.language or "und"`, NOT the answer language.
	//
	// Before this field existed the ports stamped every passage "en", so a
	// Telugu passage reported English and any caller branching on
	// passage_language was branching on a constant.
	Language string `json:"language,omitempty"`
}

// DefaultTopK is the retrieval cutoff used by the hermetic flow.
const DefaultTopK = 5

// row is one indexed evidence unit: a document embedded as a single EU.
type row struct {
	euID       string
	documentID string
	text       string
	language   string // declared document language; "" when undeclared.
	vector     []float64
	order      int // corpus insertion order, for stable tie-breaking.
}

// Ask answers the question grounded in the corpus, or refuses, using this
// port's deterministic fakes. It mirrors SmokePipeline.ask: embed every doc as
// one EU, rank by descending cosine to the question (stable by insertion order
// on ties), keep the top topK, filter to rows that share a content token with
// the question, then require the echoed answer to pass the faithfulness gate
// before answering.
//
// It is AskWith with an empty provider set. The signature keeps no error return
// because the hermetic fakes have no failure mode — they are pure functions of
// their input — so there is nothing for a caller to handle.
func Ask(corpus []Doc, question string, topK int) result.Result {
	res, err := AskWith(corpus, question, topK, Providers{})
	if err != nil {
		// Unreachable: hermeticEmbedding and hermeticGenerator both return a
		// nil error unconditionally. Panicking rather than returning a refusal
		// is deliberate — if this ever fires, the flow changed underneath the
		// fakes, and silently abstaining would hide that behind the library's
		// own safe default.
		panic("answer: the hermetic flow failed, which it cannot do: " + err.Error())
	}
	return res
}
