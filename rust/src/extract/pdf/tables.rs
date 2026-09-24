//! Deterministic tables (ADR-0017 decision 3; research §8 #8, #11).
//!
//! Sources, in order:
//! 1. **Struct tree** — `Table` → `TR` → `TH`/`TD` (with `RowSpan`/`ColSpan`),
//!    words mapped to cells by marked-content ID. Wins outright.
//! 2. **Ruled grid** — thin path objects AND the edges of rectangles (cell
//!    borders and row shading are often drawn as thin filled rects), snapped
//!    to x/y clusters; slots between consecutive lines; a missing border
//!    between two slots merges them (spans, rectangular only).
//! 3. **Column tracks** — runs of lines with ≥2 segments; column separators
//!    are whitespace rivers no segment crosses; one-segment lines that sit
//!    in a later column are wrapped continuations of the row above. Scored.
//!
//! Every candidate is validated before it may become a table:
//! - ≥2 rows and ≥2 columns (a one-column "table" is text);
//! - fake-table validators on column tracks: a table of contents (last
//!   column mostly bare page numbers), a key-value list (first column mostly
//!   ends in ":"), prose set in columns (cells average ≥3 words and most
//!   continue a sentence in lower case);
//! - the **geometry gate** (`checks::geometry_gate`), the same one model
//!   grids face: rows and columns must occupy disjoint, ordered bands. A
//!   deterministic grid the gate would reject is not emitted either.
//! - a unit may not be split: a segment with words both inside and outside
//!   the table rejects it.
//!
//! A tracks candidate scoring below `ACCEPT` (0.75, Marker's VLM-fallback
//! threshold) but at least `UNCERTAIN` (0.4) stays paragraphs marked
//! `table_uncertain` and becomes a model request (step-3 contract).
//!
//! When two candidates cover the same region, `choose` decides — never "more
//! rows wins": both must pass the gate (position check); GriTS-Con ≥
//! `AGREE` means they agree and the stronger evidence is kept
//! (struct > ruled > model grid > tracks); if they disagree, the stronger
//! evidence is still kept but marked `table_uncertain`.
//!
//! Cells are filled only from pdfium characters: a cell's text is its words'
//! text, joined by single spaces, in reading order. No value is ever invented.
//!
//! Ideas after LiteParse `tables.rs` (Apache-2.0), Marker `table_recon.py`
//! (Apache-2.0), Xberg `table_core.rs` / `table_reconstruct.rs` validators
//! (MIT) and pdfplumber's lines strategy (MIT); no code copied (`rust/NOTICE`).

use std::collections::{BTreeMap, BTreeSet};

use super::layout::{Segment, HYPHEN_MARK};
use super::raw::RawPage;
use crate::checks::{self, GridCell, WordBox};
use crate::units::TableSource;

pub const ACCEPT: f64 = 0.75;
pub const UNCERTAIN: f64 = 0.4;
pub const AGREE: f64 = 0.9;
/// Line snapping tolerance (points).
const SNAP: f64 = 3.0;

/// A word: (segment index, word index within the segment).
pub type WordRef = (usize, usize);

#[derive(Debug, Clone, PartialEq)]
pub struct TCell {
    pub words: Vec<WordRef>,
    /// Words of a spanning header over this cell, prefixed in its TEXT only
    /// (a flattened header). Not part of the geometry gate: they sit above.
    pub prefix: Vec<WordRef>,
    /// A struct-tree `TH` (a header cell).
    pub header: bool,
    pub colspan: usize,
    pub rowspan: usize,
}

#[derive(Debug, Clone, PartialEq)]
pub struct PageTable {
    pub source: TableSource,
    pub bbox: [f64; 4],
    pub rows: Vec<Vec<TCell>>,
    pub score: f64,
    /// Lost to a competing grid that agreed/disagreed (see `choose`).
    pub uncertain: bool,
    /// Segments fully inside the table.
    pub segs: Vec<usize>,
    /// Struct node index of the `Table` element (struct tables only).
    pub struct_node: Option<usize>,
    /// A ruled grid built only from filled-rectangle edges (shading, not rules).
    pub weak: bool,
    /// A struct-tree table that does not account for its region: a row with
    /// no words at all, or a word inside its box that belongs to no cell.
    pub incomplete: bool,
    /// A spanning header was flattened into its sub-headers.
    pub header_flattened: bool,
}

/// Why a candidate was not accepted (diagnostics).
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum Reject {
    TooSmall,
    OneColumn,
    Toc,
    GeometryRows,
    GeometryColumns,
    GeometrySpan,
    GeometryOther,
    KeyValue,
    Prose,
    Geometry,
    SplitUnit,
    NotRectangular,
    LowScore,
    Overlap,
    /// A struct table that misses words of its region lost to a drawn grid.
    Incomplete,
}

impl Reject {
    pub fn is_geometry(self) -> bool {
        matches!(
            self,
            Reject::Geometry
                | Reject::GeometryRows
                | Reject::GeometryColumns
                | Reject::GeometrySpan
                | Reject::GeometryOther
        )
    }
}

#[derive(Debug, Default, Clone)]
pub struct PageTables {
    pub accepted: Vec<PageTable>,
    /// Regions that look like tables but scored low: model requests.
    pub uncertain: Vec<[f64; 4]>,
    pub rejected: Vec<(TableSource, Reject)>,
}

// ------------------------------------------------------------ helpers ----

pub fn word_box(page: &RawPage, seg: &Segment, k: usize) -> WordBox {
    let mut b = [f64::MAX, f64::MAX, f64::MIN, f64::MIN];
    for &c in &seg.words[k] {
        let ch = &page.chars[c];
        b = [
            b[0].min(ch.x0),
            b[1].min(ch.y0),
            b[2].max(ch.x1),
            b[3].max(ch.y1),
        ];
    }
    b
}

pub fn word_text(page: &RawPage, seg: &Segment, k: usize) -> String {
    seg.words[k]
        .iter()
        .map(|&c| {
            let ch = &page.chars[c];
            if ch.hyphen || ch.ch == HYPHEN_MARK {
                '-'
            } else {
                ch.ch
            }
        })
        .collect()
}

fn center(b: &[f64; 4]) -> (f64, f64) {
    ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0)
}

fn union(a: [f64; 4], b: [f64; 4]) -> [f64; 4] {
    [
        a[0].min(b[0]),
        a[1].min(b[1]),
        a[2].max(b[2]),
        a[3].max(b[3]),
    ]
}

const EMPTY_BOX: [f64; 4] = [f64::MAX, f64::MAX, f64::MIN, f64::MIN];

fn overlap_area(a: &[f64; 4], b: &[f64; 4]) -> f64 {
    let w = (a[2].min(b[2]) - a[0].max(b[0])).max(0.0);
    let h = (a[3].min(b[3]) - a[1].max(b[1])).max(0.0);
    w * h
}

/// Share of the smaller box covered by the intersection.
pub fn overlap_ratio(a: &[f64; 4], b: &[f64; 4]) -> f64 {
    let area = |x: &[f64; 4]| ((x[2] - x[0]) * (x[3] - x[1])).max(1e-6);
    overlap_area(a, b) / area(a).min(area(b))
}

/// Order a cell's words: by baseline (line), then x.
fn sort_words(segs: &[Segment], page: &RawPage, words: &mut [WordRef]) {
    words.sort_by(|a, b| {
        let (sa, sb) = (&segs[a.0], &segs[b.0]);
        let ba = word_box(page, sa, a.1);
        let bb = word_box(page, sb, b.1);
        let la = (sa.baseline * 2.0).round() as i64;
        let lb = (sb.baseline * 2.0).round() as i64;
        la.cmp(&lb).then(ba[0].total_cmp(&bb[0])).then(a.cmp(b))
    });
}

pub fn cell_text(segs: &[Segment], page: &RawPage, cell: &TCell) -> String {
    cell.prefix
        .iter()
        .chain(cell.words.iter())
        .map(|&(s, k)| checks::strip_leaders(&word_text(page, &segs[s], k)))
        .filter(|t| !t.is_empty())
        .collect::<Vec<_>>()
        .join(" ")
}

fn n_cols(rows: &[Vec<TCell>]) -> usize {
    layout(rows)
        .iter()
        .flat_map(|r| r.iter())
        .map(|&(_, c, cs)| c + cs)
        .max()
        .unwrap_or(0)
}

/// HTML span layout: per row, per cell, (row, col, colspan).
fn layout(rows: &[Vec<TCell>]) -> Vec<Vec<(usize, usize, usize)>> {
    let mut occ: BTreeSet<(usize, usize)> = BTreeSet::new();
    let mut out = Vec::with_capacity(rows.len());
    for (r, row) in rows.iter().enumerate() {
        let mut c = 0;
        let mut pl = Vec::with_capacity(row.len());
        for cell in row {
            while occ.contains(&(r, c)) {
                c += 1;
            }
            pl.push((r, c, cell.colspan));
            for dr in 0..cell.rowspan.max(1) {
                for dc in 0..cell.colspan.max(1) {
                    occ.insert((r + dr, c + dc));
                }
            }
            c += cell.colspan.max(1);
        }
        out.push(pl);
    }
    out
}

/// The table as a text matrix (spanned slots empty), for markdown and GriTS.
pub fn text_grid(segs: &[Segment], page: &RawPage, rows: &[Vec<TCell>]) -> Vec<Vec<String>> {
    let pl = layout(rows);
    let cols = n_cols(rows);
    let mut m = vec![vec![String::new(); cols]; rows.len()];
    for (r, row) in rows.iter().enumerate() {
        for (k, cell) in row.iter().enumerate() {
            let (_, c, _) = pl[r][k];
            m[r][c] = cell_text(segs, page, cell);
        }
    }
    m
}

/// GitHub pipe table; spanned slots are empty; `|` escaped.
pub fn markdown(grid: &[Vec<String>]) -> String {
    if grid.is_empty() {
        return String::new();
    }
    let cols = grid.iter().map(|r| r.len()).max().unwrap_or(0);
    let line = |cells: &[String]| {
        let mut v: Vec<String> = cells.iter().map(|c| c.replace('|', "\\|")).collect();
        v.resize(cols, String::new());
        format!("| {} |", v.join(" | "))
    };
    let mut out = vec![line(&grid[0]), line(&vec!["---".to_string(); cols])];
    out.extend(grid[1..].iter().map(|r| line(r)));
    out.join("\n")
}

/// Run the geometry gate over a deterministic grid.
fn gate(segs: &[Segment], page: &RawPage, rows: &[Vec<TCell>]) -> Result<(), Reject> {
    let mut boxes: BTreeMap<String, WordBox> = BTreeMap::new();
    let cells: Vec<Vec<GridCell>> = rows
        .iter()
        .map(|row| {
            row.iter()
                .map(|c| GridCell {
                    words: c
                        .words
                        .iter()
                        .filter(|&&(s, k)| !checks::has_leader(&word_text(page, &segs[s], k)))
                        .map(|&(s, k)| {
                            let id = format!("{s}:{k}");
                            boxes.insert(id.clone(), word_box(page, &segs[s], k));
                            id
                        })
                        .collect(),
                    colspan: c.colspan.max(1),
                    rowspan: c.rowspan.max(1),
                })
                .collect()
        })
        .collect();
    checks::geometry_gate(&cells, &boxes)
        .map(|_| ())
        .map_err(|f| match f {
            checks::Failure::GeometryRows => Reject::GeometryRows,
            checks::Failure::GeometryColumns => Reject::GeometryColumns,
            checks::Failure::Span => Reject::GeometrySpan,
            _ => Reject::GeometryOther,
        })
}

/// Segments the table fully contains, or Err when a segment is split.
/// Every distinct word of the table (header prefixes, then cells), in order.
pub fn table_words(rows: &[Vec<TCell>]) -> Vec<WordRef> {
    let mut seen = BTreeSet::new();
    let mut out = Vec::new();
    for c in rows.iter().flatten() {
        for &w in c.prefix.iter().chain(c.words.iter()) {
            if seen.insert(w) {
                out.push(w);
            }
        }
    }
    out
}

fn consumed(segs: &[Segment], rows: &[Vec<TCell>]) -> Result<Vec<usize>, Reject> {
    let mut per: BTreeMap<usize, usize> = BTreeMap::new();
    for (s, _) in table_words(rows) {
        *per.entry(s).or_default() += 1;
    }
    let mut out = Vec::new();
    for (s, n) in per {
        if n != segs[s].words.len() {
            return Err(Reject::SplitUnit);
        }
        out.push(s);
    }
    Ok(out)
}

fn bbox_of(segs: &[Segment], page: &RawPage, rows: &[Vec<TCell>]) -> [f64; 4] {
    let mut b = EMPTY_BOX;
    for (s, k) in table_words(rows) {
        b = union(b, word_box(page, &segs[s], k));
    }
    b
}

/// Common validation; returns the finished table or why not.
fn finish(
    segs: &[Segment],
    page: &RawPage,
    mut rows: Vec<Vec<TCell>>,
    source: TableSource,
    score: f64,
    region: Option<[f64; 4]>,
) -> Result<PageTable, Reject> {
    // drop rows with no cells at all
    rows.retain(|r| !r.is_empty());
    for c in rows.iter_mut().flatten() {
        sort_words(segs, page, &mut c.words);
    }
    let non_empty_rows = rows
        .iter()
        .filter(|r| r.iter().any(|c| !c.words.is_empty()))
        .count();
    if non_empty_rows < 2 {
        return Err(Reject::TooSmall);
    }
    let grid = text_grid(segs, page, &rows);
    let used_cols = (0..n_cols(&rows))
        .filter(|&c| grid.iter().any(|r| !r[c].is_empty()))
        .count();
    if used_cols < 2 {
        return Err(Reject::OneColumn);
    }
    let segs_in = consumed(segs, &rows)?;
    gate(segs, page, &rows)?;
    let bbox = region.unwrap_or_else(|| bbox_of(segs, page, &rows));
    Ok(PageTable {
        source,
        bbox,
        rows,
        score,
        uncertain: false,
        segs: segs_in,
        struct_node: None,
        weak: false,
        incomplete: false,
        header_flattened: false,
    })
}

// -------------------------------------------------------- struct tree ----

fn struct_tables(page: &RawPage, segs: &[Segment], out: &mut PageTables) {
    let nodes = &page.struct_nodes;
    // mcid -> cell (table index, row, cell)
    for (ti, t) in nodes.iter().enumerate().filter(|(_, n)| n.kind == "Table") {
        let end = (ti + 1..nodes.len())
            .find(|&k| nodes[k].depth <= t.depth)
            .unwrap_or(nodes.len());
        let mut rows: Vec<Vec<(usize, u32, u32)>> = Vec::new(); // (node, rs, cs)
        let mut k = ti + 1;
        let mut cell_mcids: BTreeMap<usize, BTreeSet<i32>> = BTreeMap::new();
        while k < end {
            let n = &nodes[k];
            if n.kind == "Table" {
                // a nested table: skip its subtree
                k = (k + 1..end)
                    .find(|&j| nodes[j].depth <= n.depth)
                    .unwrap_or(end);
                continue;
            }
            if n.kind == "TR" {
                rows.push(Vec::new());
            } else if (n.kind == "TD" || n.kind == "TH") && !rows.is_empty() {
                let cend = (k + 1..end)
                    .find(|&j| nodes[j].depth <= n.depth)
                    .unwrap_or(end);
                let set: BTreeSet<i32> = (k..cend)
                    .flat_map(|j| nodes[j].mcids.iter().copied())
                    .collect();
                cell_mcids.insert(k, set);
                rows.last_mut()
                    .unwrap()
                    .push((k, n.rowspan.max(1), n.colspan.max(1)));
                k = cend;
                continue;
            }
            k += 1;
        }
        if rows.is_empty() {
            continue;
        }
        let mut owner: BTreeMap<i32, usize> = BTreeMap::new();
        for (&node, set) in &cell_mcids {
            for &m in set {
                owner.entry(m).or_insert(node);
            }
        }
        let mut words_of: BTreeMap<usize, Vec<WordRef>> = BTreeMap::new();
        for (s, seg) in segs.iter().enumerate() {
            for (w, chars) in seg.words.iter().enumerate() {
                // the word's majority MCID (ties: the lowest)
                let mut count: BTreeMap<i32, usize> = BTreeMap::new();
                for &c in chars {
                    *count.entry(page.chars[c].mcid).or_default() += 1;
                }
                let best = count
                    .iter()
                    .max_by(|a, b| a.1.cmp(b.1).then(b.0.cmp(a.0)))
                    .map(|(m, _)| *m);
                if let Some(node) = best.and_then(|m| owner.get(&m)) {
                    words_of.entry(*node).or_default().push((s, w));
                }
            }
        }
        let trows: Vec<Vec<TCell>> = rows
            .iter()
            .map(|r| {
                r.iter()
                    .map(|&(node, rs, cs)| TCell {
                        prefix: vec![],
                        header: nodes[node].kind == "TH",
                        words: words_of.remove(&node).unwrap_or_default(),
                        colspan: cs as usize,
                        rowspan: rs as usize,
                    })
                    .collect()
            })
            .collect();
        let trows = place_short_rows(segs, page, trows);
        let (trows, flattened) = flatten_header_spans(trows);
        let region = bbox_of(segs, page, &trows);
        match finish(segs, page, trows, TableSource::StructTree, 1.0, None) {
            Ok(mut t) => {
                t.struct_node = Some(ti);
                t.header_flattened = flattened;
                let empty_row = t.rows.iter().any(|r| r.iter().all(|c| c.words.is_empty()));
                let mine: BTreeSet<WordRef> = table_words(&t.rows).into_iter().collect();
                let orphan = segs.iter().enumerate().any(|(s, seg)| {
                    (0..seg.words.len()).any(|w| {
                        let (cx, cy) = center(&word_box(page, seg, w));
                        !mine.contains(&(s, w))
                            && cx >= t.bbox[0]
                            && cx <= t.bbox[2]
                            && cy >= t.bbox[1]
                            && cy <= t.bbox[3]
                    })
                });
                t.incomplete = empty_row || orphan;
                out.accepted.push(t);
            }
            Err(r) => {
                out.rejected.push((TableSource::StructTree, r));
                // the tree says table but the geometry disagrees: ask a model
                if (r.is_geometry() || r == Reject::SplitUnit) && region[0] < region[2] {
                    out.uncertain.push(region);
                }
            }
        }
    }
}

/// Flatten struct-tree row-0 header cells that span several columns
/// (markdown cannot span): when every column a spanning cell covers holds
/// exactly one non-empty, single-column `TH` sub-header in row 1 (a data row
/// under a spanning header is left alone), the spanning cell's words
/// become a PREFIX of each sub-header ("<label> <sub-header>") and leave row 0.
/// If row 0 then holds nothing but cells that also span row 1 (a `RowSpan`
/// stub such as "Functie"), row 0 is dropped and those cells move down.
/// Only the PDF's own words are used; nothing is invented.
fn flatten_header_spans(mut rows: Vec<Vec<TCell>>) -> (Vec<Vec<TCell>>, bool) {
    if rows.len() < 2 {
        return (rows, false);
    }
    let pl = layout(&rows);
    let mut flattened = false;
    for k in 0..rows[0].len() {
        let (cs, empty) = (rows[0][k].colspan.max(1), rows[0][k].words.is_empty());
        if cs < 2 || empty || rows[0][k].rowspan > 1 {
            continue;
        }
        let c0 = pl[0][k].1;
        let subs: Vec<usize> = (0..rows[1].len())
            .filter(|&j| pl[1][j].1 >= c0 && pl[1][j].1 < c0 + cs)
            .collect();
        // sub-headers, not data: every covered row-1 cell is a TH
        let ok = subs.len() == cs
            && subs.iter().all(|&j| {
                rows[1][j].colspan.max(1) == 1 && !rows[1][j].words.is_empty() && rows[1][j].header
            });
        if !ok {
            continue;
        }
        let label = std::mem::take(&mut rows[0][k].words);
        for &j in &subs {
            let mut p = label.clone();
            p.extend(std::mem::take(&mut rows[1][j].prefix));
            rows[1][j].prefix = p;
        }
        flattened = true;
    }
    if !flattened {
        return (rows, false);
    }
    let droppable = rows[0].iter().all(|c| c.words.is_empty() || c.rowspan >= 2);
    if droppable {
        let pl = layout(&rows);
        let row0 = rows.remove(0);
        for (k, mut cell) in row0.into_iter().enumerate() {
            if cell.words.is_empty() && cell.rowspan < 2 {
                continue;
            }
            let col = pl[0][k].1;
            cell.rowspan = cell.rowspan.saturating_sub(1).max(1);
            let at = pl[1].iter().filter(|&&(_, c, _)| c < col).count();
            let at = at.min(rows[0].len());
            rows[0].insert(at, cell);
        }
    }
    (rows, true)
}

/// Rows whose cells fill fewer slots than the table (a merged cell written
/// without a `ColSpan` attribute): place each cell by geometry, spanning the
/// columns its words cover. Column bands come from the complete rows.
fn place_short_rows(segs: &[Segment], page: &RawPage, rows: Vec<Vec<TCell>>) -> Vec<Vec<TCell>> {
    let width = |r: &Vec<TCell>| r.iter().map(|c| c.colspan.max(1)).sum::<usize>();
    let ncols = rows.iter().map(width).max().unwrap_or(0);
    if ncols < 2 || rows.iter().any(|r| r.iter().any(|c| c.rowspan > 1)) {
        return rows;
    }
    let mut bands: Vec<Option<(f64, f64)>> = vec![None; ncols];
    for r in rows.iter().filter(|r| width(r) == ncols) {
        let mut c = 0;
        for cell in r {
            if cell.colspan <= 1 {
                for &(s, w) in &cell.words {
                    let b = word_box(page, &segs[s], w);
                    bands[c] = Some(match bands[c] {
                        Some((lo, hi)) => (lo.min(b[0]), hi.max(b[2])),
                        None => (b[0], b[2]),
                    });
                }
            }
            c += cell.colspan.max(1);
        }
    }
    if bands.iter().any(|b| b.is_none()) {
        return rows;
    }
    let bands: Vec<(f64, f64)> = bands.into_iter().flatten().collect();
    rows.into_iter()
        .map(|r| {
            if width(&r) == ncols {
                return r;
            }
            let mut out: Vec<TCell> = Vec::new();
            let mut cur = 0usize;
            let n = r.len();
            for (i, cell) in r.into_iter().enumerate() {
                let bb = cell.words.iter().fold(EMPTY_BOX, |b, &(s, w)| {
                    union(b, word_box(page, &segs[s], w))
                });
                let (mut s0, mut e0) = if cell.words.is_empty() {
                    (cur, cur)
                } else {
                    let s0 = bands.iter().position(|b| b.1 >= bb[0]).unwrap_or(ncols - 1);
                    let e0 = bands.iter().rposition(|b| b.0 <= bb[2]).unwrap_or(s0);
                    (s0, e0.max(s0))
                };
                s0 = s0.max(cur);
                e0 = e0.max(s0).min(ncols - 1);
                // the last cell of a short row takes the rest of the row
                if i + 1 == n {
                    e0 = ncols - 1;
                }
                for _ in cur..s0 {
                    out.push(TCell {
                        prefix: vec![],
                        header: false,
                        words: vec![],
                        colspan: 1,
                        rowspan: 1,
                    });
                }
                out.push(TCell {
                    prefix: vec![],
                    header: false,
                    words: cell.words,
                    colspan: e0 - s0 + 1,
                    rowspan: 1,
                });
                cur = e0 + 1;
                if cur >= ncols {
                    break;
                }
            }
            out
        })
        .collect()
}

// --------------------------------------------------------- ruled grid ----

#[derive(Clone, Copy)]
struct Edge {
    /// the fixed coordinate (y for horizontal, x for vertical)
    at: f64,
    lo: f64,
    hi: f64,
    /// An edge of a filled rectangle (shading), not a drawn rule.
    rect: bool,
}

fn edges(page: &RawPage) -> (Vec<Edge>, Vec<Edge>) {
    let page_area = (page.width * page.height).max(1.0);
    let (mut h, mut v) = (Vec::new(), Vec::new());
    for b in &page.paths {
        let (w, ht) = (b[2] - b[0], b[3] - b[1]);
        if ht <= SNAP && w > SNAP {
            h.push(Edge {
                at: (b[1] + b[3]) / 2.0,
                lo: b[0],
                hi: b[2],
                rect: false,
            });
        } else if w <= SNAP && ht > SNAP {
            v.push(Edge {
                at: (b[0] + b[2]) / 2.0,
                lo: b[1],
                hi: b[3],
                rect: false,
            });
        } else if w > SNAP && ht > SNAP && w * ht < 0.6 * page_area {
            h.push(Edge {
                at: b[1],
                lo: b[0],
                hi: b[2],
                rect: true,
            });
            h.push(Edge {
                at: b[3],
                lo: b[0],
                hi: b[2],
                rect: true,
            });
            v.push(Edge {
                at: b[0],
                lo: b[1],
                hi: b[3],
                rect: true,
            });
            v.push(Edge {
                at: b[2],
                lo: b[1],
                hi: b[3],
                rect: true,
            });
        }
    }
    (h, v)
}

/// Cluster coordinates within `SNAP`; returns sorted cluster centres.
fn clusters(mut xs: Vec<f64>) -> Vec<f64> {
    xs.sort_by(|a, b| a.total_cmp(b));
    let mut out: Vec<Vec<f64>> = Vec::new();
    for x in xs {
        match out.last_mut() {
            Some(c) if x - c[c.len() - 1] <= SNAP => c.push(x),
            _ => out.push(vec![x]),
        }
    }
    out.iter()
        .map(|c| (c.iter().sum::<f64>() / c.len() as f64 * 100.0).round() / 100.0)
        .collect()
}

/// Connected components of crossing horizontal/vertical edges.
fn components(h: &[Edge], v: &[Edge]) -> Vec<(Vec<usize>, Vec<usize>)> {
    let n = h.len() + v.len();
    let mut parent: Vec<usize> = (0..n).collect();
    fn find(p: &mut [usize], x: usize) -> usize {
        let mut r = x;
        while p[r] != r {
            r = p[r];
        }
        let mut y = x;
        while p[y] != r {
            let nx = p[y];
            p[y] = r;
            y = nx;
        }
        r
    }
    for (i, e) in h.iter().enumerate() {
        for (j, f) in v.iter().enumerate() {
            if f.at >= e.lo - SNAP
                && f.at <= e.hi + SNAP
                && e.at >= f.lo - SNAP
                && e.at <= f.hi + SNAP
            {
                let (a, b) = (find(&mut parent, i), find(&mut parent, h.len() + j));
                if a != b {
                    parent[a.max(b)] = a.min(b);
                }
            }
        }
    }
    let mut groups: BTreeMap<usize, (Vec<usize>, Vec<usize>)> = BTreeMap::new();
    for i in 0..n {
        let r = find(&mut parent, i);
        let g = groups.entry(r).or_default();
        if i < h.len() {
            g.0.push(i);
        } else {
            g.1.push(i - h.len());
        }
    }
    groups
        .into_values()
        .filter(|(a, b)| a.len() >= 2 && b.len() >= 2)
        .collect()
}

fn covers(edges: &[&Edge], at: f64, lo: f64, hi: f64) -> bool {
    let need = 0.6 * (hi - lo);
    let got: f64 = edges
        .iter()
        .filter(|e| (e.at - at).abs() <= SNAP)
        .map(|e| (e.hi.min(hi) - e.lo.max(lo)).max(0.0))
        .sum();
    got >= need
}

fn ruled_tables(
    page: &RawPage,
    segs: &[Segment],
    skip: &dyn Fn(usize) -> bool,
    out: &mut PageTables,
) {
    let (h, v) = edges(page);
    for (hi, vi) in components(&h, &v) {
        let he: Vec<&Edge> = hi.iter().map(|&i| &h[i]).collect();
        let ve: Vec<&Edge> = vi.iter().map(|&i| &v[i]).collect();
        let x_lo = he.iter().map(|e| e.lo).fold(f64::MAX, f64::min);
        let x_hi = he.iter().map(|e| e.hi).fold(f64::MIN, f64::max);
        let y_lo = ve.iter().map(|e| e.lo).fold(f64::MAX, f64::min);
        let y_hi = ve.iter().map(|e| e.hi).fold(f64::MIN, f64::max);
        let mut xs_raw: Vec<f64> = ve.iter().map(|e| e.at).collect();
        xs_raw.extend([x_lo, x_hi]);
        let mut ys_raw: Vec<f64> = he.iter().map(|e| e.at).collect();
        ys_raw.extend([y_lo, y_hi]);
        let mut xs = clusters(xs_raw);
        let mut ys = clusters(ys_raw);
        let weak = he.iter().chain(ve.iter()).all(|e| e.rect);
        // Keep an interior boundary only where it is drawn across at least
        // half of the table (Word draws per-cell borders; a line present in
        // a few rows only is a split inside one visual column, e.g. a
        // currency sign in its own sub-cell).
        let half = |edges: &[&Edge], at: f64, cuts: &[f64]| {
            let n = cuts.len().saturating_sub(1).max(1);
            let drawn = (0..cuts.len().saturating_sub(1))
                .filter(|&k| covers(edges, at, cuts[k], cuts[k + 1]))
                .count();
            drawn * 2 >= n
        };
        let keep_x: Vec<f64> = xs
            .iter()
            .enumerate()
            .filter(|&(k, &x)| k == 0 || k + 1 == xs.len() || half(&ve, x, &ys))
            .map(|(_, &x)| x)
            .collect();
        let keep_y: Vec<f64> = ys
            .iter()
            .enumerate()
            .filter(|&(k, &y)| k == 0 || k + 1 == ys.len() || half(&he, y, &keep_x))
            .map(|(_, &y)| y)
            .collect();
        xs = keep_x;
        ys = keep_y;
        // Drop boundaries that only bound an empty strip (no word centre).
        let centres: Vec<(f64, f64)> = segs
            .iter()
            .enumerate()
            .filter(|(s, _)| !skip(*s))
            .flat_map(|(_, seg)| (0..seg.words.len()).map(move |w| center(&word_box(page, seg, w))))
            .collect();
        let (y_top, y_bot) = (ys[0], ys[ys.len() - 1]);
        let (x_left, x_right) = (xs[0], xs[xs.len() - 1]);
        let inside_y = |c: &(f64, f64)| c.1 >= y_top && c.1 <= y_bot;
        let inside_x = |c: &(f64, f64)| c.0 >= x_left && c.0 <= x_right;
        let mut k = 0;
        while k + 1 < xs.len() && xs.len() > 2 {
            let empty = !centres
                .iter()
                .any(|c| inside_y(c) && c.0 >= xs[k] && c.0 <= xs[k + 1]);
            if empty {
                // merge into the neighbour: remove the interior edge of the strip
                let rm = if k + 2 < xs.len() { k + 1 } else { k };
                xs.remove(rm);
            } else {
                k += 1;
            }
        }
        let mut k = 0;
        while k + 1 < ys.len() && ys.len() > 2 {
            let empty = !centres
                .iter()
                .any(|c| inside_x(c) && c.1 >= ys[k] && c.1 <= ys[k + 1]);
            if empty {
                let rm = if k + 2 < ys.len() { k + 1 } else { k };
                ys.remove(rm);
            } else {
                k += 1;
            }
        }
        if xs.len() < 3 || ys.len() < 3 {
            // fewer than 2×2 slots: a box, not a table
            out.rejected.push((TableSource::Ruled, Reject::TooSmall));
            continue;
        }
        let (nr, nc) = (ys.len() - 1, xs.len() - 1);
        // union-find over slots with a missing border between them
        let idx = |r: usize, c: usize| r * nc + c;
        let mut parent: Vec<usize> = (0..nr * nc).collect();
        fn find(p: &mut [usize], x: usize) -> usize {
            let mut r = x;
            while p[r] != r {
                r = p[r];
            }
            r
        }
        let join = |p: &mut Vec<usize>, a: usize, b: usize| {
            let (x, y) = (find(p, a), find(p, b));
            if x != y {
                p[x.max(y)] = x.min(y);
            }
        };
        for r in 0..nr {
            for c in 0..nc {
                if c + 1 < nc && !covers(&ve, xs[c + 1], ys[r], ys[r + 1]) {
                    join(&mut parent, idx(r, c), idx(r, c + 1));
                }
                if r + 1 < nr && !covers(&he, ys[r + 1], xs[c], xs[c + 1]) {
                    join(&mut parent, idx(r, c), idx(r + 1, c));
                }
            }
        }
        // groups must be rectangles
        let mut groups: BTreeMap<usize, (usize, usize, usize, usize)> = BTreeMap::new(); // r0,c0,r1,c1
        for r in 0..nr {
            for c in 0..nc {
                let g = find(&mut parent, idx(r, c));
                let e = groups.entry(g).or_insert((r, c, r, c));
                *e = (e.0.min(r), e.1.min(c), e.2.max(r), e.3.max(c));
            }
        }
        let mut rect = true;
        for (&g, &(r0, c0, r1, c1)) in &groups {
            for r in r0..=r1 {
                for c in c0..=c1 {
                    if find(&mut parent, idx(r, c)) != g {
                        rect = false;
                    }
                }
            }
        }
        if !rect {
            out.rejected
                .push((TableSource::Ruled, Reject::NotRectangular));
            continue;
        }
        // fill: every non-furniture word whose centre is inside the grid
        let region = [xs[0], ys[0], xs[nc], ys[nr]];
        let mut cell_words: BTreeMap<usize, Vec<WordRef>> = BTreeMap::new();
        for (s, seg) in segs.iter().enumerate() {
            if skip(s) {
                continue;
            }
            for w in 0..seg.words.len() {
                let (cx, cy) = center(&word_box(page, seg, w));
                if cx < region[0] || cx > region[2] || cy < region[1] || cy > region[3] {
                    continue;
                }
                let c = (0..nc).find(|&c| cx <= xs[c + 1]).unwrap_or(nc - 1);
                let r = (0..nr).find(|&r| cy <= ys[r + 1]).unwrap_or(nr - 1);
                let g = find(&mut parent, idx(r, c));
                cell_words.entry(g).or_default().push((s, w));
            }
        }
        // `groups` iterates by root slot = the group's top-left slot (the
        // union keeps the smaller index), i.e. row-major: cells arrive in
        // column order within each row.
        let mut rows: Vec<Vec<TCell>> = vec![Vec::new(); nr];
        for (&g, &(r0, c0, r1, c1)) in &groups {
            rows[r0].push(TCell {
                prefix: vec![],
                header: false,
                words: cell_words.remove(&g).unwrap_or_default(),
                colspan: c1 - c0 + 1,
                rowspan: r1 - r0 + 1,
            });
        }
        match finish(segs, page, rows, TableSource::Ruled, 1.0, Some(region)) {
            Ok(mut t) => {
                t.weak = weak;
                out.accepted.push(t);
            }
            Err(r) => {
                out.rejected.push((TableSource::Ruled, r));
                if r.is_geometry() || r == Reject::SplitUnit {
                    out.uncertain.push(region);
                }
            }
        }
    }
}

// ------------------------------------------------------ column tracks ----

fn is_page_number(t: &str) -> bool {
    let t = t.trim();
    !t.is_empty()
        && t.len() <= 4
        && (t.chars().all(|c| c.is_ascii_digit())
            || t.chars()
                .all(|c| matches!(c, 'i' | 'v' | 'x' | 'I' | 'V' | 'X')))
}

fn is_numeric(t: &str) -> bool {
    let t = t.trim();
    !t.is_empty()
        && t.chars().any(|c| c.is_ascii_digit())
        && t.chars()
            .all(|c| c.is_ascii_digit() || " .,-+%€$£/()".contains(c))
}

/// Fake-table validators and the score for a tracks grid.
fn score_tracks(grid: &[Vec<String>]) -> Result<f64, Reject> {
    let rows = grid.len();
    let cols = grid.iter().map(|r| r.len()).max().unwrap_or(0);
    let cells: Vec<&String> = grid.iter().flatten().filter(|c| !c.is_empty()).collect();
    if cells.is_empty() {
        return Err(Reject::TooSmall);
    }
    let last_numbers = grid
        .iter()
        .filter(|r| r.last().is_some_and(|c| is_page_number(c)))
        .count();
    let first_text = grid
        .iter()
        .filter(|r| r.first().is_some_and(|c| c.split_whitespace().count() >= 2))
        .count();
    if cols == 2 && last_numbers * 10 >= rows * 7 && first_text * 2 >= rows {
        return Err(Reject::Toc);
    }
    let colon = grid
        .iter()
        .filter(|r| r.first().is_some_and(|c| c.trim_end().ends_with(':')))
        .count();
    if colon * 10 >= rows * 7 {
        return Err(Reject::KeyValue);
    }
    let words: usize = cells.iter().map(|c| c.split_whitespace().count()).sum();
    let mean_words = words as f64 / cells.len() as f64;
    let lower = grid
        .iter()
        .skip(1)
        .flatten()
        .filter(|c| c.chars().next().is_some_and(|ch| ch.is_lowercase()))
        .count();
    let body_cells = grid
        .iter()
        .skip(1)
        .flatten()
        .filter(|c| !c.is_empty())
        .count()
        .max(1);
    let numeric = cells.iter().filter(|c| is_numeric(c)).count() as f64 / cells.len() as f64;
    if mean_words >= 3.0 && lower * 2 >= body_cells && numeric < 0.2 {
        return Err(Reject::Prose);
    }
    let fill = cells.len() as f64 / (rows * cols) as f64;
    let short = ((10.0 - mean_words) / 6.0).clamp(0.0, 1.0);
    Ok(0.5 * fill + 0.3 * short + 0.2 * (numeric * 2.0).min(1.0))
}

fn track_tables(
    page: &RawPage,
    segs: &[Segment],
    lines: &[Vec<usize>],
    skip: &dyn Fn(usize) -> bool,
    out: &mut PageTables,
) {
    let body: Vec<Vec<usize>> = lines
        .iter()
        .map(|l| l.iter().copied().filter(|&s| !skip(s)).collect::<Vec<_>>())
        .filter(|l: &Vec<usize>| !l.is_empty())
        .collect();
    // runs of lines with ≥2 segments (single-segment lines may continue a row)
    let mut runs: Vec<Vec<usize>> = Vec::new();
    let mut cur: Vec<usize> = Vec::new();
    let mut multi = 0;
    for (i, l) in body.iter().enumerate() {
        let size = segs[l[0]].size.max(1.0);
        let gap_ok = cur
            .last()
            .map(|&p: &usize| segs[l[0]].baseline - segs[body[p][0]].baseline <= 2.5 * size)
            .unwrap_or(true);
        if !gap_ok {
            if multi >= 3 {
                runs.push(std::mem::take(&mut cur));
            }
            cur.clear();
            multi = 0;
        }
        if l.len() >= 2 {
            cur.push(i);
            multi += 1;
        } else if !cur.is_empty() {
            cur.push(i);
        }
    }
    if multi >= 3 {
        runs.push(cur);
    }
    for mut run in runs {
        // trim trailing single-segment lines
        while run.last().is_some_and(|&i| body[i].len() < 2) {
            run.pop();
        }
        let run_segs: Vec<usize> = run.iter().flat_map(|&i| body[i].iter().copied()).collect();
        let x0 = run_segs
            .iter()
            .map(|&s| segs[s].bbox[0])
            .fold(f64::MAX, f64::min);
        let x1 = run_segs
            .iter()
            .map(|&s| segs[s].bbox[2])
            .fold(f64::MIN, f64::max);
        // whitespace rivers over the multi-segment lines
        let width = (x1 - x0).ceil() as usize + 1;
        let mut cover = vec![false; width];
        let leader_seg = |s: usize| {
            (0..segs[s].words.len()).all(|w| checks::is_leader(&word_text(page, &segs[s], w)))
        };
        for &i in run.iter().filter(|&&i| body[i].len() >= 2) {
            for &s in body[i].iter().filter(|&&s| !leader_seg(s)) {
                let a = (segs[s].bbox[0] - x0).floor().max(0.0) as usize;
                let b = ((segs[s].bbox[2] - x0).ceil() as usize).min(width - 1);
                cover[a..=b].iter_mut().for_each(|x| *x = true);
            }
        }
        let mut seps: Vec<f64> = Vec::new();
        let mut k = 0;
        while k < width {
            if !cover[k] {
                let start = k;
                while k < width && !cover[k] {
                    k += 1;
                }
                if k - start >= 4 {
                    seps.push(x0 + (start + k) as f64 / 2.0);
                }
            } else {
                k += 1;
            }
        }
        let ncols = seps.len() + 1;
        if ncols < 2 {
            out.rejected.push((TableSource::Tracks, Reject::OneColumn));
            continue;
        }
        let col_of = |x: f64| seps.iter().filter(|&&s| x > s).count();
        let mut rows: Vec<Vec<TCell>> = Vec::new();
        let mut leader_rows = 0usize;
        for &i in &run {
            let line = &body[i];
            let mut leaders_in_row = line.iter().any(|&s| {
                (0..segs[s].words.len()).any(|w| checks::has_leader(&word_text(page, &segs[s], w)))
            });
            if line.len() < 2 && !rows.is_empty() && col_of(segs[line[0]].bbox[0]) > 0 {
                // a wrapped continuation of the row above
                let c = col_of(segs[line[0]].bbox[0]);
                let row = rows.last_mut().unwrap();
                if let Some(cell) = row.get_mut(c) {
                    cell.words
                        .extend((0..segs[line[0]].words.len()).map(|w| (line[0], w)));
                    continue;
                }
            }
            let mut row: Vec<TCell> = (0..ncols)
                .map(|_| TCell {
                    prefix: vec![],
                    header: false,
                    words: vec![],
                    colspan: 1,
                    rowspan: 1,
                })
                .collect();
            for &s in line {
                if leader_seg(s) {
                    // filler: accounted to the row (no split unit), never a column
                    leaders_in_row = true;
                    row[0]
                        .words
                        .extend((0..segs[s].words.len()).map(|w| (s, w)));
                    continue;
                }
                let (a, b) = (col_of(segs[s].bbox[0] + 0.5), col_of(segs[s].bbox[2] - 0.5));
                // a segment crossing a river keeps its words together in its first column
                let c = a.min(b);
                row[c]
                    .words
                    .extend((0..segs[s].words.len()).map(|w| (s, w)));
            }
            rows.push(row);
            leader_rows += leaders_in_row as usize;
        }
        // An axis label directly above the sub-header row (tight line pitch),
        // right of an EMPTY stub column, spanning ≥2 sub-headers: prefix it
        // to each ("<label> <sub-header>"). A caption over a full header row
        // (no empty stub) is left alone.
        let mut flattened = false;
        if run[0] > 0 && !rows.is_empty() && !seps.is_empty() {
            let above = &body[run[0] - 1];
            let head = &body[run[0]];
            let size = segs[head[0]].size.max(1.0);
            let gap = segs[head[0]].baseline - segs[above[0]].baseline;
            let stub_empty = rows[0][0].words.is_empty();
            let filled: Vec<usize> = (1..rows[0].len())
                .filter(|&j| !rows[0][j].words.is_empty())
                .collect();
            let right_of_stub = above.iter().all(|&s| segs[s].bbox[0] > seps[0]);
            if gap > 0.0
                && gap <= 1.6 * size
                && stub_empty
                && right_of_stub
                && filled.len() >= 2
                && above.len() < filled.len()
            {
                let cx = |j: usize| {
                    let b = rows[0][j].words.iter().fold(EMPTY_BOX, |b, &(s, w)| {
                        union(b, word_box(page, &segs[s], w))
                    });
                    (b[0] + b[2]) / 2.0
                };
                let mut owner: BTreeMap<usize, Vec<usize>> = BTreeMap::new();
                for &j in &filled {
                    let x = cx(j);
                    let best = (0..above.len())
                        .min_by(|&a, &b| {
                            let da =
                                ((segs[above[a]].bbox[0] + segs[above[a]].bbox[2]) / 2.0 - x).abs();
                            let db =
                                ((segs[above[b]].bbox[0] + segs[above[b]].bbox[2]) / 2.0 - x).abs();
                            da.total_cmp(&db).then(a.cmp(&b))
                        })
                        .unwrap();
                    owner.entry(best).or_default().push(j);
                }
                if owner.len() == above.len() && owner.values().all(|v| v.len() >= 2) {
                    for (a, cols) in owner {
                        let label: Vec<WordRef> = (0..segs[above[a]].words.len())
                            .map(|w| (above[a], w))
                            .collect();
                        for j in cols {
                            rows[0][j].prefix = label.clone();
                        }
                    }
                    flattened = true;
                }
            }
        }
        let text = text_grid(segs, page, &rows);
        // Leaders into bare page numbers: a table of contents, whatever the
        // title column holds. No table, and no model request either.
        let last_is_number = text
            .iter()
            .filter(|r| {
                r.iter()
                    .rev()
                    .find(|c| !c.is_empty())
                    .and_then(|c| c.split_whitespace().last())
                    .is_some_and(is_page_number)
            })
            .count();
        if leader_rows * 2 >= rows.len() && last_is_number * 10 >= rows.len() * 7 {
            out.rejected.push((TableSource::Tracks, Reject::Toc));
            continue;
        }
        let score = match score_tracks(&text) {
            Ok(s) => s,
            Err(r) => {
                out.rejected.push((TableSource::Tracks, r));
                continue;
            }
        };
        match finish(segs, page, rows, TableSource::Tracks, score, None) {
            Ok(mut t) if score >= ACCEPT => {
                t.header_flattened = flattened;
                out.accepted.push(t)
            }
            Ok(t) => {
                out.rejected.push((TableSource::Tracks, Reject::LowScore));
                if score >= UNCERTAIN {
                    out.uncertain.push(t.bbox);
                }
            }
            Err(r) => {
                out.rejected.push((TableSource::Tracks, r));
                if r.is_geometry() && score >= UNCERTAIN {
                    let run_box = run_segs
                        .iter()
                        .fold(EMPTY_BOX, |b, &s| union(b, segs[s].bbox));
                    out.uncertain.push(run_box);
                }
            }
        }
    }
}

// ------------------------------------------------------------- choose ----

fn priority(s: TableSource) -> u8 {
    match s {
        TableSource::StructTree => 4,
        TableSource::Ruled => 3,
        TableSource::ModelGrid => 2,
        TableSource::Tracks => 1,
        TableSource::Ooxml => 0,
    }
}

/// Decide between two candidate grids for one region, both of which passed
/// the geometry gate; `a` is the incumbent (deterministic) grid. Returns
/// (a wins?, they disagree).
pub fn choose(
    a: TableSource,
    a_grid: &[Vec<String>],
    b: TableSource,
    b_grid: &[Vec<String>],
) -> (bool, bool) {
    let agree = checks::grits_con(a_grid, b_grid) >= AGREE;
    // Agreement keeps the incumbent `a` (the deterministic grid): same
    // content, text-layer provenance. Disagreement: the stronger evidence.
    let a_wins = agree || priority(a) >= priority(b);
    (a_wins, !agree)
}

/// All deterministic tables on a page. `skip(s)`: segment s is furniture.
pub fn detect(
    page: &RawPage,
    segs: &[Segment],
    lines: &[Vec<usize>],
    skip: &dyn Fn(usize) -> bool,
) -> PageTables {
    let mut st = PageTables::default();
    struct_tables(page, segs, &mut st);
    let mut ru = PageTables::default();
    ruled_tables(page, segs, skip, &mut ru);
    let mut tr = PageTables::default();
    track_tables(page, segs, lines, skip, &mut tr);

    // The struct tree wins outright where it is complete. An incomplete one
    // competes with an overlapping ruled grid (`choose`, struct ranked below
    // ruled): drawn lines that account for every word beat a tree that does not.
    let mut structs: Vec<PageTable> = Vec::new();
    for t in st.accepted {
        if !t.incomplete {
            structs.push(t);
            continue;
        }
        let rival = ru
            .accepted
            .iter()
            .position(|r| overlap_ratio(&r.bbox, &t.bbox) >= 0.3 && !r.weak);
        match rival {
            Some(k) => {
                let (tg, rg) = (
                    text_grid(segs, page, &t.rows),
                    text_grid(segs, page, &ru.accepted[k].rows),
                );
                let agree = checks::grits_con(&tg, &rg) >= AGREE;
                if agree {
                    // same content: keep the tree (its spans), drop the grid
                    ru.accepted.remove(k);
                    structs.push(t);
                } else {
                    st.rejected
                        .push((TableSource::StructTree, Reject::Incomplete));
                }
            }
            None => structs.push(t),
        }
    }
    let mut out = PageTables {
        accepted: structs,
        uncertain: vec![],
        rejected: st.rejected,
    };
    // struct wins outright; others only where they do not overlap it
    let struct_boxes: Vec<[f64; 4]> = out.accepted.iter().map(|t| t.bbox).collect();
    let clear = |b: &[f64; 4]| struct_boxes.iter().all(|s| overlap_ratio(s, b) < 0.3);
    let mut det: Vec<PageTable> = ru.accepted.into_iter().filter(|t| clear(&t.bbox)).collect();
    for t in tr.accepted.into_iter().filter(|t| clear(&t.bbox)) {
        match det
            .iter()
            .position(|d| overlap_ratio(&d.bbox, &t.bbox) >= 0.3)
        {
            Some(k) => {
                let dg = text_grid(segs, page, &det[k].rows);
                let tg = text_grid(segs, page, &t.rows);
                let (mut keep_det, uncertain) = choose(det[k].source, &dg, t.source, &tg);
                // Shading rectangles band rows; they do not draw cells. A
                // disagreeing tracks grid beats a rectangles-only grid.
                if det[k].weak && uncertain {
                    keep_det = false;
                }
                if !keep_det {
                    det[k] = t;
                }
                // Disagreement with an INFERRED grid does not make drawn
                // lines uncertain; it does make a kept tracks grid uncertain.
                if uncertain && det[k].source == TableSource::Tracks {
                    det[k].uncertain = true;
                }
                out.rejected.push((TableSource::Tracks, Reject::Overlap));
            }
            None => det.push(t),
        }
    }
    // no two accepted tables may share a segment
    let mut used: BTreeSet<usize> = out
        .accepted
        .iter()
        .flat_map(|t| t.segs.iter().copied())
        .collect();
    for t in det {
        if t.segs.iter().any(|s| used.contains(s)) {
            out.rejected.push((t.source, Reject::Overlap));
            continue;
        }
        used.extend(t.segs.iter().copied());
        out.accepted.push(t);
    }
    let taken: Vec<[f64; 4]> = out.accepted.iter().map(|t| t.bbox).collect();
    for u in ru.uncertain.into_iter().chain(tr.uncertain) {
        if taken.iter().all(|t| overlap_ratio(t, &u) < 0.3)
            && out.uncertain.iter().all(|x| overlap_ratio(x, &u) < 0.3)
        {
            out.uncertain.push(u);
        }
    }
    out.rejected.extend(ru.rejected);
    out.rejected.extend(tr.rejected);
    out.accepted.sort_by(|a, b| {
        a.bbox[1]
            .total_cmp(&b.bbox[1])
            .then(a.bbox[0].total_cmp(&b.bbox[0]))
    });
    out.uncertain
        .sort_by(|a, b| a[1].total_cmp(&b[1]).then(a[0].total_cmp(&b[0])));
    out
}

#[cfg(test)]
mod choose_tests {
    use super::*;

    fn g(rows: &[&[&str]]) -> Vec<Vec<String>> {
        rows.iter()
            .map(|r| r.iter().map(|s| s.to_string()).collect())
            .collect()
    }

    #[test]
    fn agreement_keeps_the_incumbent_disagreement_the_stronger_evidence() {
        let a = g(&[&["a", "1"], &["b", "2"], &["c", "3"]]);
        let b = g(&[&["a", "2"], &["b", "1"], &["c", "3"]]);
        // tracks vs an agreeing model grid: tracks stays, not uncertain
        assert_eq!(
            choose(TableSource::Tracks, &a, TableSource::ModelGrid, &a),
            (true, false)
        );
        // tracks vs a disagreeing model grid: the model wins, uncertain
        assert_eq!(
            choose(TableSource::Tracks, &a, TableSource::ModelGrid, &b),
            (false, true)
        );
        // ruled vs a disagreeing model grid: ruled stays, uncertain
        assert_eq!(
            choose(TableSource::Ruled, &a, TableSource::ModelGrid, &b),
            (true, true)
        );
    }
}
