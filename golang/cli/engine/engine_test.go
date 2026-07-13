package engine

import (
	"path/filepath"
	"testing"

	"github.com/muthuishere/citenexus/golang/cli/config"
	"github.com/muthuishere/citenexus/golang/cli/store"
	"github.com/muthuishere/citenexus/golang/result"
)

// splitExtractor is a trivial pure extractor for tests: one block per input.
type splitExtractor struct{}

func (splitExtractor) Extract(data []byte, sourceType, documentID string) ([]Block, error) {
	return []Block{{Order: 0, Kind: "text", Text: string(data)}}, nil
}

func newEngine(t *testing.T) *Engine {
	t.Helper()
	st, err := store.Open(filepath.Join(t.TempDir(), "data"))
	if err != nil {
		t.Fatal(err)
	}
	emb, _ := NewEmbedder(&config.ModelConfig{Provider: "fake"})
	gen, _ := NewGenerator(&config.ModelConfig{Provider: "fake"})
	return &Engine{Store: st, Extractor: splitExtractor{}, Embedder: emb, Generator: gen, Partition: "default"}
}

func TestIngestRetrieveAsk(t *testing.T) {
	e := newEngine(t)

	n, err := e.Ingest([]byte("The termination notice period is thirty days for salaried staff."), "txt", "hr-policy")
	if err != nil || n == 0 {
		t.Fatalf("ingest: n=%d err=%v", n, err)
	}
	if _, err := e.Ingest([]byte("Company holidays include a paid winter break in December."), "txt", "holidays"); err != nil {
		t.Fatal(err)
	}

	// Retrieve surfaces the relevant document.
	cands, err := e.Retrieve("What is the termination notice period?")
	if err != nil {
		t.Fatal(err)
	}
	if len(cands) == 0 || cands[0].DocumentID != "hr-policy" {
		t.Fatalf("retrieve did not surface hr-policy first: %+v", cands)
	}

	// Ask returns a grounded, supported answer.
	res, err := e.Ask("What is the termination notice period?", "en")
	if err != nil {
		t.Fatal(err)
	}
	if res.Evidence.Decision != result.DecisionAnswered {
		t.Fatalf("expected answered, got %s (%q)", res.Evidence.Decision, res.Answer)
	}
	if len(res.Sources) == 0 || res.Sources[0].Document != "hr-policy" {
		t.Errorf("answer not cited to hr-policy: %+v", res.Sources)
	}
}

func TestAskAbstainsWhenNoRelevantEvidence(t *testing.T) {
	e := newEngine(t)
	if _, err := e.Ingest([]byte("The winter break falls in December each year."), "txt", "holidays"); err != nil {
		t.Fatal(err)
	}
	res, err := e.Ask("What is the capital of France?", "en")
	if err != nil {
		t.Fatal(err)
	}
	if res.Evidence.Decision != result.DecisionRefused {
		t.Fatalf("expected refusal on off-topic question, got %s (%q)", res.Evidence.Decision, res.Answer)
	}
}

func TestLexicalOnlyWithoutEmbedder(t *testing.T) {
	st, _ := store.Open(filepath.Join(t.TempDir(), "data"))
	e := &Engine{Store: st, Extractor: splitExtractor{}, Partition: "default"} // no Embedder
	if _, err := e.Ingest([]byte("Refund requests must be filed within fourteen days."), "txt", "refunds"); err != nil {
		t.Fatal(err)
	}
	cands, err := e.Retrieve("refund window days")
	if err != nil {
		t.Fatal(err)
	}
	if len(cands) == 0 || cands[0].DocumentID != "refunds" {
		t.Fatalf("lexical retrieve failed: %+v", cands)
	}
	// Stored rows carry no vector when there is no embedder.
	units, _ := st.Scan("default")
	if len(units) == 0 || len(units[0].Vector) != 0 {
		t.Errorf("expected no vectors in lexical-only ingest: %+v", units)
	}
}
