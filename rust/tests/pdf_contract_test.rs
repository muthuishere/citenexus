//! ADR-0017 step 3: the structure-not-text contract over SYNTHETIC PDFs.
//! Runs every vector in `tests/data/pdf/pdf_assemble.json`, plus the
//! determinism vectors. Skips (with a message) without libpdfium.
#![cfg(feature = "pdf")]

mod common;

use std::collections::BTreeMap;

use citenexus_core::extract::pdf::{pdf_assemble, pdf_prepare, pdf_units, raw};
use citenexus_core::units::*;
use common::pdfgen::{Doc, Page};

fn have_pdfium() -> bool {
    match raw::pdfium() {
        Ok(_) => true,
        Err(e) => {
            eprintln!("SKIP: libpdfium unavailable ({e}); set PDFIUM_DYNAMIC_LIB_PATH");
            false
        }
    }
}

fn opts() -> PdfOptions {
    PdfOptions {
        language: Some("nl".into()),
        layout_text: false,
        model_tables: true,
    }
}

/// A ruled 3×4 table between two paragraphs; one empty cell.
pub fn table_fixture() -> Doc {
    let mut page = Page::a4().para(
        72.0,
        60.0,
        11.0,
        &["Declaraties over het jaar 2024 staan hieronder."],
    );
    let ys = [100.0, 120.0, 140.0, 160.0, 180.0];
    for y in ys {
        page = page.line(72.0, y, 472.0, y);
    }
    for x in [72.0, 222.0, 322.0, 472.0] {
        page = page.line(x, 100.0, x, 180.0);
    }
    page = page
        .bold(76.0, 104.0, 10.0, "Omschrijving")
        .bold(226.0, 104.0, 10.0, "Bedrag")
        .bold(326.0, 104.0, 10.0, "Opmerking");
    let rows = [
        ("Reiskosten", "7.000,00", "geen"),
        ("Hotel", "5.100,00", ""),
        ("Diner", "1.250,00", "vooraf"),
    ];
    for (k, (a, b, c)) in rows.iter().enumerate() {
        let y = 124.0 + k as f64 * 20.0;
        page = page.text(76.0, y, 10.0, a).text(226.0, y, 10.0, b);
        if !c.is_empty() {
            page = page.text(326.0, y, 10.0, c);
        }
    }
    page = page.para(72.0, 210.0, 11.0, &["Bedragen zijn exclusief btw."]);
    Doc::new(vec![page])
}

/// A full-page scan image with an invisible OCR layer (render mode 3).
pub fn scan_fixture() -> Doc {
    let lines = [
        "Declaratie reiskosten 2024",
        "Reiskosten 7.000,00 geen voorschot",
        "Hotel 5.100,00 per jaar",
        "Diner 1.250,00 vooraf betaald",
        "Artikel I.3 is van toepassing",
    ];
    let mut page = Page::a4().image(0.0, 0.0, 595.0, 842.0);
    for (k, l) in lines.iter().enumerate() {
        page = page.ocr(72.0, 80.0 + k as f64 * 20.0, 11.0, l);
    }
    Doc::new(vec![page])
}

/// A text page with an image region (a form screenshot) and no words in it.
pub fn region_fixture() -> Doc {
    let page = Page::a4()
        .para(
            72.0,
            60.0,
            11.0,
            &["Vul het formulier hieronder in en lever het in."],
        )
        .image(72.0, 120.0, 300.0, 200.0)
        .para(
            72.0,
            360.0,
            11.0,
            &["Lever het formulier binnen een week in."],
        );
    Doc::new(vec![page])
}

fn fixture(name: &str) -> Vec<u8> {
    match name {
        "table" => table_fixture(),
        "scan" => scan_fixture(),
        "region" => region_fixture(),
        other => panic!("unknown fixture {other}"),
    }
    .build()
}

/// Resolve printed-text cell references to word IDs through prepare's words.
fn resolve(prep: &PdfPrepared, request: &str, cell: &[serde_json::Value]) -> Vec<String> {
    let req = prep.requests.iter().find(|r| r.id == request);
    cell.iter()
        .map(|v| {
            let s = v.as_str().unwrap();
            if let Some(id) = s.strip_prefix('@') {
                return id.to_string();
            }
            let (text, nth) = match s.rsplit_once('#') {
                Some((t, n)) if n.chars().all(|c| c.is_ascii_digit()) => {
                    (t, n.parse::<usize>().unwrap())
                }
                _ => (s, 1),
            };
            let req = req.unwrap_or_else(|| panic!("no request {request}: {:?}", prep.requests));
            req.words
                .iter()
                .filter(|w| w.text == text)
                .nth(nth - 1)
                .unwrap_or_else(|| panic!("no word {s:?} in {request}"))
                .id
                .clone()
        })
        .collect()
}

fn responses(prep: &PdfPrepared, spec: &serde_json::Value) -> Vec<PdfResponse> {
    spec.as_array()
        .unwrap()
        .iter()
        .map(|r| {
            let request = r["request"].as_str().unwrap();
            let tables = r["tables"].as_array().map(|ts| {
                ts.iter()
                    .map(|t| PdfGrid {
                        rows: t["rows"]
                            .as_array()
                            .unwrap()
                            .iter()
                            .map(|row| {
                                row.as_array()
                                    .unwrap()
                                    .iter()
                                    .map(|c| {
                                        PdfCell::Words(resolve(
                                            prep,
                                            request,
                                            c.as_array().unwrap(),
                                        ))
                                    })
                                    .collect()
                            })
                            .collect(),
                    })
                    .collect()
            });
            PdfResponse {
                request_id: request.to_string(),
                finish_reason: r["finish_reason"].as_str().map(String::from),
                tables,
                markdown: r["markdown"].as_str().map(String::from),
            }
        })
        .collect()
}

fn vectors() -> serde_json::Value {
    let p = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/tests/data/pdf/pdf_assemble.json"
    );
    serde_json::from_str(&std::fs::read_to_string(p).unwrap()).unwrap()
}

#[test]
fn prepare_emits_the_expected_requests() {
    if !have_pdfium() {
        return;
    }
    let t = pdf_prepare(&fixture("table"), &opts()).unwrap();
    assert_eq!(t.requests.len(), 1);
    let r = &t.requests[0];
    assert_eq!(
        (r.id.as_str(), r.kind),
        ("p1:table0", PdfRequestKind::TableStructure)
    );
    let texts: Vec<&str> = r.words.iter().map(|w| w.text.as_str()).collect();
    assert!(
        texts.contains(&"7.000,00") && texts.contains(&"Omschrijving"),
        "{texts:?}"
    );
    assert!(r.words.iter().all(|w| w.id.starts_with("p1w")));
    let s = pdf_prepare(&fixture("scan"), &opts()).unwrap();
    assert_eq!(
        s.requests.iter().map(|r| r.id.as_str()).collect::<Vec<_>>(),
        vec!["p1:page:v1", "p1:page:v2"]
    );
    // two independent variants, each told to use another model or seed
    assert_eq!(
        s.requests.iter().map(|r| r.variant).collect::<Vec<_>>(),
        vec![Some(1), Some(2)]
    );
    assert!(s.requests.iter().all(|r| r
        .hint
        .as_deref()
        .is_some_and(|h| h.contains("different model"))));
    assert_eq!(r.variant, None);
    let g = pdf_prepare(&fixture("region"), &opts()).unwrap();
    assert_eq!(
        g.requests.iter().map(|r| r.id.as_str()).collect::<Vec<_>>(),
        vec!["p1:img0:v1", "p1:img0:v2"]
    );
}

#[test]
fn assemble_vectors() {
    if !have_pdfium() {
        return;
    }
    let v = vectors();
    let cases = v["cases"].as_array().unwrap();
    let mut tally: BTreeMap<String, usize> = BTreeMap::new();
    for c in cases {
        let name = c["name"].as_str().unwrap();
        let bytes = fixture(c["fixture"].as_str().unwrap());
        let prep = pdf_prepare(&bytes, &opts()).unwrap();
        let rs = responses(&prep, &c["responses"]);
        let out = pdf_assemble(&bytes, &opts(), &rs).unwrap();
        let e = &c["expect"];
        let d = &out.document;
        assert_eq!(
            d.responses_applied as u64,
            e["applied"].as_u64().unwrap(),
            "{name}"
        );
        assert_eq!(
            d.responses_rejected as u64,
            e["rejected"].as_u64().unwrap(),
            "{name}"
        );
        let failed: Vec<&str> = out
            .units
            .iter()
            .filter_map(|u| u.provenance.failed_check.as_deref())
            .collect();
        match e["failed_check"].as_str() {
            Some(f) => {
                assert!(
                    !failed.is_empty() && failed.iter().all(|x| *x == f),
                    "{name}: {failed:?} != {f}"
                );
                if e["base_kept"].as_bool() == Some(true) {
                    // A rejected response leaves the base text in place.
                    assert_eq!(
                        out.units.iter().map(|u| &u.markdown).collect::<Vec<_>>(),
                        prep.units.iter().map(|u| &u.markdown).collect::<Vec<_>>(),
                        "{name}: base text must survive a rejection"
                    );
                }
            }
            None => assert!(failed.is_empty(), "{name}: {failed:?}"),
        }
        if let Some(t) = e["table"].as_str() {
            let tables: Vec<&DocUnit> = out
                .units
                .iter()
                .filter(|u| u.kind == UnitKind::Table)
                .collect();
            assert_eq!(tables.len(), 1, "{name}");
            assert_eq!(tables[0].markdown, t, "{name}");
            let want_src = match e["table_source"].as_str() {
                Some("ruled") => TableSource::Ruled,
                Some("tracks") => TableSource::Tracks,
                Some("struct_tree") => TableSource::StructTree,
                _ => TableSource::ModelGrid,
            };
            assert_eq!(tables[0].provenance.table_source, Some(want_src), "{name}");
            if let Some(u) = e["table_uncertain"].as_bool() {
                assert_eq!(tables[0].provenance.table_uncertain, u, "{name}");
            }
            assert!(!tables[0].provenance.vision_transcribed);
            // the table sits between the two paragraphs, which survive
            let md: Vec<&str> = out.units.iter().map(|u| u.markdown.as_str()).collect();
            assert_eq!(
                md.first(),
                Some(&"Declaraties over het jaar 2024 staan hieronder."),
                "{md:?}"
            );
            assert_eq!(md.last(), Some(&"Bedragen zijn exclusief btw."), "{md:?}");
            assert_eq!(md.len(), 3, "{md:?}");
        }
        if e["vision_transcribed"].as_bool() == Some(true) {
            let vt: Vec<&DocUnit> = out
                .units
                .iter()
                .filter(|u| u.provenance.vision_transcribed)
                .collect();
            assert_eq!(vt.len(), 1, "{name}");
            let u = vt[0];
            assert!(!u.markdown.is_empty());
            if let Some(dsp) = e["vision_disputed"].as_bool() {
                assert_eq!(u.provenance.vision_disputed, dsp, "{name}: {}", u.markdown);
            }
            let citable = citenexus_core::vision::citable_text(&u.markdown);
            for want in e["citable_contains"].as_array().into_iter().flatten() {
                let w = want.as_str().unwrap();
                assert!(
                    citable.contains(w),
                    "{name}: citable lacks {w:?}:\n{citable}"
                );
            }
            for bad in e["citable_excludes"].as_array().into_iter().flatten() {
                let b = bad.as_str().unwrap();
                assert!(
                    !citable.contains(b),
                    "{name}: citable has {b:?}:\n{citable}"
                );
            }
            for want in e["markdown_contains"].as_array().into_iter().flatten() {
                let w = want.as_str().unwrap();
                assert!(
                    u.markdown.contains(w),
                    "{name}: markdown lacks {w:?}:\n{}",
                    u.markdown
                );
            }
        }
        *tally
            .entry(c["category"].as_str().unwrap().to_string())
            .or_default() += 1;
    }
    eprintln!("pdf_assemble vectors: {tally:?}");
    assert!(tally["must_reject"] >= 14);
}

fn mixed() -> (Vec<u8>, Vec<PdfResponse>) {
    // table + scan + region pages in one document, one response each.
    let mut doc = table_fixture();
    doc.pages.push(scan_fixture().pages.remove(0));
    doc.pages.push(region_fixture().pages.remove(0));
    let bytes = doc.build();
    let prep = pdf_prepare(&bytes, &opts()).unwrap();
    let ids: Vec<&str> = prep.requests.iter().map(|r| r.id.as_str()).collect();
    assert_eq!(
        ids,
        vec![
            "p1:table0",
            "p2:page:v1",
            "p2:page:v2",
            "p3:img0:v1",
            "p3:img0:v2"
        ]
    );
    let spec = serde_json::json!([
        {"request": "p1:table0", "finish_reason": "stop", "tables": [{"rows": [
            [["Omschrijving"], ["Bedrag"], ["Opmerking"]],
            [["Reiskosten"], ["7.000,00"], ["geen"]],
            [["Hotel"], ["5.100,00"], []],
            [["Diner"], ["1.250,00"], ["vooraf"]]]}]},
        {"request": "p2:page:v1", "markdown": "Declaratie reiskosten 2024\nReiskosten 7.000,00 geen voorschot\nHotel 5.100,00 per jaar\nDiner 1.250,00 vooraf betaald\nArtikel I.3 is van toepassing"},
        {"request": "p2:page:v2", "markdown": "Declaratie reiskosten 2024\nReiskosten 7.000,00 voorschot\nHotel 5.100,00 geen per jaar\nDiner 1.250,00 vooraf betaald\nArtikel I.3 is van toepassing"},
        {"request": "p3:img0:v1", "markdown": "Formulier: naam, datum, handtekening"},
        {"request": "p3:img0:v2", "markdown": "Formulier: naam, datum, handtekening"}
    ]);
    let rs = responses(&prep, &spec);
    (bytes, rs)
}

#[test]
fn assemble_is_deterministic_and_units_is_assemble_without_responses() {
    if !have_pdfium() {
        return;
    }
    let (bytes, rs) = mixed();
    let a = serde_json::to_string(&pdf_assemble(&bytes, &opts(), &rs).unwrap()).unwrap();
    let b = serde_json::to_string(&pdf_assemble(&bytes, &opts(), &rs).unwrap()).unwrap();
    assert_eq!(a, b);
    let out: PdfUnitsOutput = serde_json::from_str(&a).unwrap();
    assert_eq!(out.document.responses_applied, 5, "{:?}", out.document);
    let base = serde_json::to_string(&pdf_units(&bytes, &opts()).unwrap()).unwrap();
    let none = serde_json::to_string(&pdf_assemble(&bytes, &opts(), &[]).unwrap()).unwrap();
    assert_eq!(base, none);
    // an unknown request id changes nothing either
    let stray = vec![PdfResponse {
        request_id: "p9:table".into(),
        finish_reason: None,
        tables: None,
        markdown: Some("x".into()),
    }];
    let s = serde_json::to_string(&pdf_assemble(&bytes, &opts(), &stray).unwrap()).unwrap();
    assert_eq!(s, base);
}

/// The cross-port determinism vector: the committed fixture + responses must
/// produce these exact bytes in every binding (Go reads the same files).
#[test]
fn committed_golden_assemble_vector() {
    if !have_pdfium() {
        return;
    }
    let dir = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/data/pdf");
    let (bytes, rs) = mixed();
    let responses_json = serde_json::to_string_pretty(&rs).unwrap();
    let golden = serde_json::to_string(&pdf_assemble(&bytes, &opts(), &rs).unwrap()).unwrap();
    let files = [
        ("assemble-mixed.pdf", bytes.clone()),
        ("assemble-mixed.responses.json", responses_json.into_bytes()),
        ("assemble-mixed.golden.json", golden.clone().into_bytes()),
    ];
    for (name, content) in files {
        let path = dir.join(name);
        if std::env::var_os("CITENEXUS_WRITE_PDF_FIXTURES").is_some() {
            std::fs::write(&path, &content).unwrap();
        }
        let on_disk = std::fs::read(&path).expect("regenerate with CITENEXUS_WRITE_PDF_FIXTURES=1");
        assert!(on_disk == content, "{name} drifted from its generator");
    }
}
