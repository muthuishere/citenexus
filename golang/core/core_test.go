//go:build citenexus_ffi

package core

import (
	"encoding/json"
	"os"
	"reflect"
	"strings"
	"testing"

	"github.com/muthuishere/citenexus/golang/rrf"
)

// expectedCoreRRFCases pins the size of conformance/cases/rrf.json as this
// package consumes it (golang/rrf pins the same file independently).
const expectedCoreRRFCases = 13

func TestVersion(t *testing.T) {
	v := Version()
	if v == "" {
		t.Fatal("empty core version")
	}
	t.Logf("citenexus-core version: %s", v)
}

// TestFuse drives the core-backed reciprocal-rank fusion (ADR-0006: rrf lives
// once in the Rust core) and proves it is byte-identical to BOTH the committed
// Python-generated fixture AND the deprecated pure golang/rrf.Fuse helper.
func TestFuse(t *testing.T) {
	raw, err := os.ReadFile("../../conformance/cases/rrf.json")
	if err != nil {
		t.Fatalf("read rrf fixture: %v", err)
	}
	var cases []struct {
		Lists [][]string `json:"lists"`
		K     int        `json:"k"`
		Fused []string   `json:"fused"`
	}
	if err := json.Unmarshal(raw, &cases); err != nil {
		t.Fatalf("parse rrf fixture: %v", err)
	}
	if len(cases) != expectedCoreRRFCases {
		t.Fatalf("rrf.json: got %d cases, want %d", len(cases), expectedCoreRRFCases)
	}
	for i, c := range cases {
		got, err := Fuse(c.Lists, c.K)
		if err != nil {
			t.Fatalf("case %d: Fuse error: %v", i, err)
		}
		want := c.Fused
		if want == nil {
			want = []string{}
		}
		if !reflect.DeepEqual(got, want) {
			t.Errorf("case %d: core.Fuse = %v, want %v", i, got, want)
		}
		if pure := rrf.Fuse(c.Lists, c.K); !reflect.DeepEqual(got, pure) {
			t.Errorf("case %d: core.Fuse = %v, deprecated rrf.Fuse = %v (must match)", i, got, pure)
		}
	}

	if _, err := Fuse([][]string{{"a", "b"}, {"b", "a"}}, 60); err != nil {
		t.Fatalf("simple fuse errored: %v", err)
	}
}

func TestExtractPlain(t *testing.T) {
	out := Extract([]byte("Hello CiteNexus.\n\nSecond paragraph here."), "plain", "doc1")
	if strings.Contains(out, `"error"`) {
		t.Fatalf("extract returned error: %s", out)
	}
	var doc struct {
		DocumentID string `json:"document_id"`
		Blocks     []struct {
			Text string `json:"text"`
		} `json:"blocks"`
	}
	if err := json.Unmarshal([]byte(out), &doc); err != nil {
		t.Fatalf("extract output not valid JSON: %v\n%s", err, out)
	}
	if doc.DocumentID != "doc1" {
		t.Fatalf("document_id = %q, want doc1", doc.DocumentID)
	}
	if len(doc.Blocks) == 0 {
		t.Fatalf("expected at least one block, got none: %s", out)
	}
}

func TestToMarkdown(t *testing.T) {
	data, err := os.ReadFile("../../conformance/fixtures/sample.xlsx")
	if err != nil {
		t.Fatalf("read xlsx fixture: %v", err)
	}
	out := ToMarkdown(data, "xlsx")
	var payload struct {
		Markdown string `json:"markdown"`
		Error    string `json:"error"`
	}
	if err := json.Unmarshal([]byte(out), &payload); err != nil {
		t.Fatalf("to_markdown output not valid JSON: %v\n%s", err, out)
	}
	if payload.Error != "" {
		t.Fatalf("to_markdown returned error: %s", payload.Error)
	}
	if !strings.Contains(payload.Markdown, "# People") ||
		!strings.Contains(payload.Markdown, "name: ada, age: 36, active: true") {
		t.Fatalf("unexpected markdown: %q", payload.Markdown)
	}

	if out := ToMarkdown([]byte("not a workbook"), "xlsx"); !strings.Contains(out, `"error"`) {
		t.Fatalf("expected error for invalid workbook, got: %s", out)
	}
}

// TestStoreRoundTrip drives the real Rust Lance store over a temp directory URI:
// open → upsert one row → scan finds it → search finds it.
func TestStoreRoundTrip(t *testing.T) {
	dir := t.TempDir()
	store, err := Open(dir, "")
	if err != nil {
		t.Fatalf("open store: %v", err)
	}
	defer store.Close()

	const euID = "eu-roundtrip-1"
	row := map[string]any{
		"eu_id":  euID,
		"vector": []float64{0.1, 0.2, 0.3, 0.4},
		"text":   "the employee may disclose under NDA carve-outs",
	}
	rowsJSON, err := json.Marshal([]any{row})
	if err != nil {
		t.Fatalf("marshal row: %v", err)
	}
	if out := store.Upsert(string(rowsJSON)); strings.Contains(out, `"error"`) {
		t.Fatalf("upsert error: %s", out)
	}

	// scan returns the row we inserted.
	scanOut := store.Scan(-1)
	if strings.Contains(scanOut, `"error"`) {
		t.Fatalf("scan error: %s", scanOut)
	}
	var scanned []map[string]any
	if err := json.Unmarshal([]byte(scanOut), &scanned); err != nil {
		t.Fatalf("scan output not JSON: %v\n%s", err, scanOut)
	}
	if len(scanned) != 1 || scanned[0]["eu_id"] != euID {
		t.Fatalf("scan did not return the upserted row: %s", scanOut)
	}

	// search returns the row we inserted (nearest to its own vector).
	searchOut := store.Search("[0.1, 0.2, 0.3, 0.4]", 5)
	if strings.Contains(searchOut, `"error"`) {
		t.Fatalf("search error: %s", searchOut)
	}
	var found []map[string]any
	if err := json.Unmarshal([]byte(searchOut), &found); err != nil {
		t.Fatalf("search output not JSON: %v\n%s", err, searchOut)
	}
	if len(found) == 0 || found[0]["eu_id"] != euID {
		t.Fatalf("search did not return the upserted row: %s", searchOut)
	}
}

// TestStoreDeleteDocument exercises the row-level inverse of upsert used by
// document-revoke: it removes only the named document's rows and is a no-op on
// an unknown id / a leaf with no table yet (mirrors the Python reference).
func TestStoreDeleteDocument(t *testing.T) {
	dir := t.TempDir()
	store, err := Open(dir, "")
	if err != nil {
		t.Fatalf("open store: %v", err)
	}
	defer store.Close()

	// Delete before any table exists must be a no-op.
	if out := store.DeleteDocument("nda"); strings.Contains(out, `"error"`) {
		t.Fatalf("delete on empty leaf errored: %s", out)
	}

	rows := []any{
		map[string]any{"eu_id": "nda::0", "vector": []float64{1, 0, 0, 0}, "text": "secret", "document_id": "nda"},
		map[string]any{"eu_id": "leave::0", "vector": []float64{0, 1, 0, 0}, "text": "leave", "document_id": "leave"},
	}
	rowsJSON, _ := json.Marshal(rows)
	if out := store.Upsert(string(rowsJSON)); strings.Contains(out, `"error"`) {
		t.Fatalf("upsert error: %s", out)
	}

	if out := store.DeleteDocument("nda"); strings.Contains(out, `"error"`) {
		t.Fatalf("delete error: %s", out)
	}
	var remaining []map[string]any
	if err := json.Unmarshal([]byte(store.Scan(-1)), &remaining); err != nil {
		t.Fatalf("scan output not JSON: %v", err)
	}
	if len(remaining) != 1 || remaining[0]["document_id"] != "leave" {
		t.Fatalf("delete_document did not remove only nda: %v", remaining)
	}

	// Unknown id is a no-op.
	if out := store.DeleteDocument("ghost"); strings.Contains(out, `"error"`) {
		t.Fatalf("delete unknown errored: %s", out)
	}
}

// TestDetect exercises the real lid.176 detector when the model is present, and
// skips otherwise (the binding still compiled — that's the point). Set
// CITENEXUS_LID176_PATH to the model file to run it.
func TestDetect(t *testing.T) {
	modelPath := os.Getenv("CITENEXUS_LID176_PATH")
	if modelPath == "" {
		modelPath = "../../models/lid.176.bin"
	}
	if _, err := os.Stat(modelPath); err != nil {
		t.Skipf("lid.176 model not present at %q (set CITENEXUS_LID176_PATH); skipping detect test", modelPath)
	}
	out, err := Detect(modelPath, "The quick brown fox jumps over the lazy dog.")
	if err != nil {
		t.Fatalf("detect: %v", err)
	}
	if strings.Contains(out, `"error"`) {
		t.Fatalf("detect returned error: %s", out)
	}
	var det struct {
		Language   string  `json:"language"`
		Confidence float64 `json:"confidence"`
	}
	if err := json.Unmarshal([]byte(out), &det); err != nil {
		t.Fatalf("detect output not JSON: %v\n%s", err, out)
	}
	if det.Language != "en" {
		t.Fatalf("detected language = %q, want en (%s)", det.Language, out)
	}
}

func TestPdfUnits(t *testing.T) {
	data, err := os.ReadFile("../../conformance/fixtures/pdf/base-structure.pdf")
	if err != nil {
		t.Fatalf("read pdf fixture: %v", err)
	}
	res, err := PdfAnalyze(data, PdfOptions{Language: "nl"})
	if err != nil {
		if strings.Contains(err.Error(), "`pdf` feature") || strings.Contains(err.Error(), "libpdfium") {
			t.Skipf("SKIP: %v (build the core with --features pdf and set PDFIUM_DYNAMIC_LIB_PATH)", err)
		}
		t.Fatalf("PdfAnalyze: %v", err)
	}
	var got []string
	for _, u := range res.Units {
		got = append(got, u.Kind+": "+u.Markdown)
	}
	want := []string{
		"heading: # Leave Policy",
		"paragraph: Staff must send an e-mail before the regulation deadline.",
		"furniture: laatst bijgewerkt 12-03-2024",
		"heading: ## Scope",
		"paragraph: It applies to all staff.",
	}
	if strings.Join(got, "\n") != strings.Join(want, "\n") {
		t.Fatalf("units:\n%s\nwant:\n%s", strings.Join(got, "\n"), strings.Join(want, "\n"))
	}
	if hs := res.Units[0].Provenance.HeadingSource; hs == nil || *hs != "struct_tree" {
		t.Fatalf("heading source: %v", hs)
	}
	if res.Units[0].Page == nil || *res.Units[0].Page != 1 || res.Units[0].BBox == nil {
		t.Fatalf("page/bbox missing: %+v", res.Units[0])
	}

	units, err := PdfUnits(data, PdfOptions{})
	if err != nil || len(units) != len(res.Units) {
		t.Fatalf("PdfUnits: %v (%d units)", err, len(units))
	}
	if _, err := PdfUnits([]byte("not a pdf"), PdfOptions{}); err == nil {
		t.Fatal("expected an error for non-PDF bytes")
	}
}

// The cross-port determinism vector (ADR-0017 decision 11): the committed
// fixture and responses give exactly the bytes the Rust core committed.
func TestPdfAssembleGolden(t *testing.T) {
	dir := "../../rust/tests/data/pdf/"
	pdf, err := os.ReadFile(dir + "assemble-mixed.pdf")
	if err != nil {
		t.Fatalf("read fixture: %v", err)
	}
	responses, err := os.ReadFile(dir + "assemble-mixed.responses.json")
	if err != nil {
		t.Fatalf("read responses: %v", err)
	}
	golden, err := os.ReadFile(dir + "assemble-mixed.golden.json")
	if err != nil {
		t.Fatalf("read golden: %v", err)
	}
	got, err := PdfAssembleJSON(pdf, PdfOptions{Language: "nl", ModelTables: true}, responses)
	if err != nil {
		if strings.Contains(err.Error(), "`pdf` feature") || strings.Contains(err.Error(), "libpdfium") {
			t.Skipf("SKIP: %v", err)
		}
		t.Fatalf("PdfAssembleJSON: %v", err)
	}
	if string(got) != string(golden) {
		t.Fatalf("assemble bytes differ from the Rust golden")
	}

	// Typed round trip: prepare lists the requests, assemble applies them.
	prep, err := PdfPrepare(pdf, PdfOptions{Language: "nl", ModelTables: true})
	if err != nil {
		t.Fatalf("PdfPrepare: %v", err)
	}
	var ids []string
	for _, r := range prep.Requests {
		ids = append(ids, r.ID)
	}
	if strings.Join(ids, ",") != "p1:table0,p2:page,p3:img0" {
		t.Fatalf("requests: %v", ids)
	}
	var typed []PdfResponse
	if err := json.Unmarshal(responses, &typed); err != nil {
		t.Fatalf("responses decode: %v", err)
	}
	res, err := PdfAssemble(pdf, PdfOptions{Language: "nl", ModelTables: true}, typed)
	if err != nil {
		t.Fatalf("PdfAssemble: %v", err)
	}
	// The model grid agrees with the ruled grid (GriTS >= 0.9): the drawn
	// table stays, confirmed, not uncertain.
	tables := 0
	for _, u := range res.Units {
		if u.Kind == "table" && u.Provenance.TableSource != nil && *u.Provenance.TableSource == "ruled" && !u.Provenance.TableUncertain {
			tables++
		}
	}
	if tables != 1 {
		t.Fatalf("expected one confirmed ruled table, got %d", tables)
	}

	// No responses == PdfUnits, byte for byte.
	none, err := PdfAssembleJSON(pdf, PdfOptions{Language: "nl", ModelTables: true}, nil)
	if err != nil {
		t.Fatal(err)
	}
	base, err := pdfCall("units", pdf, PdfOptions{Language: "nl", ModelTables: true}, nil)
	if err != nil {
		t.Fatal(err)
	}
	if string(none) != string(base) {
		t.Fatal("PdfAssemble with no responses must equal PdfUnits")
	}
}
