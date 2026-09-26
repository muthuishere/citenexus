//! Committed synthetic PDF fixtures, written by `common::pdfgen` so bindings
//! (Go `core.PdfUnits`) can test without a generator of their own. The test
//! fails if a fixture drifts from its generator; regenerate with
//! `CITENEXUS_WRITE_PDF_FIXTURES=1 cargo test --test pdf_fixtures_test`.

mod common;

use common::pdfgen::{Doc, Page};

/// Tagged H1/H2 + a two-line paragraph + a pdfium hyphen + a running footer.
pub fn base_structure() -> Doc {
    let p1 = Page::a4()
        .tagged("H1", 72.0, 60.0, 18.0, true, "Leave Policy")
        .tagged("P#a", 72.0, 100.0, 11.0, false, "Staff must send an e-")
        .tagged("P#a", 72.0, 114.0, 11.0, false, "mail before the regu-")
        .tagged("P#a", 72.0, 128.0, 11.0, false, "lation deadline.")
        .text(250.0, 800.0, 9.0, "laatst bijgewerkt 12-03-2024");
    let p2 = Page::a4()
        .tagged("H2", 72.0, 60.0, 14.0, true, "Scope")
        .tagged("P#b", 72.0, 100.0, 11.0, false, "It applies to all staff.")
        .text(250.0, 800.0, 9.0, "laatst bijgewerkt 12-03-2024");
    Doc::new(vec![p1, p2])
}

#[test]
fn committed_pdf_fixtures_match_the_generator() {
    let dir = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../conformance/fixtures/pdf");
    let fixtures = [("base-structure.pdf", base_structure().build())];
    for (name, bytes) in fixtures {
        let path = dir.join(name);
        if std::env::var_os("CITENEXUS_WRITE_PDF_FIXTURES").is_some() {
            std::fs::create_dir_all(&dir).unwrap();
            std::fs::write(&path, &bytes).unwrap();
        }
        let on_disk = std::fs::read(&path)
            .expect("fixture missing: regenerate with CITENEXUS_WRITE_PDF_FIXTURES=1");
        assert_eq!(on_disk, bytes, "{name} drifted from its generator");
    }
}
