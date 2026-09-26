//! The Rust number reader against the Python reference's 30
//! `number_readings` vectors (ADR-0015). See `tests/data/number_readings.json`
//! for where they come from.

use citenexus_core::numbers::read_number;

#[test]
fn number_readings_match_the_reference_vectors() {
    let raw = std::fs::read_to_string(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/tests/data/number_readings.json"
    ))
    .unwrap();
    let v: serde_json::Value = serde_json::from_str(&raw).unwrap();
    let cases = v["number_readings"].as_array().unwrap();
    assert_eq!(cases.len(), 30);
    for c in cases {
        let got = read_number(
            c["raw"].as_str().unwrap(),
            c["dash"].as_bool().unwrap(),
            c["language"].as_str(),
        );
        assert_eq!(got.key, c["key"].as_str().unwrap(), "{c}");
    }
}
