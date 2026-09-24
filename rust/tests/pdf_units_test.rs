//! The no-model base PDF extractor (ADR-0017 step 2) over SYNTHETIC PDFs.
//!
//! Needs libpdfium at runtime: set `PDFIUM_DYNAMIC_LIB_PATH` to the library
//! (or its directory). Without it every test here prints a SKIP line and
//! passes — see `rust/README.md`.
#![cfg(feature = "pdf")]

mod common;

use citenexus_core::extract::pdf::{pdf_units, raw};
use citenexus_core::units::*;
use common::pdfgen::{Doc, Page};

fn have_pdfium() -> bool {
    match raw::pdfium() {
        Ok(_) => true,
        Err(e) => {
            eprintln!("SKIP: libpdfium unavailable ({e}); set PDFIUM_DYNAMIC_LIB_PATH to run the PDF tests");
            false
        }
    }
}

fn run(doc: &Doc, lang: Option<&str>) -> PdfUnitsOutput {
    let opts = PdfOptions {
        language: lang.map(String::from),
        layout_text: true,
        ..Default::default()
    };
    pdf_units(&doc.build(), &opts).expect("pdf_units failed")
}

fn md(out: &PdfUnitsOutput) -> String {
    out.units
        .iter()
        .map(|u| u.markdown.as_str())
        .collect::<Vec<_>>()
        .join("\n\n")
}

// ------------------------------------------------------------- hyphens ----

fn hyphen_page(witness: bool) -> Doc {
    let mut lines = vec![
        "Staff must send an e-",
        "mail to the office about the long-",
        "term plan. The regu-",
        "lation covers in-",
        "en verkoop and every-",
        "one in the cost-",
        "center.",
    ];
    if witness {
        lines.push("Each cost-center reports monthly.");
    }
    Doc::new(vec![Page::a4().para(72.0, 100.0, 11.0, &lines)])
}

#[test]
fn hyphens_join_only_on_evidence() {
    if !have_pdfium() {
        return;
    }
    let out = run(&hyphen_page(false), Some("nl"));
    let text = md(&out);
    assert!(!text.contains('\u{2}'), "U+0002 leaked: {text:?}");
    for want in [
        "e-mail",
        "long-term",
        "regulation",
        "in- en verkoop",
        "everyone",
        "costcenter",
    ] {
        assert!(text.contains(want), "missing {want:?} in {text:?}");
    }
    assert!(
        !text.contains("email") && !text.contains("longterm"),
        "{text:?}"
    );
    let d = &out.document;
    assert_eq!(d.hyphen_markers, 6, "{d:?}");
    assert_eq!((d.hyphens_joined, d.hyphens_kept), (3, 3), "{d:?}");
    assert!(out.units.iter().any(|u| u.provenance.joined_hyphen));

    // A joined-elsewhere witness keeps the printed hyphen.
    let out = run(&hyphen_page(true), Some("nl"));
    let text = md(&out);
    assert!(text.contains("in the cost-center."), "{text:?}");
    assert!(!text.contains("costcenter"), "{text:?}");
}

// ---------------------------------------------------------- two columns ----

#[test]
fn two_column_page_reads_column_by_column() {
    if !have_pdfium() {
        return;
    }
    let page = Page::a4()
        .bold(72.0, 60.0, 20.0, "Annual Report")
        .para(
            72.0,
            110.0,
            10.0,
            &[
                "Left one alpha text",
                "left two alpha text",
                "left three alpha end.",
            ],
        )
        .para(
            320.0,
            110.0,
            10.0,
            &[
                "Right one beta text",
                "right two beta text",
                "right three beta end.",
            ],
        )
        .para(
            72.0,
            200.0,
            10.0,
            &["Left second para gamma", "left gamma closes."],
        )
        .para(
            320.0,
            200.0,
            10.0,
            &["Right second para delta", "right delta closes."],
        );
    let out = run(&Doc::new(vec![page]), Some("en"));
    let t = md(&out);
    let pos = |s: &str| t.find(s).unwrap_or_else(|| panic!("{s:?} not in {t:?}"));
    assert!(pos("# Annual Report") < pos("Left one"));
    assert!(pos("left three alpha end.") < pos("Left second para"));
    assert!(pos("left gamma closes.") < pos("Right one beta"));
    assert!(pos("right three beta end.") < pos("Right second para"));
    assert_eq!(
        out.units[1].markdown,
        "Left one alpha text left two alpha text left three alpha end."
    );
    let p = &out.pages[0];
    assert_eq!(p.signals.text_columns, 2);
    assert_eq!(p.signals.reading_order, "rule_based");
    assert_eq!(p.route, Route::Formatted);
    // The layout text keeps both columns on one line, pdftotext -layout style.
    let lt = p.layout_text.as_deref().unwrap();
    let row = lt.lines().find(|l| l.contains("Left one")).unwrap();
    assert!(row.contains("Right one beta text"), "{lt}");
}

// ------------------------------------------------- running header/footer ----

#[test]
fn running_header_footer_kept_once_as_furniture() {
    if !have_pdfium() {
        return;
    }
    let pages: Vec<Page> = (1..=3)
        .map(|n| {
            Page::a4()
                .text(
                    72.0,
                    30.0,
                    9.0,
                    "Verlofbeleid - laatst bijgewerkt 12-03-2024",
                )
                .para(
                    72.0,
                    150.0,
                    11.0,
                    &[&format!("Body paragraph number {n} with content.")],
                )
                .text(270.0, 800.0, 9.0, &format!("Pagina {n} van 3"))
        })
        .collect();
    let out = run(&Doc::new(pages), Some("nl"));
    let furn: Vec<&DocUnit> = out
        .units
        .iter()
        .filter(|u| u.kind == UnitKind::Furniture)
        .collect();
    let texts: Vec<&str> = furn.iter().map(|u| u.markdown.as_str()).collect();
    assert_eq!(
        texts,
        vec![
            "Verlofbeleid - laatst bijgewerkt 12-03-2024",
            "Pagina 1 van 3"
        ],
        "{texts:?}"
    );
    assert_eq!(furn[0].page, Some(1));
    assert_eq!(out.document.furniture_lines, 6);
    assert_eq!(out.document.furniture_units, 2);
    let body: Vec<&DocUnit> = out
        .units
        .iter()
        .filter(|u| u.kind == UnitKind::Paragraph)
        .collect();
    assert_eq!(body.len(), 3);
    assert!(body
        .iter()
        .all(|u| !u.markdown.contains("bijgewerkt") && !u.markdown.contains("Pagina")));
}

#[test]
fn a_different_date_is_different_evidence() {
    if !have_pdfium() {
        return;
    }
    let pages: Vec<Page> = ["12-03-2024", "14-05-2024"]
        .iter()
        .map(|d| {
            Page::a4()
                .text(72.0, 30.0, 9.0, &format!("laatst bijgewerkt {d}"))
                .para(72.0, 150.0, 11.0, &["Body."])
        })
        .collect();
    let out = run(&Doc::new(pages), Some("nl"));
    let furn: Vec<&str> = out
        .units
        .iter()
        .filter(|u| u.kind == UnitKind::Furniture)
        .map(|u| u.markdown.as_str())
        .collect();
    assert_eq!(
        furn,
        vec![
            "laatst bijgewerkt 12-03-2024",
            "laatst bijgewerkt 14-05-2024"
        ]
    );
}

// ------------------------------------------------------------- headings ----

fn tagged_hierarchy() -> Doc {
    let p1 = Page::a4()
        .tagged("H1", 72.0, 60.0, 18.0, true, "Leave Policy")
        .tagged(
            "P#a",
            72.0,
            100.0,
            11.0,
            false,
            "This policy explains how leave",
        )
        .tagged("P#a", 72.0, 114.0, 11.0, false, "works for every employee.")
        .tagged("H2", 72.0, 150.0, 14.0, true, "Scope")
        .tagged("P#b", 72.0, 180.0, 11.0, false, "It applies to all staff.");
    let p2 = Page::a4()
        .tagged("H2", 72.0, 60.0, 14.0, true, "Sick Leave")
        .tagged("H3", 72.0, 95.0, 12.0, true, "Reporting")
        .tagged(
            "P#c",
            72.0,
            125.0,
            11.0,
            false,
            "Report sickness before nine.",
        );
    Doc::new(vec![p1, p2])
}

#[test]
fn tagged_heading_hierarchy_from_the_struct_tree() {
    if !have_pdfium() {
        return;
    }
    let out = run(&tagged_hierarchy(), Some("en"));
    let heads: Vec<(u32, &str, Option<HeadingSource>)> = out
        .units
        .iter()
        .filter(|u| u.kind == UnitKind::Heading)
        .map(|u| {
            (
                u.level.unwrap(),
                u.markdown.as_str(),
                u.provenance.heading_source,
            )
        })
        .collect();
    let s = Some(HeadingSource::StructTree);
    assert_eq!(
        heads,
        vec![
            (1, "# Leave Policy", s),
            (2, "## Scope", s),
            (2, "## Sick Leave", s),
            (3, "### Reporting", s)
        ]
    );
    let d = &out.document;
    assert!(d.tagged && d.struct_headings);
    assert_eq!(d.heading_source, "struct_tree");
    let a = d.heading_agreement.as_ref().unwrap();
    assert!(a.struct_tree_trusted);
    assert_eq!((a.compared_pages, a.agreeing_pages, a.rate), (2, 2, 1.0));
    assert!(out
        .units
        .iter()
        .any(|u| u.markdown == "This policy explains how leave works for every employee."));
    assert_eq!(out.pages[0].signals.reading_order, "struct_tree");
}

#[test]
fn tags_that_disagree_with_the_print_keep_only_agreeing_headings() {
    if !have_pdfium() {
        return;
    }
    // Page 1 agrees. Page 2's tags call a body sentence H1 and the big bold
    // heading a P. Default policy (per heading): the contradicted tag is
    // dropped, and print alone never adds a heading to a tagged document.
    let p1 = Page::a4()
        .tagged("H1", 72.0, 60.0, 18.0, true, "Leave Policy")
        .tagged("P", 72.0, 100.0, 11.0, false, "Plain body sentence here.");
    let p2 = Page::a4()
        .tagged(
            "H1",
            72.0,
            60.0,
            11.0,
            false,
            "A body sentence tagged as heading.",
        )
        .tagged("P", 72.0, 100.0, 16.0, true, "Holidays")
        .tagged("P", 72.0, 130.0, 11.0, false, "More body text.");
    let out = run(&Doc::new(vec![p1, p2]), Some("en"));
    let d = &out.document;
    let a = d.heading_agreement.as_ref().unwrap();
    assert!(!a.struct_tree_trusted, "{a:?}");
    assert_eq!((a.compared_pages, a.agreeing_pages), (2, 1));
    assert_eq!(d.heading_source, "struct_tree");
    let heads: Vec<(&str, Option<HeadingSource>)> = out
        .units
        .iter()
        .filter(|u| u.kind == UnitKind::Heading)
        .map(|u| (u.markdown.as_str(), u.provenance.heading_source))
        .collect();
    assert_eq!(
        heads,
        vec![("# Leave Policy", Some(HeadingSource::StructTree))]
    );
    for body in ["A body sentence tagged as heading.", "Holidays"] {
        assert!(out
            .units
            .iter()
            .any(|u| u.kind == UnitKind::Paragraph && u.markdown == body));
    }
}

#[test]
fn outline_sets_levels_on_an_untagged_document() {
    if !have_pdfium() {
        return;
    }
    let page = Page::a4().bold(72.0, 60.0, 16.0, "Working Hours").para(
        72.0,
        100.0,
        11.0,
        &["Office hours are nine to five."],
    );
    let mut doc = Doc::new(vec![page]);
    doc.outline.push(("Working Hours".into(), 0));
    let out = run(&doc, Some("en"));
    let h = out
        .units
        .iter()
        .find(|u| u.kind == UnitKind::Heading)
        .unwrap();
    assert_eq!(h.markdown, "# Working Hours");
    assert_eq!(h.provenance.heading_source, Some(HeadingSource::Outline));
    assert!(out.document.heading_agreement.is_none());
}

// ------------------------------------------------------ lists and routes ----

#[test]
fn bullets_become_one_list_unit() {
    if !have_pdfium() {
        return;
    }
    let page = Page::a4()
        .para(72.0, 60.0, 11.0, &["You are entitled to:"])
        .para(
            72.0,
            80.0,
            11.0,
            &[
                "\u{2022} annual leave;",
                "\u{2022} sick leave with pay",
                "  for two years;",
                "\u{2022} parental leave.",
            ],
        );
    let out = run(&Doc::new(vec![page]), Some("en"));
    let list = out
        .units
        .iter()
        .find(|u| u.kind == UnitKind::List)
        .expect("no list unit");
    assert_eq!(
        list.markdown,
        "- annual leave;\n- sick leave with pay for two years;\n- parental leave."
    );
}

#[test]
fn scan_page_without_text_layer_routes_scan() {
    if !have_pdfium() {
        return;
    }
    let scan = Page::a4().image(0.0, 0.0, 595.0, 842.0);
    let text = Page::a4().para(72.0, 72.0, 11.0, &["A normal text page."]);
    let out = run(&Doc::new(vec![text, scan]), None);
    assert_eq!(out.pages[0].route, Route::Plain);
    let p = &out.pages[1];
    assert_eq!(p.route, Route::Scan);
    assert_eq!(p.signals.chars, 0);
    assert!(p.signals.image_coverage >= 0.99, "{:?}", p.signals);
    let img: Vec<&DocUnit> = out.units.iter().filter(|u| u.page == Some(2)).collect();
    assert_eq!(img.len(), 1);
    assert_eq!(img[0].kind, UnitKind::Image);
    assert_eq!(img[0].provenance.route, Route::Scan);
}

#[test]
fn ruled_grid_routes_table() {
    if !have_pdfium() {
        return;
    }
    let mut page = Page::a4();
    for k in 0..4 {
        let y = 100.0 + k as f64 * 20.0;
        page = page.line(72.0, y, 372.0, y);
    }
    for x in [72.0, 222.0, 372.0] {
        page = page.line(x, 100.0, x, 160.0);
    }
    page = page
        .text(76.0, 104.0, 10.0, "Item")
        .text(226.0, 104.0, 10.0, "Amount")
        .text(76.0, 124.0, 10.0, "Travel")
        .text(226.0, 124.0, 10.0, "1.250,00");
    let out = run(&Doc::new(vec![page]), None);
    let s = &out.pages[0].signals;
    assert!(s.ruling_lines_h >= 4 && s.ruling_lines_v >= 3, "{s:?}");
    assert_eq!(out.pages[0].route, Route::Table);
}

// ----------------------------------------------------------- determinism ----

#[test]
fn same_bytes_twice_give_identical_json() {
    if !have_pdfium() {
        return;
    }
    let mut doc = tagged_hierarchy();
    doc.pages.push(hyphen_page(false).pages.remove(0));
    doc.pages.push(Page::a4().image(0.0, 0.0, 595.0, 842.0));
    let bytes = doc.build();
    let opts = PdfOptions {
        language: Some("nl".into()),
        layout_text: true,
        ..Default::default()
    };
    let a = serde_json::to_string(&pdf_units(&bytes, &opts).unwrap()).unwrap();
    let b = serde_json::to_string(&pdf_units(&bytes, &opts).unwrap()).unwrap();
    assert_eq!(a, b);
    assert!(!a.contains("\\u0002"));
}

#[test]
fn garbage_bytes_are_an_error_not_a_crash() {
    if !have_pdfium() {
        return;
    }
    assert!(pdf_units(b"not a pdf", &PdfOptions::default()).is_err());
}

// ------------------------------------------ heading rules (diagnosis A) ----

fn headings_of(out: &PdfUnitsOutput) -> Vec<String> {
    out.units
        .iter()
        .filter(|u| u.kind == UnitKind::Heading)
        .map(|u| u.markdown.clone())
        .collect()
}

#[test]
fn bold_alone_never_makes_a_font_heading() {
    if !have_pdfium() {
        return;
    }
    // Untagged: a bold body-size label ending in ":" and a bold lead-in
    // followed by same-size text stay paragraphs; a bold numbered section and
    // a larger title are headings.
    let page = Page::a4()
        .bold(72.0, 50.0, 16.0, "Verlofregeling")
        .bold(72.0, 90.0, 11.0, "Voorwaarden:")
        .para(
            72.0,
            106.0,
            11.0,
            &["Verlof wordt vooraf aangevraagd bij de leidinggevende."],
        )
        .bold(72.0, 140.0, 11.0, "Let op")
        .para(
            72.0,
            156.0,
            11.0,
            &["Niet opgenomen dagen vervallen na vijf jaar."],
        )
        .bold(72.0, 190.0, 11.0, "3.2 Bijzonder verlof")
        .para(
            72.0,
            206.0,
            11.0,
            &["Bij verhuizing heeft de werknemer recht op een dag."],
        );
    let out = run(&Doc::new(vec![page]), Some("nl"));
    assert_eq!(
        headings_of(&out),
        vec!["# Verlofregeling", "## 3.2 Bijzonder verlof"]
    );
    assert!(out
        .units
        .iter()
        .any(|u| u.kind == UnitKind::Paragraph && u.markdown == "Voorwaarden:"));
    assert!(out
        .units
        .iter()
        .any(|u| u.kind == UnitKind::Paragraph && u.markdown == "Let op"));
}

#[test]
fn article_label_and_title_merge_into_one_heading() {
    if !have_pdfium() {
        return;
    }
    // Word writes "Artikel 5." and its title as two paragraphs in one heading
    // style; the tree tags both H1. One heading, not a label with no body.
    let page = Page::a4()
        .tagged("H1", 72.0, 60.0, 11.0, true, "Artikel 5.")
        .tagged("H1", 72.0, 76.0, 11.0, true, "Vakantiedagen")
        .tagged(
            "P#a",
            72.0,
            100.0,
            11.0,
            false,
            "De werknemer heeft recht op vakantie.",
        )
        .tagged("H1", 72.0, 130.0, 11.0, true, "Artikel 6.")
        .tagged("H1", 72.0, 146.0, 11.0, true, "Ziekte")
        .tagged(
            "P#b",
            72.0,
            170.0,
            11.0,
            false,
            "Ziekte wordt direct gemeld.",
        );
    let out = run(&Doc::new(vec![page]), Some("nl"));
    assert_eq!(
        headings_of(&out),
        vec!["# Artikel 5. Vakantiedagen", "# Artikel 6. Ziekte"]
    );
    let h = out
        .units
        .iter()
        .find(|u| u.kind == UnitKind::Heading)
        .unwrap();
    let bb = h.bbox.unwrap();
    assert!(bb[3] > 76.0, "merged bbox spans both lines: {bb:?}");
}

#[test]
fn a_larger_bold_cell_in_a_ruled_table_is_not_a_heading() {
    if !have_pdfium() {
        return;
    }
    let mut page = Page::a4().para(72.0, 60.0, 11.0, &["Tarieven gelden per jaar."]);
    for k in 0..3 {
        let y = 100.0 + k as f64 * 24.0;
        page = page.line(72.0, y, 372.0, y);
    }
    for x in [72.0, 222.0, 372.0] {
        page = page.line(x, 100.0, x, 148.0);
    }
    page = page
        .bold(76.0, 104.0, 14.0, "Categorie")
        .bold(226.0, 104.0, 14.0, "Bedrag")
        .text(76.0, 128.0, 11.0, "Reiskosten")
        .text(226.0, 128.0, 11.0, "1.250,00");
    let out = run(&Doc::new(vec![page]), Some("nl"));
    assert!(headings_of(&out).is_empty(), "{:?}", headings_of(&out));
}

// ----------------------------------------- peer findings (standard-14) ----

#[test]
fn standard14_helvetica_without_widths_has_real_increasing_positions() {
    if !have_pdfium() {
        return;
    }
    // The generator's fonts are exactly `<< /Type /Font /Subtype /Type1
    // /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>`: no /Widths, no
    // /FontDescriptor. pdfium must supply the AFM metrics. Assert POSITIONS:
    // text comes out in order even on a broken geometry layer.
    let page =
        Page::a4()
            .text(72.0, 100.0, 12.0, "Platform effort")
            .bold(72.0, 130.0, 12.0, "Migration");
    let r = raw::read(&Doc::new(vec![page]).build()).unwrap();
    let chars: Vec<_> = r.pages[0]
        .chars
        .iter()
        .filter(|c| !c.generated && !c.ch.is_whitespace())
        .collect();
    assert_eq!(
        chars.iter().map(|c| c.ch).collect::<String>(),
        "PlatformeffortMigration"
    );
    for word in [&chars[0..8], &chars[8..14], &chars[14..]] {
        for c in word.iter() {
            assert!(c.x1 - c.x0 > 0.5, "zero-width glyph {:?}", c.ch);
        }
        for pair in word.windows(2) {
            assert!(
                pair[1].x0 > pair[0].x0,
                "x not strictly increasing at {:?}->{:?}",
                pair[0].ch,
                pair[1].ch
            );
        }
    }
    // "Platform" in Helvetica 12 pt is ~46 pt wide (AFM), not a collapsed box
    let w = chars[7].x1 - chars[0].x0;
    assert!(w > 40.0 && w < 52.0, "{w}");
}

// ------------------------------------- peer findings (furniture trap) ----

#[test]
fn a_repeated_body_sentence_with_a_page_number_stays_body_on_every_page() {
    if !have_pdfium() {
        return;
    }
    // Digit masking makes "zie pagina 3 van 5" and "zie pagina 4 van 5"
    // equal. Keeping furniture ONCE must never delete body text:
    // (1) mid-page; (2) at the top, inside the 12 % band, directly under the
    // running header and glued to the body below it.
    let pages: Vec<Page> = (1..=4)
        .map(|n| {
            Page::a4()
                .text(72.0, 30.0, 9.0, "Personeelshandboek")
                .para(
                    72.0,
                    60.0,
                    10.0,
                    &[
                        &format!("Zie pagina {n} van 4 voor de regeling."),
                        "De regeling geldt voor iedereen.",
                    ],
                )
                .para(
                    72.0,
                    400.0,
                    10.0,
                    &[
                        &format!("Deze tekst staat op pagina {n} van 4."),
                        "Einde van de tekst.",
                    ],
                )
        })
        .collect();
    let out = run(&Doc::new(pages), Some("nl"));
    for n in 1..=4u32 {
        let body: Vec<&str> = out
            .units
            .iter()
            .filter(|u| u.page == Some(n) && u.kind != UnitKind::Furniture)
            .map(|u| u.markdown.as_str())
            .collect();
        let all = body.join(" ");
        assert!(
            all.contains(&format!("Zie pagina {n} van 4")),
            "page {n}: {body:?}"
        );
        assert!(
            all.contains(&format!("op pagina {n} van 4")),
            "page {n}: {body:?}"
        );
    }
    let furn: Vec<&str> = out
        .units
        .iter()
        .filter(|u| u.kind == UnitKind::Furniture)
        .map(|u| u.markdown.as_str())
        .collect();
    assert_eq!(furn, vec!["Personeelshandboek"]);
}

// ----------------------------------------- peer findings (ligatures) ----

#[test]
fn ligature_glyphs_mapping_one_code_to_several_characters_round_trip() {
    if !have_pdfium() {
        return;
    }
    // tests/data/pdf/ligatures.pdf: generated once by LibreOffice from
    // ligatures.gen.py (Carlito). Its ToUnicode CMap maps ONE code to TWO
    // characters for "tf", "ti" and "ff". Assert the TEXT round-trips exactly
    // (a count can be right while the order is wrong) and boxes advance.
    let bytes = std::fs::read(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/tests/data/pdf/ligatures.pdf"
    ))
    .unwrap();
    let out = pdf_units(
        &bytes,
        &PdfOptions {
            language: Some("en".into()),
            ..Default::default()
        },
    )
    .unwrap();
    let text: Vec<&str> = out.units.iter().map(|u| u.markdown.as_str()).collect();
    assert_eq!(
        text,
        vec!["Platform", "Option", "Migration effort", "Trade-offs"],
        "{text:?}"
    );
    let r = raw::read(&bytes).unwrap();
    let chars: Vec<_> = r.pages[0]
        .chars
        .iter()
        .filter(|c| !c.generated && !c.ch.is_whitespace())
        .collect();
    for pair in chars.windows(2) {
        if (pair[1].baseline - pair[0].baseline).abs() < 1.0 {
            assert!(
                pair[1].x0 >= pair[0].x0,
                "x went backwards at {:?}->{:?}",
                pair[0].ch,
                pair[1].ch
            );
        }
    }
}

#[test]
fn fake_bold_drawn_twice_still_counts_once() {
    if !have_pdfium() {
        return;
    }
    let page = Page::a4().text(72.0, 100.0, 11.0, "Offerte effect").text(
        72.0,
        100.0,
        11.0,
        "Offerte effect",
    );
    let out = run(&Doc::new(vec![page]), Some("nl"));
    assert_eq!(
        out.units
            .iter()
            .map(|u| u.markdown.as_str())
            .collect::<Vec<_>>(),
        vec!["Offerte effect"]
    );
}
