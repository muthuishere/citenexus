//! `pdf_units`: the no-model base extractor (ADR-0017 decisions 1, 2, 11).
//!
//! raw (pdfium, once) → segments → running header/footer → blocks → reading
//! order → hyphen resolution → headings (per document) → lists → units, with
//! per-page routes and signals. `PdfUnits` in every binding is exactly this.

use std::collections::{BTreeMap, BTreeSet};

use super::furniture::{self, Band};
use super::headings::{self, HBlock};
use super::hyphen::{self, Decision, HyphenStats, Lang, Witnesses};
use super::layout::{self, Block, PageLayout, Segment, HYPHEN_MARK};
use super::order;
use super::raw::{r2, RawDoc, StructNode};
use super::route;
use super::tables;
use crate::units::*;

const BLOCK_ROLES: &[&str] = &[
    "P",
    "H",
    "H1",
    "H2",
    "H3",
    "H4",
    "H5",
    "H6",
    "Title",
    "LI",
    "TD",
    "TH",
    "Caption",
    "Note",
    "BlockQuote",
    "TOCI",
    "Figure",
];

fn heading_tag(kind: &str) -> Option<u32> {
    match kind {
        "H" => Some(0),
        "Title" => Some(1),
        k if k.len() == 2 && k.starts_with('H') => {
            k[1..].parse::<u32>().ok().filter(|n| (1..=6).contains(n))
        }
        _ => None,
    }
}

/// For each struct node: its block-level group (nearest block-role ancestor
/// or self) — the unit of reading order and of block grouping.
fn struct_groups(nodes: &[StructNode]) -> Vec<usize> {
    let mut stack: Vec<usize> = Vec::new();
    let mut group = Vec::with_capacity(nodes.len());
    for (k, n) in nodes.iter().enumerate() {
        while stack.last().is_some_and(|&s| nodes[s].depth >= n.depth) {
            stack.pop();
        }
        stack.push(k);
        // Outermost block role wins for LI (Lbl + LBody share one line);
        // otherwise the innermost block role.
        let li = stack.iter().copied().find(|&s| nodes[s].kind == "LI");
        let inner = stack
            .iter()
            .rev()
            .copied()
            .find(|&s| BLOCK_ROLES.contains(&nodes[s].kind.as_str()));
        group.push(li.or(inner).unwrap_or(k));
    }
    group
}

struct PageWork {
    pl: PageLayout,
    dups: usize,
    order: Vec<usize>,
    method: order::Method,
    /// Struct group node index -> heading tag.
    group_tag: BTreeMap<usize, Option<u32>>,
    /// Struct group node index -> its role ("P", "TD", "H2", ...).
    group_role: BTreeMap<usize, String>,
    /// Deterministic tables (accepted ones are blocks with `table: Some`).
    tables: tables::PageTables,
}

/// Everything before the heading decision: the shared first half of
/// `analyze` and of the heading diagnostics.
pub(crate) struct Staged {
    work: Vec<PageWork>,
    furn: Vec<(usize, usize)>,
    /// Document-order (page, block) pairs.
    doc_blocks: Vec<(usize, usize)>,
    texts: Vec<String>,
    joined: Vec<bool>,
    hblocks: Vec<HBlock>,
    pub(crate) body_size: f64,
    stats: HyphenStats,
    /// `[page][segment]` → the 1-based page ordinals of the segment's words
    /// (line order, then left to right): the `p{page}w{n}` word IDs.
    word_ord: Vec<Vec<Vec<usize>>>,
}

/// The stable word ID for 0-based page `p`, 1-based ordinal `n`.
pub fn word_id(p: usize, n: usize) -> String {
    format!("p{}w{}", p + 1, n)
}

/// The block's centre lies inside the box spanned by the page's ruling lines
/// (≥2 horizontal and ≥2 vertical thin paths): a ruled table region.
pub(crate) fn in_ruled_region(paths: &[[f64; 4]], bbox: [f64; 4]) -> bool {
    let h: Vec<&[f64; 4]> = paths
        .iter()
        .filter(|p| p[3] - p[1] <= 2.0 && p[2] - p[0] >= 15.0)
        .collect();
    let v: Vec<&[f64; 4]> = paths
        .iter()
        .filter(|p| p[2] - p[0] <= 2.0 && p[3] - p[1] >= 15.0)
        .collect();
    if h.len() < 2 || v.len() < 2 {
        return false;
    }
    let all = h.iter().chain(v.iter());
    let (mut x0, mut y0, mut x1, mut y1) = (f64::MAX, f64::MAX, f64::MIN, f64::MIN);
    for p in all {
        x0 = x0.min(p[0]);
        y0 = y0.min(p[1]);
        x1 = x1.max(p[2]);
        y1 = y1.max(p[3]);
    }
    let (cx, cy) = ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0);
    cx >= x0 && cx <= x1 && cy >= y0 && cy <= y1
}

fn lines_of(pl: &PageLayout, b: &Block) -> Vec<String> {
    b.segs
        .iter()
        .map(|&s| pl.segments[s].text.clone())
        .collect()
}

fn list_markdown(text: &str) -> String {
    let t = text.trim_start();
    let mut cs = t.chars();
    let first = cs.next().unwrap_or(' ');
    let rest = cs.as_str();
    if layout::is_bullet(first) && rest.starts_with(' ') {
        format!("- {}", rest.trim())
    } else {
        format!("- {}", t.trim())
    }
}

pub fn analyze(raw: &RawDoc, opts: &PdfOptions) -> PdfUnitsOutput {
    let st = stage(raw, opts);
    let plan = headings::plan(&st.hblocks, st.body_size, &raw.outline, raw.pages.len());
    emit(raw, opts, st, plan).0
}

pub(crate) fn stage(raw: &RawDoc, opts: &PdfOptions) -> Staged {
    let lang = Lang::parse(opts.language.as_deref());
    let n_pages = raw.pages.len();

    // 1. segments per page
    let seg_pages: Vec<(Vec<Segment>, Vec<Vec<usize>>, usize)> =
        raw.pages.iter().map(layout::segments).collect();

    // 2. running headers/footers
    let band_input: Vec<(f64, &[Segment])> = raw
        .pages
        .iter()
        .zip(&seg_pages)
        .map(|(p, s)| (p.height, s.0.as_slice()))
        .collect();
    let furn: Vec<(usize, usize)> = furniture::detect(&band_input);

    // 3. blocks + reading order per page
    let mut work: Vec<PageWork> = Vec::with_capacity(n_pages);
    for (p, (page, (segs, lines, dups))) in raw.pages.iter().zip(seg_pages).enumerate() {
        let groups = struct_groups(&page.struct_nodes);
        let mut mcid_group: BTreeMap<i32, usize> = BTreeMap::new();
        for (k, node) in page.struct_nodes.iter().enumerate() {
            for &m in &node.mcids {
                mcid_group.entry(m).or_insert(groups[k]);
            }
        }
        let group_tag: BTreeMap<usize, Option<u32>> = groups
            .iter()
            .map(|&g| (g, heading_tag(&page.struct_nodes[g].kind)))
            .collect();
        let group_role: BTreeMap<usize, String> = groups
            .iter()
            .map(|&g| (g, page.struct_nodes[g].kind.clone()))
            .collect();
        let elem_of = |m: i32| mcid_group.get(&m).copied();
        let is_furn = |s: usize| furn.binary_search(&(p, s)).is_ok();
        let page_tables = tables::detect(page, &segs, &lines, &is_furn);
        let in_table: BTreeSet<usize> = page_tables
            .accepted
            .iter()
            .flat_map(|t| t.segs.iter().copied())
            .collect();
        let body_lines: Vec<Vec<usize>> = lines
            .iter()
            .map(|l| {
                l.iter()
                    .copied()
                    .filter(|&s| !is_furn(s) && !in_table.contains(&s))
                    .collect::<Vec<_>>()
            })
            .filter(|l: &Vec<usize>| !l.is_empty())
            .collect();
        let (mut blocks, pitch) = layout::blocks(&segs, &body_lines, &elem_of);
        for (k, t) in page_tables.accepted.iter().enumerate() {
            let size =
                layout::mode_half(t.segs.iter().map(|&s| (segs[s].size, segs[s].chars.len())))
                    .unwrap_or(0.0);
            blocks.push(Block {
                segs: t.segs.clone(),
                bbox: t.bbox,
                size,
                bold: false,
                elem: t.struct_node,
                table: Some(k),
            });
        }
        let tagged_chars = segs
            .iter()
            .filter(|s| mcid_group.contains_key(&s.mcid))
            .map(|s| s.chars.len())
            .sum::<usize>();
        let all_chars = segs.iter().map(|s| s.chars.len()).sum::<usize>().max(1);
        let use_struct = !page.struct_nodes.is_empty() && tagged_chars * 2 >= all_chars;
        let boxes: Vec<[f64; 4]> = blocks.iter().map(|b| b.bbox).collect();
        let keys: Vec<Option<usize>> = blocks.iter().map(|b| b.elem).collect();
        let (ord, method) = if blocks.is_empty() {
            (vec![], order::Method::RuleBased)
        } else {
            order::order(&boxes, &keys, use_struct)
        };
        work.push(PageWork {
            pl: PageLayout {
                segments: segs,
                lines,
                blocks,
                pitch,
            },
            dups,
            order: ord,
            method,
            group_tag,
            group_role,
            tables: page_tables,
        });
    }

    // 4. hyphens: witnesses from every line of the document
    let wit = Witnesses::collect(
        work.iter()
            .flat_map(|w| w.pl.segments.iter().map(|s| s.text.as_str())),
    );
    let mut stats = HyphenStats::default();
    // doc-order list of (page, block) and their texts
    let mut doc_blocks: Vec<(usize, usize)> = Vec::new();
    for (p, w) in work.iter().enumerate() {
        for &b in &w.order {
            doc_blocks.push((p, b));
        }
    }
    let mut texts: Vec<String> = Vec::with_capacity(doc_blocks.len());
    let mut joined: Vec<bool> = Vec::with_capacity(doc_blocks.len());
    for &(p, b) in &doc_blocks {
        let blk = &work[p].pl.blocks[b];
        if let Some(k) = blk.table {
            let t = &work[p].tables.accepted[k];
            let grid = tables::text_grid(&work[p].pl.segments, &raw.pages[p], &t.rows);
            texts.push(tables::markdown(&grid));
            joined.push(false);
            continue;
        }
        let lines = lines_of(&work[p].pl, blk);
        let (t, j) = hyphen::join_lines(&lines, lang, &wit, &mut stats);
        texts.push(t);
        joined.push(j);
    }
    let is_table_block: Vec<bool> = doc_blocks
        .iter()
        .map(|&(p, b)| work[p].pl.blocks[b].table.is_some())
        .collect();
    // a marker ending a block continues into the next block (column/page break)
    for k in 0..texts.len() {
        if !texts[k].ends_with(HYPHEN_MARK) {
            continue;
        }
        stats.markers += 1;
        texts[k].pop();
        let next = texts.get(k + 1).cloned().unwrap_or_default();
        let is_list_next = layout::starts_list_item(&next);
        let table_next = is_table_block.get(k + 1).copied().unwrap_or(false);
        let d = if next.trim().is_empty() || is_list_next || table_next {
            Decision::Keep
        } else {
            hyphen::decide(&texts[k], &next, lang, &wit, true)
        };
        match d {
            Decision::Join => {
                stats.joined += 1;
                let nt = next.trim_start();
                let (word, rest) = match nt.find(char::is_whitespace) {
                    Some(i) => (&nt[..i], nt[i..].trim_start()),
                    None => (nt, ""),
                };
                texts[k].push_str(word);
                joined[k] = true;
                texts[k + 1] = rest.to_string();
            }
            Decision::Keep | Decision::KeepSpaced => {
                stats.kept += 1;
                texts[k].push('-');
            }
        }
    }
    for t in texts.iter_mut() {
        if t.contains(HYPHEN_MARK) {
            *t = t.replace(HYPHEN_MARK, "-");
        }
    }

    // 5. headings (per document)
    let body_size = layout::mode_half(work.iter().flat_map(|w| {
        w.pl.blocks.iter().flat_map(|b| {
            b.segs
                .iter()
                .map(|&s| (w.pl.segments[s].size, w.pl.segments[s].chars.len()))
        })
    }))
    .unwrap_or(10.0);
    let hblocks: Vec<HBlock> = doc_blocks
        .iter()
        .zip(&texts)
        .map(|(&(p, b), t)| {
            let blk = &work[p].pl.blocks[b];
            let struct_tag = blk
                .elem
                .and_then(|g| work[p].group_tag.get(&g).copied().flatten());
            let role = blk.elem.and_then(|g| work[p].group_role.get(&g));
            let in_table = blk.table.is_some()
                || matches!(role.map(String::as_str), Some("TD" | "TH"))
                || in_ruled_region(&raw.pages[p].paths, blk.bbox);
            HBlock {
                page: p,
                text: t.clone(),
                lines: blk.segs.len(),
                size: blk.size,
                bold: blk.bold,
                list: blk.table.is_none()
                    && layout::starts_list_item(&work[p].pl.segments[blk.segs[0]].text),
                in_table,
                struct_tag,
            }
        })
        .collect();
    let word_ord = work
        .iter()
        .map(|w| {
            let mut ord = vec![Vec::new(); w.pl.segments.len()];
            let mut n = 0usize;
            for line in &w.pl.lines {
                for &s in line {
                    for _ in &w.pl.segments[s].words {
                        n += 1;
                        ord[s].push(n);
                    }
                }
            }
            ord
        })
        .collect();
    Staged {
        work,
        furn,
        doc_blocks,
        texts,
        joined,
        hblocks,
        body_size,
        stats,
        word_ord,
    }
}

/// Per page: (accepted table boxes, uncertain table regions).
pub(crate) type TableRegions = (Vec<[f64; 4]>, Vec<[f64; 4]>);

impl Staged {
    /// Per page: (accepted table boxes, uncertain table regions).
    pub(crate) fn table_regions(&self) -> Vec<TableRegions> {
        self.work
            .iter()
            .map(|w| {
                (
                    w.tables.accepted.iter().map(|t| t.bbox).collect(),
                    w.tables.uncertain.clone(),
                )
            })
            .collect()
    }

    pub(crate) fn table_diag(&self) -> Vec<super::diag::TableDiag> {
        self.work
            .iter()
            .enumerate()
            .map(|(p, w)| super::diag::TableDiag {
                page: p,
                accepted: w
                    .tables
                    .accepted
                    .iter()
                    .map(|t| {
                        let cols = t
                            .rows
                            .iter()
                            .map(|r| r.iter().map(|c| c.colspan.max(1)).sum::<usize>())
                            .max()
                            .unwrap_or(0);
                        (t.source, t.rows.len(), cols, t.score)
                    })
                    .collect(),
                uncertain: w.tables.uncertain.len(),
                rejected: w.tables.rejected.clone(),
            })
            .collect()
    }

    /// Every word on page `p` in ID order, and whether it is running furniture.
    pub(crate) fn page_words(&self, raw: &RawDoc, p: usize) -> Vec<(PdfWord, bool)> {
        let w = &self.work[p];
        let chars = &raw.pages[p].chars;
        let mut out = Vec::new();
        for line in &w.pl.lines {
            for &s in line {
                let furn = self.furn.binary_search(&(p, s)).is_ok();
                for (k, word) in w.pl.segments[s].words.iter().enumerate() {
                    let mut bb = [f64::MAX, f64::MAX, f64::MIN, f64::MIN];
                    let mut text = String::new();
                    for &c in word {
                        let ch = &chars[c];
                        text.push(if ch.hyphen { '-' } else { ch.ch });
                        bb = [
                            bb[0].min(ch.x0),
                            bb[1].min(ch.y0),
                            bb[2].max(ch.x1),
                            bb[3].max(ch.y1),
                        ];
                    }
                    let id = word_id(p, self.word_ord[p][s][k]);
                    out.push((PdfWord { id, text, bbox: bb }, furn));
                }
            }
        }
        out
    }

    pub(crate) fn hblocks(&self) -> &[HBlock] {
        &self.hblocks
    }
    pub(crate) fn bbox(&self, i: usize) -> [f64; 4] {
        let (p, b) = self.doc_blocks[i];
        self.work[p].pl.blocks[b].bbox
    }
    /// Struct role of block i: its group's role, "none" when untagged on a
    /// tagged page, "" on an untagged page.
    pub(crate) fn role(&self, i: usize, page_tagged: bool) -> String {
        let (p, b) = self.doc_blocks[i];
        match self.work[p].pl.blocks[b]
            .elem
            .and_then(|g| self.work[p].group_role.get(&g))
        {
            Some(r) => r.clone(),
            None if page_tagged => "none".into(),
            None => String::new(),
        }
    }
}

pub(crate) fn emit(
    raw: &RawDoc,
    opts: &PdfOptions,
    st: Staged,
    plan: headings::Plan,
) -> (PdfUnitsOutput, Vec<Vec<String>>) {
    let Staged {
        work,
        furn,
        doc_blocks,
        texts,
        joined,
        hblocks,
        stats,
        word_ord,
        ..
    } = st;
    let seg_ids = |p: usize, s: usize| -> Vec<String> {
        word_ord[p][s].iter().map(|&n| word_id(p, n)).collect()
    };
    let block_ids = |p: usize, b: usize| -> Vec<String> {
        work[p].pl.blocks[b]
            .segs
            .iter()
            .flat_map(|&s| seg_ids(p, s))
            .collect()
    };
    let mut unit_words: Vec<Vec<String>> = Vec::new();
    let n_pages = raw.pages.len();
    let struct_headings = raw.pages.iter().any(|p| {
        p.struct_nodes
            .iter()
            .any(|n| heading_tag(&n.kind).is_some())
    });

    // 6. units per page
    let mut furn_seen: BTreeMap<String, ()> = BTreeMap::new();
    let mut furniture_units = 0u32;
    let mut units: Vec<DocUnit> = Vec::new();
    let mut pages_out: Vec<PdfPageInfo> = Vec::new();
    let mut k = 0usize; // index into doc_blocks
    type Tracked = (DocUnit, Vec<String>);
    for (p, w) in work.iter().enumerate() {
        let page = &raw.pages[p];
        let pg = (p + 1) as u32;
        let mut body: Vec<Tracked> = Vec::new();
        let mut structure = false;
        let mut i = 0;
        let count = w.order.len();
        while i < count {
            let idx = k + i;
            let b = &w.pl.blocks[doc_blocks[idx].1];
            let text = texts[idx].trim().to_string();
            if let Some(tk) = b.table {
                structure = true;
                let t = &w.tables.accepted[tk];
                let mut prov = Provenance::new(Route::Plain);
                prov.table_source = Some(t.source);
                prov.table_uncertain = t.uncertain;
                let ids: Vec<String> = t
                    .rows
                    .iter()
                    .flatten()
                    .flat_map(|c| {
                        c.words
                            .iter()
                            .map(|&(s, wi)| word_id(p, word_ord[p][s][wi]))
                    })
                    .collect();
                body.push((
                    DocUnit {
                        page: Some(pg),
                        bbox: Some(t.bbox.map(r2)),
                        kind: UnitKind::Table,
                        level: None,
                        markdown: text,
                        provenance: prov,
                    },
                    ids,
                ));
                i += 1;
                continue;
            }
            if let Some((lvl, src)) = plan.levels[idx] {
                structure = true;
                let mut text = text;
                let mut bbox = b.bbox;
                let mut joined_h = joined[idx];
                let mut ids = block_ids(p, doc_blocks[idx].1);
                if plan.merge_next[idx] && i + 1 < count {
                    ids.extend(block_ids(p, doc_blocks[idx + 1].1));
                    let nb = &w.pl.blocks[doc_blocks[idx + 1].1];
                    text = format!("{} {}", text, texts[idx + 1].trim())
                        .trim()
                        .to_string();
                    bbox = [
                        bbox[0].min(nb.bbox[0]),
                        bbox[1].min(nb.bbox[1]),
                        bbox[2].max(nb.bbox[2]),
                        bbox[3].max(nb.bbox[3]),
                    ];
                    joined_h |= joined[idx + 1];
                    i += 1; // the title block is consumed
                }
                if !text.is_empty() {
                    let mut prov = Provenance::new(Route::Plain);
                    prov.heading_source = Some(src);
                    prov.joined_hyphen = joined_h;
                    body.push((
                        DocUnit {
                            page: Some(pg),
                            bbox: Some(bbox),
                            kind: UnitKind::Heading,
                            level: Some(lvl),
                            markdown: format!("{} {}", "#".repeat(lvl as usize), text),
                            provenance: prov,
                        },
                        ids,
                    ));
                }
                i += 1;
                continue;
            }
            if hblocks[idx].list {
                structure = true;
                let mut md = Vec::new();
                let mut bbox = b.bbox;
                let mut j_any = false;
                let mut ids = Vec::new();
                while i < count && hblocks[k + i].list && plan.levels[k + i].is_none() {
                    ids.extend(block_ids(p, doc_blocks[k + i].1));
                    let bb = &w.pl.blocks[doc_blocks[k + i].1];
                    bbox = [
                        bbox[0].min(bb.bbox[0]),
                        bbox[1].min(bb.bbox[1]),
                        bbox[2].max(bb.bbox[2]),
                        bbox[3].max(bb.bbox[3]),
                    ];
                    j_any |= joined[k + i];
                    let t = texts[k + i].trim();
                    if !t.is_empty() {
                        md.push(list_markdown(t));
                    }
                    i += 1;
                }
                let mut prov = Provenance::new(Route::Plain);
                prov.joined_hyphen = j_any;
                body.push((
                    DocUnit {
                        page: Some(pg),
                        bbox: Some(bbox),
                        kind: UnitKind::List,
                        level: None,
                        markdown: md.join("\n"),
                        provenance: prov,
                    },
                    ids,
                ));
                continue;
            }
            if b.bold {
                structure = true;
            }
            if !text.is_empty() {
                let mut prov = Provenance::new(Route::Plain);
                prov.joined_hyphen = joined[idx];
                body.push((
                    DocUnit {
                        page: Some(pg),
                        bbox: Some(b.bbox),
                        kind: UnitKind::Paragraph,
                        level: None,
                        markdown: text,
                        provenance: prov,
                    },
                    block_ids(p, doc_blocks[idx].1),
                ));
            }
            i += 1;
        }
        k += count;

        // furniture: first occurrence of each distinct line, top then bottom
        let mut top: Vec<(DocUnit, Vec<String>)> = Vec::new();
        let mut bottom: Vec<(DocUnit, Vec<String>)> = Vec::new();
        let mut fsegs: Vec<usize> = furn
            .iter()
            .filter(|(fp, _)| *fp == p)
            .map(|x| x.1)
            .collect();
        fsegs.sort_by(|&a, &b| {
            let (sa, sb) = (&w.pl.segments[a], &w.pl.segments[b]);
            sa.bbox[1]
                .total_cmp(&sb.bbox[1])
                .then(sa.bbox[0].total_cmp(&sb.bbox[0]))
                .then(a.cmp(&b))
        });
        for s in fsegs {
            let seg = &w.pl.segments[s];
            let key = furniture::emit_key(&seg.text);
            if furn_seen.insert(key, ()).is_some() {
                continue;
            }
            furniture_units += 1;
            let u = DocUnit {
                page: Some(pg),
                bbox: Some(seg.bbox),
                kind: UnitKind::Furniture,
                level: None,
                markdown: seg
                    .text
                    .replace(HYPHEN_MARK, "-")
                    .split_whitespace()
                    .collect::<Vec<_>>()
                    .join(" "),
                provenance: Provenance::new(Route::Plain),
            };
            let band = if seg.bbox[1] < page.height / 2.0 {
                Band::Top
            } else {
                Band::Bottom
            };
            match band {
                Band::Top => top.push((u, seg_ids(p, s))),
                Band::Bottom => bottom.push((u, seg_ids(p, s))),
            }
        }

        // image regions (≥5 % of the page): their own units, never merged
        let page_area = (page.width * page.height).max(1.0);
        let mut imgs: Vec<[f64; 4]> = page
            .images
            .iter()
            .copied()
            .filter(|b| (b[2] - b[0]) * (b[3] - b[1]) >= 0.05 * page_area)
            .collect();
        imgs.sort_by(|a, b| a[1].total_cmp(&b[1]).then(a[0].total_cmp(&b[0])));
        let image_units: Vec<(DocUnit, Vec<String>)> = imgs
            .into_iter()
            .map(|b| DocUnit {
                page: Some(pg),
                bbox: Some([
                    r2(b[0].max(0.0)),
                    r2(b[1].max(0.0)),
                    r2(b[2].min(page.width)),
                    r2(b[3].min(page.height)),
                ]),
                kind: UnitKind::Image,
                level: None,
                markdown: String::new(),
                provenance: Provenance::new(Route::Plain),
            })
            .map(|u| (u, Vec::new()))
            .collect();

        let mut sig = route::signals(page, &w.pl, w.dups);
        sig.reading_order = if w.pl.blocks.is_empty() {
            "none".into()
        } else {
            w.method.as_str().into()
        };
        let rt = route::route(&sig, structure);
        // Each image region goes before the first body unit that starts below
        // its top, so it keeps its place in the reading order.
        for img in image_units {
            let y = img.0.bbox.map(|b| b[1]).unwrap_or(0.0);
            let at = body
                .iter()
                .position(|(u, _)| u.bbox.is_some_and(|b| b[1] >= y))
                .unwrap_or(body.len());
            body.insert(at, img);
        }
        for (mut u, ids) in top.into_iter().chain(body).chain(bottom) {
            u.provenance.route = rt;
            if matches!(
                u.kind,
                UnitKind::Paragraph | UnitKind::List | UnitKind::Heading
            ) {
                if let Some(b) = u.bbox {
                    let (cx, cy) = ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0);
                    if w.tables
                        .uncertain
                        .iter()
                        .any(|r| cx >= r[0] && cx <= r[2] && cy >= r[1] && cy <= r[3])
                    {
                        u.provenance.table_uncertain = true;
                    }
                }
            }
            units.push(u);
            unit_words.push(ids);
        }
        pages_out.push(PdfPageInfo {
            page: pg,
            width: page.width,
            height: page.height,
            route: rt,
            signals: sig,
            layout_text: opts.layout_text.then(|| layout::layout_text(page, &w.pl)),
        });
    }

    let document = PdfDocumentSignals {
        pages: n_pages as u32,
        tagged: raw.tagged(),
        struct_headings,
        outline_entries: raw.outline.len() as u32,
        heading_source: plan.source.to_string(),
        heading_agreement: plan.agreement,
        hyphen_markers: stats.markers as u32,
        hyphens_joined: stats.joined as u32,
        hyphens_kept: stats.kept as u32,
        furniture_lines: furn.len() as u32,
        furniture_units,
        responses_applied: 0,
        responses_rejected: 0,
    };
    (
        PdfUnitsOutput {
            units,
            pages: pages_out,
            document,
        },
        unit_words,
    )
}
