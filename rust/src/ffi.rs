//! The C ABI every binding uses (cgo / napi / pyo3 / ctypes).
//!
//! Contract (SPEC-PORTS-v1 §3.4): JSON in/out, no callbacks. Success returns
//! the `ExtractedDoc` JSON; failure returns `{"error": "..."}` — the caller
//! distinguishes by the `error` key. Every returned string MUST be released
//! with `citenexus_free_string`.

use std::collections::BTreeMap;
use std::ffi::{c_char, CStr, CString};

use crate::detect::Detector;
use crate::extract;
use crate::store::LanceStore;
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
pub unsafe extern "C" fn citenexus_extract(
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

/// Convert `bytes[0..len]` of `source_type` straight to markdown: extract,
/// then render deterministically (`emit::markdown`). Returns malloc'd JSON:
/// `{"markdown": "..."}`, or `{"error": ...}`.
///
/// # Safety
/// `bytes` must point to `len` readable bytes; `source_type` must be a valid
/// NUL-terminated UTF-8 C string.
#[no_mangle]
pub unsafe extern "C" fn citenexus_to_markdown(
    bytes: *const u8,
    len: usize,
    source_type: *const c_char,
) -> *mut c_char {
    if bytes.is_null() || source_type.is_null() {
        return to_c_string(error_json("null argument"));
    }
    let data = std::slice::from_raw_parts(bytes, len);
    let source_type = match CStr::from_ptr(source_type).to_str() {
        Ok(s) => s,
        Err(_) => return to_c_string(error_json("source_type is not UTF-8")),
    };
    let Some(kind) = parse_source_type(source_type) else {
        return to_c_string(error_json(&format!("unknown source_type: {source_type}")));
    };

    let payload = match extract::extract(data, kind, "doc", None) {
        Ok(doc) => {
            let markdown = crate::emit::markdown::to_markdown(&doc);
            serde_json::json!({ "markdown": markdown }).to_string()
        }
        Err(message) => error_json(&message),
    };
    to_c_string(payload)
}

/// Reciprocal-rank-fuse the ranked `eu_id` lists in `lists_json` (a JSON array
/// of arrays of strings) with constant `k`. Returns malloc'd JSON: a JSON array
/// of fused `eu_id`s (descending fused score, ascending `eu_id` tie-break), or
/// `{"error": ...}`. Pure rank arithmetic — no tokenization, no key (ADR-0006).
///
/// # Safety
/// `lists_json` must be a valid NUL-terminated UTF-8 C string.
#[no_mangle]
pub unsafe extern "C" fn citenexus_rrf(lists_json: *const c_char, k: i64) -> *mut c_char {
    if lists_json.is_null() {
        return to_c_string(error_json("null argument"));
    }
    let raw = match CStr::from_ptr(lists_json).to_str() {
        Ok(s) => s,
        Err(_) => return to_c_string(error_json("lists_json is not UTF-8")),
    };
    let lists: Vec<Vec<String>> = match serde_json::from_str(raw) {
        Ok(v) => v,
        Err(e) => return to_c_string(error_json(&format!("lists_json: {e}"))),
    };
    let fused = crate::rrf::rrf(&lists, k);
    let payload =
        serde_json::to_string(&fused).unwrap_or_else(|e| error_json(&e.to_string()));
    to_c_string(payload)
}

/// Release a string returned by any `citenexus_*` call.
///
/// # Safety
/// `s` must be a pointer previously returned by this library (or null).
#[no_mangle]
pub unsafe extern "C" fn citenexus_free_string(s: *mut c_char) {
    if !s.is_null() {
        drop(CString::from_raw(s));
    }
}

/// The core's version, as a static C string (no free needed).
#[no_mangle]
pub extern "C" fn citenexus_core_version() -> *const c_char {
    concat!(env!("CARGO_PKG_VERSION"), "\0").as_ptr() as *const c_char
}

// ---------------------------------------------------------------------------
// store — Lance over an opaque handle. Handles come from `citenexus_store_open`
// (Box::into_raw) and MUST be released with `citenexus_store_close`. Every
// returned string is JSON (`{"error": ...}` on failure) and MUST be released
// with `citenexus_free_string`.
// ---------------------------------------------------------------------------

unsafe fn utf8_arg<'a>(ptr: *const c_char, name: &str) -> Result<&'a str, String> {
    if ptr.is_null() {
        return Err(format!("{name} is null"));
    }
    CStr::from_ptr(ptr)
        .to_str()
        .map_err(|_| format!("{name} is not UTF-8"))
}

/// Open (or create) the Lance database at `uri`. `storage_options_json` is a
/// JSON object of string pairs (endpoint, access_key_id, …) or null/`{}` for
/// none. Returns an opaque handle, or null on failure.
///
/// # Safety
/// `uri` must be a valid NUL-terminated UTF-8 C string;
/// `storage_options_json` must be one too, or null. The returned handle must
/// be released with `citenexus_store_close` exactly once.
#[no_mangle]
pub unsafe extern "C" fn citenexus_store_open(
    uri: *const c_char,
    storage_options_json: *const c_char,
) -> *mut LanceStore {
    let Ok(uri) = utf8_arg(uri, "uri") else {
        return std::ptr::null_mut();
    };
    let options: BTreeMap<String, String> = if storage_options_json.is_null() {
        BTreeMap::new()
    } else {
        let Ok(raw) = utf8_arg(storage_options_json, "storage_options_json") else {
            return std::ptr::null_mut();
        };
        match serde_json::from_str(raw) {
            Ok(map) => map,
            Err(_) => return std::ptr::null_mut(),
        }
    };
    match LanceStore::open(uri, &options) {
        Ok(store) => Box::into_raw(Box::new(store)),
        Err(_) => std::ptr::null_mut(),
    }
}

/// Upsert `rows_json` (a JSON array of row objects, keyed by `eu_id`).
/// Returns `{"ok":true}` or `{"error": ...}`.
///
/// # Safety
/// `handle` must be a live pointer from `citenexus_store_open`; `rows_json`
/// must be a valid NUL-terminated UTF-8 C string.
#[no_mangle]
pub unsafe extern "C" fn citenexus_store_upsert(
    handle: *mut LanceStore,
    rows_json: *const c_char,
) -> *mut c_char {
    if handle.is_null() {
        return to_c_string(error_json("null store handle"));
    }
    let rows = match utf8_arg(rows_json, "rows_json") {
        Ok(raw) => match serde_json::from_str::<serde_json::Value>(raw) {
            Ok(v) => v,
            Err(e) => return to_c_string(error_json(&format!("rows_json: {e}"))),
        },
        Err(msg) => return to_c_string(error_json(&msg)),
    };
    let payload = match (*handle).upsert(&rows) {
        Ok(()) => r#"{"ok":true}"#.to_string(),
        Err(message) => error_json(&message),
    };
    to_c_string(payload)
}

/// Vector search: `vector_json` is a JSON array of numbers; returns the
/// nearest `limit` rows as a JSON array (each row carries `_distance`), or
/// `{"error": ...}`.
///
/// # Safety
/// `handle` must be a live pointer from `citenexus_store_open`; `vector_json`
/// must be a valid NUL-terminated UTF-8 C string.
#[no_mangle]
pub unsafe extern "C" fn citenexus_store_search(
    handle: *mut LanceStore,
    vector_json: *const c_char,
    limit: usize,
) -> *mut c_char {
    if handle.is_null() {
        return to_c_string(error_json("null store handle"));
    }
    let vector: Vec<f32> = match utf8_arg(vector_json, "vector_json") {
        Ok(raw) => match serde_json::from_str(raw) {
            Ok(v) => v,
            Err(e) => return to_c_string(error_json(&format!("vector_json: {e}"))),
        },
        Err(msg) => return to_c_string(error_json(&msg)),
    };
    let payload = match (*handle).search(&vector, limit) {
        Ok(rows) => rows.to_string(),
        Err(message) => error_json(&message),
    };
    to_c_string(payload)
}

/// Scan all rows (`limit` < 0 means no limit). Returns a JSON array, or
/// `{"error": ...}`.
///
/// # Safety
/// `handle` must be a live pointer from `citenexus_store_open`.
#[no_mangle]
pub unsafe extern "C" fn citenexus_store_scan(handle: *mut LanceStore, limit: i64) -> *mut c_char {
    if handle.is_null() {
        return to_c_string(error_json("null store handle"));
    }
    let limit = usize::try_from(limit).ok();
    let payload = match (*handle).scan(limit) {
        Ok(rows) => rows.to_string(),
        Err(message) => error_json(&message),
    };
    to_c_string(payload)
}

/// Remove every row for `document_id` (no-op when absent) — the row-level
/// inverse of upsert used by document-revoke. Returns `{"ok":true}` or
/// `{"error": ...}`.
///
/// # Safety
/// `handle` must be a live pointer from `citenexus_store_open`; `document_id`
/// must be a valid NUL-terminated UTF-8 C string.
#[no_mangle]
pub unsafe extern "C" fn citenexus_store_delete_document(
    handle: *mut LanceStore,
    document_id: *const c_char,
) -> *mut c_char {
    if handle.is_null() {
        return to_c_string(error_json("null store handle"));
    }
    let document_id = match utf8_arg(document_id, "document_id") {
        Ok(raw) => raw,
        Err(msg) => return to_c_string(error_json(&msg)),
    };
    let payload = match (*handle).delete_document(document_id) {
        Ok(()) => r#"{"ok":true}"#.to_string(),
        Err(message) => error_json(&message),
    };
    to_c_string(payload)
}

/// Drop the `evidence_units` table (no-op when absent). Returns `{"ok":true}`
/// or `{"error": ...}`.
///
/// # Safety
/// `handle` must be a live pointer from `citenexus_store_open`.
#[no_mangle]
pub unsafe extern "C" fn citenexus_store_drop(handle: *mut LanceStore) -> *mut c_char {
    if handle.is_null() {
        return to_c_string(error_json("null store handle"));
    }
    let payload = match (*handle).drop_table() {
        Ok(()) => r#"{"ok":true}"#.to_string(),
        Err(message) => error_json(&message),
    };
    to_c_string(payload)
}

/// Release a store handle. Safe to call with null.
///
/// # Safety
/// `handle` must be a pointer from `citenexus_store_open` (or null) and must
/// not be used after this call.
#[no_mangle]
pub unsafe extern "C" fn citenexus_store_close(handle: *mut LanceStore) {
    if !handle.is_null() {
        drop(Box::from_raw(handle));
    }
}

// ---------------------------------------------------------------------------
// detect — fastText lid.176 over an opaque handle. Handles come from
// `citenexus_detector_open` and MUST be released with `citenexus_detector_close`.
// ---------------------------------------------------------------------------

/// Load the lid.176 model at `model_path`. Returns an opaque handle, or null
/// when the file is missing or unloadable. The model is caller-supplied — the
/// core never downloads it.
///
/// # Safety
/// `model_path` must be a valid NUL-terminated UTF-8 C string. The returned
/// handle must be released with `citenexus_detector_close` exactly once.
#[no_mangle]
pub unsafe extern "C" fn citenexus_detector_open(model_path: *const c_char) -> *mut Detector {
    let Ok(path) = utf8_arg(model_path, "model_path") else {
        return std::ptr::null_mut();
    };
    match Detector::open(path) {
        Ok(detector) => Box::into_raw(Box::new(detector)),
        Err(_) => std::ptr::null_mut(),
    }
}

/// Detect the language of `text`. Returns
/// `{"language":"fr","confidence":0.98}` or `{"error": ...}`.
///
/// # Safety
/// `handle` must be a live pointer from `citenexus_detector_open`; `text`
/// must be a valid NUL-terminated UTF-8 C string.
#[no_mangle]
pub unsafe extern "C" fn citenexus_detect(
    handle: *mut Detector,
    text: *const c_char,
) -> *mut c_char {
    if handle.is_null() {
        return to_c_string(error_json("null detector handle"));
    }
    let text = match utf8_arg(text, "text") {
        Ok(t) => t,
        Err(msg) => return to_c_string(error_json(&msg)),
    };
    let payload = match (*handle).detect(text) {
        Ok(detection) => {
            serde_json::to_string(&detection).unwrap_or_else(|e| error_json(&e.to_string()))
        }
        Err(message) => error_json(&message),
    };
    to_c_string(payload)
}

/// Release a detector handle. Safe to call with null.
///
/// # Safety
/// `handle` must be a pointer from `citenexus_detector_open` (or null) and
/// must not be used after this call.
#[no_mangle]
pub unsafe extern "C" fn citenexus_detector_close(handle: *mut Detector) {
    if !handle.is_null() {
        drop(Box::from_raw(handle));
    }
}
