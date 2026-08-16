package contracts

import (
	"errors"
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

// ---------------------------------------------------------------------------
// Providers written the way an outsider would write them. Nothing below embeds,
// extends, or otherwise names a CiteNexus concrete type.
// ---------------------------------------------------------------------------

type outsideBatchEmbedder struct {
	batches [][]string
	fail    error
	dim     int
}

func (e *outsideBatchEmbedder) Embed(texts []string) ([][]float64, error) {
	e.batches = append(e.batches, append([]string(nil), texts...))
	if e.fail != nil {
		return nil, e.fail
	}
	dim := e.dim
	if dim == 0 {
		dim = 3
	}
	out := make([][]float64, len(texts))
	for i, t := range texts {
		vec := make([]float64, dim)
		vec[0] = float64(len(t))
		out[i] = vec
	}
	return out, nil
}

type outsideSingleEmbedder struct {
	calls []string
	fail  error
}

func (e *outsideSingleEmbedder) Embed(text string) ([]float64, error) {
	e.calls = append(e.calls, text)
	if e.fail != nil {
		return nil, e.fail
	}
	return []float64{float64(len(text)), 1, 0}, nil
}

type outsideGenerator struct {
	seen []string
	fail error
}

func (g *outsideGenerator) Answer(question, passage, answerLanguage string) (string, error) {
	g.seen = append(g.seen, question+"|"+passage+"|"+answerLanguage)
	if g.fail != nil {
		return "", g.fail
	}
	return passage, nil
}

// The whole point, asserted at COMPILE time: shape alone is enough.
var (
	_ EmbeddingProvider  = (*outsideBatchEmbedder)(nil)
	_ SingleTextEmbedder = (*outsideSingleEmbedder)(nil)
	_ GeneratorProvider  = (*outsideGenerator)(nil)
)

// ---------------------------------------------------------------------------
// 1. The contracts exist and mean what Python's mean
// ---------------------------------------------------------------------------

func TestTheTwoConsumedSeamsArePublished(t *testing.T) {
	for name, iface := range map[string]reflect.Type{
		"EmbeddingProvider":  reflect.TypeOf((*EmbeddingProvider)(nil)).Elem(),
		"GeneratorProvider":  reflect.TypeOf((*GeneratorProvider)(nil)).Elem(),
		"SingleTextEmbedder": reflect.TypeOf((*SingleTextEmbedder)(nil)).Elem(),
	} {
		if iface.Kind() != reflect.Interface {
			t.Fatalf("%s must be an interface, got %v", name, iface.Kind())
		}
		if iface.NumMethod() != 1 {
			t.Errorf("%s has %d methods; one seam is one operation", name, iface.NumMethod())
		}
	}
}

// The three seams Python publishes that neither port consumes MUST NOT appear
// here. A contract with no call site advertises support that does not exist.
func TestTheUnconsumedSeamsAreAbsent(t *testing.T) {
	src := packageSource(t)
	for _, absent := range []string{
		"CompletionProvider", "VisionProvider", "RerankerProvider",
		"Candidate", "Complete(", "Describe(", "Rerank(",
	} {
		if strings.Contains(src, absent) {
			t.Errorf("the Go port publishes %q but has no consumer for it "+
				"(see design.md §1) — a contract nothing calls is worse than none", absent)
		}
	}
}

// Every contract returns (value, error). No sentinels: a provider that cannot
// fulfil a call must be able to SAY so (ADR-0014 R2).
func TestEveryContractMethodReturnsAnError(t *testing.T) {
	errType := reflect.TypeOf((*error)(nil)).Elem()
	for _, iface := range []reflect.Type{
		reflect.TypeOf((*EmbeddingProvider)(nil)).Elem(),
		reflect.TypeOf((*GeneratorProvider)(nil)).Elem(),
		reflect.TypeOf((*SingleTextEmbedder)(nil)).Elem(),
	} {
		m := iface.Method(0)
		if m.Type.NumOut() != 2 || m.Type.Out(1) != errType {
			t.Errorf("%s.%s must return (T, error); got %v", iface, m.Name, m.Type)
		}
	}
}

// R3: the contract names the OPERATION, never the transport. Asserted on both
// the parameter NAMES (from the AST) and the parameter TYPES (from reflect), so
// a provider that never opens a socket satisfies everything here.
func TestNoContractMentionsATransport(t *testing.T) {
	banned := map[string]bool{
		"baseurl": true, "baseUrl": true, "url": true, "headers": true,
		"transport": true, "timeout": true, "client": true, "apikey": true,
	}
	for iface, params := range interfaceParamNames(t) {
		for _, p := range params {
			if banned[strings.ToLower(p)] {
				t.Errorf("%s takes a transport concern %q — R3 forbids it", iface, p)
			}
		}
	}

	for _, iface := range []reflect.Type{
		reflect.TypeOf((*EmbeddingProvider)(nil)).Elem(),
		reflect.TypeOf((*GeneratorProvider)(nil)).Elem(),
		reflect.TypeOf((*SingleTextEmbedder)(nil)).Elem(),
	} {
		mt := iface.Method(0).Type
		for i := 0; i < mt.NumIn(); i++ {
			switch mt.In(i).Kind() {
			case reflect.Map, reflect.Func, reflect.Chan, reflect.Interface:
				t.Errorf("%s parameter %d is a %v — that is a transport shape, not an operation",
					iface, i, mt.In(i).Kind())
			}
		}
	}
}

// A provider author's only dependency must be this file.
func TestTheContractsPackageDependsOnNothingOfOurs(t *testing.T) {
	fset := token.NewFileSet()
	pkgs, err := parser.ParseDir(fset, ".", func(fi os.FileInfo) bool {
		return !strings.HasSuffix(fi.Name(), "_test.go")
	}, 0)
	if err != nil {
		t.Fatalf("parse package: %v", err)
	}
	for _, pkg := range pkgs {
		for name, file := range pkg.Files {
			for _, imp := range file.Imports {
				if strings.Contains(imp.Path.Value, "citenexus") {
					t.Errorf("%s imports %s; the contracts package must import nothing of ours",
						filepath.Base(name), imp.Path.Value)
				}
			}
		}
	}
}

// ---------------------------------------------------------------------------
// 2. The two embedding shapes cannot be confused — the Python hazard, checked
// ---------------------------------------------------------------------------

// Python had to name the batch method `embed_many` because `str` IS a
// `Sequence[str]`, so `embed` could not be told apart from the single-text
// shape. In Go `string` and `[]string` are unrelated types, so the natural name
// is safe — and this test is the proof, not the claim.
func TestTheSingleAndBatchShapesAreNotInterchangeable(t *testing.T) {
	var single any = &outsideSingleEmbedder{}
	if _, ok := single.(EmbeddingProvider); ok {
		t.Error("a single-text embedder satisfied the batch contract — the Python hazard IS present in Go")
	}
	var batch any = &outsideBatchEmbedder{}
	if _, ok := batch.(SingleTextEmbedder); ok {
		t.Error("a batch provider satisfied the single-text contract")
	}
}

// ---------------------------------------------------------------------------
// 3. Dispatch: batch preferred, single-text fallback, order preserved
// ---------------------------------------------------------------------------

func TestEmbedTextsPrefersTheBatchContract(t *testing.T) {
	batch := &outsideBatchEmbedder{}
	vecs, err := EmbedTexts(batch, []string{"a", "bb", "ccc"})
	if err != nil {
		t.Fatalf("EmbedTexts: %v", err)
	}
	if len(batch.batches) != 1 {
		t.Fatalf("batch path not taken once: %v", batch.batches)
	}
	if len(vecs) != 3 {
		t.Fatalf("got %d vectors for 3 texts", len(vecs))
	}
	// Order preserved: the fake encodes len(text) in slot 0.
	for i, want := range []float64{1, 2, 3} {
		if vecs[i][0] != want {
			t.Errorf("vector %d is out of input order: %v", i, vecs[i])
		}
	}
}

func TestEmbedTextsFallsBackToTheSingleTextShape(t *testing.T) {
	single := &outsideSingleEmbedder{}
	vecs, err := EmbedTexts(single, []string{"a", "bb"})
	if err != nil {
		t.Fatalf("EmbedTexts: %v", err)
	}
	if len(vecs) != 2 || len(single.calls) != 2 {
		t.Fatalf("single-text fallback wrong: vecs=%d calls=%v", len(vecs), single.calls)
	}
	if single.calls[0] != "a" || single.calls[1] != "bb" {
		t.Errorf("input order lost: %v", single.calls)
	}
}

func TestEmbedTextsOnEmptyInputCallsNothing(t *testing.T) {
	batch := &outsideBatchEmbedder{}
	vecs, err := EmbedTexts(batch, nil)
	if err != nil || len(vecs) != 0 {
		t.Fatalf("empty input: vecs=%v err=%v", vecs, err)
	}
	if len(batch.batches) != 0 {
		t.Errorf("an empty batch was still sent to the model: %v", batch.batches)
	}
}

var errBoom = errors.New("model call timed out after 30s")

func TestEmbedTextsPropagatesTheProviderError(t *testing.T) {
	if _, err := EmbedTexts(&outsideBatchEmbedder{fail: errBoom}, []string{"a"}); !errors.Is(err, errBoom) {
		t.Fatalf("batch error swallowed: %v", err)
	}
	if _, err := EmbedTexts(&outsideSingleEmbedder{fail: errBoom}, []string{"a"}); !errors.Is(err, errBoom) {
		t.Fatalf("single-text error swallowed: %v", err)
	}
}

func TestEmbedTextsRefusesSomethingThatIsNeither(t *testing.T) {
	_, err := EmbedTexts(struct{}{}, []string{"a"})
	if !errors.Is(err, ErrNotAnEmbedder) {
		t.Fatalf("a non-embedder was accepted: %v", err)
	}
	if _, err := EmbedTexts(nil, []string{"a"}); !errors.Is(err, ErrNotAnEmbedder) {
		t.Fatalf("nil was accepted: %v", err)
	}
}

func TestEmbedOneIsABatchOfOne(t *testing.T) {
	batch := &outsideBatchEmbedder{}
	vec, err := EmbedOne(batch, "hello")
	if err != nil {
		t.Fatalf("EmbedOne: %v", err)
	}
	if vec[0] != 5 {
		t.Errorf("wrong vector: %v", vec)
	}
	if len(batch.batches) != 1 || len(batch.batches[0]) != 1 {
		t.Errorf("a single text must be a batch of one, got %v", batch.batches)
	}
}

// ---------------------------------------------------------------------------
// 4. SingleFrom — a batch provider plugs into the single-text ingest seam
// ---------------------------------------------------------------------------

func TestSingleFromAdaptsABatchProvider(t *testing.T) {
	batch := &outsideBatchEmbedder{}
	var adapted SingleTextEmbedder = SingleFrom(batch)
	vec, err := adapted.Embed("hello")
	if err != nil {
		t.Fatalf("SingleFrom: %v", err)
	}
	if vec[0] != 5 {
		t.Errorf("wrong vector: %v", vec)
	}
}

func TestSingleFromReportsAShortBatchRatherThanAPlaceholder(t *testing.T) {
	_, err := SingleFrom(shortBatch{}).Embed("hello")
	if err == nil {
		t.Fatal("a provider that returned no vector was reported as success")
	}
}

type shortBatch struct{}

func (shortBatch) Embed(texts []string) ([][]float64, error) { return nil, nil }

// ---------------------------------------------------------------------------
// 5. The shared vector guard
// ---------------------------------------------------------------------------

func TestCheckVector(t *testing.T) {
	for _, c := range []struct {
		name string
		vec  []float64
		dim  int
		want string // substring the error must name; "" = must be accepted
	}{
		{"zero", []float64{0, 0, 0, 0}, 4, "zero vector"},
		{"nil", nil, 0, "empty vector"},
		{"empty", []float64{}, 0, "empty vector"},
		{"wrong dim", []float64{1, 2}, 4, "2-dim vector"},
		{"defines the run", []float64{0, 0, 0.5, 0}, 0, ""},
		{"matching dim", []float64{0, 0, 0.5, 0}, 4, ""},
	} {
		err := CheckVector("eu", c.vec, c.dim)
		if c.want == "" {
			if err != nil {
				t.Errorf("%s: rejected a valid vector: %v", c.name, err)
			}
			continue
		}
		if err == nil {
			t.Errorf("%s: accepted a vector that must never be indexed", c.name)
		} else if !strings.Contains(err.Error(), c.want) {
			t.Errorf("%s: error should name %q, got %v", c.name, c.want, err)
		}
	}
}

func TestIsZeroVector(t *testing.T) {
	for _, c := range []struct {
		vec  []float64
		want bool
	}{
		{[]float64{0, 0, 0}, true},
		{[]float64{}, true},
		{[]float64{0, 0, -0.0}, true},
		{[]float64{0, 1e-12, 0}, false},
		{[]float64{-1, 0, 0}, false},
	} {
		if got := IsZeroVector(c.vec); got != c.want {
			t.Errorf("IsZeroVector(%v) = %v, want %v", c.vec, got, c.want)
		}
	}
}

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

func packageSource(t *testing.T) string {
	t.Helper()
	entries, err := os.ReadDir(".")
	if err != nil {
		t.Fatalf("read package dir: %v", err)
	}
	var sb strings.Builder
	for _, e := range entries {
		if !strings.HasSuffix(e.Name(), ".go") || strings.HasSuffix(e.Name(), "_test.go") {
			continue
		}
		raw, err := os.ReadFile(e.Name())
		if err != nil {
			t.Fatalf("read %s: %v", e.Name(), err)
		}
		sb.Write(raw)
	}
	return sb.String()
}

// interfaceParamNames maps each exported interface in the package to the
// parameter names of its methods, read from the AST (reflect drops names).
func interfaceParamNames(t *testing.T) map[string][]string {
	t.Helper()
	fset := token.NewFileSet()
	pkgs, err := parser.ParseDir(fset, ".", func(fi os.FileInfo) bool {
		return !strings.HasSuffix(fi.Name(), "_test.go")
	}, 0)
	if err != nil {
		t.Fatalf("parse package: %v", err)
	}
	out := map[string][]string{}
	for _, pkg := range pkgs {
		for _, file := range pkg.Files {
			ast.Inspect(file, func(n ast.Node) bool {
				ts, ok := n.(*ast.TypeSpec)
				if !ok {
					return true
				}
				it, ok := ts.Type.(*ast.InterfaceType)
				if !ok {
					return true
				}
				for _, m := range it.Methods.List {
					ft, ok := m.Type.(*ast.FuncType)
					if !ok || ft.Params == nil {
						continue
					}
					for _, p := range ft.Params.List {
						for _, id := range p.Names {
							out[ts.Name.Name] = append(out[ts.Name.Name], id.Name)
						}
					}
				}
				return true
			})
		}
	}
	if len(out) == 0 {
		t.Fatal("no interfaces found — the contracts package is empty")
	}
	return out
}
