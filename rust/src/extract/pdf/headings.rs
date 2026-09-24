//! Heading detection and levels (ADR-0017 decision 1; research §8 #10).
//!
//! Sources, in order: the tagged-PDF structure tree (`/H1`..`/H6`, `/H`,
//! `/Title`), the outline (bookmarks), numbering ("1.2 Scope", "Artikel 5"),
//! and font size.
//!
//! **When in doubt, no heading (consumer rule).** A false heading starts a new
//! chunk and can cut a rule from its condition; a missed one costs little.
//!
//! **Font-only rule (`font_candidate`).** A block is a heading candidate only
//! when it is short (≤2 lines, ≤150 chars), not a list item, not in a ruled
//! table or `TD`/`TH`, does not end in `:` `;` `,`, is not a sentence (ends in
//! `.` with >3 words), AND either
//! - is printed at ≥ `LARGER` (1.15) × the body size, or
//! - carries a real section number ("1.", "1.2", "IV.", "Artikel 5", ≤15
//!   words) and is bold.
//!
//! Bold alone never makes a heading. Why 1.15: on the Lex5 corpus
//! (`examples/pdf_headings.rs`, counts only), 11 of 11,249 struct-tagged body
//! blocks (0.1 %) sit at ≥1.15 × body, against 24 more between 1.05 and 1.15.
//! Below 1.15 the font carries no signal a body line lacks. The step-2 rule
//! also admitted bold body-size lines; 60 % of the headings it emitted on
//! font-only documents were such lines, half of them followed directly by
//! same-size body text: lead-ins ("Voorwaarden:", "Let op"), not headings.
//!
//! **Struct tree: per heading, where tag and print agree (the default,
//! `Policy::PerHeading`).** On a document whose structure tree carries
//! headings, a heading is emitted only where the tree tags one AND the print
//! supports it (≥1.15 × body, bold, or a section number), outside tables and
//! lists; the level comes from the tag. Print alone never adds a heading to a
//! tagged document, and a tag the print contradicts is dropped. Only one source
//! (the tree) ever names headings in a document, filtered by the other — the
//! sources are never mixed page by page. On Lex5, 766 tagged headings are
//! 99.6 % bold but 84 % at body size (Word heading styles printed at body
//! size), which is why the tree, not the font size, knows these headings.
//!
//! The per-document agreement is still computed and exposed
//! (`HeadingAgreement`): a page DISAGREES when a tagged heading is printed like
//! body text, or when a strict font candidate at ≥1.15 × body is tagged as
//! body text. `Policy::Doc` (the step-2 contract, kept for measurement) trusts
//! the WHOLE tree when ≤ `MAX_DISAGREEMENT` (20 %) of compared pages disagree
//! and uses the font rule for the WHOLE document otherwise. Why the default
//! changed (Lex5, 28 documents in the 0.5–0.8 agreement bucket under the
//! step-2 rule): per-heading emits 118 headings with 4 heading-to-heading spans
//! under five words (1 flat), per-document 117 with 11 (7 flat) — the same
//! headings, fewer that open an empty chunk.
//!
//! **Label + title merge (`merge_labels`).** Word writes "Artikel 5." and its
//! title as two paragraphs in one heading style. A heading that is only a
//! numbered label, directly followed on the same page by a heading at the same
//! or a shallower level, absorbs it into ONE heading.
//!
//! On the font path the outline refines the LEVEL of a heading the print
//! supports (or of a short block whose text matches an outline title exactly).
//! After docling `heading_levels` / docling.rs `heading_hierarchy.rs` (MIT)
//! for the "a wrong level is worse than none" rationale; see `rust/NOTICE`.

use super::raw::OutlineEntry;
use crate::units::{HeadingAgreement, HeadingSource};

pub const MAX_DISAGREEMENT: f64 = 0.20;

/// A font-only heading must be at least this much larger than the body size
/// (see the module docs for why this value).
pub const LARGER: f64 = 1.15;

#[derive(Debug, Clone)]
pub struct HBlock {
    pub page: usize,
    pub text: String,
    pub lines: usize,
    pub size: f64,
    pub bold: bool,
    pub list: bool,
    /// Inside a ruled table region, or a struct `TD`/`TH`.
    pub in_table: bool,
    /// From the struct tree: None = not a heading element; Some(0) = a heading
    /// element without a level (`/H`); Some(n) = `/Hn` or `/Title` (1).
    pub struct_tag: Option<u32>,
}

pub struct Plan {
    pub levels: Vec<Option<(u32, HeadingSource)>>,
    /// `merge_next[i]`: heading i is a bare numbered label ("Artikel 5.") and
    /// absorbs heading i+1 (its title) into ONE heading; i+1 emits nothing.
    pub merge_next: Vec<bool>,
    pub agreement: Option<HeadingAgreement>,
    pub source: &'static str,
}

/// How headings are decided. `PerHeading` is what `pdf_units` ships; the
/// others exist so the diagnostics can measure the alternatives on one corpus.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum Policy {
    /// Step-2 rule: a bold body-size line was a heading candidate; struct tree
    /// trusted per document.
    V1Doc,
    /// Strict font rule; struct tree trusted per document (all or nothing).
    Doc,
    /// The shipped default (consumer decision, 2026-09-25). Strict font rule
    /// on untagged documents; on a struct-tagged document a heading is emitted
    /// only where the tag AND the print agree (larger, bold or numbered) —
    /// never from print alone.
    #[default]
    PerHeading,
}

impl Policy {
    pub const ALL: [Policy; 3] = [Policy::V1Doc, Policy::Doc, Policy::PerHeading];
    pub fn name(self) -> &'static str {
        match self {
            Policy::V1Doc => "v1_doc",
            Policy::Doc => "doc",
            Policy::PerHeading => "per_heading",
        }
    }
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

/// "Artikel 5", "Article 12", "Art. 3" (+ optional title).
pub fn is_artikel(text: &str) -> bool {
    let mut w = text.split_whitespace();
    let first = w.next().unwrap_or("").to_lowercase();
    let second = w.next().unwrap_or("");
    matches!(first.as_str(), "artikel" | "article" | "art." | "art")
        && second.chars().next().is_some_and(|c| c.is_ascii_digit())
}

/// A digit, "§", or a Roman-numeral token ("IV", "IV.").
pub fn has_number_token(t: &str) -> bool {
    t.chars().any(|c| c.is_ascii_digit() || c == '§')
        || t.split_whitespace().any(|w| {
            let w = w.trim_end_matches(['.', ':', ')']);
            !w.is_empty() && w.len() <= 5 && w.chars().all(|c| matches!(c, 'I' | 'V' | 'X'))
        })
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

pub fn font_candidate_v1(b: &HBlock, body: f64) -> bool {
    let t = b.text.trim();
    let chars = t.chars().count();
    if b.list || b.lines > 3 || chars == 0 || chars > 200 || !t.chars().any(|c| c.is_alphabetic()) {
        return false;
    }
    if t.ends_with(',') || t.ends_with(';') || t.ends_with(':') {
        return false;
    }
    let sentence = t.ends_with('.') && t.split_whitespace().count() > 3;
    let bigger = b.size >= body * LARGER && b.lines <= 2 && !sentence;
    let bold_line = b.bold && b.size >= body * 0.95 && b.lines <= 2 && !t.ends_with('.');
    bigger || bold_line
}

/// The strict font rule (consumer rules 1–2): short, not a lead-in, not in a
/// table, and EITHER larger than body text OR a real section number printed
/// bold or larger. Bold alone never makes a heading.
pub fn font_candidate(b: &HBlock, body: f64) -> bool {
    let t = b.text.trim();
    let chars = t.chars().count();
    let words = t.split_whitespace().count();
    if b.list || b.in_table || b.lines > 2 || chars == 0 || chars > 150 {
        return false;
    }
    if !t.chars().any(|c| c.is_alphabetic()) {
        return false;
    }
    if t.ends_with(',') || t.ends_with(';') || t.ends_with(':') {
        return false;
    }
    if t.ends_with('.') && words > 3 {
        return false; // a sentence, not a title ("Art. 5." stays eligible)
    }
    let larger = b.size >= body * LARGER;
    let numbered = (numbering_depth(t).is_some() || is_artikel(t)) && words <= 15;
    larger || (numbered && b.bold)
}

/// Font levels: distinct candidate sizes, largest = 1; bold at body size is
/// one level below the smallest larger size.
fn font_levels(blocks: &[HBlock], cand: &[bool], body: f64) -> Vec<u32> {
    let mut sizes: Vec<i64> = blocks
        .iter()
        .zip(cand)
        .filter(|(b, &c)| c && b.size >= body * LARGER)
        .map(|(b, _)| (b.size * 2.0).round() as i64)
        .collect();
    sizes.sort_by(|a, b| b.cmp(a));
    sizes.dedup();
    blocks
        .iter()
        .map(|b| {
            let k = (b.size * 2.0).round() as i64;
            let lvl = match sizes.iter().position(|&s| s == k) {
                Some(p) if b.size >= body * LARGER => p + 1,
                _ => sizes.iter().filter(|&&s| s > k).count() + 1,
            };
            (lvl as u32).clamp(1, 6)
        })
        .collect()
}

/// The print supports a tagged heading: larger, bold, or numbered.
fn printed_like_heading(b: &HBlock, body: f64) -> bool {
    let t = b.text.trim();
    b.size >= body * LARGER || b.bold || numbering_depth(t).is_some() || is_artikel(t)
}

pub fn plan(blocks: &[HBlock], body: f64, outline: &[OutlineEntry], pages: usize) -> Plan {
    plan_with(blocks, body, outline, pages, Policy::default())
}

pub fn plan_with(
    blocks: &[HBlock],
    body: f64,
    outline: &[OutlineEntry],
    pages: usize,
    policy: Policy,
) -> Plan {
    let mut plan = plan_levels(blocks, body, outline, pages, policy);
    if policy != Policy::V1Doc {
        merge_labels(blocks, &mut plan);
    }
    plan
}

/// A heading that is only a numbered label: ≤3 words with a number token
/// ("Artikel 5.", "§ 3", "Hoofdstuk IV").
fn is_label(t: &str) -> bool {
    let t = t.trim();
    t.split_whitespace().count() <= 3 && has_number_token(t)
}

/// Merge "label" + "title" heading pairs: Word writes the article label and
/// its title as two paragraphs in the same heading style. Measured on Lex5:
/// 94 % of the headings that opened a heading-to-heading span under five
/// words were such labels, and 223 of 236 had no block between them. Split,
/// the label becomes a heading with nothing under it; merged, one chunk
/// boundary carries both. Only when the title is at the same or a shallower
/// level (a deeper one is real nesting) and on the same page.
fn merge_labels(blocks: &[HBlock], plan: &mut Plan) {
    let mut i = 0;
    while i + 1 < blocks.len() {
        if let (Some((l1, s1)), Some((l2, _))) = (plan.levels[i], plan.levels[i + 1]) {
            if blocks[i].page == blocks[i + 1].page && l2 <= l1 && is_label(&blocks[i].text) {
                plan.levels[i] = Some((l1.min(l2), s1));
                plan.levels[i + 1] = None;
                plan.merge_next[i] = true;
                i += 2;
                continue;
            }
        }
        i += 1;
    }
}

fn plan_levels(
    blocks: &[HBlock],
    body: f64,
    outline: &[OutlineEntry],
    pages: usize,
    policy: Policy,
) -> Plan {
    let cand: Vec<bool> = blocks
        .iter()
        .map(|b| match policy {
            Policy::V1Doc => font_candidate_v1(b, body),
            _ => font_candidate(b, body),
        })
        .collect();
    let flevel = font_levels(blocks, &cand, body);
    let has_struct = blocks.iter().any(|b| b.struct_tag.is_some());

    let mut agreement = None;
    let mut trust_struct = false;
    if has_struct {
        let (mut compared, mut agree) = (0u32, 0u32);
        let (mut unsupported, mut strong, mut weak) = (0u32, 0u32, 0u32);
        for p in 0..pages {
            let on: Vec<usize> = (0..blocks.len()).filter(|&i| blocks[i].page == p).collect();
            let tagged = |i: usize| blocks[i].struct_tag.is_some();
            let strong_font = |i: usize| cand[i] && blocks[i].size >= body * LARGER;
            if !on.iter().any(|&i| tagged(i) || cand[i]) {
                continue;
            }
            compared += 1;
            // A tagged heading printed exactly like body text.
            let u = on
                .iter()
                .filter(|&&i| tagged(i) && !printed_like_heading(&blocks[i], body))
                .count() as u32;
            // A clearly larger short line the tags call body text.
            let st = on.iter().filter(|&&i| strong_font(i) && !tagged(i)).count() as u32;
            // A bold body-size short line the tags call body text: weak, counted only.
            let wk = on
                .iter()
                .filter(|&&i| {
                    !tagged(i)
                        && !strong_font(i)
                        && blocks[i].bold
                        && blocks[i].lines <= 2
                        && !blocks[i].list
                })
                .count() as u32;
            unsupported += u;
            strong += st;
            weak += wk;
            if u == 0 && st == 0 {
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
            struct_unsupported: unsupported,
            font_untagged_strong: strong,
            font_untagged_weak: weak,
        });
    }

    let mut levels = vec![None; blocks.len()];
    let struct_level = |i: usize, tag: u32| if tag == 0 { flevel[i] } else { tag.min(6) };
    if has_struct && policy == Policy::PerHeading {
        let mut any = false;
        for (i, b) in blocks.iter().enumerate() {
            if let Some(tag) = b.struct_tag {
                if printed_like_heading(b, body) && !b.in_table && !b.list {
                    levels[i] = Some((struct_level(i, tag), HeadingSource::StructTree));
                    any = true;
                }
            }
        }
        return Plan {
            merge_next: vec![false; blocks.len()],
            levels,
            agreement,
            source: if any { "struct_tree" } else { "none" },
        };
    }
    if trust_struct {
        for (i, b) in blocks.iter().enumerate() {
            if let Some(tag) = b.struct_tag {
                levels[i] = Some((struct_level(i, tag), HeadingSource::StructTree));
            }
        }
        return Plan {
            merge_next: vec![false; blocks.len()],
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
        let short = b.lines <= 2 && b.text.chars().count() <= 150 && !b.list && !b.in_table;
        let lvl = if let Some(o) = outl.filter(|_| cand[i] || short) {
            Some(((o.depth + 1).min(6), HeadingSource::Outline))
        } else if cand[i] {
            let t = b.text.trim();
            match numbering_depth(t) {
                Some(d) => Some((d, HeadingSource::Numbering)),
                None if is_artikel(t) => Some((1, HeadingSource::Numbering)),
                None => Some((flevel[i], HeadingSource::Font)),
            }
        } else {
            None
        };
        any |= lvl.is_some();
        levels[i] = lvl;
    }
    Plan {
        merge_next: vec![false; blocks.len()],
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
            in_table: false,
            struct_tag: tag,
        }
    }

    #[test]
    fn labels_merge_with_a_same_level_title_only() {
        let b = vec![
            hb(0, "Artikel 5.", 11.0, true, Some(1)),
            hb(0, "Vakantie", 11.0, true, Some(1)),
            hb(0, "Body.", 11.0, false, None),
            hb(0, "Hoofdstuk 2", 11.0, true, Some(1)),
            hb(0, "Deeper title", 11.0, true, Some(2)),
        ];
        let p = plan(&b, 11.0, &[], 1);
        assert_eq!(p.merge_next, vec![true, false, false, false, false]);
        assert_eq!(p.levels[1], None);
        // a deeper title is real nesting: no merge
        assert!(p.levels[3].is_some() && p.levels[4].is_some());
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
    fn per_heading_is_the_default_and_keeps_only_agreeing_tags() {
        let b = vec![
            hb(0, "Title", 18.0, true, Some(1)),
            hb(1, "Body text that is tagged.", 11.0, false, Some(2)),
            hb(1, "Real heading", 14.0, true, None),
        ];
        let p = plan(&b, 11.0, &[], 2);
        assert_eq!(Policy::default(), Policy::PerHeading);
        assert_eq!(p.levels[0], Some((1, HeadingSource::StructTree)));
        assert_eq!(p.levels[1], None); // tag contradicted by the print
        assert_eq!(p.levels[2], None); // print alone never adds one
        assert!(!p.agreement.unwrap().struct_tree_trusted);
    }

    #[test]
    fn doc_policy_falls_back_to_font_for_the_whole_document() {
        // Page 0 agrees; page 1 tags a body paragraph as H2 and misses a real
        // heading: 1 of 2 pages disagree (50 % > 20 %).
        let b = vec![
            hb(0, "Title", 18.0, true, Some(1)),
            hb(1, "Body text that is tagged.", 11.0, false, Some(2)),
            hb(1, "Real heading", 14.0, true, None),
        ];
        let p = plan_with(&b, 11.0, &[], 2, Policy::Doc);
        let a = p.agreement.unwrap();
        assert!(!a.struct_tree_trusted);
        assert_eq!((a.compared_pages, a.agreeing_pages), (2, 1));
        assert_eq!(p.levels[0], Some((1, HeadingSource::Font)));
        assert_eq!(p.levels[1], None);
        assert_eq!(p.levels[2], Some((2, HeadingSource::Font)));
    }
}
