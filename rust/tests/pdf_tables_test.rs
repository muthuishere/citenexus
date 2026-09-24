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
