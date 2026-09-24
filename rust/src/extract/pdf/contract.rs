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
use crate::vision::{self, Reconciled};

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
/// Two independent transcriptions per vision region (`crate::vision`).
pub const VARIANTS: u32 = 2;

fn variant_hint(v: u32) -> String {
    format!(
        "variant {v} of {VARIANTS}: transcribe independently of the other variant, with a different model or a different sampling seed; only sentences both variants agree on become citable content"
    )
}

/// The request id without its `:v{n}` variant suffix.
pub fn base_id(id: &str) -> &str {
    match id.rsplit_once(":v") {
        Some((b, v)) if !v.is_empty() && v.chars().all(|c| c.is_ascii_digit()) => b,
        _ => id,
    }
}

/// The number after `img` or `table` in a request id (0 when absent).
fn id_index(id: &str) -> usize {
    let b = base_id(id);
    let tail = b.rsplit(':').next().unwrap_or("");
    let digits: String = tail.chars().skip_while(|c| !c.is_ascii_digit()).collect();
    digits.parse().unwrap_or(0)
}

/// Sort key: page, kind (table, page, region), region index, variant.
fn request_key(r: &PdfRequest) -> (u32, PdfRequestKind, usize, u32) {
    (r.page, r.kind, id_index(&r.id), r.variant.unwrap_or(0))
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

/// Growth above this factor (words in the grown region over words in the
/// original region) means the region was not a table region: skip it.
pub const MAX_REGION_GROWTH: f64 = 2.5;

/// The region's words as lines (by vertical centre, 3 pt), checked with the
/// TOC validator (`checks::is_toc_lines`).
fn is_toc_region(words: &[PdfWord], region: &[f64; 4]) -> bool {
    let mut ws: Vec<&PdfWord> = words.iter().filter(|w| inside(&w.bbox, region)).collect();
    ws.sort_by(|a, b| {
        let (ya, yb) = ((a.bbox[1] + a.bbox[3]) / 2.0, (b.bbox[1] + b.bbox[3]) / 2.0);
        ya.total_cmp(&yb).then(a.bbox[0].total_cmp(&b.bbox[0]))
    });
    let mut lines: Vec<(f64, Vec<&PdfWord>)> = Vec::new();
    for w in ws {
        let y = (w.bbox[1] + w.bbox[3]) / 2.0;
        match lines.last_mut() {
            Some((ly, l)) if (y - *ly).abs() <= 3.0 => l.push(w),
            _ => lines.push((y, vec![w])),
        }
    }
    let texts: Vec<String> = lines
        .into_iter()
        .map(|(_, mut l)| {
            l.sort_by(|a, b| a.bbox[0].total_cmp(&b.bbox[0]));
            l.iter()
                .map(|w| w.text.as_str())
                .collect::<Vec<_>>()
                .join(" ")
        })
        .collect();
    checks::is_toc_lines(&texts)
}

fn grow_to_units(b: &Base, p: usize, pg: u32, region: &[f64; 4]) -> Option<[f64; 4]> {
    let centre_in = |bb: &[f64; 4], r: &[f64; 4]| inside(bb, r);
    let boxes: BTreeMap<&str, [f64; 4]> = b.words[p]
        .iter()
        .map(|(w, _)| (w.id.as_str(), w.bbox))
        .collect();
    let before = boxes.values().filter(|bb| centre_in(bb, region)).count();
    let mut grown = *region;
    for (i, u) in b.out.units.iter().enumerate() {
        if u.page != Some(pg)
            || !matches!(
                u.kind,
                UnitKind::Paragraph | UnitKind::List | UnitKind::Heading | UnitKind::Table
            )
        {
            continue;
        }
        let ws = &b.unit_words[i];
        if ws.iter().any(|w| {
            boxes
                .get(w.as_str())
                .is_some_and(|bb| centre_in(bb, region))
        }) {
            for w in ws {
                if let Some(bb) = boxes.get(w.as_str()) {
                    grown = [
                        grown[0].min(bb[0]),
                        grown[1].min(bb[1]),
                        grown[2].max(bb[2]),
                        grown[3].max(bb[3]),
                    ];
                }
            }
        }
    }
    let after = boxes.values().filter(|bb| centre_in(bb, &grown)).count();
    if before == 0 || after as f64 > MAX_REGION_GROWTH * before as f64 {
        return None;
    }
    Some(grown)
}

fn requests(b: &Base, opts: &PdfOptions) -> Vec<PdfRequest> {
    let mut out = Vec::new();
    for (p, info) in b.out.pages.iter().enumerate() {
        let page = &b.raw.pages[p];
        let pg = info.page;
        let page_box = [0.0, 0.0, page.width, page.height];
        if info.route == Route::Scan {
            for v in 1..=VARIANTS {
                out.push(PdfRequest {
                    id: format!("p{pg}:page:v{v}"),
                    page: pg,
                    kind: PdfRequestKind::VisionPage,
                    prompt: "vision_page".into(),
                    bbox: page_box,
                    words: vec![],
                    chunks: vec![],
                    variant: Some(v),
                    hint: Some(variant_hint(v)),
                });
            }
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
            let mut k = 0usize;
            for region in &regions {
                // Grow the region to the whole units it intersects: a grid
                // over half a unit is a certain partial_unit. If growing more
                // than doubles the words in play, the region was mostly
                // something else: no request (the base stays).
                let Some(region) = grow_to_units(b, p, pg, region) else {
                    continue;
                };
                let words = words_in(b, p, &region);
                if words.is_empty() || is_toc_region(&words, &region) {
                    // a table of contents: no table, and no model call
                    continue;
                }
                let k_here = k;
                k += 1;
                let chunks = chunks_of(&words);
                out.push(PdfRequest {
                    id: format!("p{pg}:table{k_here}"),
                    page: pg,
                    kind: PdfRequestKind::TableStructure,
                    prompt: "table_structure".into(),
                    bbox: region.map(r2),
                    words,
                    chunks,
                    variant: None,
                    hint: None,
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
                for v in 1..=VARIANTS {
                    out.push(PdfRequest {
                        id: format!("p{pg}:img{k}:v{v}"),
                        page: pg,
                        kind: PdfRequestKind::VisionRegion,
                        prompt: "vision_region".into(),
                        bbox: region,
                        words: vec![],
                        chunks: vec![],
                        variant: Some(v),
                        hint: Some(variant_hint(v)),
                    });
                }
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
    boxes: &BTreeMap<String, WordBox>,
    runs: &[super::tables::RotRun],
) -> String {
    use super::tables::Slot;
    let n_rows = placement.len();
    let n_cols = rows
        .iter()
        .zip(placement)
        .flat_map(|(row, pl)| row.iter().zip(pl).map(|(c, &(_, col))| col + c.colspan))
        .max()
        .unwrap_or(0);
    let mut m = vec![vec![String::new(); n_cols]; n_rows];
    let mut slots = vec![vec![Slot::Covered; n_cols]; n_rows];
    for (r, row) in rows.iter().enumerate() {
        for (k, cell) in row.iter().enumerate() {
            let (pr, pc) = placement[r][k];
            let bb = cell.words.iter().filter_map(|w| boxes.get(w)).fold(
                [f64::MAX, f64::MAX, f64::MIN, f64::MIN],
                |a, b| {
                    [
                        a[0].min(b[0]),
                        a[1].min(b[1]),
                        a[2].max(b[2]),
                        a[3].max(b[3]),
                    ]
                },
            );
            let single = cell.colspan.max(1) == 1 && cell.rowspan.max(1) == 1;
            slots[pr][pc] = match (cell.words.is_empty(), single) {
                (true, true) => Slot::Empty,
                (true, false) => Slot::Covered,
                (false, true) => Slot::Text(bb),
                (false, false) => Slot::Spanned(bb),
            };
            let mut ws: Vec<(usize, String)> = cell
                .words
                .iter()
                .filter_map(|w| text.get(w.as_str()).copied())
                .map(|(i, t)| (i, checks::strip_leaders(t)))
                .filter(|(_, t)| !t.is_empty())
                .collect();
            ws.sort();
            m[pr][pc] = escape_cell(
                &ws.iter()
                    .map(|(_, t)| t.as_str())
                    .collect::<Vec<_>>()
                    .join(" "),
            );
        }
    }
    let mut rot = vec![vec![String::new(); n_cols]; n_rows];
    super::tables::fill_rotated(runs, &slots, &mut rot);
    for (r, row) in rot.into_iter().enumerate() {
        for (c, t) in row.into_iter().enumerate() {
            if !t.is_empty() && m[r][c].is_empty() {
                m[r][c] = escape_cell(&t);
            }
        }
    }
    let line = |cells: &[String]| format!("| {} |", cells.join(" | "));
    let mut out = vec![line(&m[0]), line(&vec!["---".to_string(); n_cols])];
    out.extend(m[1..].iter().map(|r| line(r)));
    out.join("\n")
}

/// The request's phrase chunks: every chunk ALL of whose words are listed.
fn chunks_of(words: &[PdfWord]) -> Vec<PdfChunk> {
    let mut by: BTreeMap<&str, Vec<&PdfWord>> = BTreeMap::new();
    let mut order: Vec<&str> = Vec::new();
    for w in words {
        if let Some(c) = w.chunk.as_deref() {
            if !by.contains_key(c) {
                order.push(c);
            }
            by.entry(c).or_default().push(w);
        }
    }
    order
        .into_iter()
        .map(|c| {
            let ws = &by[c];
            let mut bb = [f64::MAX, f64::MAX, f64::MIN, f64::MIN];
            for w in ws {
                bb = [
                    bb[0].min(w.bbox[0]),
                    bb[1].min(w.bbox[1]),
                    bb[2].max(w.bbox[2]),
                    bb[3].max(w.bbox[3]),
                ];
            }
            PdfChunk {
                id: c.to_string(),
                text: ws
                    .iter()
                    .map(|w| w.text.as_str())
                    .collect::<Vec<_>>()
                    .join(" "),
                bbox: bb,
                words: ws.iter().map(|w| w.id.clone()).collect(),
            }
        })
        .collect()
}

/// A cell's IDs with every chunk ID replaced by its words (in order).
fn expand(ids: &[String], chunks: &BTreeMap<&str, &PdfChunk>) -> Vec<String> {
    ids.iter()
        .flat_map(|id| match chunks.get(id.as_str()) {
            Some(c) => c.words.clone(),
            None => vec![id.clone()],
        })
        .collect()
}

fn to_cells(grid: &PdfGrid, req: &PdfRequest) -> Vec<Vec<GridCell>> {
    let chunks: BTreeMap<&str, &PdfChunk> = req.chunks.iter().map(|c| (c.id.as_str(), c)).collect();
    grid.rows
        .iter()
        .map(|row| {
            row.iter()
                .map(|c| match c {
                    PdfCell::Words(w) => GridCell {
                        words: expand(w, &chunks),
                        colspan: 1,
                        rowspan: 1,
                    },
                    PdfCell::Spanned {
                        words,
                        colspan,
                        rowspan,
                    } => GridCell {
                        words: expand(words, &chunks),
                        colspan: colspan.unwrap_or(1) as usize,
                        rowspan: rowspan.unwrap_or(1) as usize,
                    },
                })
                .collect()
        })
        .collect()
}

struct Fill {
    unit: usize,
    markdown: String,
    disputed: bool,
    failed: Option<Failure>,
}

struct Edit {
    /// Unit indices to remove.
    remove: BTreeSet<usize>,
    /// (insert before this original index, units + their words)
    insert: Vec<(usize, DocUnit, Vec<String>)>,
    /// In-place vision fills.
    fill: Vec<Fill>,
    /// Kept deterministic tables a disagreeing model grid made uncertain.
    uncertain: Vec<usize>,
    /// Units that get `model_verdict = "no_table"`.
    verdict: Vec<usize>,
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
        // The model's verdict "no table here": informative, not a failure.
        return Ok(Edit {
            remove: BTreeSet::new(),
            insert: vec![],
            fill: vec![],
            uncertain: vec![],
            verdict: region_units(units, unit_words, req, &BTreeSet::new()),
        });
    }
    let p = (req.page - 1) as usize;
    let boxes: BTreeMap<String, WordBox> =
        req.words.iter().map(|w| (w.id.clone(), w.bbox)).collect();
    let order: BTreeMap<&str, (usize, &str)> = b.words[p]
        .iter()
        .enumerate()
        .map(|(i, (w, _))| (w.id.as_str(), (i, w.text.as_str())))
        .collect();
    // words with leader runs are filler for the band test (they run across);
    // pure leaders are also exempt from coverage and partial-unit accounting
    let leaders: BTreeSet<&str> = req
        .words
        .iter()
        .filter(|w| checks::has_leader(&w.text))
        .map(|w| w.id.as_str())
        .collect();
    let pure_leaders: BTreeSet<&str> = req
        .words
        .iter()
        .filter(|w| checks::is_leader(&w.text))
        .map(|w| w.id.as_str())
        .collect();
    let runs = super::tables::rotated_runs(&b.raw.pages[p]);
    let mut all: BTreeSet<String> = BTreeSet::new();
    let mut grids = Vec::new();
    for g in tables {
        let cells = to_cells(g, req);
        // leaders are filler: outside the column-band test (they run across)
        let gate_cells: Vec<Vec<GridCell>> = cells
            .iter()
            .map(|r| {
                r.iter()
                    .map(|c| GridCell {
                        words: c
                            .words
                            .iter()
                            .filter(|w| !leaders.contains(w.as_str()))
                            .cloned()
                            .collect(),
                        colspan: c.colspan,
                        rowspan: c.rowspan,
                    })
                    .collect()
            })
            .collect();
        for w in cells.iter().flatten().flat_map(|c| c.words.iter()) {
            if !boxes.contains_key(w) {
                return Err(Failure::UnknownWord);
            }
        }
        let placement = checks::geometry_gate(&gate_cells, &boxes)?;
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
        if req.words.iter().any(|w| {
            !w.marker
                && !pure_leaders.contains(w.id.as_str())
                && !ids.contains(&w.id)
                && inside(&w.bbox, &gb)
        }) {
            return Err(Failure::GridCoverage);
        }
        grids.push((cells, placement, ids));
    }
    let page_units = on_page(units, req.page);
    let markers: BTreeSet<&str> = b.words[p]
        .iter()
        .filter(|(w, _)| w.marker)
        .map(|(w, _)| w.id.as_str())
        .collect();
    let mut touched: Vec<Vec<usize>> = vec![Vec::new(); grids.len()];
    for &i in &page_units {
        let w: BTreeSet<&String> = unit_words[i].iter().collect();
        let hit = w.iter().filter(|x| all.contains(**x)).count();
        if hit == 0 {
            continue;
        }
        // A grid may take a unit minus its list-marker glyphs (they are not
        // content and are not emitted); any other word left out splits it.
        if w.iter().any(|x| {
            !all.contains(*x)
                && !markers.contains(x.as_str())
                && !checks::is_leader(order.get(x.as_str()).map(|t| t.1).unwrap_or(""))
        }) {
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
        let md = table_markdown(&cells, &placement, &order, &boxes, &runs);
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
        verdict: vec![],
    })
}

/// One vision variant's checks: markdown present, output guards, and (for a
/// page with an OCR/garbled layer) the text checks against that layer.
fn validate_vision(
    units: &[DocUnit],
    req: &PdfRequest,
    resp: &PdfResponse,
    lang: Option<&str>,
) -> Result<(String, bool), Failure> {
    let Some(md) = resp.markdown.as_deref() else {
        return Err(Failure::Malformed);
    };
    let description = match resp.mode.as_deref() {
        None | Some("transcription") => false,
        // a page with no text layer is text: it is transcribed, not described
        Some("description") if req.kind == PdfRequestKind::VisionRegion => true,
        _ => return Err(Failure::Malformed),
    };
    checks::guard_text(md, resp.finish_reason.as_deref())?;
    if description {
        return Ok((md.trim().to_string(), true));
    }
    if req.kind == PdfRequestKind::VisionPage {
        let reference = page_reference(units, req.page);
        if checks::tokens(&reference).len() >= MIN_REFERENCE_TOKENS {
            checks::check_text(md, &reference, lang)?;
        }
    }
    Ok((md.trim().to_string(), false))
}

fn page_text_units(units: &[DocUnit], pg: u32) -> Vec<usize> {
    on_page(units, pg)
        .into_iter()
        .filter(|&i| !matches!(units[i].kind, UnitKind::Furniture | UnitKind::Image))
        .collect()
}

fn page_reference(units: &[DocUnit], pg: u32) -> String {
    page_text_units(units, pg)
        .iter()
        .map(|&i| units[i].markdown.as_str())
        .collect::<Vec<_>>()
        .join("\n")
}

/// Place a reconciled transcription: a page replaces the page's text units
/// and lands in its largest image unit (or a new paragraph); a region fills
/// its image unit. `failed` records a variant that failed its checks.
fn vision_edit(
    units: &[DocUnit],
    req: &PdfRequest,
    rec: Reconciled,
    failed: Option<Failure>,
) -> Result<Edit, Failure> {
    let fill = |i: usize| Fill {
        unit: i,
        markdown: rec.markdown.clone(),
        disputed: rec.disputed,
        failed,
    };
    if req.kind == PdfRequestKind::VisionRegion {
        let i = region_unit(units, req).ok_or(Failure::Malformed)?;
        return Ok(Edit {
            remove: BTreeSet::new(),
            insert: vec![],
            fill: vec![fill(i)],
            uncertain: vec![],
            verdict: vec![],
        });
    }
    let page_units = on_page(units, req.page);
    let text_units = page_text_units(units, req.page);
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
            fill: vec![fill(i)],
            uncertain: vec![],
            verdict: vec![],
        }),
        None => {
            let at = text_units
                .first()
                .or(page_units.first())
                .copied()
                .unwrap_or(units.len());
            let mut prov = Provenance::new(Route::Scan);
            prov.vision_transcribed = true;
            prov.vision_disputed = rec.disputed;
            prov.failed_check = failed.map(|f| f.as_str().to_string());
            let unit = DocUnit {
                page: Some(req.page),
                bbox: Some(req.bbox),
                kind: UnitKind::Paragraph,
                level: None,
                markdown: rec.markdown,
                provenance: prov,
            };
            Ok(Edit {
                remove,
                insert: vec![(at, unit, vec![])],
                fill: vec![],
                uncertain: vec![],
                verdict: vec![],
            })
        }
    }
}

fn region_unit(units: &[DocUnit], req: &PdfRequest) -> Option<usize> {
    if !base_id(&req.id).contains(":img") {
        return None;
    }
    let k = id_index(&req.id);
    on_page(units, req.page)
        .into_iter()
        .filter(|&i| units[i].kind == UnitKind::Image)
        .nth(k)
}

fn commit(units: &mut Vec<DocUnit>, unit_words: &mut Vec<Vec<String>>, edit: Edit) {
    for &i in &edit.verdict {
        units[i].provenance.model_verdict = Some("no_table".into());
    }
    for &i in &edit.uncertain {
        units[i].provenance.table_uncertain = true;
    }
    for f in edit.fill {
        let u = &mut units[f.unit];
        u.markdown = f.markdown;
        u.provenance.vision_transcribed = true;
        u.provenance.vision_disputed = f.disputed;
        if let Some(fail) = f.failed {
            u.provenance.failed_check = Some(fail.as_str().to_string());
        }
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

/// The units of a table request's REGION: a word whose centre lies inside
/// the request's region box (not the 12 pt listing margin), plus any unit the
/// response's grid referenced. Prose around the table is not touched.
fn region_units(
    units: &[DocUnit],
    unit_words: &[Vec<String>],
    req: &PdfRequest,
    referenced: &BTreeSet<String>,
) -> Vec<usize> {
    let in_region: BTreeSet<&str> = req
        .words
        .iter()
        .filter(|w| inside(&w.bbox, &req.bbox))
        .map(|w| w.id.as_str())
        .collect();
    (0..units.len())
        .filter(|&i| {
            units[i].page == Some(req.page)
                && unit_words[i]
                    .iter()
                    .any(|w| in_region.contains(w.as_str()) || referenced.contains(w))
        })
        .collect()
}

/// Record a failed response: on a table request's region units, or on the
/// vision request's image unit / page text units.
fn mark_failed(
    units: &mut [DocUnit],
    unit_words: &[Vec<String>],
    req: &PdfRequest,
    resp: Option<&PdfResponse>,
    f: Failure,
) {
    let referenced: BTreeSet<String> = resp
        .and_then(|r| r.tables.as_ref())
        .into_iter()
        .flatten()
        .flat_map(|g| to_cells(g, req).into_iter().flatten().flat_map(|c| c.words))
        .collect();
    let targets: Vec<usize> = match req.kind {
        PdfRequestKind::VisionRegion => region_unit(units, req).into_iter().collect(),
        PdfRequestKind::TableStructure => region_units(units, unit_words, req, &referenced),
        PdfRequestKind::VisionPage => on_page(units, req.page)
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
    let mut paired: BTreeSet<String> = BTreeSet::new();
    for req in &reqs {
        if req.kind != PdfRequestKind::TableStructure {
            // Vision: handle both variants of this region together, once.
            let base = base_id(&req.id).to_string();
            if !paired.insert(base.clone()) {
                continue;
            }
            let variants: Vec<&PdfRequest> =
                reqs.iter().filter(|r| base_id(&r.id) == base).collect();
            let mut texts: Vec<Option<String>> = vec![None; VARIANTS as usize];
            let mut descriptions: Vec<Option<String>> = vec![None; VARIANTS as usize];
            let mut first_fail: Option<Failure> = None;
            let mut any = false;
            for vr in &variants {
                let Some(rs) = by_id.get(vr.id.as_str()) else {
                    continue;
                };
                any = true;
                let res = if rs.len() > 1 {
                    Err(Failure::DuplicateResponse)
                } else {
                    validate_vision(&units, vr, rs[0], lang)
                };
                match res {
                    Ok((t, described)) => {
                        let slot = vr.variant.unwrap_or(1).clamp(1, VARIANTS) as usize - 1;
                        if described {
                            descriptions[slot] = Some(t);
                        } else {
                            texts[slot] = Some(t);
                        }
                        applied += 1;
                    }
                    Err(f) => {
                        rejected += 1;
                        first_fail.get_or_insert(f);
                    }
                }
            }
            if !any {
                continue;
            }
            // Only descriptions: an image_description unit (never citable,
            // no dual agreement: it is not evidence). Any transcription:
            // transcriptions alone go through dual agreement.
            if texts.iter().all(|t| t.is_none()) {
                if let Some(desc) = descriptions.iter().flatten().next() {
                    if let Some(i) = region_unit(&units, req) {
                        let u = &mut units[i];
                        u.kind = UnitKind::ImageDescription;
                        u.markdown = vision::description_block(desc);
                        u.provenance.vision_transcribed = true;
                        u.provenance.failed_check = first_fail.map(|f| f.as_str().to_string());
                    }
                    continue;
                }
            }
            match vision::reconcile(texts[0].as_deref(), texts[1].as_deref(), lang) {
                Some(rec) => match vision_edit(&units, req, rec, first_fail) {
                    Ok(edit) => commit(&mut units, &mut unit_words, edit),
                    Err(f) => mark_failed(&mut units, &unit_words, req, None, f),
                },
                None => mark_failed(
                    &mut units,
                    &unit_words,
                    req,
                    None,
                    first_fail.unwrap_or(Failure::Malformed),
                ),
            }
            continue;
        }
        let Some(rs) = by_id.get(req.id.as_str()) else {
            continue;
        };
        let result = if rs.len() > 1 {
            Err(Failure::DuplicateResponse)
        } else {
            apply_table(&b, &units, &unit_words, req, rs[0])
        };
        match result {
            Ok(edit) => {
                commit(&mut units, &mut unit_words, edit);
                applied += 1;
            }
            Err(f) => {
                mark_failed(&mut units, &unit_words, req, rs.first().copied(), f);
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
