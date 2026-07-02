//! LanceStore semantics — must mirror Python's `LanceVectorStore`
//! (`src/trustrag/storage/lance_store.py`): empty store returns `[]`, upsert
//! is idempotent by `eu_id`, search carries `_distance`, drop empties.

use serde_json::{json, Value};
use trustrag_core::LanceStore;

fn rows() -> Value {
    json!([
        {
            "eu_id": "doc::0",
            "vector": [1.0, 0.0, 0.0, 0.0],
            "text": "Employees accrue leave.",
            "document_id": "doc",
            "language": "en",
            "page": 1,
            "checksum": "c0",
            "raw_uri": "s3://bucket/raw/doc"
        },
        {
            "eu_id": "doc::1",
            "vector": [0.0, 1.0, 0.0, 0.0],
            "text": "Remote work needs approval.",
            "document_id": "doc",
            "language": "en",
            "page": 2,
            "checksum": "c1",
            "raw_uri": "s3://bucket/raw/doc"
        },
        {
            "eu_id": "doc::2",
            "vector": [0.0, 0.0, 1.0, 0.0],
            "text": "Les employés accumulent des congés.",
            "document_id": "doc",
            "language": "fr",
            "page": 3,
            "checksum": "c2",
            "raw_uri": "s3://bucket/raw/doc"
        }
    ])
}

fn open_store() -> (tempfile::TempDir, LanceStore) {
    let dir = tempfile::tempdir().expect("tempdir");
    let store = LanceStore::open(dir.path().to_str().unwrap(), &Default::default())
        .expect("open store");
    (dir, store)
}

fn eu_ids(rows: &Value) -> Vec<&str> {
    let mut ids: Vec<&str> = rows
        .as_array()
        .unwrap()
        .iter()
        .map(|r| r["eu_id"].as_str().unwrap())
        .collect();
    ids.sort();
    ids
}

#[test]
fn empty_store_scan_and_search_return_empty() {
    let (_dir, store) = open_store();
    assert_eq!(store.scan(None).unwrap(), json!([]));
    assert_eq!(store.search(&[1.0, 0.0, 0.0, 0.0], 5).unwrap(), json!([]));
}

#[test]
fn upsert_empty_rows_is_a_noop() {
    let (_dir, store) = open_store();
    store.upsert(&json!([])).unwrap();
    assert_eq!(store.scan(None).unwrap(), json!([]));
}

#[test]
fn upsert_then_scan_roundtrips_rows() {
    let (_dir, store) = open_store();
    store.upsert(&rows()).unwrap();
    let scanned = store.scan(None).unwrap();
    assert_eq!(eu_ids(&scanned), vec!["doc::0", "doc::1", "doc::2"]);
    let first = scanned
        .as_array()
        .unwrap()
        .iter()
        .find(|r| r["eu_id"] == "doc::0")
        .unwrap();
    assert_eq!(first["text"], "Employees accrue leave.");
    assert_eq!(first["document_id"], "doc");
    assert_eq!(first["language"], "en");
    assert_eq!(first["page"], 1);
    assert_eq!(first["checksum"], "c0");
    assert_eq!(first["raw_uri"], "s3://bucket/raw/doc");
    let vector: Vec<f64> = first["vector"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_f64().unwrap())
        .collect();
    assert_eq!(vector, vec![1.0, 0.0, 0.0, 0.0]);
}

#[test]
fn upsert_is_idempotent_by_eu_id() {
    let (_dir, store) = open_store();
    store.upsert(&rows()).unwrap();
    store.upsert(&rows()).unwrap(); // same rows again: no duplicates
    assert_eq!(store.scan(None).unwrap().as_array().unwrap().len(), 3);

    // Re-upserting a changed row updates in place.
    let mut updated = rows();
    updated[1]["text"] = json!("Remote work is pre-approved.");
    store.upsert(&updated).unwrap();
    let scanned = store.scan(None).unwrap();
    assert_eq!(scanned.as_array().unwrap().len(), 3);
    let row = scanned
        .as_array()
        .unwrap()
        .iter()
        .find(|r| r["eu_id"] == "doc::1")
        .unwrap();
    assert_eq!(row["text"], "Remote work is pre-approved.");
}

#[test]
fn search_returns_nearest_first_with_distance() {
    let (_dir, store) = open_store();
    store.upsert(&rows()).unwrap();
    let hits = store.search(&[0.0, 0.9, 0.1, 0.0], 2).unwrap();
    let hits = hits.as_array().unwrap();
    assert_eq!(hits.len(), 2);
    assert_eq!(hits[0]["eu_id"], "doc::1");
    let d0 = hits[0]["_distance"].as_f64().unwrap();
    let d1 = hits[1]["_distance"].as_f64().unwrap();
    assert!(d0 <= d1, "nearest first: {d0} <= {d1}");
    // An exact-match query is at (near-)zero L2 distance.
    let exact = store.search(&[1.0, 0.0, 0.0, 0.0], 1).unwrap();
    assert!(exact[0]["_distance"].as_f64().unwrap() < 1e-6);
}

#[test]
fn scan_respects_limit() {
    let (_dir, store) = open_store();
    store.upsert(&rows()).unwrap();
    assert_eq!(store.scan(Some(2)).unwrap().as_array().unwrap().len(), 2);
    assert_eq!(store.scan(None).unwrap().as_array().unwrap().len(), 3);
}

#[test]
fn drop_table_empties_the_leaf_and_is_idempotent() {
    let (_dir, store) = open_store();
    store.upsert(&rows()).unwrap();
    store.drop_table().unwrap();
    assert_eq!(store.scan(None).unwrap(), json!([]));
    store.drop_table().unwrap(); // dropping a missing table is a no-op
    // The leaf is usable again after a drop.
    store.upsert(&rows()).unwrap();
    assert_eq!(store.scan(None).unwrap().as_array().unwrap().len(), 3);
}
