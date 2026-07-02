//! The C ABI every binding uses (cgo / napi / pyo3 / ctypes).
//!
//! Contract (SPEC-PORTS-v1 §3.4): JSON in/out, no callbacks. Success returns
//! the `ExtractedDoc` JSON; failure returns `{"error": "..."}` — the caller
//! distinguishes by the `error` key. Every returned string MUST be released
//! with `trustrag_free_string`.

use std::ffi::{c_char, CStr, CString};

use crate::extract;
use crate::types::SourceType;

fn to_c_string(payload: String) -> *mut c_char {
    // JSON never contains interior NULs; fall back to an error literal if so.
    CString::new(payload)
        .unwrap_or_else(|_| CString::new(r#"{"error":"interior NUL in output"}"#).unwrap())
        .into_raw()
}

fn error_json(message: &str) -> String {
    serde_json::json!({ "error": message }).to_string()
}

fn parse_source_type(raw: &str) -> Option<SourceType> {
    serde_json::from_value(serde_json::Value::String(raw.to_string())).ok()
}

/// Extract `bytes[0..len]` as `source_type` (e.g. "pdf", "docx", "html").
/// Returns malloc'd JSON: an `ExtractedDoc`, or `{"error": ...}`.
///
/// # Safety
/// `bytes` must point to `len` readable bytes; `source_type` and
/// `document_id` must be valid NUL-terminated UTF-8 C strings.
#[no_mangle]
pub unsafe extern "C" fn trustrag_extract(
    bytes: *const u8,
    len: usize,
    source_type: *const c_char,
    document_id: *const c_char,
) -> *mut c_char {
    if bytes.is_null() || source_type.is_null() || document_id.is_null() {
        return to_c_string(error_json("null argument"));
    }
    let data = std::slice::from_raw_parts(bytes, len);
    let source_type = match CStr::from_ptr(source_type).to_str() {
        Ok(s) => s,
        Err(_) => return to_c_string(error_json("source_type is not UTF-8")),
    };
    let document_id = match CStr::from_ptr(document_id).to_str() {
        Ok(s) => s,
        Err(_) => return to_c_string(error_json("document_id is not UTF-8")),
    };
    let Some(kind) = parse_source_type(source_type) else {
        return to_c_string(error_json(&format!("unknown source_type: {source_type}")));
    };

    let payload = match extract::extract(data, kind, document_id, None) {
        Ok(doc) => serde_json::to_string(&doc).unwrap_or_else(|e| error_json(&e.to_string())),
        Err(message) => error_json(&message),
    };
    to_c_string(payload)
}

/// Release a string returned by any `trustrag_*` call.
///
/// # Safety
/// `s` must be a pointer previously returned by this library (or null).
#[no_mangle]
pub unsafe extern "C" fn trustrag_free_string(s: *mut c_char) {
    if !s.is_null() {
        drop(CString::from_raw(s));
    }
}

/// The core's version, as a static C string (no free needed).
#[no_mangle]
pub extern "C" fn trustrag_core_version() -> *const c_char {
    concat!(env!("CARGO_PKG_VERSION"), "\0").as_ptr() as *const c_char
}
