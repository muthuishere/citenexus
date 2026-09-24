//! Heading detection and levels (ADR-0017 decision 1; research §8 #10).
//!
//! Sources, in order: the tagged-PDF structure tree (`/H1`..`/H6`, `/H`,
//! `/Title`), the outline (bookmarks), numbering ("1.2 Scope"), and font
//! clustering (size above the body size, or a short bold line at body size).
//!
//! **Decided per document, never page by page (consumer rule).** When the
//! structure tree carries headings, it is compared with the font evidence on
//! every page where either names a heading. A page agrees when both name
//! exactly the same heading blocks. If more than `MAX_DISAGREEMENT` (20 %) of
//! those pages disagree, the tags are treated as systematically unreliable and
//! the WHOLE document uses font evidence; otherwise the WHOLE document uses the
//! tags. Why 20 %: one odd page in five is the kind of local quirk a real
//! document has (a cover title tagged `/P`, one bold lead-in paragraph) and
//! should not discard good tags; two in five is a pattern — headings styled
//! by hand, or tags written by a converter that guessed. On a short document
//! a single disagreeing page out of one to four exceeds 20 %, which is the
//! intended bias: with little evidence, trust what is printed.
//!
//! On the font path the outline and numbering refine the LEVEL (outline depth,
//! number depth) but a heading is only emitted where the font evidence names
//! one, or where an outline title matches a short block exactly.
//! Docling's "a wrong level is worse than none" rationale; after docling
//! `heading_levels` / docling.rs `heading_hierarchy.rs` (MIT); see `rust/NOTICE`.

use super::raw::OutlineEntry;
use crate::units::{HeadingAgreement, HeadingSource};

pub const MAX_DISAGREEMENT: f64 = 0.20;

#[derive(Debug, Clone)]
pub struct HBlock {
    pub page: usize,
    pub text: String,
    pub lines: usize,
    pub size: f64,
    pub bold: bool,
    pub list: bool,
    /// From the struct tree: None = not a heading element; Some(0) = a heading
    /// element without a level (`/H`); Some(n) = `/Hn` or `/Title` (1).
    pub struct_tag: Option<u32>,
}

pub struct Plan {
    pub levels: Vec<Option<(u32, HeadingSource)>>,
    pub agreement: Option<HeadingAgreement>,
    pub source: &'static str,
}

fn r4(v: f64) -> f64 {
    (v * 10_000.0).round() / 10_000.0
}

/// "1", "1.2", "1.2.3" (optionally with a trailing dot) or a Roman numeral
/// with a dot, followed by a space: the number depth.
pub fn numbering_depth(text: &str) -> Option<u32> {
    let head = text.split_whitespace().next()?;
    text.split_whitespace().nth(1)?;
    let h = head.trim_end_matches('.');
    if !h.is_empty()
        && h.split('.')
            .all(|p| !p.is_empty() && p.len() <= 3 && p.chars().all(|c| c.is_ascii_digit()))
    {
        return Some(h.split('.').count().min(6) as u32);
    }
    if head.ends_with('.')
        && h.len() <= 5
        && h.chars().all(|c| matches!(c, 'I' | 'V' | 'X'))
        && !h.is_empty()
    {
        return Some(1);
    }
    None
}

fn norm(t: &str) -> String {
    let t = t.trim();
    let t = match numbering_depth(t) {
        Some(_) => t.split_once(char::is_whitespace).map(|x| x.1).unwrap_or(t),
        None => t,
    };
    t.chars()
        .filter(|c| c.is_alphanumeric() || c.is_whitespace())
        .collect::<String>()
        .to_lowercase()
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
}

fn font_candidate(b: &HBlock, body: f64) -> bool {
    let t = b.text.trim();
    let chars = t.chars().count();
    if b.list || b.lines > 3 || chars == 0 || chars > 200 || !t.chars().any(|c| c.is_alphabetic()) {
        return false;
    }
    if t.ends_with(',') || t.ends_with(';') || t.ends_with(':') {
        return false;
    }
    let bigger = b.size >= body * 1.15;
    let bold_line = b.bold && b.size >= body * 0.95 && b.lines <= 2 && !t.ends_with('.');
    bigger || bold_line
}

/// Font levels: distinct candidate sizes, largest = 1; bold at body size is
/// one level below the smallest larger size.
fn font_levels(blocks: &[HBlock], cand: &[bool], body: f64) -> Vec<u32> {
    let mut sizes: Vec<i64> = blocks
        .iter()
        .zip(cand)
        .filter(|(b, &c)| c && b.size >= body * 1.15)
        .map(|(b, _)| (b.size * 2.0).round() as i64)
        .collect();
    sizes.sort_by(|a, b| b.cmp(a));
    sizes.dedup();
    blocks
        .iter()
        .map(|b| {
            let k = (b.size * 2.0).round() as i64;
            let lvl = match sizes.iter().position(|&s| s == k) {
                Some(p) if b.size >= body * 1.15 => p + 1,
                _ => sizes.iter().filter(|&&s| s > k).count() + 1,
            };
            (lvl as u32).clamp(1, 6)
        })
        .collect()
}

pub fn plan(blocks: &[HBlock], body: f64, outline: &[OutlineEntry], pages: usize) -> Plan {
    let cand: Vec<bool> = blocks.iter().map(|b| font_candidate(b, body)).collect();
    let flevel = font_levels(blocks, &cand, body);
    let has_struct = blocks.iter().any(|b| b.struct_tag.is_some());

    let mut agreement = None;
    let mut trust_struct = false;
    if has_struct {
        let (mut compared, mut agree) = (0u32, 0u32);
        for p in 0..pages {
            let on: Vec<usize> = (0..blocks.len()).filter(|&i| blocks[i].page == p).collect();
            let s: Vec<usize> = on
                .iter()
                .copied()
                .filter(|&i| blocks[i].struct_tag.is_some())
                .collect();
            let f: Vec<usize> = on.iter().copied().filter(|&i| cand[i]).collect();
            if s.is_empty() && f.is_empty() {
                continue;
            }
            compared += 1;
            if s == f {
                agree += 1;
            }
        }
        let rate = if compared == 0 {
            1.0
        } else {
            agree as f64 / compared as f64
        };
        trust_struct = 1.0 - rate <= MAX_DISAGREEMENT + 1e-9;
        agreement = Some(HeadingAgreement {
            compared_pages: compared,
            agreeing_pages: agree,
            rate: r4(rate),
            struct_tree_trusted: trust_struct,
        });
    }

    let mut levels = vec![None; blocks.len()];
    if trust_struct {
        for (i, b) in blocks.iter().enumerate() {
            if let Some(tag) = b.struct_tag {
                let lvl = if tag == 0 { flevel[i] } else { tag.min(6) };
                levels[i] = Some((lvl, HeadingSource::StructTree));
            }
        }
        return Plan {
            levels,
            agreement,
            source: "struct_tree",
        };
    }

    let mut any = false;
    for (i, b) in blocks.iter().enumerate() {
        let n = norm(&b.text);
        let outl = outline
            .iter()
            .find(|o| !n.is_empty() && norm(&o.title) == n && o.page.is_none_or(|p| p == b.page));
        let short = b.lines <= 2 && b.text.chars().count() <= 150 && !b.list;
        let lvl = if let Some(o) = outl.filter(|_| cand[i] || short) {
            Some(((o.depth + 1).min(6), HeadingSource::Outline))
        } else if cand[i] {
            match numbering_depth(&b.text) {
                Some(d) => Some((d, HeadingSource::Numbering)),
                None => Some((flevel[i], HeadingSource::Font)),
            }
        } else {
            None
        };
        any |= lvl.is_some();
        levels[i] = lvl;
    }
    Plan {
        levels,
        agreement,
        source: if any { "font" } else { "none" },
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn hb(page: usize, text: &str, size: f64, bold: bool, tag: Option<u32>) -> HBlock {
        HBlock {
            page,
            text: text.into(),
            lines: 1,
            size,
            bold,
            list: false,
            struct_tag: tag,
        }
    }

    #[test]
    fn numbering() {
        assert_eq!(numbering_depth("1.2 Scope"), Some(2));
        assert_eq!(numbering_depth("3. Leave"), Some(1));
        assert_eq!(numbering_depth("IV. Pay"), Some(1));
        assert_eq!(numbering_depth("2024 was a year"), None);
        assert_eq!(numbering_depth("Scope"), None);
    }

    #[test]
    fn tags_agreeing_with_fonts_are_trusted() {
        let b = vec![
            hb(0, "Title", 18.0, true, Some(1)),
            hb(0, "Body text.", 11.0, false, None),
        ];
        let p = plan(&b, 11.0, &[], 1);
        assert_eq!(p.levels[0], Some((1, HeadingSource::StructTree)));
        assert!(p.agreement.unwrap().struct_tree_trusted);
    }

    #[test]
    fn disagreeing_tags_fall_back_to_font_for_the_whole_document() {
        // Page 0 agrees; page 1 tags a body paragraph as H2 and misses a real
        // heading: 1 of 2 pages disagree (50 % > 20 %).
        let b = vec![
            hb(0, "Title", 18.0, true, Some(1)),
            hb(1, "Body text that is tagged.", 11.0, false, Some(2)),
            hb(1, "Real heading", 14.0, true, None),
        ];
        let p = plan(&b, 11.0, &[], 2);
        let a = p.agreement.unwrap();
        assert!(!a.struct_tree_trusted);
        assert_eq!((a.compared_pages, a.agreeing_pages), (2, 1));
        assert_eq!(p.levels[0], Some((1, HeadingSource::Font)));
        assert_eq!(p.levels[1], None);
        assert_eq!(p.levels[2], Some((2, HeadingSource::Font)));
    }
}
