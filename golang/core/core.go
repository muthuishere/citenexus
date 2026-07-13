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
// Link flags live in build-tagged files (link_dynamic.go / link_static.go) so a
// self-contained CLI can static-link the .a while the FFI ports keep the dylib.
#include <stdlib.h>
#include <stdint.h>
char* citenexus_extract(const uint8_t* bytes, size_t len, const char* source_type, const char* document_id);
char* citenexus_to_markdown(const uint8_t* bytes, size_t len, const char* source_type);
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
	"errors"
	"unsafe"
)

// Version returns the shared Rust core's version (static string, no free needed).
func Version() string {
	return C.GoString(C.citenexus_core_version())
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
