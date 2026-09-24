//! Heading diagnostics: per-block FEATURES, never text.
//!
//! Built for corpus measurement over client documents (`examples/pdf_measure.rs`):
//! everything returned here is a number, a flag or a structure-role name, so
//! aggregating it can never quote a document. It runs the exact `analyze`
//! pipeline up to the heading decision (`build::stage`), then evaluates each
//! heading policy on the same blocks.

use std::collections::BTreeMap;

use super::build;
use super::headings::{self, numbering_depth, Policy};
use super::raw::{self, RawDoc};
use crate::units::{HeadingSource, PdfOptions};

#[derive(Debug, Clone, PartialEq)]
pub struct BlockFeatures {
    /// 0-based page.
    pub page: usize,
    /// Struct role of the block's element ("P", "TD", "H2", …), "none" when
    /// the block is untagged on a tagged page, "" on an untagged document.
    pub role: String,
    /// Struct-tree heading tag (0 = `/H`, n = `/Hn`).
    pub struct_heading: Option<u32>,
    pub size_ratio: f64,
    pub bold: bool,
    pub chars: usize,
    pub words: usize,
    pub lines: usize,
    pub ends_colon: bool,
    pub ends_period: bool,
    pub all_caps: bool,
    /// "1.", "1.2", "IV." section numbering.
    pub numbered: bool,
    /// Starts with "Artikel"/"Article"/"Art." + a number.
    pub artikel: bool,
    pub list: bool,
    pub first_on_page: bool,
    /// Top of the block over page height.
    pub y_ratio: f64,
    /// Left edge over page width.
    pub x_ratio: f64,
    /// The same text (digits masked) appears on ≥2 pages.
    pub repeats: bool,
    /// Inside the ruling-line box of a ruled page, or struct role TD/TH.
    pub in_table: bool,
    /// The next block on the same page has the same size and is not bold.
    pub next_same_size_body: bool,
    /// The text contains a digit, "§" or a Roman-numeral token.
    pub has_number: bool,
    /// Heading candidate under the step-2 font rule (bold alone counted).
    pub font_cand_v1: bool,
    /// Heading candidate under the strict font rule.
    pub font_cand: bool,
}

#[derive(Debug, Clone, Default, PartialEq)]
pub struct PolicyStats {
    pub headings: usize,
    pub per_page: Vec<usize>,
    /// Heading → next heading with fewer than `SHORT_SPAN_WORDS` words of
    /// body text between them (a heading with no sentence under it).
    pub short_spans: usize,
    /// Of the short spans: the next heading is DEEPER (legitimate nesting,
    /// e.g. "Artikel 5" then its title).
    pub short_nested: usize,
    /// Of the flat short spans: nothing at all between the two headings.
    pub short_flat_adjacent: usize,
    /// Block indices of headings that open a short span to a heading at the
    /// same or a shallower level (the suspicious ones).
    pub short_flat_at: Vec<usize>,
    pub struct_tree_used: bool,
}

/// A span under a heading shorter than this many words is "shorter than one
/// sentence": an average Dutch/English sentence runs 15–20 words, and even a
/// terse rule ("Verlof moet vooraf worden aangevraagd.") has 5.
pub const SHORT_SPAN_WORDS: usize = 5;

#[derive(Debug, Clone)]
pub struct HeadingDiag {
    pub body_size: f64,
    pub pages: usize,
    pub struct_headings: bool,
    pub blocks: Vec<BlockFeatures>,
    /// Per block: the level/source under each policy.
    pub levels: BTreeMap<&'static str, Vec<Option<(u32, HeadingSource)>>>,
    pub stats: BTreeMap<&'static str, PolicyStats>,
    /// Agreement under the document rule (the default policy).
    pub agreement_rate: Option<f64>,
    /// Agreement under each policy's own font rule.
    pub agreement_rates: BTreeMap<&'static str, Option<f64>>,
}

fn stats_for(
    blocks: &[BlockFeatures],
    levels: &[Option<(u32, HeadingSource)>],
    merged: &[bool],
    pages: usize,
) -> PolicyStats {
    let mut st = PolicyStats {
        per_page: vec![0; pages],
        ..Default::default()
    };
    // (block index, level, words under it so far)
    let mut open: Option<(usize, u32, usize)> = None;
    for (i, (b, lvl)) in blocks.iter().zip(levels).enumerate() {
        if let Some((level, src)) = lvl {
            if let Some((h, hl, w)) = open {
                if w < SHORT_SPAN_WORDS {
                    st.short_spans += 1;
                    if *level > hl {
                        st.short_nested += 1;
                    } else {
                        st.short_flat_at.push(h);
                        if h + 1 == i {
                            st.short_flat_adjacent += 1;
                        }
                    }
                }
            }
            open = Some((i, *level, 0));
            st.headings += 1;
            st.per_page[b.page] += 1;
            st.struct_tree_used |= *src == HeadingSource::StructTree;
        } else if i > 0 && merged[i - 1] {
            // the title half of a merged "label + title" heading: not body
        } else if let Some((_, _, w)) = open.as_mut() {
            *w += b.words;
        }
    }
    st
}

fn mask(t: &str) -> String {
    t.chars()
        .map(|c| if c.is_ascii_digit() { '#' } else { c })
        .collect::<String>()
        .to_lowercase()
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
}

pub fn diagnose(bytes: &[u8], opts: &PdfOptions) -> Result<HeadingDiag, String> {
    let raw = raw::read(bytes)?;
    Ok(diagnose_raw(&raw, opts))
}

pub fn diagnose_raw(raw: &RawDoc, opts: &PdfOptions) -> HeadingDiag {
    let st = build::stage(raw, opts);
    let pages = raw.pages.len();
    let body = st.body_size.max(1.0);
    let hb = st.hblocks();

    // repeats: masked text on ≥2 distinct pages
    let mut seen: BTreeMap<String, Vec<usize>> = BTreeMap::new();
    for b in hb {
        let e = seen.entry(mask(&b.text)).or_default();
        if e.last() != Some(&b.page) {
            e.push(b.page);
        }
    }
    let mut blocks = Vec::with_capacity(hb.len());
    for (i, b) in hb.iter().enumerate() {
        let t = b.text.trim();
        let letters: Vec<char> = t.chars().filter(|c| c.is_alphabetic()).collect();
        let bbox = st.bbox(i);
        let page = &raw.pages[b.page];
        let role = st.role(i, !page.struct_nodes.is_empty());
        let next_same = hb
            .get(i + 1)
            .filter(|n| n.page == b.page)
            .is_some_and(|n| (n.size - b.size).abs() < 0.5 && !n.bold);
        blocks.push(BlockFeatures {
            page: b.page,
            struct_heading: b.struct_tag,
            size_ratio: (b.size / body * 100.0).round() / 100.0,
            bold: b.bold,
            chars: t.chars().count(),
            words: t.split_whitespace().count(),
            lines: b.lines,
            ends_colon: t.ends_with(':'),
            ends_period: t.ends_with('.'),
            all_caps: letters.len() >= 3 && letters.iter().all(|c| c.is_uppercase()),
            numbered: numbering_depth(t).is_some(),
            artikel: headings::is_artikel(t),
            list: b.list,
            first_on_page: i == 0 || hb[i - 1].page != b.page,
            y_ratio: if page.height > 0.0 {
                (bbox[1] / page.height * 100.0).round() / 100.0
            } else {
                0.0
            },
            x_ratio: if page.width > 0.0 {
                (bbox[0] / page.width * 100.0).round() / 100.0
            } else {
                0.0
            },
            repeats: seen.get(&mask(&b.text)).is_some_and(|p| p.len() >= 2),
            in_table: b.in_table,
            next_same_size_body: next_same,
            has_number: headings::has_number_token(t),
            font_cand_v1: headings::font_candidate_v1(b, body),
            font_cand: headings::font_candidate(b, body),
            role,
        });
    }

    let mut levels = BTreeMap::new();
    let mut stats = BTreeMap::new();
    let mut agreement_rate = None;
    let mut agreement_rates = BTreeMap::new();
    for policy in Policy::ALL {
        let plan = headings::plan_with(hb, st.body_size, &raw.outline, pages, policy);
        agreement_rates.insert(policy.name(), plan.agreement.as_ref().map(|a| a.rate));
        if policy == Policy::default() {
            agreement_rate = plan.agreement.as_ref().map(|a| a.rate);
        }
        stats.insert(
            policy.name(),
            stats_for(&blocks, &plan.levels, &plan.merge_next, pages),
        );
        levels.insert(policy.name(), plan.levels);
    }
    HeadingDiag {
        body_size: st.body_size,
        pages,
        struct_headings: hb.iter().any(|b| b.struct_tag.is_some()),
        blocks,
        levels,
        stats,
        agreement_rate,
        agreement_rates,
    }
}

/// Table detection per page (diagnostics): accepted sources + shapes,
/// uncertain regions and rejection reasons. No text.
pub fn tables(bytes: &[u8], opts: &PdfOptions) -> Result<Vec<TableDiag>, String> {
    let raw = raw::read(bytes)?;
    let st = build::stage(&raw, opts);
    Ok(st.table_diag())
}

#[derive(Debug, Clone)]
pub struct TableDiag {
    pub page: usize,
    /// (source, rows, cols, score)
    pub accepted: Vec<(crate::units::TableSource, usize, usize, f64)>,
    pub uncertain: usize,
    pub rejected: Vec<(crate::units::TableSource, super::tables::Reject)>,
}

/// Every text-layer word per page (IDs, text from pdfium chars, boxes), for
/// independent integrity checks in measurement tools.
pub fn page_words(
    bytes: &[u8],
    opts: &PdfOptions,
) -> Result<Vec<Vec<crate::units::PdfWord>>, String> {
    let raw = raw::read(bytes)?;
    let st = build::stage(&raw, opts);
    Ok((0..raw.pages.len())
        .map(|p| st.page_words(&raw, p).into_iter().map(|(w, _)| w).collect())
        .collect())
}
