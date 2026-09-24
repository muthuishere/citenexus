//! Shared synthetic fixtures (invented text).
#![allow(dead_code)]

use super::pdfgen::Page;

/// Helvetica AFM advance widths for the characters used in amounts.
pub fn width(s: &str, size: f64) -> f64 {
    s.chars()
        .map(|c| match c {
            '0'..='9' | '\u{20AC}' => 556.0,
            '.' | ',' | ' ' => 278.0,
            '%' => 889.0,
            _ => 556.0,
        })
        .sum::<f64>()
        * size
        / 1000.0
}

/// Text right-aligned at `right`.
pub fn right(p: Page, right: f64, y: f64, s: &str) -> Page {
    p.text(right - width(s, 10.0), y, 10.0, s)
}

pub fn invoice_page() -> Page {
    let mut p = Page::a4().para(72.0, 60.0, 10.0, &["Factuur voor geleverde diensten."]);
    let head = 100.0;
    p = p
        .bold(72.0, head, 10.0, "#")
        .bold(100.0, head, 10.0, "Description");
    p = right(p, 330.0, head, "Qty").bold(0.0, -100.0, 1.0, "");
    p = right(p, 420.0, head, "Unit price");
    p = right(p, 520.0, head, "Amount");
    let items = [
        ("1", "Consultancy", "84", "125,00", "10.500,00"),
        ("2", "Licentie", "1", "3.000,00", "3.000,00"),
        ("3", "Training", "16", "112,50", "1.800,00"),
    ];
    for (k, (n, d, q, u, a)) in items.iter().enumerate() {
        let y = 116.0 + k as f64 * 16.0;
        p = p.text(72.0, y, 10.0, n).text(100.0, y, 10.0, d);
        p = right(p, 330.0, y, q);
        p = right(p, 420.0, y, u);
        p = right(p, 520.0, y, a);
    }
    for (k, (l, a)) in [
        ("Subtotal", "15.300,00"),
        ("VAT 21%", "3.213,00"),
        ("Total due", "18.513,00"),
    ]
    .iter()
    .enumerate()
    {
        let y = 164.0 + k as f64 * 16.0;
        p = p.text(100.0, y, 10.0, l);
        p = right(p, 520.0, y, a);
    }
    p
}
