//! The host-facing contract (`docs/pdf-model-contract.md`) cannot drift: the
//! committed synthetic fixtures must validate against
//! `docs/schema/pdf-model-contract.schema.json`, and obvious violations must
//! not.

use std::path::Path;

fn root() -> &'static Path {
    Path::new(env!("CARGO_MANIFEST_DIR"))
}

fn json(rel: &str) -> serde_json::Value {
    let p = root().join(rel);
    serde_json::from_str(
        &std::fs::read_to_string(&p).unwrap_or_else(|e| panic!("{}: {e}", p.display())),
    )
    .unwrap()
}

fn check(def: &str, instance: &serde_json::Value) -> Result<(), String> {
    let schema = json("../docs/schema/pdf-model-contract.schema.json");
    let mut schemas = boon::Schemas::new();
    let mut compiler = boon::Compiler::new();
    let url = "https://citenexus.dev/schema/pdf-model-contract.schema.json";
    compiler
        .add_resource(url, schema)
        .map_err(|e| e.to_string())?;
    let idx = compiler
        .compile(&format!("{url}#/$defs/{def}"), &mut schemas)
        .map_err(|e| e.to_string())?;
    schemas
        .validate(instance, idx)
        .map_err(|e| format!("{e:#}"))
}

#[test]
fn committed_responses_validate() {
    let v = json("tests/data/pdf/assemble-mixed.responses.json");
    check("PdfResponses", &v).unwrap();
}

#[test]
fn committed_prepared_and_assembled_outputs_validate() {
    check(
        "PdfPrepared",
        &json("tests/data/pdf/assemble-mixed.prepared.json"),
    )
    .unwrap();
    check(
        "PdfUnitsOutput",
        &json("tests/data/pdf/assemble-mixed.golden.json"),
    )
    .unwrap();
}

#[test]
fn violations_are_rejected() {
    // a response without request_id
    assert!(check("PdfResponse", &serde_json::json!({"markdown": "x"})).is_err());
    // a vision request without its variant
    let mut prepared = json("tests/data/pdf/assemble-mixed.prepared.json");
    let reqs = prepared["requests"].as_array_mut().unwrap();
    let vision = reqs
        .iter_mut()
        .find(|r| r["kind"] == "vision_page")
        .unwrap();
    vision["variant"] = serde_json::Value::Null;
    assert!(check("PdfPrepared", &prepared).is_err());
    // an unknown failed_check value on a unit
    let mut golden = json("tests/data/pdf/assemble-mixed.golden.json");
    golden["units"][0]["provenance"]["failed_check"] = serde_json::json!("vibes");
    assert!(check("PdfUnitsOutput", &golden).is_err());
    // model text on a table request is a shape the schema allows (the core
    // rejects it at assemble time); an unknown field is not
    assert!(check(
        "PdfResponse",
        &serde_json::json!({"request_id": "p1:table0", "cells": []})
    )
    .is_err());
}
