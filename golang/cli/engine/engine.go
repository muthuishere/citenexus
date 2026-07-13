// Package engine is the CLI orchestration seam: it wires extraction, chunking,
// embedding, retrieval (BM25 + vector, RRF-fused) and the cite-or-abstain ASK
// flow over the local store. Models and the extractor are INJECTED (CLAUDE.md: no
// bundled models; the core owns orchestration), so the same code answers with the
// deterministic fakes (hermetic tests) or real OpenAI-compatible endpoints.
package engine

import (
	"fmt"
	"math"
	"sort"

	"github.com/muthuishere/citenexus/golang/bm25"
	"github.com/muthuishere/citenexus/golang/chunker"
	"github.com/muthuishere/citenexus/golang/cli/store"
	"github.com/muthuishere/citenexus/golang/gate"
	"github.com/muthuishere/citenexus/golang/result"
	"github.com/muthuishere/citenexus/golang/rrf"
)

// Block is one extracted unit of a document, before chunking.
type Block struct {
	Order         int      `json:"order"`
	Kind          string   `json:"kind"`
	Text          string   `json:"text"`
	StructurePath []string `json:"structure_path"`
}

// Extractor turns raw artifact bytes into ordered blocks. Implementations: a pure
// text splitter (default build) or the Rust core (citenexus_ffi build).
type Extractor interface {
	Extract(data []byte, sourceType, documentID string) ([]Block, error)
}

// Embedder turns text into a dense vector. Injected; nil means lexical-only.
type Embedder interface {
	Embed(text string) ([]float64, error)
}

// Generator produces a grounded answer from a passage. Injected; required for Ask.
type Generator interface {
	Answer(question, passage, answerLanguage string) (string, error)
}

// DefaultTopK is the retrieval cutoff, matching the Go answer flow.
const DefaultTopK = 5

// rrfK is the pinned RRF constant (SPEC §4).
const rrfK = 60

// Engine holds the injected collaborators for one CLI invocation.
type Engine struct {
	Store     *store.Store
	Extractor Extractor
	Embedder  Embedder  // nil ⇒ no vectors written / vector retrieval skipped
	Generator Generator // required by Ask
	Partition string
	TopK      int
}

func (e *Engine) topK() int {
	if e.TopK > 0 {
		return e.TopK
	}
	return DefaultTopK
}

// Ingest extracts data as sourceType, chunks each block, embeds (when an Embedder
// is present) and upserts the Evidence-Unit rows. Returns the number written.
func (e *Engine) Ingest(data []byte, sourceType, documentID string) (int, error) {
	blocks, err := e.Extractor.Extract(data, sourceType, documentID)
	if err != nil {
		return 0, err
	}
	var rows []store.Unit
	for _, b := range blocks {
		for ci, chunk := range chunker.ChunkText(b.Text, chunker.DefaultMaxTokens, chunker.DefaultOverlap) {
			u := store.Unit{
				EuID:       fmt.Sprintf("%s:b%d:c%d", documentID, b.Order, ci),
				DocumentID: documentID,
				BlockOrder: b.Order,
				ChunkIndex: ci,
				Text:       chunk,
			}
			if e.Embedder != nil {
				vec, err := e.Embedder.Embed(chunk)
				if err != nil {
					return 0, fmt.Errorf("ingest: embed: %w", err)
				}
				u.Vector = vec
			}
			rows = append(rows, u)
		}
	}
	if len(rows) == 0 {
		return 0, nil
	}
	if err := e.Store.Upsert(e.Partition, rows); err != nil {
		return 0, err
	}
	return len(rows), nil
}

// Candidate is one fused retrieval hit.
type Candidate struct {
	EuID       string  `json:"eu_id"`
	DocumentID string  `json:"document_id"`
	Text       string  `json:"text"`
	Score      float64 `json:"score"`
}

// Retrieve returns the top-k fused candidates for query. It fuses a BM25-lite
// lexical ranking with a cosine vector ranking (when vectors + an Embedder are
// available) via RRF; with no Embedder it is lexical-only. Cite-only: every hit
// carries its EU id and text, never a synthesized claim.
func (e *Engine) Retrieve(query string) ([]Candidate, error) {
	units, err := e.Store.Scan(e.Partition)
	if err != nil {
		return nil, err
	}
	if len(units) == 0 {
		return nil, nil
	}
	byID := make(map[string]store.Unit, len(units))
	for _, u := range units {
		byID[u.EuID] = u
	}

	// Lexical ranking.
	bmRows := make([]bm25.Row, len(units))
	for i, u := range units {
		bmRows[i] = bm25.Row{EuID: u.EuID, Text: u.Text}
	}
	lexical := make([]string, 0, len(units))
	for _, r := range bm25.Rank(bmRows, query) {
		lexical = append(lexical, r.EuID)
	}

	lists := [][]string{lexical}

	// Vector ranking (optional).
	if e.Embedder != nil {
		if vlist, ok, err := e.vectorRank(query, units); err != nil {
			return nil, err
		} else if ok {
			lists = append(lists, vlist)
		}
	}

	fused := rrf.Fuse(lists, rrfK)
	out := make([]Candidate, 0, len(fused))
	for _, id := range fused {
		u := byID[id]
		out = append(out, Candidate{EuID: u.EuID, DocumentID: u.DocumentID, Text: u.Text})
		if len(out) >= e.topK() {
			break
		}
	}
	return out, nil
}

// vectorRank ranks units by descending cosine to the embedded query. ok=false
// when no unit carries a vector (lexical-only corpus).
func (e *Engine) vectorRank(query string, units []store.Unit) ([]string, bool, error) {
	qvec, err := e.Embedder.Embed(query)
	if err != nil {
		return nil, false, err
	}
	type scored struct {
		id    string
		score float64
		order int
	}
	var rows []scored
	any := false
	for i, u := range units {
		if len(u.Vector) == 0 {
			continue
		}
		any = true
		rows = append(rows, scored{id: u.EuID, score: cosine(qvec, u.Vector), order: i})
	}
	if !any {
		return nil, false, nil
	}
	sort.SliceStable(rows, func(i, j int) bool {
		if rows[i].score != rows[j].score {
			return rows[i].score > rows[j].score
		}
		return rows[i].order < rows[j].order
	})
	out := make([]string, len(rows))
	for i, r := range rows {
		out[i] = r.id
	}
	return out, true, nil
}

// Ask retrieves, applies the relevance and faithfulness gates, and answers or
// abstains — the guarantee. Mirrors golang/answer.Ask but over the store and the
// injected Generator (real or fake).
func (e *Engine) Ask(question, answerLanguage string) (result.Result, error) {
	if e.Generator == nil {
		return result.Result{}, fmt.Errorf("ask: no llm generator configured")
	}
	if answerLanguage == "" {
		answerLanguage = "en"
	}
	candidates, err := e.Retrieve(question)
	if err != nil {
		return result.Result{}, err
	}

	grounded := make([]Candidate, 0, len(candidates))
	for _, c := range candidates {
		if gate.HasRelevanceOverlap(question, c.Text) {
			grounded = append(grounded, c)
		}
	}
	if len(grounded) == 0 {
		return result.Refused(result.TrustModeStrict), nil
	}

	top := grounded[0]
	ans, err := e.Generator.Answer(question, top.Text, answerLanguage)
	if err != nil {
		return result.Result{}, fmt.Errorf("ask: generate: %w", err)
	}

	// Faithfulness gate: never emit an ungrounded claim. This gate is the product.
	if !gate.IsSupported(ans, top.Text) {
		return result.Refused(result.TrustModeStrict), nil
	}

	distinct := map[string]struct{}{}
	for _, c := range grounded {
		distinct[c.DocumentID] = struct{}{}
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
		},
		Claims: []result.Claim{
			{Claim: ans, Supported: true, Sources: []string{top.EuID}},
		},
		Sources: []result.SourceRef{
			{Document: top.DocumentID, Passage: top.Text, PassageLanguage: answerLanguage},
		},
		MissingEvidence: []string{},
		Conflicts:       []string{},
		Provenance:      []result.ProvenanceEntry{},
	}, nil
}

// cosine is the dot product of two vectors (FakeEmbedding output is normalized;
// real embeddings are normalized here for a stable ranking).
func cosine(a, b []float64) float64 {
	n := len(a)
	if len(b) < n {
		n = len(b)
	}
	var dot, na, nb float64
	for i := 0; i < n; i++ {
		dot += a[i] * b[i]
		na += a[i] * a[i]
		nb += b[i] * b[i]
	}
	if na == 0 || nb == 0 {
		return 0
	}
	return dot / (math.Sqrt(na) * math.Sqrt(nb))
}
