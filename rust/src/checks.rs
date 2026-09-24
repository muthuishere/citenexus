//! Deterministic checks that gate model output before it may replace base
//! text (ADR-0017 decision 5). Pure functions, no pdfium: every check here is
//! testable on invented strings and boxes.
//!
//! Two families:
//!
//! 1. **Structure over text-layer words** (`geometry_gate`). On a page with a
//!    text layer the model returns a grid of WORD IDS, never text; Rust fills
//!    the cells from pdfium's characters. The gate then proves the grid is
//!    physically possible: every ID is known and used once; every row's cells
//!    sit in one horizontal band and the bands are disjoint and top-to-bottom;
//!    every column's cells sit in one vertical band and the bands are disjoint
//!    and left-to-right; a spanning cell stays inside the bands it spans. This
//!    is what catches amounts swapped between rows, a "geen" moved to another
//!    cell, and an empty cell filled with a value from elsewhere: no bag of
//!    words can see a swap, but a swap breaks the geometry.
//!
//! 2. **Model-written text against a reference layer** (`check_text`), used
//!    only where there is no trustworthy text layer and a vision model wrote
//!    the text (a scan with an OCR layer to compare against):
//!    - output guards: finish reason, empty, a repeated tail (olmOCR-style);
//!    - digit bag: no digit the reference lacks (catches "I.3" → "1.3"), and
//!      ≥90 % of the reference digits present; list markers the model added
//!      ("1. ", "- ", "a) ") are ignored;
//!    - values (ADR-0015, `numbers`): every number the model wrote must read
//!      to a value present in the reference, counted as a MULTISET (catches
//!      `7.000,00` → `70.000,0`, `5.100,00` → `100`, a dropped digit);
//!    - tokens: multiset coverage ≥ 0.90 and novelty ≤ 0.08 (the spike's
//!      thresholds); the caller exempts furniture from the reference.
//!
//!    Bags cannot see a MOVED word ("geen" moved to another sentence). Vision
//!    text is therefore labelled `vision_transcribed`, never passed off as
//!    text-layer evidence.

use std::collections::{BTreeMap, BTreeSet};

use unicode_normalization::UnicodeNormalization;

use crate::numbers::numbers_in;

/// Which check failed. `as_str()` is what `Provenance::failed_check` carries.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Failure {
    FinishReason,
    Empty,
    Repetition,
    UnknownWord,
    DuplicateWord,
    EmptyGrid,
    GeometryRows,
    GeometryColumns,
    Span,
    /// A grid takes part of a base unit's words but not all of them.
    PartialUnit,
    /// A text-layer word inside a grid's box that the grid does not reference.
    GridCoverage,
    /// The model wrote text where the text layer must supply it.
    ModelTextOnTextLayer,
    /// The response lacks what the request asked for.
    Malformed,
    DuplicateResponse,
    DigitBag,
    ValueNovel,
    Coverage,
    Novelty,
}

impl Failure {
    pub fn as_str(self) -> &'static str {
        match self {
            Failure::FinishReason => "finish_reason",
            Failure::Empty => "empty",
            Failure::Repetition => "repetition",
            Failure::UnknownWord => "unknown_word",
            Failure::DuplicateWord => "duplicate_word",
            Failure::EmptyGrid => "empty_grid",
            Failure::GeometryRows => "geometry_rows",
            Failure::GeometryColumns => "geometry_columns",
            Failure::Span => "geometry_span",
            Failure::PartialUnit => "partial_unit",
            Failure::GridCoverage => "grid_coverage",
            Failure::ModelTextOnTextLayer => "model_text_on_text_layer",
            Failure::Malformed => "malformed_response",
            Failure::DuplicateResponse => "duplicate_response",
            Failure::DigitBag => "digit_bag",
            Failure::ValueNovel => "value_novel",
            Failure::Coverage => "coverage",
            Failure::Novelty => "novelty",
        }
    }
}

// ------------------------------------------------------------- guards ----

/// Finish reasons that mean "the model stopped on its own".
const STOP_REASONS: &[&str] = &["stop", "end_turn", "stop_sequence", "eos", "complete"];

pub fn guard_finish(finish_reason: Option<&str>) -> Result<(), Failure> {
    match finish_reason {
        None => Ok(()),
        Some(r) if STOP_REASONS.contains(&r.trim().to_lowercase().as_str()) => Ok(()),
        Some(_) => Err(Failure::FinishReason),
    }
}

/// Lower-cased letter/digit runs after NFKC and soft-hyphen removal (the
/// spike's token view).
pub fn tokens(text: &str) -> Vec<String> {
    let n: String = text
        .nfkc()
        .collect::<String>()
        .replace('\u{AD}', "")
        .to_lowercase();
    let mut out = Vec::new();
    let mut cur = String::new();
    for c in n.chars() {
        if c.is_alphanumeric() {
            cur.push(c);
        } else if !cur.is_empty() {
            out.push(std::mem::take(&mut cur));
        }
    }
    if !cur.is_empty() {
        out.push(cur);
    }
    out
}

/// The tail repeats one n-gram (n ≤ 12) at least 4 times, covering ≥30
/// tokens: a generation loop.
pub fn repeated_tail(toks: &[String]) -> bool {
    for n in 1..=12usize {
        if toks.len() < n * 4 {
            break;
        }
        let tail = &toks[toks.len() - n..];
        let mut reps = 1;
        let mut end = toks.len() - n;
        while end >= n && &toks[end - n..end] == tail {
            reps += 1;
            end -= n;
        }
        if reps >= 4 && reps * n >= 30 {
            return true;
        }
    }
    false
}

/// Guards every model-written text passes: finish reason, non-empty, no loop.
pub fn guard_text(text: &str, finish_reason: Option<&str>) -> Result<(), Failure> {
    guard_finish(finish_reason)?;
    let toks = tokens(text);
    if toks.is_empty() {
        return Err(Failure::Empty);
    }
    if repeated_tail(&toks) {
        return Err(Failure::Repetition);
    }
    Ok(())
}

// ------------------------------------------------------- bag checks ----

/// Drop list markers a model adds at line starts: "- ", "* ", "• ", "1. ",
/// "1) ", "a) ", "(a) ", "#" runs. "1.3 text" is NOT a marker.
pub fn strip_list_markers(text: &str) -> String {
    let mut out = String::new();
    for line in text.lines() {
        let mut t = line.trim_start().trim_start_matches('#').trim_start();
        loop {
            let before = t;
            for m in ["- ", "* ", "• ", "+ "] {
                if let Some(r) = t.strip_prefix(m) {
                    t = r.trim_start();
                }
            }
            let head: String = t.chars().take_while(|c| !c.is_whitespace()).collect();
            if !head.is_empty() && t.len() > head.len() {
                let core = head.trim_start_matches('(');
                let body = core.trim_end_matches(['.', ')']);
                let closed = core.len() > body.len() && core.len() - body.len() == 1;
                let numeric =
                    !body.is_empty() && body.len() <= 3 && body.bytes().all(|b| b.is_ascii_digit());
                let letter = body.len() == 1 && body.chars().all(|c| c.is_ascii_lowercase());
                if closed && (numeric || letter) {
                    t = t[head.len()..].trim_start();
                }
            }
            if t == before {
                break;
            }
        }
        out.push_str(t);
        out.push('\n');
    }
    out
}

pub fn digit_bag(text: &str) -> [usize; 10] {
    let mut bag = [0usize; 10];
    for c in text.nfkc() {
        if let Some(d) = c.to_digit(10) {
            if c.is_ascii_digit() {
                bag[d as usize] += 1;
            }
        }
    }
    bag
}

fn multiset<I: IntoIterator<Item = String>>(items: I) -> BTreeMap<String, usize> {
    let mut m = BTreeMap::new();
    for i in items {
        *m.entry(i).or_insert(0) += 1;
    }
    m
}

/// Σ min(cand, ref) / Σ ref and Σ max(0, cand − ref) / Σ cand.
fn cover_novel(cand: &BTreeMap<String, usize>, reference: &BTreeMap<String, usize>) -> (f64, f64) {
    let rsum: usize = reference.values().sum();
    let csum: usize = cand.values().sum();
    let hit: usize = reference
        .iter()
        .map(|(k, &r)| r.min(*cand.get(k).unwrap_or(&0)))
        .sum();
    let novel: usize = cand
        .iter()
        .map(|(k, &c)| c.saturating_sub(*reference.get(k).unwrap_or(&0)))
        .sum();
    let cov = if rsum == 0 {
        1.0
    } else {
        hit as f64 / rsum as f64
    };
    let nov = if csum == 0 {
        0.0
    } else {
        novel as f64 / csum as f64
    };
    (cov, nov)
}

pub const MIN_COVERAGE: f64 = 0.90;
pub const MAX_NOVELTY: f64 = 0.08;
pub const MIN_DIGIT_COVERAGE: f64 = 0.90;

/// Check model-written `candidate` against the `reference` text layer (both
/// read in `language`, ADR-0015). Order: digit bag, values, tokens.
pub fn check_text(candidate: &str, reference: &str, language: Option<&str>) -> Result<(), Failure> {
    let cand = strip_list_markers(candidate);
    let (cd, rd) = (digit_bag(&cand), digit_bag(reference));
    let rsum: usize = rd.iter().sum();
    if (0..10).any(|d| cd[d] > rd[d]) {
        return Err(Failure::DigitBag);
    }
    if rsum > 0 {
        let hit: usize = (0..10).map(|d| cd[d].min(rd[d])).sum();
        if (hit as f64) / (rsum as f64) < MIN_DIGIT_COVERAGE {
            return Err(Failure::DigitBag);
        }
    }
    let cv = multiset(numbers_in(&cand, language).into_iter().map(|r| r.key));
    let rv = multiset(numbers_in(reference, language).into_iter().map(|r| r.key));
    if cv.iter().any(|(k, &c)| c > *rv.get(k).unwrap_or(&0)) {
        return Err(Failure::ValueNovel);
    }
    let (cov, nov) = cover_novel(&multiset(tokens(&cand)), &multiset(tokens(reference)));
    if cov < MIN_COVERAGE {
        return Err(Failure::Coverage);
    }
    if nov > MAX_NOVELTY {
        return Err(Failure::Novelty);
    }
    Ok(())
}

// ----------------------------------------------------- geometry gate ----

/// A word's box, top-left origin: `[x0, y0, x1, y1]`.
pub type WordBox = [f64; 4];

#[derive(Debug, Clone, PartialEq)]
pub struct GridCell {
    pub words: Vec<String>,
    pub colspan: usize,
    pub rowspan: usize,
}

/// Band tolerance in points: tight glyph boxes of adjacent lines never
/// overlap by more than this.
pub const BAND_TOLERANCE: f64 = 1.0;

/// Where each cell landed: (row, col) of its top-left slot.
pub type Placement = Vec<Vec<(usize, usize)>>;

fn band(words: &[String], boxes: &BTreeMap<String, WordBox>, axis: usize) -> Option<(f64, f64)> {
    let mut it = words.iter().filter_map(|w| boxes.get(w));
    let first = it.next()?;
    let mut lo = first[axis];
    let mut hi = first[axis + 2];
    for b in it {
        lo = lo.min(b[axis]);
        hi = hi.max(b[axis + 2]);
    }
    Some((lo, hi))
}

/// Lay out spans (HTML table rules) and check the grid against the word boxes.
pub fn geometry_gate(
    rows: &[Vec<GridCell>],
    boxes: &BTreeMap<String, WordBox>,
) -> Result<Placement, Failure> {
    let mut seen = BTreeSet::new();
    let mut any = false;
    for row in rows {
        for cell in row {
            if cell.colspan == 0 || cell.rowspan == 0 {
                return Err(Failure::Span);
            }
            for w in &cell.words {
                if !boxes.contains_key(w) {
                    return Err(Failure::UnknownWord);
                }
                if !seen.insert(w.clone()) {
                    return Err(Failure::DuplicateWord);
                }
                any = true;
            }
        }
    }
    if !any {
        return Err(Failure::EmptyGrid);
    }
    // Placement with row/col spans.
    let mut occupied: BTreeSet<(usize, usize)> = BTreeSet::new();
    let mut placement: Placement = Vec::with_capacity(rows.len());
    for (r, row) in rows.iter().enumerate() {
        let mut c = 0usize;
        let mut places = Vec::with_capacity(row.len());
        for cell in row {
            while occupied.contains(&(r, c)) {
                c += 1;
            }
            places.push((r, c));
            for dr in 0..cell.rowspan {
                for dc in 0..cell.colspan {
                    occupied.insert((r + dr, c + dc));
                }
            }
            c += cell.colspan;
        }
        placement.push(places);
    }
    let n_rows = rows.len();
    let n_cols = occupied.iter().map(|&(_, c)| c + 1).max().unwrap_or(0);
    // Row bands (rowspan 1) and column bands (colspan 1).
    let mut row_band: Vec<Option<(f64, f64)>> =
        vec![None; n_rows.max(occupied.iter().map(|&(r, _)| r + 1).max().unwrap_or(0))];
    let mut col_band: Vec<Option<(f64, f64)>> = vec![None; n_cols];
    let merge = |slot: &mut Option<(f64, f64)>, b: (f64, f64)| {
        *slot = Some(match *slot {
            Some((lo, hi)) => (lo.min(b.0), hi.max(b.1)),
            None => b,
        });
    };
    for (r, row) in rows.iter().enumerate() {
        for (k, cell) in row.iter().enumerate() {
            let (pr, pc) = placement[r][k];
            if cell.rowspan == 1 {
                if let Some(b) = band(&cell.words, boxes, 1) {
                    merge(&mut row_band[pr], b);
                }
            }
            if cell.colspan == 1 {
                if let Some(b) = band(&cell.words, boxes, 0) {
                    merge(&mut col_band[pc], b);
                }
            }
        }
    }
    let ordered = |bands: &[Option<(f64, f64)>]| {
        let present: Vec<(f64, f64)> = bands.iter().flatten().copied().collect();
        present
            .windows(2)
            .all(|w| w[0].1 <= w[1].0 + BAND_TOLERANCE && w[0].0 < w[1].0)
    };
    if !ordered(&row_band) {
        return Err(Failure::GeometryRows);
    }
    if !ordered(&col_band) {
        return Err(Failure::GeometryColumns);
    }
    // Spanning cells stay inside the bands they span.
    for (r, row) in rows.iter().enumerate() {
        for (k, cell) in row.iter().enumerate() {
            let (pr, pc) = placement[r][k];
            let span_ok = |bands: &[Option<(f64, f64)>], from: usize, n: usize, axis: usize| {
                let covered: Vec<(f64, f64)> =
                    bands.iter().skip(from).take(n).flatten().copied().collect();
                let Some(b) = band(&cell.words, boxes, axis) else {
                    return true;
                };
                if covered.is_empty() {
                    return true;
                }
                // Neighbouring bands outside the span must not be entered.
                let before = bands[..from].iter().flatten().last().map(|x| x.1);
                let after = bands.iter().skip(from + n).flatten().next().map(|x| x.0);
                before.is_none_or(|e| b.0 >= e - BAND_TOLERANCE)
                    && after.is_none_or(|s| b.1 <= s + BAND_TOLERANCE)
            };
            if cell.rowspan > 1 && !span_ok(&row_band, pr, cell.rowspan, 1) {
                return Err(Failure::Span);
            }
            if cell.colspan > 1 && !span_ok(&col_band, pc, cell.colspan, 0) {
                return Err(Failure::Span);
            }
        }
    }
    Ok(placement)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn boxes() -> BTreeMap<String, WordBox> {
        // two columns × three rows, 20 pt row pitch
        let mut m = BTreeMap::new();
        for (r, y) in [100.0, 120.0, 140.0].iter().enumerate() {
            m.insert(format!("a{r}"), [72.0, *y, 120.0, y + 10.0]);
            m.insert(format!("b{r}"), [220.0, *y, 270.0, y + 10.0]);
        }
        m
    }

    fn cell(ws: &[&str]) -> GridCell {
        GridCell {
            words: ws.iter().map(|s| s.to_string()).collect(),
            colspan: 1,
            rowspan: 1,
        }
    }

    #[test]
    fn a_true_grid_passes_and_a_swap_fails() {
        let ok = vec![
            vec![cell(&["a0"]), cell(&["b0"])],
            vec![cell(&["a1"]), cell(&["b1"])],
        ];
        assert!(geometry_gate(&ok, &boxes()).is_ok());
        let swapped = vec![
            vec![cell(&["a0"]), cell(&["b1"])],
            vec![cell(&["a1"]), cell(&["b0"])],
        ];
        assert_eq!(
            geometry_gate(&swapped, &boxes()),
            Err(Failure::GeometryRows)
        );
        let cols = vec![vec![cell(&["b0"]), cell(&["a0"])]];
        assert_eq!(
            geometry_gate(&cols, &boxes()),
            Err(Failure::GeometryColumns)
        );
        let dup = vec![vec![cell(&["a0"]), cell(&["a0"])]];
        assert_eq!(geometry_gate(&dup, &boxes()), Err(Failure::DuplicateWord));
        let unk = vec![vec![cell(&["zz"])]];
        assert_eq!(geometry_gate(&unk, &boxes()), Err(Failure::UnknownWord));
    }

    #[test]
    fn a_colspan_header_is_allowed() {
        let mut head = cell(&["a0", "b0"]);
        head.colspan = 2;
        let g = vec![vec![head], vec![cell(&["a1"]), cell(&["b1"])]];
        assert!(geometry_gate(&g, &boxes()).is_ok());
    }

    #[test]
    fn list_markers_are_ignored_but_i3_is_not() {
        assert_eq!(
            strip_list_markers("1. Reiskosten\n- b) geen\n1.3 blijft"),
            "Reiskosten\ngeen\n1.3 blijft\n"
        );
        assert_eq!(
            check_text("artikel 1.3", "artikel I.3", Some("nl")),
            Err(Failure::DigitBag)
        );
    }

    #[test]
    fn value_and_token_checks() {
        let reference =
            "Reiskosten € 7.000,00 per jaar. Hotel € 5.100,00 per jaar. Diner € 1.250,00 vooraf.";
        assert_eq!(check_text(reference, reference, Some("nl")), Ok(()));
        let v = reference.replace("7.000,00", "70.000,0");
        assert_eq!(
            check_text(&v, reference, Some("nl")),
            Err(Failure::ValueNovel)
        );
        let v = reference.replace("5.100,00", "100");
        assert_eq!(
            check_text(&v, reference, Some("nl")),
            Err(Failure::DigitBag)
        );
        let v = reference.replace("1.250,00", "125,00");
        assert_eq!(
            check_text(&v, reference, Some("nl")),
            Err(Failure::ValueNovel)
        );
        let v = format!("{reference} Extra verzonnen zin met veel nieuwe woorden erin hier.");
        assert_eq!(check_text(&v, reference, Some("nl")), Err(Failure::Novelty));
    }

    #[test]
    fn guards() {
        assert_eq!(guard_text("ok", Some("length")), Err(Failure::FinishReason));
        assert_eq!(guard_text("  ", None), Err(Failure::Empty));
        let looped = format!("start {}", "de de de ".repeat(20));
        assert_eq!(guard_text(&looped, Some("stop")), Err(Failure::Repetition));
        assert_eq!(guard_text("Normal text.", Some("STOP")), Ok(()));
    }
}
