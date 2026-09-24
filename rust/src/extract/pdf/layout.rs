//! Layout text layer: characters → baseline lines → segments → blocks.
//!
//! Pure functions over `RawPage` (geometry already rounded to 0.01 in
//! `raw.rs`). Nothing here iterates a hash map, reads a clock or draws a
//! random number; ties are broken by character index, so the result is a
//! function of the input bytes only.
//!
//! - A **line** is every visible character sharing a baseline (within 0.3 of
//!   the font size).
//! - A **segment** is a run of a line with no gap wider than 1.5 × font size,
//!   so two text columns on one baseline become two segments.
//! - A **block** stacks segments vertically: same column (horizontal overlap or
//!   aligned left edge), same style (size within 10 %, same boldness), a line
//!   pitch no larger than 1.35 × the page's modal pitch, and — on a tagged
//!   page — the same structure element.
//!
//! `layout_text` renders the lines back into a monospaced page, the
//! equivalent of `pdftotext -layout` (column positions kept with spaces).

use super::raw::{RawChar, RawPage};

/// The hyphen marker pdfium substitutes for a line-end hyphen.
pub const HYPHEN_MARK: char = '\u{2}';

#[derive(Debug, Clone, PartialEq)]
pub struct Segment {
    /// Indices into `RawPage::chars`, left to right.
    pub chars: Vec<usize>,
    /// Text with single spaces between words; a pdfium hyphen stays as
    /// `HYPHEN_MARK`.
    pub text: String,
    pub bbox: [f64; 4],
    pub baseline: f64,
    pub size: f64,
    pub bold: bool,
    /// Dominant marked-content ID (-1 when untagged).
    pub mcid: i32,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Block {
    /// Indices into the page's segment list, top to bottom.
    pub segs: Vec<usize>,
    pub bbox: [f64; 4],
    pub size: f64,
    pub bold: bool,
    /// Struct-tree element index shared by the block (tagged pages), else None.
    pub elem: Option<usize>,
}

pub struct PageLayout {
    pub segments: Vec<Segment>,
    /// Line groups: indices into `segments`, one entry per baseline.
    pub lines: Vec<Vec<usize>>,
    pub blocks: Vec<Block>,
    /// Modal line pitch on the page (baseline to baseline).
    pub pitch: f64,
}

fn visible(c: &RawChar) -> bool {
    !c.generated && !c.rotated && (c.hyphen || !c.ch.is_whitespace()) && c.x1 > c.x0 - 0.001
}

/// Most frequent value after rounding to 0.5, ties to the larger value.
pub fn mode_half(values: impl Iterator<Item = (f64, usize)>) -> Option<f64> {
    let mut hist: Vec<(i64, usize)> = Vec::new();
    for (v, w) in values {
        let k = (v * 2.0).round() as i64;
        match hist.iter_mut().find(|(key, _)| *key == k) {
            Some(e) => e.1 += w,
            None => hist.push((k, w)),
        }
    }
    hist.sort();
    hist.iter()
        .max_by(|a, b| a.1.cmp(&b.1).then(a.0.cmp(&b.0)))
        .map(|(k, _)| *k as f64 / 2.0)
}

fn union(a: [f64; 4], b: [f64; 4]) -> [f64; 4] {
    [
        a[0].min(b[0]),
        a[1].min(b[1]),
        a[2].max(b[2]),
        a[3].max(b[3]),
    ]
}

fn build_segment(page: &RawPage, idx: Vec<usize>) -> Segment {
    let chars = &page.chars;
    let mut text = String::new();
    let mut bbox = [f64::MAX, f64::MAX, f64::MIN, f64::MIN];
    let mut prev: Option<usize> = None;
    for &i in &idx {
        let c = &chars[i];
        if let Some(p) = prev {
            let pc = &chars[p];
            let gap = c.lx0 - pc.lx1;
            let size = c.size.max(pc.size).max(1.0);
            // A space in the stream right before this char, when the two chars are
            // stream-adjacent apart from whitespace, or a geometric word gap.
            let stream_space =
                c.space_before && i > p && chars[p + 1..i].iter().all(|x| x.ch.is_whitespace());
            if gap > 0.1 * size || (stream_space && gap > -0.01 * size) {
                text.push(' ');
            }
        }
        text.push(if c.hyphen { HYPHEN_MARK } else { c.ch });
        bbox = union(bbox, [c.x0, c.y0, c.x1, c.y1]);
        prev = Some(i);
    }
    let size = mode_half(idx.iter().map(|&i| (chars[i].size, 1))).unwrap_or(0.0);
    let letters: Vec<&RawChar> = idx
        .iter()
        .map(|&i| &chars[i])
        .filter(|c| c.ch.is_alphanumeric())
        .collect();
    let bold =
        !letters.is_empty() && letters.iter().filter(|c| c.bold).count() * 10 >= letters.len() * 9;
    let mut mcids: Vec<(i32, usize)> = Vec::new();
    for &i in &idx {
        let m = chars[i].mcid;
        if m < 0 {
            continue;
        }
        match mcids.iter_mut().find(|(k, _)| *k == m) {
            Some(e) => e.1 += 1,
            None => mcids.push((m, 1)),
        }
    }
    // Dominant MCID; ties to the first seen (left-most) — deterministic.
    let mcid = mcids
        .iter()
        .fold(None::<(i32, usize)>, |best, &(m, n)| match best {
            Some((_, bn)) if bn >= n => best,
            _ => Some((m, n)),
        })
        .map(|(m, _)| m)
        .unwrap_or(-1);
    let baseline = mode_half(idx.iter().map(|&i| (chars[i].baseline, 1))).unwrap_or(bbox[3]);
    Segment {
        chars: idx,
        text,
        bbox,
        baseline,
        size,
        bold,
        mcid,
    }
}

/// Group a page's visible characters into baseline lines and segments.
/// Also returns how many duplicate glyphs (drawn twice at one spot) were dropped.
pub fn segments(page: &RawPage) -> (Vec<Segment>, Vec<Vec<usize>>, usize) {
    let mut idx: Vec<usize> = (0..page.chars.len())
        .filter(|&i| visible(&page.chars[i]))
        .collect();
    let c = &page.chars;
    // Fake bold (the same glyph drawn twice at ~the same spot) counts once.
    idx.sort_by(|&a, &b| {
        c[a].baseline
            .total_cmp(&c[b].baseline)
            .then(c[a].x0.total_cmp(&c[b].x0))
            .then(a.cmp(&b))
    });
    // Baseline groups.
    let mut groups: Vec<Vec<usize>> = Vec::new();
    for i in idx {
        let tol = 0.3 * c[i].size.max(1.0);
        match groups.last_mut() {
            Some(g) if (c[i].baseline - c[g[0]].baseline).abs() <= tol => g.push(i),
            _ => groups.push(vec![i]),
        }
    }
    let mut segs = Vec::new();
    let mut lines = Vec::new();
    let mut dups = 0usize;
    for mut g in groups {
        g.sort_by(|&a, &b| c[a].x0.total_cmp(&c[b].x0).then(a.cmp(&b)));
        let before = g.len();
        g.dedup_by(|b, a| {
            c[*a].ch == c[*b].ch
                && (c[*a].x0 - c[*b].x0).abs() < 0.5
                && (c[*a].y0 - c[*b].y0).abs() < 0.5
        });
        dups += before - g.len();
        let mut line = Vec::new();
        let mut run: Vec<usize> = Vec::new();
        for i in g {
            if let Some(&p) = run.last() {
                let gap = c[i].lx0 - c[p].lx1;
                if gap > 1.5 * c[i].size.max(c[p].size).max(1.0) {
                    line.push(segs.len());
                    segs.push(build_segment(page, std::mem::take(&mut run)));
                }
            }
            run.push(i);
        }
        if !run.is_empty() {
            line.push(segs.len());
            segs.push(build_segment(page, run));
        }
        lines.push(line);
    }
    (segs, lines, dups)
}

fn x_overlap(a: [f64; 4], b: [f64; 4]) -> f64 {
    (a[2].min(b[2]) - a[0].max(b[0])).max(0.0)
}

/// A bullet glyph (U+F0B7 is the Symbol-font bullet Word emits).
pub fn is_bullet(c: char) -> bool {
    matches!(
        c,
        '•' | '●' | '▪' | '■' | '◦' | '‣' | '–' | '—' | '*' | '·' | '\u{F0B7}' | '-'
    )
}

/// Does this segment open a list item?
pub fn starts_list_item(text: &str) -> bool {
    let t = text.trim_start();
    let mut chars = t.chars();
    let first = match chars.next() {
        Some(ch) => ch,
        None => return false,
    };
    if is_bullet(first) {
        return chars.next().is_some_and(|c| c == ' ');
    }
    // "1." "1)" "a)" "(a)" "(1)" "iv." followed by a space.
    let head: String = t.chars().take_while(|c| !c.is_whitespace()).collect();
    if head.len() > 5 || head.len() < 2 || t.len() == head.len() {
        return false;
    }
    let core = head.trim_start_matches('(');
    let (body, tail) = core.split_at(core.len() - 1);
    if !matches!(tail, ")" | ".") || body.is_empty() {
        return false;
    }
    let numeric = body.chars().all(|c| c.is_ascii_digit());
    let alpha = body.len() == 1 && body.chars().all(|c| c.is_ascii_lowercase());
    let roman = body.chars().all(|c| matches!(c, 'i' | 'v' | 'x')) && body.len() <= 4;
    // "1." alone is ambiguous with section numbering; only ")" forms and
    // lower-case letters/romans are list markers here.
    (numeric && tail == ")") || alpha || (roman && tail == ")")
}

/// The modal baseline pitch between vertically adjacent same-column segments.
fn modal_pitch(segs: &[Segment], lines: &[Vec<usize>]) -> f64 {
    let mut pitches = Vec::new();
    for w in lines.windows(2) {
        for &a in &w[0] {
            for &b in &w[1] {
                let (sa, sb) = (&segs[a], &segs[b]);
                if x_overlap(sa.bbox, sb.bbox) > 0.0 && (sa.size - sb.size).abs() < 0.5 {
                    let d = sb.baseline - sa.baseline;
                    if d > 0.0 && d < 3.0 * sa.size.max(1.0) {
                        pitches.push((d, 1));
                    }
                }
            }
        }
    }
    let body = mode_half(segs.iter().map(|s| (s.size, s.chars.len()))).unwrap_or(10.0);
    mode_half(pitches.into_iter()).unwrap_or(1.25 * body.max(1.0))
}

/// Stack segments into blocks. `elem_of` maps a segment's MCID to a
/// struct-element index on tagged pages.
pub fn blocks(
    segs: &[Segment],
    lines: &[Vec<usize>],
    elem_of: &dyn Fn(i32) -> Option<usize>,
) -> (Vec<Block>, f64) {
    let pitch = modal_pitch(segs, lines);
    let mut blocks: Vec<Block> = Vec::new();
    for line in lines {
        for &si in line {
            let s = &segs[si];
            let elem = elem_of(s.mcid);
            let list_start = starts_list_item(&s.text);
            let mut best: Option<(usize, f64)> = None;
            for (bi, b) in blocks.iter().enumerate() {
                let last = &segs[*b.segs.last().unwrap()];
                let d = s.baseline - last.baseline;
                let same_col = {
                    let ov = x_overlap(b.bbox, s.bbox);
                    let narrow = (s.bbox[2] - s.bbox[0]).min(b.bbox[2] - b.bbox[0]).max(1.0);
                    ov >= 0.5 * narrow || (s.bbox[0] - b.bbox[0]).abs() <= 2.0 * s.size.max(1.0)
                };
                let same_style =
                    (s.size - b.size).abs() <= 0.1 * b.size.max(1.0) && s.bold == b.bold;
                let same_elem = match (elem, b.elem) {
                    (Some(x), Some(y)) => x == y,
                    (None, None) => true,
                    _ => false,
                };
                if d > 0.0
                    && d <= 1.35 * pitch.max(s.size)
                    && same_col
                    && same_style
                    && same_elem
                    && !list_start
                {
                    // Prefer the nearest block above, then the lower index.
                    if best.is_none_or(|(_, bd)| d < bd) {
                        best = Some((bi, d));
                    }
                }
            }
            match best {
                Some((bi, _)) => {
                    let b = &mut blocks[bi];
                    b.segs.push(si);
                    b.bbox = union(b.bbox, s.bbox);
                }
                None => blocks.push(Block {
                    segs: vec![si],
                    bbox: s.bbox,
                    size: s.size,
                    bold: s.bold,
                    elem,
                }),
            }
        }
    }
    (blocks, pitch)
}

pub fn layout(page: &RawPage, elem_of: &dyn Fn(i32) -> Option<usize>) -> PageLayout {
    let (segments, lines, _) = segments(page);
    let (blocks, pitch) = blocks(&segments, &lines, elem_of);
    PageLayout {
        segments,
        lines,
        blocks,
        pitch,
    }
}

/// The page rendered as monospaced text with column positions kept, the
/// equivalent of `pdftotext -layout`. Hyphen markers print as `-`.
pub fn layout_text(page: &RawPage, pl: &PageLayout) -> String {
    let widths: Vec<(f64, usize)> = page
        .chars
        .iter()
        .filter(|c| visible(c) && c.ch.is_alphanumeric())
        .map(|c| (c.x1 - c.x0, 1))
        .collect();
    let cw = mode_half(widths.into_iter()).unwrap_or(5.0).max(2.0);
    let mut out = String::new();
    let mut prev_baseline: Option<f64> = None;
    for line in &pl.lines {
        let Some(&first) = line.first() else { continue };
        let base = pl.segments[first].baseline;
        if let Some(pb) = prev_baseline {
            if base - pb > 1.8 * pl.pitch {
                out.push('\n');
            }
        }
        prev_baseline = Some(base);
        let mut row = String::new();
        for &si in line {
            let s = &pl.segments[si];
            let col = (s.bbox[0] / cw).round().max(0.0) as usize;
            let cur = row.chars().count();
            if col > cur {
                row.push_str(&" ".repeat(col - cur));
            } else if cur > 0 {
                row.push(' ');
            }
            row.push_str(&s.text.replace(HYPHEN_MARK, "-"));
        }
        out.push_str(row.trim_end());
        out.push('\n');
    }
    out
}
