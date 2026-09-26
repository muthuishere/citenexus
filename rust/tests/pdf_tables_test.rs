//! Deterministic tables (ADR-0017 step 4) over SYNTHETIC PDFs: struct tree,
//! ruled grid, column tracks, and the must-not-be-a-table validators.
#![cfg(feature = "pdf")]

mod common;

use citenexus_core::extract::pdf::{pdf_units, raw};
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

fn run(page: Page) -> PdfUnitsOutput {
    let opts = PdfOptions {
        language: Some("nl".into()),
        ..Default::default()
    };
    pdf_units(&Doc::new(vec![page]).build(), &opts).expect("pdf_units")
}

fn tables(out: &PdfUnitsOutput) -> Vec<&DocUnit> {
    out.units
        .iter()
        .filter(|u| u.kind == UnitKind::Table)
        .collect()
}

fn all_text(out: &PdfUnitsOutput) -> String {
    out.units
        .iter()
        .map(|u| u.markdown.as_str())
        .collect::<Vec<_>>()
        .join("\n")
}

/// A ruled grid; `split_amounts` adds a vertical rule inside the amount column
/// in ONE row only (a currency sign in its own sub-cell, as Word draws it).
fn ruled_page(split_amounts: bool) -> Page {
    let mut p = Page::a4().para(
        72.0,
        60.0,
        11.0,
        &["Vergoedingen per jaar staan hieronder."],
    );
    for y in [100.0, 120.0, 140.0, 160.0] {
        p = p.line(72.0, y, 472.0, y);
    }
    for x in [72.0, 222.0, 472.0] {
        p = p.line(x, 100.0, x, 160.0);
    }
    if split_amounts {
        p = p.line(240.0, 120.0, 240.0, 140.0);
    }
    p.bold(76.0, 104.0, 10.0, "Soort")
        .bold(226.0, 104.0, 10.0, "Bedrag")
        .text(76.0, 124.0, 10.0, "Reiskosten")
        .text(226.0, 124.0, 10.0, "€")
        .text(246.0, 124.0, 10.0, "7.000,00")
        .text(76.0, 144.0, 10.0, "Hotel")
        .text(246.0, 144.0, 10.0, "5.100,00")
}

#[test]
fn ruled_grid_becomes_a_pipe_table_filled_from_the_text_layer() {
    if !have_pdfium() {
        return;
    }
    let out = run(ruled_page(false));
    let t = tables(&out);
    assert_eq!(t.len(), 1);
    assert_eq!(t[0].provenance.table_source, Some(TableSource::Ruled));
    assert_eq!(
        t[0].markdown,
        "| Soort | Bedrag |\n| --- | --- |\n| Reiskosten | € 7.000,00 |\n| Hotel | 5.100,00 |"
    );
    assert_eq!(
        out.units[0].markdown,
        "Vergoedingen per jaar staan hieronder."
    );
    assert!(
        !all_text(&out).contains("Reiskosten\n"),
        "table words must not also be paragraphs"
    );
}

#[test]
fn a_rule_drawn_in_a_minority_of_rows_does_not_split_a_column() {
    if !have_pdfium() {
        return;
    }
    let out = run(ruled_page(true));
    let t = tables(&out);
    assert_eq!(t.len(), 1);
    assert!(
        t[0].markdown.contains("| Reiskosten | € 7.000,00 |"),
        "{}",
        t[0].markdown
    );
}

#[test]
fn borderless_table_from_column_tracks() {
    if !have_pdfium() {
        return;
    }
    let mut p = Page::a4().para(72.0, 60.0, 11.0, &["Salarisschalen voor het jaar."]);
    let rows = [
        ("Schaal", "Minimum", "Maximum"),
        ("A", "2.500,00", "3.100,00"),
        ("B", "3.100,00", "3.900,00"),
        ("C", "3.900,00", "4.800,00"),
    ];
    for (k, (a, b, c)) in rows.iter().enumerate() {
        let y = 100.0 + k as f64 * 16.0;
        p = p
            .text(72.0, y, 10.0, a)
            .text(200.0, y, 10.0, b)
            .text(330.0, y, 10.0, c);
    }
    let out = run(p);
    let t = tables(&out);
    assert_eq!(t.len(), 1, "{:?}", out.units);
    assert_eq!(t[0].provenance.table_source, Some(TableSource::Tracks));
    assert_eq!(
        t[0].markdown,
        "| Schaal | Minimum | Maximum |\n| --- | --- | --- |\n| A | 2.500,00 | 3.100,00 |\n| B | 3.100,00 | 3.900,00 |\n| C | 3.900,00 | 4.800,00 |"
    );
}

#[test]
fn struct_tree_table_with_row_and_col_spans_wins_outright() {
    if !have_pdfium() {
        return;
    }
    // Header: "Regeling" spans two columns. Body: "Verlof" spans two rows.
    let p = Page::a4()
        .tagged("Table:t/TR:h/TH:a", 72.0, 100.0, 10.0, true, "Onderwerp")
        .tagged(
            "Table:t/TR:h/TH:b{cs=2}",
            200.0,
            100.0,
            10.0,
            true,
            "Regeling",
        )
        .tagged(
            "Table:t/TR:1/TD:a{rs=2}",
            72.0,
            120.0,
            10.0,
            false,
            "Verlof",
        )
        .tagged("Table:t/TR:1/TD:b", 200.0, 120.0, 10.0, false, "Vakantie")
        .tagged("Table:t/TR:1/TD:c", 330.0, 120.0, 10.0, false, "25 dagen")
        .tagged("Table:t/TR:2/TD:b", 200.0, 140.0, 10.0, false, "Bijzonder")
        .tagged("Table:t/TR:2/TD:c", 330.0, 140.0, 10.0, false, "3 dagen");
    let out = run(p);
    let t = tables(&out);
    assert_eq!(t.len(), 1, "{:?}", out.units);
    assert_eq!(t[0].provenance.table_source, Some(TableSource::StructTree));
    assert_eq!(
        t[0].markdown,
        "| Onderwerp | Regeling |  |\n| --- | --- | --- |\n| Verlof | Vakantie | 25 dagen |\n|  | Bijzonder | 3 dagen |"
    );
}

#[test]
fn two_column_prose_is_not_a_table() {
    if !have_pdfium() {
        return;
    }
    let p = Page::a4()
        .para(
            72.0,
            110.0,
            10.0,
            &[
                "De werknemer heeft recht op",
                "vakantie volgens de regeling",
                "die hieronder staat beschreven.",
            ],
        )
        .para(
            320.0,
            110.0,
            10.0,
            &[
                "Verlof wordt vooraf aangevraagd",
                "bij de leidinggevende van de",
                "afdeling waar men werkt.",
            ],
        );
    assert!(tables(&run(p)).is_empty());
}

#[test]
fn a_table_of_contents_is_not_a_table() {
    if !have_pdfium() {
        return;
    }
    let mut p = Page::a4();
    for (k, (t, n)) in [
        ("Inleiding en doel", "3"),
        ("Werktijden en rooster", "5"),
        ("Verlof en vakantie", "8"),
        ("Ziekte en verzuim", "12"),
    ]
    .iter()
    .enumerate()
    {
        let y = 100.0 + k as f64 * 16.0;
        p = p.text(72.0, y, 10.0, t).text(480.0, y, 10.0, n);
    }
    assert!(tables(&run(p)).is_empty());
}

#[test]
fn a_key_value_list_is_not_a_table() {
    if !have_pdfium() {
        return;
    }
    let mut p = Page::a4();
    for (k, (a, b)) in [
        ("Naam:", "Jan Jansen"),
        ("Functie:", "Adviseur"),
        ("Afdeling:", "Personeelszaken"),
        ("Datum:", "1 maart"),
    ]
    .iter()
    .enumerate()
    {
        let y = 100.0 + k as f64 * 16.0;
        p = p.text(72.0, y, 10.0, a).text(200.0, y, 10.0, b);
    }
    assert!(tables(&run(p)).is_empty());
}

#[test]
fn a_one_column_box_is_not_a_table() {
    if !have_pdfium() {
        return;
    }
    let p = Page::a4()
        .rect(60.0, 90.0, 400.0, 1.0)
        .rect(60.0, 180.0, 400.0, 1.0)
        .rect(60.0, 90.0, 1.0, 91.0)
        .rect(459.0, 90.0, 1.0, 91.0)
        .para(
            72.0,
            100.0,
            10.0,
            &["Let op: verlof moet vooraf", "worden aangevraagd."],
        );
    assert!(tables(&run(p)).is_empty());
}

#[test]
fn an_incomplete_struct_table_loses_to_the_drawn_grid() {
    if !have_pdfium() {
        return;
    }
    // The header row is drawn but untagged (as Word writes some exports):
    // the tree misses words inside its own box, the rules account for them.
    let mut p = ruled_page(false);
    p.items
        .retain(|i| !matches!(i, common::pdfgen::Item::Text { .. }));
    p = p
        .para(
            72.0,
            60.0,
            11.0,
            &["Vergoedingen per jaar staan hieronder."],
        )
        .bold(76.0, 104.0, 10.0, "Soort")
        .bold(226.0, 104.0, 10.0, "Bedrag")
        .tagged("Table:t/TR:h/TH:a", 76.0, 94.0, 1.0, false, "")
        .tagged("Table:t/TR:1/TD:a", 76.0, 124.0, 10.0, false, "Reiskosten")
        .tagged("Table:t/TR:1/TD:b", 246.0, 124.0, 10.0, false, "7.000,00")
        .tagged("Table:t/TR:2/TD:a", 76.0, 144.0, 10.0, false, "Hotel")
        .tagged("Table:t/TR:2/TD:b", 246.0, 144.0, 10.0, false, "5.100,00");
    let out = run(p);
    let t = tables(&out);
    assert_eq!(t.len(), 1, "{:?}", out.units);
    assert_eq!(t[0].provenance.table_source, Some(TableSource::Ruled));
    assert!(
        t[0].markdown.starts_with("| Soort | Bedrag |"),
        "{}",
        t[0].markdown
    );
}

#[test]
fn tables_are_deterministic() {
    if !have_pdfium() {
        return;
    }
    let a = serde_json::to_string(&run(ruled_page(true))).unwrap();
    let b = serde_json::to_string(&run(ruled_page(true))).unwrap();
    assert_eq!(a, b);
}

// ------------------------------------------- spanning headers, flattened ----

fn salary_rows(mut p: Page, y0: f64) -> Page {
    for (k, (a, b, c, d)) in [
        ("Junior", "2.500", "2.700", "2.900"),
        ("Medior", "3.100", "3.300", "3.500"),
        ("Senior", "3.900", "4.100", "4.300"),
    ]
    .iter()
    .enumerate()
    {
        let y = y0 + k as f64 * 14.0;
        p = p
            .text(72.0, y, 10.0, a)
            .text(200.0, y, 10.0, b)
            .text(300.0, y, 10.0, c)
            .text(400.0, y, 10.0, d);
    }
    p
}

#[test]
fn an_axis_label_over_sub_headers_is_prefixed_to_each_of_them() {
    if !have_pdfium() {
        return;
    }
    // "Ervaringsjaren" is one label over three range sub-headers; the stub
    // column of the sub-header row is empty. Markdown cannot span, so each
    // sub-header becomes "<label> <range>", built from the PDF's own words.
    let p = Page::a4()
        .bold(290.0, 100.0, 10.0, "Ervaringsjaren")
        .bold(200.0, 114.0, 10.0, "0-2")
        .bold(300.0, 114.0, 10.0, "3-5")
        .bold(400.0, 114.0, 10.0, "6+");
    let out = run(salary_rows(p, 128.0));
    let t = tables(&out);
    assert_eq!(t.len(), 1, "{:?}", out.units);
    assert!(t[0].provenance.header_flattened);
    assert_eq!(
        t[0].markdown,
        "|  | Ervaringsjaren 0-2 | Ervaringsjaren 3-5 | Ervaringsjaren 6+ |\n| --- | --- | --- | --- |\n| Junior | 2.500 | 2.700 | 2.900 |\n| Medior | 3.100 | 3.300 | 3.500 |\n| Senior | 3.900 | 4.100 | 4.300 |"
    );
    assert!(!out
        .units
        .iter()
        .any(|u| u.kind == UnitKind::Paragraph && u.markdown.contains("Ervaringsjaren")));
}

#[test]
fn a_struct_colspan_header_is_flattened_and_the_rowspan_stub_moves_down() {
    if !have_pdfium() {
        return;
    }
    let p = Page::a4()
        .tagged(
            "Table:t/TR:0/TH:a{rs=2}",
            72.0,
            100.0,
            10.0,
            true,
            "Functie",
        )
        .tagged(
            "Table:t/TR:0/TH:b{cs=3}",
            290.0,
            100.0,
            10.0,
            true,
            "Ervaringsjaren",
        )
        .tagged("Table:t/TR:1/TH:c", 200.0, 114.0, 10.0, true, "0-2")
        .tagged("Table:t/TR:1/TH:d", 300.0, 114.0, 10.0, true, "3-5")
        .tagged("Table:t/TR:1/TH:e", 400.0, 114.0, 10.0, true, "6+")
        .tagged("Table:t/TR:2/TD:a", 72.0, 128.0, 10.0, false, "Junior")
        .tagged("Table:t/TR:2/TD:b", 200.0, 128.0, 10.0, false, "2.500")
        .tagged("Table:t/TR:2/TD:c", 300.0, 128.0, 10.0, false, "2.700")
        .tagged("Table:t/TR:2/TD:d", 400.0, 128.0, 10.0, false, "2.900");
    let out = run(p);
    let t = tables(&out);
    assert_eq!(t.len(), 1, "{:?}", out.units);
    assert_eq!(t[0].provenance.table_source, Some(TableSource::StructTree));
    assert!(t[0].provenance.header_flattened);
    assert_eq!(
        t[0].markdown,
        "| Functie | Ervaringsjaren 0-2 | Ervaringsjaren 3-5 | Ervaringsjaren 6+ |\n| --- | --- | --- | --- |\n| Junior | 2.500 | 2.700 | 2.900 |"
    );
}

#[test]
fn a_caption_over_a_full_header_row_is_not_a_spanning_header() {
    if !have_pdfium() {
        return;
    }
    let p = Page::a4()
        .text(72.0, 100.0, 10.0, "Tabel 1 Salarisschalen per functie")
        .bold(72.0, 114.0, 10.0, "Functie")
        .bold(200.0, 114.0, 10.0, "Laag")
        .bold(300.0, 114.0, 10.0, "Midden")
        .bold(400.0, 114.0, 10.0, "Hoog");
    let out = run(salary_rows(p, 128.0));
    let t = tables(&out);
    assert_eq!(t.len(), 1);
    assert!(!t[0].provenance.header_flattened);
    assert!(
        t[0].markdown
            .starts_with("| Functie | Laag | Midden | Hoog |"),
        "{}",
        t[0].markdown
    );
    assert!(out.units.iter().any(
        |u| u.kind == UnitKind::Paragraph && u.markdown == "Tabel 1 Salarisschalen per functie"
    ));
}

// ------------------------------------------------- leaders and TOCs (A) ----

#[test]
fn a_toc_with_dot_leaders_is_neither_a_table_nor_a_model_request() {
    if !have_pdfium() {
        return;
    }
    // leaders are separate words that run into the page-number column: any
    // grid fails geometry, so the region must not cost a model call.
    let mut p = Page::a4();
    for (k, (t, n)) in [
        ("Inleiding", "3"),
        ("Werktijden", "5"),
        ("Verlof", "8"),
        ("Ziekte", "12"),
    ]
    .iter()
    .enumerate()
    {
        let y = 100.0 + k as f64 * 16.0;
        p = p
            .text(72.0, y, 10.0, t)
            .text(
                200.0,
                y,
                10.0,
                "..........................................................................",
            )
            .text(480.0, y, 10.0, n);
    }
    let opts = PdfOptions {
        language: Some("nl".into()),
        ..Default::default()
    };
    let bytes = Doc::new(vec![p]).build();
    let out = pdf_units(&bytes, &opts).unwrap();
    assert!(tables(&out).is_empty());
    let prep = citenexus_core::extract::pdf::pdf_prepare(&bytes, &opts).unwrap();
    assert!(
        prep.requests
            .iter()
            .all(|r| r.kind != PdfRequestKind::TableStructure),
        "{:?}",
        prep.requests
    );
}

#[test]
fn a_real_table_with_leaders_still_passes_and_drops_the_filler() {
    if !have_pdfium() {
        return;
    }
    let mut p = Page::a4();
    for (k, (a, b)) in [
        ("Omschrijving", "Bedrag"),
        ("Reiskosten", "7.000,00"),
        ("Hotel", "5.100,00"),
        ("Diner", "1.250,00"),
    ]
    .iter()
    .enumerate()
    {
        let y = 100.0 + k as f64 * 16.0;
        p = p
            .text(72.0, y, 10.0, a)
            .text(150.0, y, 10.0, "..............................")
            .text(330.0, y, 10.0, b);
    }
    let out = run(p);
    let t = tables(&out);
    assert_eq!(t.len(), 1, "{:?}", out.units);
    assert_eq!(
        t[0].markdown,
        "| Omschrijving | Bedrag |\n| --- | --- |\n| Reiskosten | 7.000,00 |\n| Hotel | 5.100,00 |\n| Diner | 1.250,00 |"
    );
}

#[test]
fn a_toc_with_leaders_glued_to_the_titles_is_not_a_request_either() {
    if !have_pdfium() {
        return;
    }
    let mut p = Page::a4();
    for (k, (n, t, pg)) in [
        ("1", "Inleiding", "3"),
        ("2", "Werktijden", "5"),
        ("3", "Verlof", "8"),
        ("4", "Ziekte", "12"),
    ]
    .iter()
    .enumerate()
    {
        let y = 100.0 + k as f64 * 16.0;
        p = p
            .text(72.0, y, 10.0, n)
            .text(
                100.0,
                y,
                10.0,
                &format!("{t}............................................................"),
            )
            .text(480.0, y, 10.0, pg);
    }
    let opts = PdfOptions {
        language: Some("nl".into()),
        ..Default::default()
    };
    let bytes = Doc::new(vec![p]).build();
    assert!(tables(&pdf_units(&bytes, &opts).unwrap()).is_empty());
    let prep = citenexus_core::extract::pdf::pdf_prepare(&bytes, &opts).unwrap();
    assert!(
        prep.requests
            .iter()
            .all(|r| r.kind != PdfRequestKind::TableStructure),
        "{:?}",
        prep.requests.len()
    );
}

// ------------------------------- peer findings (alignment, totals rows) ----

use common::fixtures::{invoice_page, width};

#[test]
fn right_aligned_columns_and_short_totals_rows_stay_one_table() {
    if !have_pdfium() {
        return;
    }
    // Qty "84", "1", "16" share no left edge, only a right edge; the totals
    // rows have a label under Description and an amount under Amount only.
    // One table, 7 rows, every amount in the Amount column.
    let out = run(invoice_page());
    let t = tables(&out);
    assert_eq!(t.len(), 1, "{:?}", out.units);
    assert_eq!(
        t[0].markdown,
        "| # | Description | Qty | Unit price | Amount |\n| --- | --- | --- | --- | --- |\n\
         | 1 | Consultancy | 84 | 125,00 | 10.500,00 |\n| 2 | Licentie | 1 | 3.000,00 | 3.000,00 |\n\
         | 3 | Training | 16 | 112,50 | 1.800,00 |\n|  | Subtotal |  |  | 15.300,00 |\n\
         |  | VAT 21% |  |  | 3.213,00 |\n|  | Total due |  |  | 18.513,00 |"
    );
}

#[test]
fn decimal_aligned_and_centred_columns_are_one_track_each() {
    if !have_pdfium() {
        return;
    }
    let mut p = Page::a4()
        .bold(72.0, 100.0, 10.0, "Code")
        .bold(200.0, 100.0, 10.0, "Bedrag")
        .bold(340.0, 100.0, 10.0, "Status");
    for (k, (c, int, dec, st)) in [
        ("A1", "7", ",50", "ok"),
        ("B22", "1.250", ",00", "open"),
        ("C3", "12", ",75", "betaald"),
    ]
    .iter()
    .enumerate()
    {
        let y = 116.0 + k as f64 * 16.0;
        // decimal-aligned at x = 260 (the comma), centred status at x = 360
        let amount = format!("{int}{dec}");
        let x_amount = 260.0 - width(int, 10.0);
        let status_w = st.len() as f64 * 5.3;
        p = p
            .text(72.0, y, 10.0, c)
            .text(x_amount, y, 10.0, &amount)
            .text(360.0 - status_w / 2.0, y, 10.0, st);
    }
    let out = run(p);
    let t = tables(&out);
    assert_eq!(t.len(), 1, "{:?}", out.units);
    assert_eq!(
        t[0].markdown,
        "| Code | Bedrag | Status |\n| --- | --- | --- |\n| A1 | 7,50 | ok |\n| B22 | 1.250,00 | open |\n| C3 | 12,75 | betaald |"
    );
}

#[test]
fn a_long_small_type_table_does_not_become_the_body_size() {
    if !have_pdfium() {
        return;
    }
    // Three pages of an 8 pt table (far more characters than the prose) and
    // short, distinct 10 pt prose lines mid-page. If table rows counted
    // toward the body size, the body would be 8 pt and every short prose
    // line (1.25 x) would turn into a heading.
    let prose = [
        (
            "Deze regeling beschrijft de vergoedingen",
            "voor reiskosten en verblijf",
        ),
        (
            "Bedragen worden maandelijks uitbetaald",
            "na goedkeuring door de manager",
        ),
        (
            "Vragen gaan naar de afdeling personeelszaken",
            "die binnen een week antwoordt",
        ),
    ];
    let pages: Vec<Page> = (0..3)
        .map(|pg| {
            let mut p = Page::a4();
            for r in 0..25 {
                let y = 100.0 + r as f64 * 16.0;
                let n = pg * 25 + r;
                p = p
                    .text(72.0, y, 8.0, &format!("Medewerker nummer {n}"))
                    .text(250.0, y, 8.0, &format!("{},{:02}", 1000 + n * 7, n % 100))
                    .text(380.0, y, 8.0, &format!("{},{:02}", 200 + n * 3, n % 97));
            }
            let (a, b) = prose[pg];
            p.para(72.0, 560.0, 10.0, &[a, b])
        })
        .collect();
    let out = pdf_units(
        &Doc::new(pages).build(),
        &PdfOptions {
            language: Some("nl".into()),
            ..Default::default()
        },
    )
    .unwrap();
    assert_eq!(
        tables(&out).len(),
        3,
        "the table must still be found on each page"
    );
    let heads: Vec<&str> = out
        .units
        .iter()
        .filter(|u| u.kind == UnitKind::Heading)
        .map(|u| u.markdown.as_str())
        .collect();
    assert!(heads.is_empty(), "prose promoted to headings: {heads:?}");
    assert_eq!(
        out.units
            .iter()
            .filter(|u| u.kind == UnitKind::Paragraph)
            .count(),
        3
    );
}

/// A ruled grid whose top-left corner holds only a VERTICAL label (T5): the
/// header row is tall, the label reads bottom to top.
fn rotated_corner_page(label: bool) -> Page {
    let mut p = Page::a4().para(72.0, 60.0, 11.0, &["Salarisschalen per niveau."]);
    for y in [100.0, 140.0, 160.0, 180.0] {
        p = p.line(72.0, y, 452.0, y);
    }
    for x in [72.0, 150.0, 300.0, 452.0] {
        p = p.line(x, 100.0, x, 180.0);
    }
    if label {
        p = p.vertical(100.0, 136.0, 8.0, "Schaal");
    }
    p.text(160.0, 115.0, 10.0, "Minimum")
        .text(310.0, 115.0, 10.0, "Maximum")
        .text(80.0, 145.0, 10.0, "A")
        .text(160.0, 145.0, 10.0, "2.500,00")
        .text(310.0, 145.0, 10.0, "3.100,00")
        .text(80.0, 165.0, 10.0, "B")
        .text(160.0, 165.0, 10.0, "3.100,00")
        .text(310.0, 165.0, 10.0, "3.900,00")
}

#[test]
fn a_rotated_corner_label_fills_its_own_empty_cell() {
    if !have_pdfium() {
        return;
    }
    let out = run(rotated_corner_page(true));
    let t = tables(&out);
    assert_eq!(t.len(), 1, "{:?}", out.units);
    assert_eq!(t[0].provenance.table_source, Some(TableSource::Ruled));
    assert_eq!(
        t[0].markdown,
        "| Schaal | Minimum | Maximum |\n| --- | --- | --- |\n| A | 2.500,00 | 3.100,00 |\n| B | 3.100,00 | 3.900,00 |"
    );
    // without the label the corner stays empty: nothing is invented
    let out = run(rotated_corner_page(false));
    assert!(
        tables(&out)[0]
            .markdown
            .starts_with("|  | Minimum | Maximum |"),
        "{}",
        tables(&out)[0].markdown
    );
}

#[test]
fn a_rotated_corner_label_fills_a_borderless_corner_too() {
    if !have_pdfium() {
        return;
    }
    let mut p = Page::a4().para(72.0, 60.0, 11.0, &["Salarisschalen voor het jaar."]);
    p = p.vertical(72.0, 110.0, 8.0, "Schaal");
    let rows = [
        ("", "Minimum", "Maximum"),
        ("A", "2.500,00", "3.100,00"),
        ("B", "3.100,00", "3.900,00"),
        ("C", "3.900,00", "4.800,00"),
    ];
    for (k, (a, b, c)) in rows.iter().enumerate() {
        let y = 100.0 + k as f64 * 16.0;
        if !a.is_empty() {
            p = p.text(72.0, y, 10.0, a);
        }
        p = p.text(200.0, y, 10.0, b).text(330.0, y, 10.0, c);
    }
    let out = run(p);
    let t = tables(&out);
    assert_eq!(t.len(), 1, "{:?}", out.units);
    assert!(
        t[0].markdown.starts_with("| Schaal | Minimum | Maximum |"),
        "{}",
        t[0].markdown
    );
}

#[test]
fn rotated_text_that_is_not_a_label_is_not_a_cell() {
    if !have_pdfium() {
        return;
    }
    // (a) a diagonal stamp inside the empty corner: a label is vertical
    // (taller than wide), a stamp is not
    let p = rotated_corner_page(false).rotated(76.0, 136.0, 9.0, 30.0, "CONCEPT");
    let out = run(p);
    assert!(
        tables(&out)[0].markdown.starts_with("|  | Minimum"),
        "{}",
        tables(&out)[0].markdown
    );
    // (b) a vertical run crossing filled cells: it overlaps words
    let p = rotated_corner_page(false).vertical(82.0, 176.0, 12.0, "CONCEPT CONCEPT");
    let out = run(p);
    assert!(
        tables(&out)[0].markdown.starts_with("|  | Minimum"),
        "{}",
        tables(&out)[0].markdown
    );
    assert!(!all_text(&out).contains("CONCEPT"));
}

#[test]
fn a_vertical_label_beside_the_row_labels_heads_that_column() {
    if !have_pdfium() {
        return;
    }
    // Lex5 T5 shape: the label runs up the left of the row labels, BELOW
    // the header row; the header cell of that column is empty. It becomes
    // that header cell (the column's only empty cell).
    let mut p = Page::a4().para(72.0, 60.0, 11.0, &["Salarisschalen voor het jaar."]);
    p = p.vertical(72.0, 164.0, 8.0, "Schaal");
    let rows = [
        ("", "Minimum", "Maximum"),
        ("A", "2.500,00", "3.100,00"),
        ("B", "3.100,00", "3.900,00"),
        ("C", "3.900,00", "4.800,00"),
    ];
    for (k, (a, b, c)) in rows.iter().enumerate() {
        let y = 100.0 + k as f64 * 16.0;
        if !a.is_empty() {
            p = p.text(92.0, y, 10.0, a);
        }
        p = p.text(200.0, y, 10.0, b).text(330.0, y, 10.0, c);
    }
    let out = run(p);
    let t = tables(&out);
    assert_eq!(t.len(), 1, "{:?}", out.units);
    assert_eq!(
        t[0].markdown,
        "| Schaal | Minimum | Maximum |\n| --- | --- | --- |\n| A | 2.500,00 | 3.100,00 |\n| B | 3.100,00 | 3.900,00 |\n| C | 3.900,00 | 4.800,00 |"
    );
}
