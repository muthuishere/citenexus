//! The structure-not-text contract (ADR-0017 decisions 4, 5, 9, 10).
//!
//! `pdf_prepare(bytes, opts)` → the base output plus REQUESTS:
//! - `table_structure` for every `table`-routed page with a sound text layer,
//!   listing the page's non-furniture words with stable IDs (`p{page}w{n}`);
//! - `vision_page` for every `scan`-routed page;
//! - `vision_region` for every image unit on another page that has fewer than
//!   `REGION_MAX_WORDS` text-layer words inside it (where the text layer already
//!   covers a region, the text layer wins and no request is made).
//!
//! `pdf_assemble(bytes, opts, responses)` re-parses the PDF (no state between
//! calls), rebuilds the same base output, and applies each response that passes
//! every check, in request order:
//! - **table** — a grid of word IDs (model text on a text-layer page is never
//!   used: `model_text_on_text_layer`). `checks::geometry_gate` proves the grid
//!   is physically possible; every text-layer word inside a grid's box must be
//!   in that grid (`grid_coverage`: a dropped cell is lost text); then every
//!   base unit on the page is either fully
//!   inside the grid or untouched (`partial_unit` otherwise — no text is ever
//!   lost or split). The touched units are replaced, at the first one's place,
//!   by one `table` unit per grid whose cells are filled from pdfium's own
//!   characters (`table_source = model_grid`).
//! - **vision_page** — markdown, guarded (`checks::guard_text`); when the page
//!   carries an OCR/garbled text layer of ≥ `MIN_REFERENCE_TOKENS` tokens, the
//!   markdown must also pass `checks::check_text` against it (digit bag, values,
//!   coverage/novelty; furniture exempt). It replaces the page's text units and
//!   lands in the page's image unit, `vision_transcribed = true`.
//! - **vision_region** — markdown, guarded; fills that image unit,
//!   `vision_transcribed = true`. It never merges into or overrides text.
//!
//! Any failure keeps the base units and records the check in
//! `provenance.failed_check` (on the page's text units for a page request, on
//! the image unit for a region request). A request with no response is simply
//! base output. `pdf_units` is exactly `pdf_assemble` with no responses.

use std::collections::{BTreeMap, BTreeSet};

use super::build::{self, Staged};
use super::headings;
use super::raw::{self, r2, RawDoc};
use crate::checks::{self, Failure, GridCell, WordBox};
use crate::units::*;

/// A region with this many text-layer words or more is the text layer's.
pub const REGION_MAX_WORDS: usize = 5;
/// Below this many reference tokens a scan's text layer is too thin to check
/// a transcription against; guards only.
pub const MIN_REFERENCE_TOKENS: usize = 20;

struct Base {
    raw: RawDoc,
    out: PdfUnitsOutput,
    unit_words: Vec<Vec<String>>,
    /// Per page: words (with the furniture flag), in ID order.
    words: Vec<Vec<(PdfWord, bool)>>,
    /// Per page: (accepted table boxes, uncertain table regions).
    regions: Vec<build::TableRegions>,
}

fn base(bytes: &[u8], opts: &PdfOptions) -> Result<Base, String> {
    let raw = raw::read(bytes)?;
    let st: Staged = build::stage(&raw, opts);
    let words = (0..raw.pages.len())
        .map(|p| st.page_words(&raw, p))
        .collect();
    let regions = st.table_regions();
    let plan = headings::plan(st.hblocks(), st.body_size, &raw.outline, raw.pages.len());
    let (out, unit_words) = build::emit(&raw, opts, st, plan);
    Ok(Base {
        raw,
        out,
        unit_words,
        words,
        regions,
    })
}

fn inside(b: &[f64; 4], region: &[f64; 4]) -> bool {
    let (cx, cy) = ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0);
    cx >= region[0] && cx <= region[2] && cy >= region[1] && cy <= region[3]
}

/// Sort key: page, then kind (table, page, region), then region index.
fn request_key(r: &PdfRequest) -> (u32, PdfRequestKind, usize) {
    let idx =
        r.id.rsplit("img")
            .next()
            .and_then(|n| n.parse().ok())
            .unwrap_or(0);
    (r.page, r.kind, idx)
}

/// Words within this margin (points) of a table region are listed too, so a
/// grid may include a border word the region box clipped.
pub const REGION_MARGIN: f64 = 12.0;

fn words_in(b: &Base, p: usize, region: &[f64; 4]) -> Vec<PdfWord> {
    let r = [
        region[0] - REGION_MARGIN,
        region[1] - REGION_MARGIN,
        region[2] + REGION_MARGIN,
        region[3] + REGION_MARGIN,
    ];
    b.words[p]
        .iter()
        .filter(|(w, furn)| !furn && inside(&w.bbox, &r))
        .map(|(w, _)| w.clone())
        .collect()
}

fn requests(b: &Base, opts: &PdfOptions) -> Vec<PdfRequest> {
    let mut out = Vec::new();
    for (p, info) in b.out.pages.iter().enumerate() {
        let page = &b.raw.pages[p];
        let pg = info.page;
        let page_box = [0.0, 0.0, page.width, page.height];
        if info.route == Route::Scan {
            out.push(PdfRequest {
                id: format!("p{pg}:page"),
                page: pg,
                kind: PdfRequestKind::VisionPage,
                prompt: "vision_page".into(),
                bbox: page_box,
                words: vec![],
            });
            continue;
        }
        // Table regions: every uncertain candidate, and every accepted table
        // when the host asked for model review (`model_tables`). A page the
        // router calls `table` where the deterministic path found no
        // candidate asks nothing: its evidence was a box or a rejected
        // (prose / TOC / key-value) layout, and a page-wide request costs
        // ~260 words for no table (measured on Lex5).
        if info.signals.text_sound {
            let (accepted, uncertain) = &b.regions[p];
            let mut regions: Vec<[f64; 4]> = uncertain.clone();
            if opts.model_tables {
                regions.extend(accepted.iter().copied());
            }
            regions.sort_by(|a, c| a[1].total_cmp(&c[1]).then(a[0].total_cmp(&c[0])));
            for (k, region) in regions.iter().enumerate() {
                let words = words_in(b, p, region);
                if words.is_empty() {
                    continue;
                }
                out.push(PdfRequest {
                    id: format!("p{pg}:table{k}"),
                    page: pg,
                    kind: PdfRequestKind::TableStructure,
                    prompt: "table_structure".into(),
                    bbox: region.map(r2),
                    words,
                });
            }
        }
        let images = b
            .out
            .units
            .iter()
            .filter(|u| u.page == Some(pg) && u.kind == UnitKind::Image);
        for (k, u) in images.enumerate() {
            let region = u.bbox.unwrap_or(page_box);
            let n = b.words[p]
                .iter()
                .filter(|(w, _)| inside(&w.bbox, &region))
                .count();
            if n < REGION_MAX_WORDS {
                out.push(PdfRequest {
                    id: format!("p{pg}:img{k}"),
                    page: pg,
                    kind: PdfRequestKind::VisionRegion,
                    prompt: "vision_region".into(),
                    bbox: region,
                    words: vec![],
                });
            }
        }
    }
    out.sort_by_key(request_key);
    out
}

/// `pdf_prepare`: the base output plus the model requests.
pub fn pdf_prepare(bytes: &[u8], opts: &PdfOptions) -> Result<PdfPrepared, String> {
    let b = base(bytes, opts)?;
    let requests = requests(&b, opts);
    Ok(PdfPrepared {
        units: b.out.units,
        pages: b.out.pages,
        document: b.out.document,
        requests,
    })
}

/// `pdf_units`: the base output — `pdf_assemble` with no responses.
pub fn pdf_units(bytes: &[u8], opts: &PdfOptions) -> Result<PdfUnitsOutput, String> {
    pdf_assemble(bytes, opts, &[])
}

/// Units on a page, as indices into the unit vector.
fn on_page(units: &[DocUnit], pg: u32) -> Vec<usize> {
    (0..units.len())
        .filter(|&i| units[i].page == Some(pg))
        .collect()
}

fn escape_cell(t: &str) -> String {
    t.replace('|', "\\|")
}

fn table_markdown(
    rows: &[Vec<GridCell>],
    placement: &checks::Placement,
    text: &BTreeMap<&str, (usize, &str)>,
) -> String {
    let n_rows = placement.len();
    let n_cols = rows
        .iter()
        .zip(placement)
        .flat_map(|(row, pl)| row.iter().zip(pl).map(|(c, &(_, col))| col + c.colspan))
        .max()
        .unwrap_or(0);
    let mut m = vec![vec![String::new(); n_cols]; n_rows];
    for (r, row) in rows.iter().enumerate() {
        for (k, cell) in row.iter().enumerate() {
            let (pr, pc) = placement[r][k];
            let mut ws: Vec<(usize, &str)> = cell
                .words
                .iter()
                .filter_map(|w| text.get(w.as_str()).copied())
                .collect();
            ws.sort();
            m[pr][pc] = escape_cell(&ws.iter().map(|(_, t)| *t).collect::<Vec<_>>().join(" "));
        }
    }
    let line = |cells: &[String]| format!("| {} |", cells.join(" | "));
    let mut out = vec![line(&m[0]), line(&vec!["---".to_string(); n_cols])];
    out.extend(m[1..].iter().map(|r| line(r)));
    out.join("\n")
}

fn to_cells(grid: &PdfGrid) -> Vec<Vec<GridCell>> {
    grid.rows
        .iter()
        .map(|row| {
            row.iter()
                .map(|c| match c {
                    PdfCell::Words(w) => GridCell {
                        words: w.clone(),
                        colspan: 1,
                        rowspan: 1,
                    },
                    PdfCell::Spanned {
                        words,
                        colspan,
                        rowspan,
                    } => GridCell {
                        words: words.clone(),
                        colspan: colspan.unwrap_or(1) as usize,
                        rowspan: rowspan.unwrap_or(1) as usize,
                    },
                })
                .collect()
        })
        .collect()
}

struct Edit {
    /// Unit indices to remove.
    remove: BTreeSet<usize>,
    /// (insert before this original index, units + their words)
    insert: Vec<(usize, DocUnit, Vec<String>)>,
    /// In-place markdown fills: (unit index, markdown).
    fill: Vec<(usize, String)>,
    /// Kept deterministic tables a disagreeing model grid made uncertain.
    uncertain: Vec<usize>,
}

fn apply_table(
    b: &Base,
    units: &[DocUnit],
    unit_words: &[Vec<String>],
    req: &PdfRequest,
    resp: &PdfResponse,
) -> Result<Edit, Failure> {
    let Some(tables) = resp.tables.as_ref() else {
        return Err(if resp.markdown.is_some() {
            Failure::ModelTextOnTextLayer
        } else {
            Failure::Malformed
        });
    };
    checks::guard_finish(resp.finish_reason.as_deref())?;
    if tables.is_empty() {
        return Err(Failure::EmptyGrid);
    }
    let p = (req.page - 1) as usize;
    let boxes: BTreeMap<String, WordBox> =
        req.words.iter().map(|w| (w.id.clone(), w.bbox)).collect();
    let order: BTreeMap<&str, (usize, &str)> = b.words[p]
        .iter()
        .enumerate()
        .map(|(i, (w, _))| (w.id.as_str(), (i, w.text.as_str())))
        .collect();
    let mut all: BTreeSet<String> = BTreeSet::new();
    let mut grids = Vec::new();
    for g in tables {
        let cells = to_cells(g);
        let placement = checks::geometry_gate(&cells, &boxes)?;
        let ids: BTreeSet<String> = cells
            .iter()
            .flatten()
            .flat_map(|c| c.words.iter().cloned())
            .collect();
        if ids.iter().any(|w| all.contains(w)) {
            return Err(Failure::DuplicateWord);
        }
        all.extend(ids.iter().cloned());
        // Every text-layer word inside the grid's own box must be in the grid:
        // a dropped cell is lost text, not a smaller table.
        let mut gb = [f64::MAX, f64::MAX, f64::MIN, f64::MIN];
        for id in &ids {
            let w = boxes[id];
            gb = [
                gb[0].min(w[0]),
                gb[1].min(w[1]),
                gb[2].max(w[2]),
                gb[3].max(w[3]),
            ];
        }
        if req
            .words
            .iter()
            .any(|w| !ids.contains(&w.id) && inside(&w.bbox, &gb))
        {
            return Err(Failure::GridCoverage);
        }
        grids.push((cells, placement, ids));
    }
    let page_units = on_page(units, req.page);
    let mut touched: Vec<Vec<usize>> = vec![Vec::new(); grids.len()];
    for &i in &page_units {
        let w: BTreeSet<&String> = unit_words[i].iter().collect();
        let hit = w.iter().filter(|x| all.contains(**x)).count();
        if hit == 0 {
            continue;
        }
        if hit != w.len() {
            return Err(Failure::PartialUnit);
        }
        for (g, (_, _, ids)) in grids.iter().enumerate() {
            if w.iter().any(|x| ids.contains(*x)) {
                touched[g].push(i);
            }
        }
    }
    let route = b.out.pages[p].route;
    let end = page_units.last().map(|&i| i + 1).unwrap_or(units.len());
    let mut insert = Vec::new();
    let mut remove = BTreeSet::new();
    let mut marks = Vec::new();
    for (g, (cells, placement, ids)) in grids.into_iter().enumerate() {
        let md = table_markdown(&cells, &placement, &order);
        // A deterministic table under this grid: the two compete (GriTS +
        // the position check both already passed), never "more rows wins".
        let rivals: Vec<usize> = touched[g]
            .iter()
            .copied()
            .filter(|&i| {
                units[i].kind == UnitKind::Table
                    && units[i].provenance.table_source != Some(TableSource::ModelGrid)
            })
            .collect();
        let mut uncertain = false;
        let mut keep_det = false;
        for &d in &rivals {
            let src = units[d]
                .provenance
                .table_source
                .unwrap_or(TableSource::Tracks);
            let (det_wins, disagree) = super::tables::choose(
                src,
                &checks::pipe_grid(&units[d].markdown),
                TableSource::ModelGrid,
                &checks::pipe_grid(&md),
            );
            uncertain |= disagree;
            if det_wins {
                keep_det = true;
                if disagree {
                    marks.push(d);
                }
            }
        }
        if keep_det {
            continue; // the deterministic grid stays; the model grid is dropped
        }
        remove.extend(touched[g].iter().copied());
        let mut bb = [f64::MAX, f64::MAX, f64::MIN, f64::MIN];
        for id in &ids {
            let w = boxes[id];
            bb = [
                bb[0].min(w[0]),
                bb[1].min(w[1]),
                bb[2].max(w[2]),
                bb[3].max(w[3]),
            ];
        }
        let mut prov = Provenance::new(route);
        prov.table_source = Some(TableSource::ModelGrid);
        prov.table_uncertain = uncertain;
        let unit = DocUnit {
            page: Some(req.page),
            bbox: Some(bb),
            kind: UnitKind::Table,
            level: None,
            markdown: md,
            provenance: prov,
        };
        let mut words: Vec<String> = ids.into_iter().collect();
        words.sort_by_key(|w| order.get(w.as_str()).map(|x| x.0));
        insert.push((touched[g].first().copied().unwrap_or(end), unit, words));
    }
    Ok(Edit {
        remove,
        insert,
        fill: vec![],
        uncertain: marks,
    })
}

fn apply_vision_page(
    units: &[DocUnit],
    req: &PdfRequest,
    resp: &PdfResponse,
    lang: Option<&str>,
) -> Result<Edit, Failure> {
    let Some(md) = resp.markdown.as_deref() else {
        return Err(Failure::Malformed);
    };
    checks::guard_text(md, resp.finish_reason.as_deref())?;
    let page_units = on_page(units, req.page);
    let text_units: Vec<usize> = page_units
        .iter()
        .copied()
        .filter(|&i| !matches!(units[i].kind, UnitKind::Furniture | UnitKind::Image))
        .collect();
    let reference: String = text_units
        .iter()
        .map(|&i| units[i].markdown.as_str())
        .collect::<Vec<_>>()
        .join("\n");
    if checks::tokens(&reference).len() >= MIN_REFERENCE_TOKENS {
        checks::check_text(md, &reference, lang)?;
    }
    let md = md.trim().to_string();
    let image = page_units
        .iter()
        .copied()
        .filter(|&i| units[i].kind == UnitKind::Image)
        .max_by(|&a, &c| {
            let area = |u: &DocUnit| u.bbox.map(|b| (b[2] - b[0]) * (b[3] - b[1])).unwrap_or(0.0);
            area(&units[a]).total_cmp(&area(&units[c])).then(c.cmp(&a))
        });
    let remove: BTreeSet<usize> = text_units.iter().copied().collect();
    match image {
        Some(i) => Ok(Edit {
            remove,
            insert: vec![],
            fill: vec![(i, md)],
            uncertain: vec![],
        }),
        None => {
            let at = text_units
                .first()
                .or(page_units.first())
                .copied()
                .unwrap_or(units.len());
            let mut prov = Provenance::new(Route::Scan);
            prov.vision_transcribed = true;
            let unit = DocUnit {
                page: Some(req.page),
                bbox: Some(req.bbox),
                kind: UnitKind::Paragraph,
                level: None,
                markdown: md,
                provenance: prov,
            };
            Ok(Edit {
                remove,
                insert: vec![(at, unit, vec![])],
                fill: vec![],
                uncertain: vec![],
            })
        }
    }
}

fn region_unit(units: &[DocUnit], req: &PdfRequest) -> Option<usize> {
    let k: usize = req.id.rsplit("img").next()?.parse().ok()?;
    on_page(units, req.page)
        .into_iter()
        .filter(|&i| units[i].kind == UnitKind::Image)
        .nth(k)
}

fn apply_vision_region(
    units: &[DocUnit],
    req: &PdfRequest,
    resp: &PdfResponse,
) -> Result<Edit, Failure> {
    let Some(md) = resp.markdown.as_deref() else {
        return Err(Failure::Malformed);
    };
    checks::guard_text(md, resp.finish_reason.as_deref())?;
    let i = region_unit(units, req).ok_or(Failure::Malformed)?;
    Ok(Edit {
        remove: BTreeSet::new(),
        insert: vec![],
        fill: vec![(i, md.trim().to_string())],
        uncertain: vec![],
    })
}

fn commit(units: &mut Vec<DocUnit>, unit_words: &mut Vec<Vec<String>>, edit: Edit) {
    for &i in &edit.uncertain {
        units[i].provenance.table_uncertain = true;
    }
    for (i, md) in edit.fill {
        units[i].markdown = md;
        units[i].provenance.vision_transcribed = true;
    }
    let mut ins = edit.insert;
    ins.sort_by_key(|x| x.0);
    let mut out_u = Vec::with_capacity(units.len());
    let mut out_w = Vec::with_capacity(units.len());
    let mut it = ins.into_iter().peekable();
    for (i, (u, w)) in std::mem::take(units)
        .into_iter()
        .zip(std::mem::take(unit_words))
        .enumerate()
    {
        while it.peek().is_some_and(|x| x.0 == i) {
            let (_, nu, nw) = it.next().unwrap();
            out_u.push(nu);
            out_w.push(nw);
        }
        if !edit.remove.contains(&i) {
            out_u.push(u);
            out_w.push(w);
        }
    }
    for (_, nu, nw) in it {
        out_u.push(nu);
        out_w.push(nw);
    }
    *units = out_u;
    *unit_words = out_w;
}

fn mark_failed(units: &mut [DocUnit], unit_words: &[Vec<String>], req: &PdfRequest, f: Failure) {
    let req_words: BTreeSet<&str> = req.words.iter().map(|w| w.id.as_str()).collect();
    let targets: Vec<usize> = match req.kind {
        PdfRequestKind::VisionRegion => region_unit(units, req).into_iter().collect(),
        // a table request: exactly the units whose words it listed
        PdfRequestKind::TableStructure => (0..units.len())
            .filter(|&i| unit_words[i].iter().any(|w| req_words.contains(w.as_str())))
            .collect(),
        _ => on_page(units, req.page)
            .into_iter()
            .filter(|&i| !matches!(units[i].kind, UnitKind::Furniture | UnitKind::Image))
            .collect(),
    };
    for i in targets {
        if units[i].provenance.failed_check.is_none() {
            units[i].provenance.failed_check = Some(f.as_str().to_string());
        }
    }
}

/// `pdf_assemble`: base output with every response that passes its checks.
pub fn pdf_assemble(
    bytes: &[u8],
    opts: &PdfOptions,
    responses: &[PdfResponse],
) -> Result<PdfUnitsOutput, String> {
    let b = base(bytes, opts)?;
    if responses.is_empty() {
        return Ok(b.out);
    }
    let reqs = requests(&b, opts);
    let mut by_id: BTreeMap<&str, Vec<&PdfResponse>> = BTreeMap::new();
    for r in responses {
        by_id.entry(r.request_id.as_str()).or_default().push(r);
    }
    let lang = opts.language.as_deref();
    let mut units = b.out.units.clone();
    let mut unit_words = b.unit_words.clone();
    let (mut applied, mut rejected) = (0u32, 0u32);
    for req in &reqs {
        let Some(rs) = by_id.get(req.id.as_str()) else {
            continue;
        };
        let result = if rs.len() > 1 {
            Err(Failure::DuplicateResponse)
        } else {
            match req.kind {
                PdfRequestKind::TableStructure => apply_table(&b, &units, &unit_words, req, rs[0]),
                PdfRequestKind::VisionPage => apply_vision_page(&units, req, rs[0], lang),
                PdfRequestKind::VisionRegion => apply_vision_region(&units, req, rs[0]),
            }
        };
        match result {
            Ok(edit) => {
                commit(&mut units, &mut unit_words, edit);
                applied += 1;
            }
            Err(f) => {
                mark_failed(&mut units, &unit_words, req, f);
                rejected += 1;
            }
        }
    }
    let mut out = b.out;
    out.units = units;
    out.document.responses_applied = applied;
    out.document.responses_rejected = rejected;
    Ok(out)
}
