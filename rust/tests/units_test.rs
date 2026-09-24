//! The DocUnit JSON contract (ADR-0017): stable field order, snake_case enums,
//! null optionals, and a lossless round-trip.

use citenexus_core::units::*;

#[test]
fn doc_unit_serializes_in_declaration_order() {
    let mut prov = Provenance::new(Route::Formatted);
    prov.heading_source = Some(HeadingSource::StructTree);
    let unit = DocUnit {
        page: Some(2),
        bbox: Some([72.0, 90.5, 300.25, 110.0]),
        kind: UnitKind::Heading,
        level: Some(1),
        markdown: "# Scope".to_string(),
        provenance: prov,
    };
    let json = serde_json::to_string(&unit).unwrap();
    assert_eq!(
        json,
        r##"{"page":2,"bbox":[72.0,90.5,300.25,110.0],"kind":"heading","level":1,"markdown":"# Scope","provenance":{"route":"formatted","table_source":null,"vision_transcribed":false,"table_uncertain":false,"failed_check":null,"heading_source":"struct_tree","joined_hyphen":false}}"##
    );
    let back: DocUnit = serde_json::from_str(&json).unwrap();
    assert_eq!(back, unit);
}

#[test]
fn enums_are_snake_case() {
    let s = |v: serde_json::Value| v.as_str().unwrap().to_string();
    assert_eq!(s(serde_json::to_value(TableSource::ModelGrid).unwrap()), "model_grid");
    assert_eq!(s(serde_json::to_value(Route::Ooxml).unwrap()), "ooxml");
    assert_eq!(s(serde_json::to_value(UnitKind::Furniture).unwrap()), "furniture");
}

#[test]
fn provenance_defaults_deserialize_from_route_only() {
    let p: Provenance = serde_json::from_str(r#"{"route":"scan"}"#).unwrap();
    assert_eq!(p, Provenance::new(Route::Scan));
}
