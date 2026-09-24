//! Reading order over a page's blocks (ADR-0017 decision 1; research §8 #9).
//!
//! 1. **Struct tree** — on a tagged page (≥50 % of the visible characters
//!    belong to a structure element), blocks follow the tree's pre-order.
//!    Untagged blocks (artifacts) keep their rule-based slot.
//! 2. **Rule-based** (after Docling `reading_order_rb.py`, MIT): block A
//!    precedes B when they overlap horizontally and A lies above B. A
//!    topological walk emits the successor of the block just emitted when
//!    there is one (stay in the column), else the left-most, top-most free
//!    block.
//! 3. **XY-cut** fallback — when the precedence graph has a cycle
//!    (overlapping blocks), recursive projection cuts at the widest gap,
//!    horizontal before vertical on ties (after XY-Cut++, arXiv 2504.10258;
//!    the pre-mask of cross-layout elements is not implemented).
//!
//! Every tie is broken by block index, so the order is deterministic.

type BBox = [f64; 4];

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Method {
    StructTree,
    RuleBased,
    XyCut,
}

impl Method {
    pub fn as_str(self) -> &'static str {
        match self {
            Method::StructTree => "struct_tree",
            Method::RuleBased => "rule_based",
            Method::XyCut => "xycut",
        }
    }
}

fn overlap(a: BBox, b: BBox) -> f64 {
    (a[2].min(b[2]) - a[0].max(b[0])).max(0.0)
}

/// Rule-based order, or None when the precedence graph has a cycle.
pub fn rule_based(boxes: &[BBox]) -> Option<Vec<usize>> {
    let n = boxes.len();
    let tol = 2.0;
    let mut succ: Vec<Vec<usize>> = vec![vec![]; n];
    let mut indeg = vec![0usize; n];
    for i in 0..n {
        for j in 0..n {
            if i != j && overlap(boxes[i], boxes[j]) > 1.0 && boxes[i][3] <= boxes[j][1] + tol {
                // Tie (both "above" each other within tol): lower index first.
                if boxes[j][3] <= boxes[i][1] + tol && j < i {
                    continue;
                }
                succ[i].push(j);
                indeg[j] += 1;
            }
        }
    }
    let mut done = vec![false; n];
    let mut out = Vec::with_capacity(n);
    let mut last: Option<usize> = None;
    while out.len() < n {
        let free: Vec<usize> = (0..n).filter(|&k| !done[k] && indeg[k] == 0).collect();
        if free.is_empty() {
            return None;
        }
        let from_last: Option<usize> = last.and_then(|l| {
            free.iter()
                .copied()
                .filter(|k| succ[l].contains(k))
                .min_by(|&a, &b| {
                    boxes[a][1]
                        .total_cmp(&boxes[b][1])
                        .then(boxes[a][0].total_cmp(&boxes[b][0]))
                        .then(a.cmp(&b))
                })
        });
        let pick = from_last.unwrap_or_else(|| {
            *free
                .iter()
                .min_by(|&&a, &&b| {
                    boxes[a][0]
                        .total_cmp(&boxes[b][0])
                        .then(boxes[a][1].total_cmp(&boxes[b][1]))
                        .then(a.cmp(&b))
                })
                .unwrap()
        });
        done[pick] = true;
        for &s in &succ[pick] {
            indeg[s] -= 1;
        }
        out.push(pick);
        last = Some(pick);
    }
    Some(out)
}

/// Gaps in the projection of `idx` onto axis (0 = x, 1 = y): (gap width, cut).
fn widest_gap(boxes: &[BBox], idx: &[usize], axis: usize) -> Option<(f64, f64)> {
    let mut spans: Vec<(f64, f64)> = idx
        .iter()
        .map(|&i| (boxes[i][axis], boxes[i][axis + 2]))
        .collect();
    spans.sort_by(|a, b| a.0.total_cmp(&b.0).then(a.1.total_cmp(&b.1)));
    let mut best: Option<(f64, f64)> = None;
    let mut reach = spans.first()?.1;
    for s in spans.iter().skip(1) {
        if s.0 > reach {
            let g = s.0 - reach;
            if best.is_none_or(|(bg, _)| g > bg) {
                best = Some((g, (s.0 + reach) / 2.0));
            }
        }
        reach = reach.max(s.1);
    }
    best
}

fn xycut_rec(boxes: &[BBox], idx: Vec<usize>, out: &mut Vec<usize>, depth: u32) {
    if idx.len() <= 1 || depth > 64 {
        let mut idx = idx;
        idx.sort_by(|&a, &b| {
            boxes[a][1]
                .total_cmp(&boxes[b][1])
                .then(boxes[a][0].total_cmp(&boxes[b][0]))
                .then(a.cmp(&b))
        });
        out.extend(idx);
        return;
    }
    let hy = widest_gap(boxes, &idx, 1);
    let vx = widest_gap(boxes, &idx, 0);
    let (axis, cut) = match (hy, vx) {
        (Some((gy, cy)), Some((gx, cx))) => {
            if gx > gy {
                (0, cx)
            } else {
                (1, cy)
            }
        }
        (Some((_, cy)), None) => (1, cy),
        (None, Some((_, cx))) => (0, cx),
        (None, None) => {
            let mut idx = idx;
            idx.sort_by(|&a, &b| {
                boxes[a][1]
                    .total_cmp(&boxes[b][1])
                    .then(boxes[a][0].total_cmp(&boxes[b][0]))
                    .then(a.cmp(&b))
            });
            out.extend(idx);
            return;
        }
    };
    let (first, second): (Vec<usize>, Vec<usize>) =
        idx.into_iter().partition(|&i| boxes[i][axis + 2] <= cut);
    xycut_rec(boxes, first, out, depth + 1);
    xycut_rec(boxes, second, out, depth + 1);
}

pub fn xycut(boxes: &[BBox]) -> Vec<usize> {
    let mut out = Vec::with_capacity(boxes.len());
    xycut_rec(boxes, (0..boxes.len()).collect(), &mut out, 0);
    out
}

/// Order `boxes`. `struct_key[i]` is the struct-tree pre-order index of block
/// i on a tagged page (None for artifacts); `use_struct` selects method 1.
pub fn order(
    boxes: &[BBox],
    struct_key: &[Option<usize>],
    use_struct: bool,
) -> (Vec<usize>, Method) {
    let (geo, method) = match rule_based(boxes) {
        Some(o) => (o, Method::RuleBased),
        None => (xycut(boxes), Method::XyCut),
    };
    if !use_struct {
        return (geo, method);
    }
    // Keyed blocks take the keyed slots of the geometric order, in key order.
    let mut keyed: Vec<usize> = geo
        .iter()
        .copied()
        .filter(|&i| struct_key[i].is_some())
        .collect();
    keyed.sort_by_key(|&i| (struct_key[i], i));
    let mut it = keyed.into_iter();
    let out = geo
        .iter()
        .map(|&i| {
            if struct_key[i].is_some() {
                it.next().unwrap()
            } else {
                i
            }
        })
        .collect();
    (out, Method::StructTree)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn two_columns_under_a_title() {
        let b = vec![
            [72.0, 40.0, 520.0, 60.0],    // 0 title (full width)
            [300.0, 80.0, 520.0, 200.0],  // 1 right col top
            [72.0, 80.0, 280.0, 200.0],   // 2 left col top
            [72.0, 210.0, 280.0, 300.0],  // 3 left col bottom
            [300.0, 210.0, 520.0, 300.0], // 4 right col bottom
            [72.0, 800.0, 520.0, 810.0],  // 5 footer
        ];
        assert_eq!(rule_based(&b).unwrap(), vec![0, 2, 3, 1, 4, 5]);
        assert_eq!(xycut(&b), vec![0, 2, 3, 1, 4, 5]);
    }

    #[test]
    fn struct_order_wins_on_tagged_pages() {
        let b = vec![[72.0, 40.0, 200.0, 60.0], [72.0, 80.0, 200.0, 100.0]];
        let (o, m) = order(&b, &[Some(5), Some(1)], true);
        assert_eq!((o, m), (vec![1, 0], Method::StructTree));
    }
}
