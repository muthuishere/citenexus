//! Per-page routing with its evidence exposed (ADR-0017 decision 2; research
//! §8 #3 and #4). This step only CLASSIFIES; nothing is re-extracted.
//!
//! Signals, all deterministic:
//! - **Text-layer soundness** (after Docling `rate_text_quality` and Marker's
//!   more-than-2 % garble check): the share of characters that are U+FFFD, private-use,
//!   stray control codes or flagged by pdfium's `HasUnicodeMapError`; the
//!   share drawn in render mode 3 (invisible, an OCR layer); the share that
//!   were exact duplicates drawn on top of each other (a doubled layer).
//! - **Image coverage**: the union of image-object boxes rasterised on a
//!   64×64 grid of the page.
//! - **Ruling lines**: thin, long path objects (horizontal and vertical).
//! - **Column tracks**: left edges shared by at least three multi-segment
//!   lines (borderless tables, forms).
//!
//! Route, first match wins: `scan` (no or unsound text layer) → `table`
//! (ruled grid or ≥3 tracks) → `image` (≥30 % image coverage) → `formatted`
//! (headings, lists, several columns or bold runs) → `plain`.
//! Router idea after LiteParse `is-complex` reasons (Apache-2.0) and
//! opendataloader `TriageProcessor` (Apache-2.0); see `rust/NOTICE`.

use super::layout::{PageLayout, HYPHEN_MARK};
use super::raw::RawPage;
use crate::units::{PdfPageSignals, Route};

/// A garbled share above this makes the text layer unsound (Marker uses 2 %).
pub const MAX_BAD_SHARE: f64 = 0.02;
/// A duplicated-glyph share at or above this marks a doubled text layer.
pub const MAX_DUP_SHARE: f64 = 0.4;

fn r4(v: f64) -> f64 {
    (v * 10_000.0).round() / 10_000.0
}

fn bad(ch: char) -> bool {
    ch == '\u{FFFD}'
        || ('\u{E000}'..='\u{F8FF}').contains(&ch)
        || (ch.is_control() && ch != HYPHEN_MARK && !ch.is_whitespace())
}

pub fn image_coverage(page: &RawPage) -> f64 {
    const N: usize = 64;
    if page.width <= 0.0 || page.height <= 0.0 || page.images.is_empty() {
        return 0.0;
    }
    let mut covered = 0usize;
    for gy in 0..N {
        for gx in 0..N {
            let cx = (gx as f64 + 0.5) * page.width / N as f64;
            let cy = (gy as f64 + 0.5) * page.height / N as f64;
            if page
                .images
                .iter()
                .any(|b| cx >= b[0] && cx <= b[2] && cy >= b[1] && cy <= b[3])
            {
                covered += 1;
            }
        }
    }
    r4(covered as f64 / (N * N) as f64)
}

/// Count left-edge tracks shared by ≥3 lines that have ≥2 segments.
fn column_tracks(pl: &PageLayout) -> (usize, usize) {
    let multi: Vec<&Vec<usize>> = pl.lines.iter().filter(|l| l.len() >= 2).collect();
    let mut xs: Vec<f64> = multi
        .iter()
        .flat_map(|l| l.iter().map(|&s| pl.segments[s].bbox[0]))
        .collect();
    xs.sort_by(|a, b| a.total_cmp(b));
    // Cluster left edges within 3pt, count clusters with ≥3 members.
    let mut tracks = 0;
    let mut i = 0;
    while i < xs.len() {
        let mut j = i;
        while j + 1 < xs.len() && xs[j + 1] - xs[i] <= 3.0 {
            j += 1;
        }
        if j + 1 - i >= 3 {
            tracks += 1;
        }
        i = j + 1;
    }
    (tracks, multi.len())
}

pub fn signals(page: &RawPage, pl: &PageLayout, dup_removed: usize) -> PdfPageSignals {
    let visible: Vec<_> = page
        .chars
        .iter()
        .filter(|c| !c.generated && !c.ch.is_whitespace())
        .collect();
    let n = visible.len();
    let badn = visible
        .iter()
        .filter(|c| bad(c.ch) || c.unicode_error)
        .count();
    let inv = visible.iter().filter(|c| c.invisible).count();
    let share = |k: usize| if n == 0 { 0.0 } else { r4(k as f64 / n as f64) };
    let (mut h, mut v) = (0usize, 0usize);
    for b in &page.paths {
        let (w, ht) = (b[2] - b[0], b[3] - b[1]);
        if ht <= 2.0 && w >= 15.0 {
            h += 1;
        } else if w <= 2.0 && ht >= 15.0 {
            v += 1;
        }
    }
    let (tracks, multi_lines) = column_tracks(pl);
    let mut sizes: Vec<i64> = pl
        .segments
        .iter()
        .map(|s| (s.size * 2.0).round() as i64)
        .collect();
    sizes.sort();
    sizes.dedup();
    let columns =
        if !pl.lines.is_empty() && multi_lines * 2 >= pl.lines.len() && (1..=2).contains(&tracks) {
            2
        } else {
            1
        };
    let bad_share = share(badn);
    let dup_share = share(dup_removed);
    PdfPageSignals {
        chars: n as u32,
        bad_char_share: bad_share,
        invisible_share: share(inv),
        duplicate_share: dup_share,
        text_sound: n > 0 && bad_share <= MAX_BAD_SHARE && dup_share < MAX_DUP_SHARE,
        image_coverage: image_coverage(page),
        images: page.images.len() as u32,
        ruling_lines_h: h as u32,
        ruling_lines_v: v as u32,
        column_tracks: tracks as u32,
        multi_segment_lines: multi_lines as u32,
        text_columns: columns,
        font_sizes: sizes.len() as u32,
        reading_order: String::new(),
    }
}

/// `structure` = the page carries headings, lists or bold runs.
pub fn route(s: &PdfPageSignals, structure: bool) -> Route {
    let scan = (s.chars < 20 && s.image_coverage >= 0.5)
        || (s.chars > 0 && !s.text_sound)
        || (s.chars == 0 && s.images > 0)
        || (s.invisible_share >= 0.9 && s.image_coverage >= 0.5);
    if scan {
        return Route::Scan;
    }
    let ruled = s.ruling_lines_h >= 2 && s.ruling_lines_v >= 2;
    if ruled || (s.column_tracks >= 3 && s.multi_segment_lines >= 3) {
        return Route::Table;
    }
    if s.image_coverage >= 0.3 {
        return Route::Image;
    }
    if structure || s.text_columns >= 2 {
        return Route::Formatted;
    }
    Route::Plain
}
