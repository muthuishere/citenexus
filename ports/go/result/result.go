// Package result is the CiteNexus Result model and its parts
// (SPEC-PORTS-v1 §7). A Result is a grounded answer — or a refusal — carrying
// structured evidence signals and a reproducible provenance chain. It mirrors
// the Python reference citenexus.answer.result and serializes byte-compatibly
// with conformance/cases/result_roundtrip.json.
//
// Serialization contract: optional/absent scalar fields are nullable pointers so
// they marshal as null; list fields are initialized non-nil so they marshal as
// [] (never null or omitted).
package result

// RefusalAnswer is the single pinned refusal string every port must emit when it
// cannot ground an answer (§7).
const RefusalAnswer = "I can't answer that from the available evidence."

// Decision is the outcome recorded on the evidence signals.
type Decision string

const (
	DecisionAnswered Decision = "answered"
	DecisionRefused  Decision = "refused"
	DecisionPartial  Decision = "partial"
)

// TrustMode is the answer-flow trust mode. Only strict is exercised here.
type TrustMode string

const TrustModeStrict TrustMode = "strict"

// BBox is a page bounding box. Always null in the hermetic flow; present so the
// nullable field type is explicit.
type BBox struct {
	Page int     `json:"page"`
	X0   float64 `json:"x0"`
	Y0   float64 `json:"y0"`
	X1   float64 `json:"x1"`
	Y1   float64 `json:"y1"`
}

// EvidenceSignals are the structured retrieval/verification signals that replace
// a scalar confidence (§7/§12).
type EvidenceSignals struct {
	Decision                 Decision `json:"decision"`
	SupportingSources        int      `json:"supporting_sources"`
	DistinctDocuments        int      `json:"distinct_documents"`
	RetrievalScoreSpread     float64  `json:"retrieval_score_spread"`
	AllClaimsVerified        bool     `json:"all_claims_verified"`
	UnsupportedClaimsRemoved int      `json:"unsupported_claims_removed"`
	ConflictsDetected        int      `json:"conflicts_detected"`
	LanguagesInEvidence      []string `json:"languages_in_evidence"`
}

// SourceRef is a cited source: a verbatim passage in its source language, with an
// optional additive translation that never replaces the passage.
type SourceRef struct {
	Document        string  `json:"document"`
	Passage         string  `json:"passage"`
	PassageLanguage string  `json:"passage_language"`
	Page            *int    `json:"page"`
	BBox            *BBox   `json:"bbox"`
	SourceURI       *string `json:"source_uri"`
	Translation     *string `json:"translation"`
}

// Claim is a single claim in the answer and the evidence-unit ids that support it.
type Claim struct {
	Claim     string   `json:"claim"`
	Supported bool     `json:"supported"`
	Sources   []string `json:"sources"`
}

// ProvenanceEntry is one link of the reproducible chain: claim -> EU -> document
// -> S3 object -> checksum -> producing plugins.
type ProvenanceEntry struct {
	Claim        string         `json:"claim"`
	EvidenceUnit string         `json:"evidence_unit"`
	DocumentID   string         `json:"document_id"`
	S3Object     string         `json:"s3_object"`
	Checksum     string         `json:"checksum"`
	Page         *int           `json:"page"`
	BBox         *BBox          `json:"bbox"`
	ProducedBy   map[string]any `json:"produced_by"`
}

// Result is a grounded answer, or a refusal, with full evidence + provenance.
type Result struct {
	Answer          string            `json:"answer"`
	AnswerLanguage  string            `json:"answer_language"`
	Mode            TrustMode         `json:"mode"`
	Evidence        EvidenceSignals   `json:"evidence"`
	Claims          []Claim           `json:"claims"`
	Sources         []SourceRef       `json:"sources"`
	MissingEvidence []string          `json:"missing_evidence"`
	Conflicts       []string          `json:"conflicts"`
	Provenance      []ProvenanceEntry `json:"provenance"`
}

// Refused builds the pinned refusal Result in the given mode: refused decision,
// the pinned missing-evidence note, and empty (non-nil) claims/sources/provenance.
func Refused(mode TrustMode) Result {
	return Result{
		Answer:         RefusalAnswer,
		AnswerLanguage: "en",
		Mode:           mode,
		Evidence: EvidenceSignals{
			Decision:            DecisionRefused,
			LanguagesInEvidence: []string{},
		},
		Claims:          []Claim{},
		Sources:         []SourceRef{},
		MissingEvidence: []string{"no sufficiently relevant evidence found"},
		Conflicts:       []string{},
		Provenance:      []ProvenanceEntry{},
	}
}
