//go:build citenexus_ffi

// Package core is an OPT-IN cgo binding to the shared Rust engine
// (citenexus-core): binary-document extraction, lid.176 detection, and the Lance
// store — the heavy ingest stages the pure Go port cannot reimplement byte-identically.
//
// It is behind the `citenexus_ffi` build tag so the pure, `go get`-clean port and
// CI are unaffected. To use it, build the Rust cdylib first
// (`cd rust && cargo build --release`) and compile with `-tags citenexus_ffi`.
// One C ABI, shared with the TS napi binding (SPEC-PORTS-v1 §3.4).
package core

/*
#cgo LDFLAGS: -L${SRCDIR}/../../rust/target/release -lcitenexus_core -Wl,-rpath,${SRCDIR}/../../rust/target/release
#include <stdlib.h>
#include <stdint.h>
char* citenexus_extract(const uint8_t* bytes, size_t len, const char* source_type, const char* document_id);
char* citenexus_to_markdown(const uint8_t* bytes, size_t len, const char* source_type);
char* citenexus_rrf(const char* lists_json, int64_t k);
char* citenexus_pdf_units(const uint8_t* bytes, size_t len, const char* opts_json);
char* citenexus_pdf_prepare(const uint8_t* bytes, size_t len, const char* opts_json);
char* citenexus_pdf_assemble(const uint8_t* bytes, size_t len, const char* opts_json, const char* responses_json);
void citenexus_free_string(char* s);
const char* citenexus_core_version();

typedef struct Detector Detector;
Detector* citenexus_detector_open(const char* model_path);
char* citenexus_detect(Detector* handle, const char* text);
void citenexus_detector_close(Detector* handle);

typedef struct LanceStore LanceStore;
LanceStore* citenexus_store_open(const char* uri, const char* storage_options_json);
char* citenexus_store_upsert(LanceStore* handle, const char* rows_json);
char* citenexus_store_search(LanceStore* handle, const char* vector_json, size_t limit);
char* citenexus_store_scan(LanceStore* handle, int64_t limit);
char* citenexus_store_delete_document(LanceStore* handle, const char* document_id);
char* citenexus_store_drop(LanceStore* handle);
void citenexus_store_close(LanceStore* handle);
*/
import "C"

import (
	"encoding/json"
	"errors"
	"strings"
	"unsafe"
)

// Version returns the shared Rust core's version (static string, no free needed).
func Version() string {
	return C.GoString(C.citenexus_core_version())
}

// Fuse reciprocal-rank-fuses ranked eu_id lists through the shared Rust core
// (ADR-0006: rrf is pure rank arithmetic and lives once in the core). k is the
// RRF constant (60 is standard). The fused eu_id order is byte-identical to the
// Python reference and to every other SDK's core-backed fusion. This is the
// canonical fusion path; the pure golang/rrf.Fuse helper is deprecated in its
// favor. Returns an error only on a malformed core response.
func Fuse(lists [][]string, k int) ([]string, error) {
	payload, err := json.Marshal(lists)
	if err != nil {
		return nil, err
	}
	cLists := C.CString(string(payload))
	defer C.free(unsafe.Pointer(cLists))

	out := C.citenexus_rrf(cLists, C.int64_t(k))
	defer C.citenexus_free_string(out)

	raw := C.GoString(out)
	var fused []string
	if err := json.Unmarshal([]byte(raw), &fused); err != nil {
		return nil, errors.New("citenexus: unexpected rrf response: " + raw)
	}
	return fused, nil
}

// Extract runs the shared Rust extractor over raw bytes and returns the
// ExtractedDoc as a JSON string (or a {"error":...} JSON on failure). sourceType
// is e.g. "plain", "md", "html", "csv", "pdf", "docx", "pptx".
func Extract(data []byte, sourceType, documentID string) string {
	var bp *C.uint8_t
	if len(data) > 0 {
		bp = (*C.uint8_t)(unsafe.Pointer(&data[0]))
	}
	cSourceType := C.CString(sourceType)
	defer C.free(unsafe.Pointer(cSourceType))
	cDocID := C.CString(documentID)
	defer C.free(unsafe.Pointer(cDocID))

	out := C.citenexus_extract(bp, C.size_t(len(data)), cSourceType, cDocID)
	defer C.citenexus_free_string(out)
	return C.GoString(out)
}

// ToMarkdown converts raw bytes of sourceType ("docx", "xlsx", "html", …)
// straight to markdown via the shared Rust extract+emit path. Returns the C
// ABI's JSON verbatim: `{"markdown":...}` or `{"error":...}`.
func ToMarkdown(data []byte, sourceType string) string {
	var bp *C.uint8_t
	if len(data) > 0 {
		bp = (*C.uint8_t)(unsafe.Pointer(&data[0]))
	}
	cSourceType := C.CString(sourceType)
	defer C.free(unsafe.Pointer(cSourceType))

	out := C.citenexus_to_markdown(bp, C.size_t(len(data)), cSourceType)
	defer C.citenexus_free_string(out)
	return C.GoString(out)
}

// Detect loads the lid.176 model at modelPath, detects the language of text, and
// closes the detector. It returns the detection JSON
// (`{"language":"fr","confidence":0.98}` or `{"error":...}`). The 126MB model is
// caller-supplied — the core never downloads it; a missing/unloadable model is
// reported as an error, not a crash.
func Detect(modelPath, text string) (string, error) {
	cPath := C.CString(modelPath)
	defer C.free(unsafe.Pointer(cPath))

	handle := C.citenexus_detector_open(cPath)
	if handle == nil {
		return "", errors.New("citenexus: could not open detector (model missing or unloadable): " + modelPath)
	}
	defer C.citenexus_detector_close(handle)

	cText := C.CString(text)
	defer C.free(unsafe.Pointer(cText))

	out := C.citenexus_detect(handle, cText)
	defer C.citenexus_free_string(out)
	return C.GoString(out), nil
}

// Store is a handle to one leaf Lance database (the Rust LanceStore). Open it with
// Open, release it with Close. Every method returns the C ABI's JSON verbatim
// (`{"ok":true}` / a JSON array / `{"error":...}`).
type Store struct {
	handle *C.LanceStore
}

// Open connects to (or creates) the Lance database at uri (a local path or
// s3://…). optsJSON is a JSON object of storage-option string pairs (endpoint,
// access_key_id, …) or "" for none.
func Open(uri, optsJSON string) (*Store, error) {
	cURI := C.CString(uri)
	defer C.free(unsafe.Pointer(cURI))

	var cOpts *C.char
	if optsJSON != "" {
		cOpts = C.CString(optsJSON)
		defer C.free(unsafe.Pointer(cOpts))
	}

	handle := C.citenexus_store_open(cURI, cOpts)
	if handle == nil {
		return nil, errors.New("citenexus: could not open store at " + uri)
	}
	return &Store{handle: handle}, nil
}

// Upsert merge-inserts rowsJSON (a JSON array of row objects keyed by eu_id).
// Returns `{"ok":true}` or `{"error":...}`.
func (s *Store) Upsert(rowsJSON string) string {
	cRows := C.CString(rowsJSON)
	defer C.free(unsafe.Pointer(cRows))

	out := C.citenexus_store_upsert(s.handle, cRows)
	defer C.citenexus_free_string(out)
	return C.GoString(out)
}

// Search returns the nearest limit rows to vecJSON (a JSON array of numbers) as a
// JSON array (each row carrying _distance), or `{"error":...}`.
func (s *Store) Search(vecJSON string, limit int) string {
	cVec := C.CString(vecJSON)
	defer C.free(unsafe.Pointer(cVec))

	out := C.citenexus_store_search(s.handle, cVec, C.size_t(limit))
	defer C.citenexus_free_string(out)
	return C.GoString(out)
}

// Scan returns every row as a JSON array (limit < 0 means no limit), or
// `{"error":...}`.
func (s *Store) Scan(limit int) string {
	out := C.citenexus_store_scan(s.handle, C.int64_t(limit))
	defer C.citenexus_free_string(out)
	return C.GoString(out)
}

// DeleteDocument removes every row for documentID (no-op when absent) — the
// row-level inverse of Upsert used by document-revoke. Returns `{"ok":true}` or
// `{"error":...}`.
func (s *Store) DeleteDocument(documentID string) string {
	cID := C.CString(documentID)
	defer C.free(unsafe.Pointer(cID))

	out := C.citenexus_store_delete_document(s.handle, cID)
	defer C.citenexus_free_string(out)
	return C.GoString(out)
}

// Drop drops the evidence_units table (no-op when absent). Returns `{"ok":true}`
// or `{"error":...}`.
func (s *Store) Drop() string {
	out := C.citenexus_store_drop(s.handle)
	defer C.citenexus_free_string(out)
	return C.GoString(out)
}

// Close releases the underlying Rust store handle. Safe to call more than once.
func (s *Store) Close() {
	if s.handle != nil {
		C.citenexus_store_close(s.handle)
		s.handle = nil
	}
}

// PdfOptions configures the PDF calls. Language ("nl", "en", …) drives the
// hyphen rules and number reading; LayoutText adds each page's
// pdftotext -layout-style text to PdfResult.Pages.
type PdfOptions struct {
	Language   string `json:"language,omitempty"`
	LayoutText bool   `json:"layout_text,omitempty"`
	// ModelTables makes PdfPrepare also request a model grid for tables the
	// deterministic path already accepted (review mode); assemble then lets
	// the two grids compete (GriTS + position check). Off by default: only
	// uncertain table regions cost a model call.
	ModelTables bool `json:"model_tables,omitempty"`
}

// PdfUnit and PdfProvenance are the PDF names for the one shared unit shape
// (DocUnit / Provenance, ooxml.go) — PDF, DOCX and PPTX return the same type.
type (
	PdfUnit       = DocUnit
	PdfProvenance = Provenance
)

// PdfResult is the full base-extractor output: the units, each page's route
// with the signals behind it, and document-level signals (heading agreement,
// hyphen and furniture counts). Pages and Document are kept as raw JSON so the
// binding does not freeze a signal set that is still growing.
type PdfResult struct {
	Units    []PdfUnit       `json:"units"`
	Pages    json.RawMessage `json:"pages"`
	Document json.RawMessage `json:"document"`
}

// pdfCall runs one of the three PDF entry points and returns the raw JSON, or
// the core's {"error":...} as a Go error. responses is nil except for assemble.
func pdfCall(which string, pdf []byte, opts PdfOptions, responses []byte) ([]byte, error) {
	if len(pdf) == 0 {
		return nil, errors.New("citenexus: empty pdf")
	}
	payload, err := json.Marshal(opts)
	if err != nil {
		return nil, err
	}
	bp := (*C.uint8_t)(unsafe.Pointer(&pdf[0]))
	cOpts := C.CString(string(payload))
	defer C.free(unsafe.Pointer(cOpts))

	var out *C.char
	switch which {
	case "units":
		out = C.citenexus_pdf_units(bp, C.size_t(len(pdf)), cOpts)
	case "prepare":
		out = C.citenexus_pdf_prepare(bp, C.size_t(len(pdf)), cOpts)
	default:
		var cResp *C.char
		if responses != nil {
			cResp = C.CString(string(responses))
			defer C.free(unsafe.Pointer(cResp))
		}
		out = C.citenexus_pdf_assemble(bp, C.size_t(len(pdf)), cOpts, cResp)
	}
	defer C.citenexus_free_string(out)

	raw := []byte(C.GoString(out))
	var failure struct {
		Error string `json:"error"`
	}
	if json.Unmarshal(raw, &failure) == nil && failure.Error != "" {
		return nil, errors.New("citenexus: " + failure.Error)
	}
	return raw, nil
}

// PdfAnalyze runs the shared Rust base PDF extractor (no model, ADR-0017) and
// returns units, per-page routes and signals. It fails when the core was built
// without the `pdf` cargo feature, when libpdfium cannot be loaded (set
// PDFIUM_DYNAMIC_LIB_PATH), or when the bytes are not a PDF.
func PdfAnalyze(pdf []byte, opts PdfOptions) (*PdfResult, error) {
	raw, err := pdfCall("units", pdf, opts, nil)
	if err != nil {
		return nil, err
	}
	var res PdfResult
	if err := json.Unmarshal(raw, &res); err != nil {
		return nil, errors.New("citenexus: unexpected pdf_units response: " + err.Error())
	}
	return &res, nil
}

// PdfUnits is the base-only surface rag_go uses (ADR-0017 decision 10): no
// model, never fails for lack of a provider. It is exactly PdfAssemble with no
// responses.
func PdfUnits(pdf []byte, opts PdfOptions) ([]PdfUnit, error) {
	res, err := PdfAnalyze(pdf, opts)
	if err != nil {
		return nil, err
	}
	return res.Units, nil
}

// PdfWord is one text-layer word a table grid may reference by ID.
type PdfWord struct {
	ID   string     `json:"id"`
	Text string     `json:"text"`
	BBox [4]float64 `json:"bbox"`
}

// PdfRequest asks the host for one model call. Kind is table_structure (answer
// with Tables over Words' IDs; model-written text is never used on a
// text-layer page), vision_page or vision_region (answer with Markdown).
// Prompt is a key into the host's prompt config (default:
// rust/data/pdf_prompts.json).
type PdfRequest struct {
	ID     string     `json:"id"`
	Page   int        `json:"page"`
	Kind   string     `json:"kind"`
	Prompt string     `json:"prompt"`
	BBox   [4]float64 `json:"bbox"`
	Words  []PdfWord  `json:"words"`
	// Variant is 1 or 2 for vision requests (nil for table_structure): every
	// vision region is asked TWICE, independently. Hint says how the host
	// should make the two independent (a different model or sampling seed).
	Variant *int    `json:"variant"`
	Hint    *string `json:"hint"`
}

// PdfPrepared is phase one: the base result plus the requests.
type PdfPrepared struct {
	PdfResult
	Requests []PdfRequest `json:"requests"`
}

// PdfCell is one grid cell: word IDs, with optional spans (HTML rules).
type PdfCell struct {
	Words   []string `json:"words"`
	Colspan int      `json:"colspan,omitempty"`
	Rowspan int      `json:"rowspan,omitempty"`
}

// UnmarshalJSON accepts both cell forms the core speaks: a bare array of word
// IDs, or an object with words and spans.
func (c *PdfCell) UnmarshalJSON(b []byte) error {
	var ids []string
	if err := json.Unmarshal(b, &ids); err == nil {
		*c = PdfCell{Words: ids}
		return nil
	}
	type plain PdfCell
	var p plain
	if err := json.Unmarshal(b, &p); err != nil {
		return err
	}
	*c = PdfCell(p)
	return nil
}

// PdfGrid is one table: rows top to bottom, cells left to right.
type PdfGrid struct {
	Rows [][]PdfCell `json:"rows"`
}

// PdfResponse is the host's answer to the request with ID RequestID.
type PdfResponse struct {
	RequestID    string    `json:"request_id"`
	FinishReason string    `json:"finish_reason,omitempty"`
	Tables       []PdfGrid `json:"tables,omitempty"`
	Markdown     *string   `json:"markdown,omitempty"`
}

// PdfPrepare is phase one of the model contract (ADR-0017 decision 4).
func PdfPrepare(pdf []byte, opts PdfOptions) (*PdfPrepared, error) {
	raw, err := pdfCall("prepare", pdf, opts, nil)
	if err != nil {
		return nil, err
	}
	var res PdfPrepared
	if err := json.Unmarshal(raw, &res); err != nil {
		return nil, errors.New("citenexus: unexpected pdf_prepare response: " + err.Error())
	}
	return &res, nil
}

// PdfAssemble is phase two: the PDF is re-parsed and every response that
// passes the deterministic checks is applied. A missing response is base
// output; a failed one is base output with Provenance.FailedCheck set.
func PdfAssemble(pdf []byte, opts PdfOptions, responses []PdfResponse) (*PdfResult, error) {
	if responses == nil {
		responses = []PdfResponse{}
	}
	payload, err := json.Marshal(responses)
	if err != nil {
		return nil, err
	}
	raw, err := PdfAssembleJSON(pdf, opts, payload)
	if err != nil {
		return nil, err
	}
	var res PdfResult
	if err := json.Unmarshal(raw, &res); err != nil {
		return nil, errors.New("citenexus: unexpected pdf_assemble response: " + err.Error())
	}
	return &res, nil
}

// PdfAssembleJSON is PdfAssemble over raw JSON, returning the core's bytes
// untouched (for byte-level determinism checks and pass-through hosts).
func PdfAssembleJSON(pdf []byte, opts PdfOptions, responsesJSON []byte) ([]byte, error) {
	if responsesJSON == nil {
		responsesJSON = []byte("[]")
	}
	return pdfCall("assemble", pdf, opts, responsesJSON)
}

// CitableText returns markdown with every <!-- vision_disputed … --> block
// removed: the only text a host may cite or quote-match (ADR-0017 decision 4).
// Mirrors the Rust core's vision::citable_text.
func CitableText(markdown string) string {
	const open, closing = "<!-- vision_disputed", "-->"
	var b strings.Builder
	rest := markdown
	for {
		i := strings.Index(rest, open)
		if i < 0 {
			b.WriteString(rest)
			break
		}
		b.WriteString(rest[:i])
		j := strings.Index(rest[i:], closing)
		if j < 0 {
			break
		}
		rest = rest[i+j+len(closing):]
	}
	var lines []string
	for _, l := range strings.Split(b.String(), "\n") {
		l = strings.TrimRight(l, " \t\r")
		if strings.TrimSpace(l) != "" {
			lines = append(lines, l)
		}
	}
	return strings.Join(lines, "\n")
}
