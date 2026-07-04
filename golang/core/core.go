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
void citenexus_free_string(char* s);
const char* citenexus_core_version();
*/
import "C"

import "unsafe"

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
