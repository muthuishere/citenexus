//! `pdf_units`: the no-model base extractor (ADR-0017 decisions 1, 2, 11).
//!
//! raw (pdfium, once) → segments → running header/footer → blocks → reading
//! order → hyphen resolution → headings (per document) → lists → units, with
//! per-page routes and signals. `PdfUnits` in every binding is exactly this.

use std::collections::BTreeMap;

use super::furniture::{self, Band};
use super::headings::{self, HBlock};
use super::hyphen::{self, Decision, HyphenStats, Lang, Witnesses};
use super::layout::{self, Block, PageLayout, Segment, HYPHEN_MARK};
use super::order;
use super::raw::{self, r2, RawDoc, StructNode};
use super::route;
use crate::units::*;

/// Extract structured units from PDF bytes.
pub fn pdf_units(bytes: &[u8], opts: &PdfOptions) -> Result<PdfUnitsOutput, String> {
    let raw = raw::read(bytes)?;
    Ok(analyze(&raw, opts))
}

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
        let elem_of = |m: i32| mcid_group.get(&m).copied();
        let body_lines: Vec<Vec<usize>> = lines
            .iter()
            .map(|l| {
                l.iter()
                    .copied()
                    .filter(|&s| furn.binary_search(&(p, s)).is_err())
                    .collect::<Vec<_>>()
            })
            .filter(|l: &Vec<usize>| !l.is_empty())
            .collect();
        let (blocks, pitch) = layout::blocks(&segs, &body_lines, &elem_of);
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
        let lines = lines_of(&work[p].pl, &work[p].pl.blocks[b]);
        let (t, j) = hyphen::join_lines(&lines, lang, &wit, &mut stats);
        texts.push(t);
        joined.push(j);
    }
    // a marker ending a block continues into the next block (column/page break)
    for k in 0..texts.len() {
        if !texts[k].ends_with(HYPHEN_MARK) {
            continue;
        }
        stats.markers += 1;
        texts[k].pop();
        let next = texts.get(k + 1).cloned().unwrap_or_default();
        let is_list_next = layout::starts_list_item(&next);
        let d = if next.trim().is_empty() || is_list_next {
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
            HBlock {
                page: p,
                text: t.clone(),
                lines: blk.segs.len(),
                size: blk.size,
                bold: blk.bold,
                list: layout::starts_list_item(&work[p].pl.segments[blk.segs[0]].text),
                struct_tag,
            }
        })
        .collect();
    let plan = headings::plan(&hblocks, body_size, &raw.outline, n_pages);
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
    for (p, w) in work.iter().enumerate() {
        let page = &raw.pages[p];
        let pg = (p + 1) as u32;
        let mut body: Vec<DocUnit> = Vec::new();
        let mut structure = false;
        let mut i = 0;
        let count = w.order.len();
        while i < count {
            let idx = k + i;
            let b = &w.pl.blocks[doc_blocks[idx].1];
            let text = texts[idx].trim().to_string();
            if let Some((lvl, src)) = plan.levels[idx] {
                structure = true;
                if !text.is_empty() {
                    let mut prov = Provenance::new(Route::Plain);
                    prov.heading_source = Some(src);
                    prov.joined_hyphen = joined[idx];
                    body.push(DocUnit {
                        page: Some(pg),
                        bbox: Some(b.bbox),
                        kind: UnitKind::Heading,
                        level: Some(lvl),
                        markdown: format!("{} {}", "#".repeat(lvl as usize), text),
                        provenance: prov,
                    });
                }
                i += 1;
                continue;
            }
            if hblocks[idx].list {
                structure = true;
                let mut md = Vec::new();
                let mut bbox = b.bbox;
                let mut j_any = false;
                while i < count && hblocks[k + i].list && plan.levels[k + i].is_none() {
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
                body.push(DocUnit {
                    page: Some(pg),
                    bbox: Some(bbox),
                    kind: UnitKind::List,
                    level: None,
                    markdown: md.join("\n"),
                    provenance: prov,
                });
                continue;
            }
            if b.bold {
                structure = true;
            }
            if !text.is_empty() {
                let mut prov = Provenance::new(Route::Plain);
                prov.joined_hyphen = joined[idx];
                body.push(DocUnit {
                    page: Some(pg),
                    bbox: Some(b.bbox),
                    kind: UnitKind::Paragraph,
                    level: None,
                    markdown: text,
                    provenance: prov,
                });
            }
            i += 1;
        }
        k += count;

        // furniture: first occurrence of each distinct line, top then bottom
        let mut top: Vec<DocUnit> = Vec::new();
        let mut bottom: Vec<DocUnit> = Vec::new();
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
                Band::Top => top.push(u),
                Band::Bottom => bottom.push(u),
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
        let image_units: Vec<DocUnit> = imgs
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
            .collect();

        let mut sig = route::signals(page, &w.pl, w.dups);
        sig.reading_order = if w.pl.blocks.is_empty() {
            "none".into()
        } else {
            w.method.as_str().into()
        };
        let rt = route::route(&sig, structure);
        let mut page_units: Vec<DocUnit> = top
            .into_iter()
            .chain(body)
            .chain(image_units)
            .chain(bottom)
            .collect();
        for u in page_units.iter_mut() {
            u.provenance.route = rt;
        }
        units.extend(page_units);
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
    };
    PdfUnitsOutput {
        units,
        pages: pages_out,
        document,
    }
}
