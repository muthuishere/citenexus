//! The store C ABI, exercised in-crate: open → upsert → search → scan → drop
//! → close, all through the extern "C" surface a binding would call.

use std::ffi::{CStr, CString};
use std::os::raw::c_char;

use serde_json::{json, Value};
use citenexus_core::{ffi, LanceStore};

fn take_json(ptr: *mut c_char) -> Value {
    assert!(!ptr.is_null());
    let value = {
        let s = unsafe { CStr::from_ptr(ptr) }.to_str().expect("utf-8");
        serde_json::from_str(s).expect("json")
    };
    unsafe { ffi::citenexus_free_string(ptr) };
    value
}

#[test]
fn store_lifecycle_over_the_c_abi() {
    let dir = tempfile::tempdir().unwrap();
    let uri = CString::new(dir.path().to_str().unwrap()).unwrap();
    let options = CString::new("{}").unwrap();

    let handle: *mut LanceStore =
        unsafe { ffi::citenexus_store_open(uri.as_ptr(), options.as_ptr()) };
    assert!(!handle.is_null());

    // scan on an empty store -> []
    let empty = take_json(unsafe { ffi::citenexus_store_scan(handle, -1) });
    assert_eq!(empty, json!([]));

    let rows = CString::new(
        json!([
            {"eu_id": "doc::0", "vector": [1.0, 0.0], "text": "alpha",
             "document_id": "doc", "language": "en", "page": 1,
             "checksum": "c0", "raw_uri": "s3://b/doc"},
            {"eu_id": "doc::1", "vector": [0.0, 1.0], "text": "beta",
             "document_id": "doc", "language": "en", "page": 2,
             "checksum": "c1", "raw_uri": "s3://b/doc"}
        ])
        .to_string(),
    )
    .unwrap();
    let ok = take_json(unsafe { ffi::citenexus_store_upsert(handle, rows.as_ptr()) });
    assert_eq!(ok, json!({"ok": true}));

    let vector = CString::new("[1.0, 0.0]").unwrap();
    let hits = take_json(unsafe { ffi::citenexus_store_search(handle, vector.as_ptr(), 1) });
    assert_eq!(hits[0]["eu_id"], "doc::0");
    assert!(hits[0]["_distance"].as_f64().unwrap() < 1e-6);

    let scanned = take_json(unsafe { ffi::citenexus_store_scan(handle, -1) });
    assert_eq!(scanned.as_array().unwrap().len(), 2);
    let limited = take_json(unsafe { ffi::citenexus_store_scan(handle, 1) });
    assert_eq!(limited.as_array().unwrap().len(), 1);

    let dropped = take_json(unsafe { ffi::citenexus_store_drop(handle) });
    assert_eq!(dropped, json!({"ok": true}));
    let after = take_json(unsafe { ffi::citenexus_store_scan(handle, -1) });
    assert_eq!(after, json!([]));

    unsafe { ffi::citenexus_store_close(handle) };
}

#[test]
fn bad_inputs_return_error_json_not_crashes() {
    let dir = tempfile::tempdir().unwrap();
    let uri = CString::new(dir.path().to_str().unwrap()).unwrap();
    let handle = unsafe { ffi::citenexus_store_open(uri.as_ptr(), std::ptr::null()) };
    assert!(!handle.is_null());

    let not_json = CString::new("not json").unwrap();
    let err = take_json(unsafe { ffi::citenexus_store_upsert(handle, not_json.as_ptr()) });
    assert!(err["error"].is_string());

    let err = take_json(unsafe { ffi::citenexus_store_search(handle, not_json.as_ptr(), 3) });
    assert!(err["error"].is_string());

    // Null handles error (or no-op for close), never crash.
    let err = take_json(unsafe { ffi::citenexus_store_scan(std::ptr::null_mut(), -1) });
    assert!(err["error"].is_string());
    unsafe { ffi::citenexus_store_close(std::ptr::null_mut()) };

    unsafe { ffi::citenexus_store_close(handle) };
}

#[test]
fn detector_open_with_missing_model_returns_null() {
    let path = CString::new("/nonexistent/lid.176.ftz").unwrap();
    let handle = unsafe { ffi::citenexus_detector_open(path.as_ptr()) };
    assert!(handle.is_null());
    unsafe { ffi::citenexus_detector_close(handle) }; // null-safe
}
