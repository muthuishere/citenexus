//! Running headers and footers (ADR-0017 decision 1; research §8 #7, #14).
//!
//! A segment is a candidate when it sits in the top 12 % or bottom 12 % band
//! of its page AND belongs to the band's edge-most block (lines chained from
//! the page edge at ≤ 1.6 × font-size pitch; `edge_block`). Its key is the text lower-cased, whitespace-collapsed, with
//! every digit replaced by `#` (so "Page 3 of 9" and "Page 4 of 9" match). A
//! key is **running** when it occurs on at least 2 pages of one band and
//! either on at least half the pages, or on ≥3 pages each of which has
//! another occurrence within ±1 or ±2 pages (odd/even running heads). At most
//! 3 segments per band per page are taken, nearest the page edge first — the
//! letterhead cap, so a data-bearing first-page letterhead survives as body.
//!
//! Detected lines are NOT deleted: each distinct line is kept ONCE as a
//! `furniture` unit at its first occurrence, so "laatst bijgewerkt <date>"
//! stays citable. Lines that differ only by digits collapse to one unit only
//! when they are page-number lines; otherwise every distinct printed text is
//! kept once (a different date is different evidence).
//!
//! After LiteParse `markdown_layout/repetition.rs` and opendataloader
//! `HeaderFooterProcessor` (both Apache-2.0); see `rust/NOTICE`.

use std::collections::{BTreeMap, BTreeSet};

use super::layout::{Segment, HYPHEN_MARK};

pub const BAND: f64 = 0.12;
pub const CAP_PER_BAND: usize = 3;

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum Band {
    Top,
    Bottom,
}

pub fn key(text: &str) -> String {
    let t: String = text
        .replace(HYPHEN_MARK, "-")
        .chars()
        .map(|c| if c.is_ascii_digit() { '#' } else { c })
        .collect::<String>()
        .to_lowercase();
    t.split_whitespace().collect::<Vec<_>>().join(" ")
}

const PAGE_WORDS: &[&str] = &[
    "page", "pagina", "blz", "blad", "p", "pag", "of", "van", "seite", "von", "sheet",
];

/// "3", "- 3 -", "Page 3 of 9", "pagina 3 van 9".
pub fn is_page_number(key: &str) -> bool {
    key.contains('#')
        && key
            .split(|c: char| {
                c.is_whitespace()
                    || matches!(c, '/' | '-' | '.' | ':' | '|' | '(' | ')' | '[' | ']')
            })
            .filter(|w| !w.is_empty())
            .all(|w| w.chars().all(|c| c == '#') || PAGE_WORDS.contains(&w))
}

/// Only the EDGE-MOST BLOCK of a band may be furniture: the chain of lines
/// from the page edge whose baselines follow each other within 1.6 × the font
/// size, walked over ALL of the page's lines (`all`, sorted from that edge).
/// If the chain runs past the band (`in_band` false for a chained line), the
/// band holds body text that reaches into it — the last lines of a page with
/// no footer, the first lines with no header — and NOTHING there is
/// furniture. A body block separated from a real header/footer by whitespace
/// is never part of the chain either. Keeping furniture once would otherwise
/// DELETE such body text from every other page (digit masking makes "zie
/// pagina 3 van 12" repeat). Segments on one baseline stay together.
fn edge_block(segs: &[Segment], all: &[usize], in_band: &dyn Fn(usize) -> bool) -> Vec<usize> {
    let mut out: Vec<usize> = Vec::new();
    let mut last: Option<usize> = None;
    for &i in all {
        if let Some(l) = last {
            let size = segs[i].size.max(segs[l].size).max(1.0);
            let gap = (segs[i].baseline - segs[l].baseline).abs();
            if gap > 1.6 * size {
                break;
            }
        }
        if !in_band(i) {
            return Vec::new(); // the chain continues as body: no furniture here
        }
        out.push(i);
        last = Some(i);
    }
    out
}

/// The segments of each page that are running furniture: `(page, seg)`.
pub fn detect(pages: &[(f64, &[Segment])]) -> Vec<(usize, usize)> {
    detect_with(pages, BAND, true)
}

/// `detect` with the band depth and the edge-block rule as parameters (for
/// measurement; the pipeline uses `detect`).
pub fn detect_with(pages: &[(f64, &[Segment])], band: f64, edge_rule: bool) -> Vec<(usize, usize)> {
    let n = pages.len();
    // (band, key) -> sorted pages
    let mut occ: BTreeMap<(Band, String), Vec<usize>> = BTreeMap::new();
    let mut cands: Vec<(usize, usize, Band, String)> = Vec::new();
    for (p, (height, segs)) in pages.iter().enumerate() {
        let h = *height;
        let mut top: Vec<usize> = Vec::new();
        let mut bottom: Vec<usize> = Vec::new();
        for (i, s) in segs.iter().enumerate() {
            if s.text.trim().is_empty() {
                continue;
            }
            if s.bbox[3] <= band * h {
                top.push(i);
            } else if s.bbox[1] >= (1.0 - band) * h {
                bottom.push(i);
            }
        }
        top.sort_by(|&a, &b| segs[a].bbox[1].total_cmp(&segs[b].bbox[1]).then(a.cmp(&b)));
        bottom.sort_by(|&a, &b| segs[b].bbox[3].total_cmp(&segs[a].bbox[3]).then(a.cmp(&b)));
        let live: Vec<usize> = (0..segs.len())
            .filter(|&i| !segs[i].text.trim().is_empty())
            .collect();
        let mut from_top = live.clone();
        from_top.sort_by(|&a, &b| segs[a].bbox[1].total_cmp(&segs[b].bbox[1]).then(a.cmp(&b)));
        let mut from_bottom = live;
        from_bottom.sort_by(|&a, &b| segs[b].bbox[3].total_cmp(&segs[a].bbox[3]).then(a.cmp(&b)));
        let (top_set, bottom_set): (BTreeSet<usize>, BTreeSet<usize>) = (
            top.iter().copied().collect(),
            bottom.iter().copied().collect(),
        );
        for (band, list) in [(Band::Top, top), (Band::Bottom, bottom)] {
            let chosen = if !edge_rule {
                list
            } else if band == Band::Top {
                edge_block(segs, &from_top, &|i| top_set.contains(&i))
            } else {
                edge_block(segs, &from_bottom, &|i| bottom_set.contains(&i))
            };
            for i in chosen.into_iter().take(CAP_PER_BAND) {
                let k = key(&segs[i].text);
                let e = occ.entry((band, k.clone())).or_default();
                if e.last() != Some(&p) {
                    e.push(p);
                }
                cands.push((p, i, band, k));
            }
        }
    }
    let running = |band: Band, k: &str| -> bool {
        let Some(pages) = occ.get(&(band, k.to_string())) else {
            return false;
        };
        let c = pages.len();
        if c < 2 {
            return false;
        }
        if c * 2 >= n {
            return true;
        }
        c >= 3
            && pages.iter().all(|&p| {
                pages
                    .iter()
                    .any(|&q| q != p && (q as i64 - p as i64).abs() <= 2)
            })
    };
    let mut out: Vec<(usize, usize)> = cands
        .into_iter()
        .filter(|(_, _, band, k)| running(*band, k))
        .map(|(p, i, _, _)| (p, i))
        .collect();
    out.sort();
    out
}

/// The key under which a furniture line is kept once.
pub fn emit_key(text: &str) -> String {
    let k = key(text);
    if is_page_number(&k) {
        k
    } else {
        text.replace(HYPHEN_MARK, "-")
            .split_whitespace()
            .collect::<Vec<_>>()
            .join(" ")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn page_number_patterns() {
        assert!(is_page_number(&key("Page 3 of 9")));
        assert!(is_page_number(&key("pagina 3 van 12")));
        assert!(is_page_number(&key("- 4 -")));
        assert!(!is_page_number(&key("laatst bijgewerkt 12-03-2024")));
    }
}
