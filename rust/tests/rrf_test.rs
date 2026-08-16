//! RRF byte-parity: the core's fused ordering must equal the Python reference
//! (`citenexus.retrieve.fusion.rrf_fuse`) for every shared conformance vector.
//! The fixture at `conformance/cases/rrf.json` is generated FROM Python, so
//! passing it proves the relocated arithmetic is byte-identical (ADR-0006).

use std::ffi::{CStr, CString};
use std::os::raw::c_char;
use std::path::PathBuf;

use citenexus_core::{ffi, rrf};
use serde_json::Value;

fn fixture() -> Value {
    // this file = <repo>/rust/tests/rrf_test.rs -> up 2 to <repo>.
    let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .canonicalize()
        .unwrap();
    let raw = std::fs::read_to_string(repo.join("conformance/cases/rrf.json"))
        .expect("read conformance/cases/rrf.json");
    serde_json::from_str(&raw).expect("parse rrf.json")
}

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
fn rrf_matches_python_reference_over_all_vectors() {
    let cases = fixture();
    let cases = cases.as_array().expect("rrf.json is an array");
    assert!(!cases.is_empty(), "no rrf conformance cases");

    for case in cases {
        let lists: Vec<Vec<String>> =
            serde_json::from_value(case["lists"].clone()).expect("lists");
        let k = case["k"].as_i64().expect("k");
        let expected: Vec<String> =
            serde_json::from_value(case["fused"].clone()).expect("fused");

        // (a) the pure Rust function
        assert_eq!(rrf::rrf(&lists, k), expected, "rrf() mismatch for {case:?}");

        // (b) through the exact C ABI a binding calls
        let lists_json = CString::new(case["lists"].to_string()).unwrap();
        let got = take_json(unsafe { ffi::citenexus_rrf(lists_json.as_ptr(), k) });
        assert_eq!(
            got,
            Value::from(expected.clone()),
            "citenexus_rrf mismatch for {case:?}"
        );
    }
}

#[test]
fn rrf_ordering_is_deterministic() {
    // Agreement across lists beats a single high rank; ties break by eu_id asc.
    let lists = vec![
        vec!["a".to_string(), "b".to_string(), "c".to_string()],
        vec!["b".to_string(), "c".to_string(), "d".to_string()],
        vec!["b".to_string(), "a".to_string(), "e".to_string()],
    ];
    let once = rrf::rrf(&lists, 60);
    // Same input -> same output, every time (HashMap iteration cannot leak in).
    for _ in 0..16 {
        assert_eq!(rrf::rrf(&lists, 60), once);
    }
    assert_eq!(once[0], "b", "the unanimously-ranked id must lead");
}

#[test]
fn rrf_ffi_rejects_bad_json() {
    let bad = CString::new("not json").unwrap();
    let got = take_json(unsafe { ffi::citenexus_rrf(bad.as_ptr(), 60) });
    assert!(got.get("error").is_some(), "expected an error object: {got}");
}
