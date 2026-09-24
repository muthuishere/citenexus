//! Table acceptance measurement through the Rust output. It prints COUNTS,
//! SHAPES and SCORES ONLY: no cell values, no file names (tables are T1..Tn).
//!
//! ```text
//! PDFIUM_DYNAMIC_LIB_PATH=... cargo run --profile measure --features pdf --example pdf_tables -- \
//!     <originals-dir> <manifest.json> <measure_tables.py> <gt-md-dir> [--lang nl]
//! ```
//!
//! The ground-truth map (hand-written GT markdown file -> file_id) is PARSED
//! from spike 185's `measure_tables.py` at run time so client file names never
//! enter this repository. `score` is a line-for-line port of that script's
//! `score()` (cells: each GT row matched to the best candidate row, same
//! column, normalised equality; rows: GT row's non-empty cells occur in order
//! in one candidate row). Candidate markdown = every unit's markdown joined,
//! deterministic path only (`pdf_units`, no model).
//!
//! Positional integrity: every cell of every emitted table must be made of
//! text-layer words (from pdfium chars, `diag::page_words`) whose boxes lie
//! inside the table's bbox, each word used once.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use citenexus_core::checks::pipe_grid;
use citenexus_core::extract::pdf::{diag, pdf_prepare, pdf_units};
use citenexus_core::units::*;
use unicode_normalization::UnicodeNormalization;

fn norm(c: &str) -> String {
    let mut s: String = c
        .nfkc()
        .collect::<String>()
        .replace('\u{2}', "")
        .replace("**", "")
        .replace('\\', "");
    // (\d)([.,]) (\d) -> \1\2\3
    let ch: Vec<char> = s.chars().collect();
    let mut out = String::new();
    let mut i = 0;
    while i < ch.len() {
        if i >= 1
            && i + 2 < ch.len()
            && ch[i - 1].is_ascii_digit()
            && (ch[i] == '.' || ch[i] == ',')
            && ch[i + 1] == ' '
            && ch[i + 2].is_ascii_digit()
        {
            out.push(ch[i]);
            i += 2;
            continue;
        }
        out.push(ch[i]);
        i += 1;
    }
    s = out;
    for br in ["<br/>", "<br />", "<br>"] {
        s = s.replace(br, " ");
    }
    s.split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .to_lowercase()
}

fn is_sep(c: &str) -> bool {
    let t = c.trim_start_matches(':').trim_end_matches(':');
    t.len() >= 2 && t.chars().all(|x| x == '-') && c.len() - t.len() <= 2
}

/// The script's `tables()`: every pipe table as rows of cells.
fn tables(md: &str) -> Vec<Vec<Vec<String>>> {
    let mut out = Vec::new();
    let mut cur: Vec<Vec<String>> = Vec::new();
    for line in md.lines() {
        let s = line.trim();
        if s.starts_with('|') && s.matches('|').count() >= 2 {
            let cells: Vec<String> = s
                .trim_matches('|')
                .split('|')
                .map(|c| c.trim().to_string())
                .collect();
            if cells.iter().all(|c| is_sep(c) || c.is_empty())
                && cells.iter().any(|c| !c.is_empty())
            {
                continue;
            }
            cur.push(cells);
        } else if !cur.is_empty() {
            out.push(std::mem::take(&mut cur));
        }
    }
    if !cur.is_empty() {
        out.push(cur);
    }
    out
}

struct Score {
    gt_cells: usize,
    matched: usize,
    gt_rows: usize,
    row_hits: usize,
    best_shape: String,
    gt_shape: String,
    n_tables: usize,
}

fn score(gt_md: &str, cand_md: &str) -> Score {
    let gts = tables(gt_md);
    let cands = tables(cand_md);
    let (mut gt_cells, mut matched) = (0, 0);
    let mut best_shape = "-".to_string();
    for gt in &gts {
        let mut best: (i64, Option<&Vec<Vec<String>>>) = (-1, None);
        for ct in &cands {
            let mut s = 0i64;
            for grow in gt {
                let g: Vec<String> = grow.iter().map(|x| norm(x)).collect();
                s += ct
                    .iter()
                    .map(|c| {
                        g.iter()
                            .enumerate()
                            .filter(|(j, x)| *j < c.len() && norm(&c[*j]) == **x)
                            .count() as i64
                    })
                    .max()
                    .unwrap_or(0);
            }
            if s > best.0 {
                best = (s, Some(ct));
            }
        }
        gt_cells += gt.iter().map(|r| r.len()).sum::<usize>();
        matched += best.0.max(0) as usize;
        if let Some(t) = best.1 {
            best_shape = format!(
                "{}x{}",
                t.len(),
                t.iter().map(|r| r.len()).max().unwrap_or(0)
            );
        }
    }
    let crow: Vec<Vec<String>> = cands
        .iter()
        .flatten()
        .map(|r| r.iter().map(|c| norm(c)).collect())
        .collect();
    let in_order = |g: &[String], c: &[String]| {
        let mut k = 0;
        for x in c {
            if k < g.len() && *x == g[k] {
                k += 1;
            }
        }
        k == g.len()
    };
    let gt_rows: Vec<Vec<String>> = gts
        .iter()
        .flatten()
        .map(|r| {
            r.iter()
                .map(|c| norm(c))
                .filter(|c| !c.is_empty())
                .collect()
        })
        .collect();
    let row_hits = gt_rows
        .iter()
        .filter(|g| !g.is_empty() && crow.iter().any(|c| in_order(g, c)))
        .count();
    let gt_shape = gts
        .iter()
        .map(|t| {
            format!(
                "{}x{}",
                t.len(),
                t.iter().map(|r| r.len()).max().unwrap_or(0)
            )
        })
        .collect::<Vec<_>>()
        .join(", ");
    Score {
        gt_cells,
        matched,
        gt_rows: gt_rows.len(),
        row_hits,
        best_shape,
        gt_shape,
        n_tables: cands.len(),
    }
}

/// Parse `GT = { "x.md": "file-id", ... }` out of the spike script.
fn gt_map(script: &Path) -> Vec<(String, String)> {
    let src = std::fs::read_to_string(script).expect("measure_tables.py");
    let start = src.find("GT = {").expect("GT map");
    let end = start + src[start..].find('}').expect("GT map end");
    src[start..end]
        .lines()
        .filter_map(|l| {
            let q: Vec<&str> = l.split('"').collect();
            (q.len() >= 5 && q[1].ends_with(".md")).then(|| (q[1].to_string(), q[3].to_string()))
        })
        .collect()
}

/// Share of emitted table cells made of text-layer words inside the table box.
fn integrity(bytes: &[u8], opts: &PdfOptions, out: &PdfUnitsOutput) -> (usize, usize) {
    let words = diag::page_words(bytes, opts).unwrap_or_default();
    let (mut ok, mut total) = (0, 0);
    for u in out.units.iter().filter(|u| u.kind == UnitKind::Table) {
        let (Some(p), Some(b)) = (u.page, u.bbox) else {
            continue;
        };
        let mut pool: BTreeMap<String, usize> = BTreeMap::new();
        for w in &words[(p - 1) as usize] {
            let (cx, cy) = ((w.bbox[0] + w.bbox[2]) / 2.0, (w.bbox[1] + w.bbox[3]) / 2.0);
            if cx >= b[0] - 1.0 && cx <= b[2] + 1.0 && cy >= b[1] - 1.0 && cy <= b[3] + 1.0 {
                *pool.entry(w.text.clone()).or_default() += 1;
            }
        }
        for cell in pipe_grid(&u.markdown).into_iter().flatten() {
            if cell.is_empty() {
                continue;
            }
            total += 1;
            let mut good = true;
            for tok in cell.split_whitespace() {
                match pool.get_mut(tok) {
                    Some(n) if *n > 0 => *n -= 1,
                    _ => good = false,
                }
            }
            ok += good as usize;
        }
    }
    (ok, total)
}

fn main() {
    let a: Vec<String> = std::env::args().skip(1).collect();
    let (dir, manifest, script, gt_dir) = (
        PathBuf::from(&a[0]),
        PathBuf::from(&a[1]),
        PathBuf::from(&a[2]),
        PathBuf::from(&a[3]),
    );
    let lang = a
        .iter()
        .position(|x| x == "--lang")
        .map(|i| a[i + 1].clone())
        .or(Some("nl".into()));
    let opts = PdfOptions {
        language: lang,
        ..Default::default()
    };
    let man: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(&manifest).unwrap()).unwrap();
    let path_of = |fid: &str| -> Option<PathBuf> {
        man.as_array()?
            .iter()
            .find(|e| e["file_id"] == fid)
            .and_then(|e| {
                let p = e["path"].as_str()?;
                Some(dir.join(Path::new(p).file_name()?))
            })
    };

    // --- acceptance: the GT tables
    let gt = gt_map(&script);
    let (mut cells, mut cell_tot, mut rows, mut row_tot) = (0, 0, 0, 0);
    println!("GT tables: {}", gt.len());
    for (k, (gtf, fid)) in gt.iter().enumerate() {
        let gt_md = std::fs::read_to_string(gt_dir.join(gtf)).unwrap_or_default();
        let (md, note) = match path_of(fid).and_then(|p| std::fs::read(p).ok()) {
            Some(bytes) => match pdf_units(&bytes, &opts) {
                Ok(out) => {
                    let srcs: Vec<String> = out
                        .units
                        .iter()
                        .filter(|u| u.kind == UnitKind::Table)
                        .map(|u| format!("{:?}", u.provenance.table_source.unwrap()).to_lowercase())
                        .collect();
                    let routes: Vec<String> = out
                        .pages
                        .iter()
                        .map(|p| format!("{:?}", p.route).to_lowercase())
                        .collect();
                    let md = out
                        .units
                        .iter()
                        .map(|u| u.markdown.as_str())
                        .collect::<Vec<_>>()
                        .join("\n\n");
                    (md, format!("tables {srcs:?} routes {routes:?}"))
                }
                Err(_) => (String::new(), "pdf error".into()),
            },
            None => (String::new(), "original missing".into()),
        };
        let s = score(&gt_md, &md);
        if std::env::var_os("TABLES_DEBUG").is_some() {
            // mismatch kinds for each GT row against its best candidate row
            let cands = tables(&md);
            let mut kinds: BTreeMap<&str, usize> = BTreeMap::new();
            for gt in tables(&gt_md) {
                for grow in &gt {
                    let g: Vec<String> = grow.iter().map(|x| norm(x)).collect();
                    let best = cands.iter().flatten().max_by_key(|c| {
                        g.iter()
                            .enumerate()
                            .filter(|(j, x)| *j < c.len() && norm(&c[*j]) == **x)
                            .count()
                    });
                    let Some(c) = best else { continue };
                    for (j, x) in g.iter().enumerate() {
                        let y = c.get(j).map(|v| norm(v)).unwrap_or_default();
                        if *x == y {
                            continue;
                        }
                        let digits =
                            |t: &str| t.chars().filter(|c| c.is_ascii_digit()).collect::<String>();
                        let k = if y.is_empty() {
                            "candidate empty"
                        } else if x.is_empty() {
                            "gt empty"
                        } else if y.contains(x.as_str()) {
                            "candidate contains gt (extra text)"
                        } else if x.contains(y.as_str()) {
                            "gt contains candidate (text missing)"
                        } else if digits(x) == digits(&y) && !digits(x).is_empty() {
                            "same digits, other chars differ"
                        } else {
                            let tx: std::collections::BTreeSet<&str> =
                                x.split_whitespace().collect();
                            let ty: std::collections::BTreeSet<&str> =
                                y.split_whitespace().collect();
                            let inter = tx.intersection(&ty).count();
                            let dx: String = x.chars().filter(|c| c.is_ascii_digit()).collect();
                            let dy: String = y.chars().filter(|c| c.is_ascii_digit()).collect();
                            println!(
                                "      digits: gt {} cand {} equal {}",
                                dx.len(),
                                dy.len(),
                                dx == dy
                            );
                            println!(
                                "      different: row {} col {} gt {} tokens / cand {} tokens, shared {inter}, gt row idx in table {}",
                                gt.iter().position(|r| r == grow).unwrap_or(0),
                                j,
                                tx.len(),
                                ty.len(),
                                cands.iter().flatten().position(|r| std::ptr::eq(r, c)).unwrap_or(0)
                            );
                            "different"
                        };
                        *kinds.entry(k).or_default() += 1;
                    }
                }
            }
            println!("    mismatch kinds {kinds:?}");
            if let Some(bytes) = path_of(fid).and_then(|p| std::fs::read(p).ok()) {
                if let Ok(d) = diag::tables(&bytes, &opts) {
                    for p in d {
                        println!(
                            "    page {} accepted {:?} uncertain {} rejected {:?}",
                            p.page, p.accepted, p.uncertain, p.rejected
                        );
                    }
                }
            }
            if let Some(bytes) = path_of(fid).and_then(|p| std::fs::read(p).ok()) {
                let r = citenexus_core::extract::pdf::raw::read(&bytes).unwrap();
                for (pi, pg) in r.pages.iter().enumerate() {
                    let mut per_tr: Vec<usize> = Vec::new();
                    let mut spans: BTreeMap<(u32, u32), usize> = BTreeMap::new();
                    for n in &pg.struct_nodes {
                        if n.kind == "TR" {
                            per_tr.push(0);
                        } else if n.kind == "TD" || n.kind == "TH" {
                            if let Some(l) = per_tr.last_mut() {
                                *l += 1;
                            }
                            *spans.entry((n.rowspan, n.colspan)).or_default() += 1;
                        }
                    }
                    if !per_tr.is_empty() {
                        println!("    struct p{pi}: cells per TR {per_tr:?}; (rowspan,colspan) counts {spans:?}");
                    }
                }
            }
            // per candidate column: non-empty share (no values)
            for t in tables(&md) {
                let cols = t.iter().map(|r| r.len()).max().unwrap_or(0);
                let fill: Vec<String> = (0..cols)
                    .map(|c| {
                        format!(
                            "{:.2}",
                            t.iter()
                                .filter(|r| r.get(c).is_some_and(|x| !x.is_empty()))
                                .count() as f64
                                / t.len() as f64
                        )
                    })
                    .collect();
                println!("    candidate {}x{} column fill {:?}", t.len(), cols, fill);
                let pat: Vec<String> = t
                    .iter()
                    .map(|r| {
                        r.iter()
                            .map(|c| if c.is_empty() { '.' } else { '#' })
                            .collect()
                    })
                    .collect();
                println!("      rows {}", pat.join(" "));
                let tok: Vec<String> = t
                    .iter()
                    .map(|r| {
                        r.iter()
                            .map(|c| c.split_whitespace().count().to_string())
                            .collect::<Vec<_>>()
                            .join("")
                    })
                    .collect();
                println!("      tokens {}", tok.join(" "));
            }
            for t in tables(&gt_md) {
                let cols = t.iter().map(|r| r.len()).max().unwrap_or(0);
                let fill: Vec<String> = (0..cols)
                    .map(|c| {
                        format!(
                            "{:.2}",
                            t.iter()
                                .filter(|r| r.get(c).is_some_and(|x| !x.is_empty()))
                                .count() as f64
                                / t.len() as f64
                        )
                    })
                    .collect();
                println!("    GT        {}x{} column fill {:?}", t.len(), cols, fill);
                let pat: Vec<String> = t
                    .iter()
                    .map(|r| {
                        r.iter()
                            .map(|c| if c.is_empty() { '.' } else { '#' })
                            .collect()
                    })
                    .collect();
                println!("      rows {}", pat.join(" "));
                let tok: Vec<String> = t
                    .iter()
                    .map(|r| {
                        r.iter()
                            .map(|c| c.split_whitespace().count().to_string())
                            .collect::<Vec<_>>()
                            .join("")
                    })
                    .collect();
                println!("      tokens {}", tok.join(" "));
            }
        }
        cells += s.matched;
        cell_tot += s.gt_cells;
        rows += s.row_hits;
        row_tot += s.gt_rows;
        println!(
            "  T{}: cells {:>3}/{:<3} rows {:>2}/{:<2} shape {} vs GT {} ({} candidate tables) {note}",
            k + 1,
            s.matched,
            s.gt_cells,
            s.row_hits,
            s.gt_rows,
            s.best_shape,
            s.gt_shape,
            s.n_tables
        );
    }
    println!("TOTAL deterministic: cells {cells}/{cell_tot}, rows {rows}/{row_tot}");

    // --- corpus: every PDF
    let mut files: Vec<PathBuf> = std::fs::read_dir(&dir)
        .unwrap()
        .filter_map(|e| e.ok().map(|e| e.path()))
        .filter(|p| p.extension().is_some_and(|e| e.eq_ignore_ascii_case("pdf")))
        .collect();
    files.sort();
    let (mut ok, mut tot) = (0, 0);
    let mut by_src: BTreeMap<String, usize> = BTreeMap::new();
    let mut rejected: BTreeMap<String, usize> = BTreeMap::new();
    let (mut uncertain, mut uncertain_units) = (0, 0);
    let (mut treq, mut twords, mut tmax) = (0usize, 0usize, 0usize);
    let mut size_hist: BTreeMap<&str, (usize, usize)> = BTreeMap::new();
    for f in &files {
        let Ok(bytes) = std::fs::read(f) else {
            continue;
        };
        let Ok(out) = pdf_units(&bytes, &opts) else {
            continue;
        };
        let (o, t) = integrity(&bytes, &opts, &out);
        ok += o;
        tot += t;
        for u in &out.units {
            if u.kind == UnitKind::Table {
                *by_src
                    .entry(format!("{:?}", u.provenance.table_source.unwrap()).to_lowercase())
                    .or_default() += 1;
            } else if u.provenance.table_uncertain {
                uncertain_units += 1;
            }
        }
        if let Ok(d) = diag::tables(&bytes, &opts) {
            for p in d {
                uncertain += p.uncertain;
                for (src, r) in p.rejected {
                    *rejected
                        .entry(format!("{src:?}/{r:?}").to_lowercase())
                        .or_default() += 1;
                }
            }
        }
        if let Ok(prep) = pdf_prepare(&bytes, &opts) {
            for r in prep
                .requests
                .iter()
                .filter(|r| r.kind == PdfRequestKind::TableStructure)
            {
                let pg = &prep.pages[(r.page - 1) as usize];
                let share = (r.bbox[3] - r.bbox[1]) / pg.height.max(1.0);
                let k = if share >= 0.6 {
                    "region >= 60% of page height"
                } else {
                    "region < 60% of page height"
                };
                let e = size_hist.entry(k).or_default();
                e.0 += 1;
                e.1 += r.words.len();
                treq += 1;
                twords += r.words.len();
                tmax = tmax.max(r.words.len());
            }
        }
    }
    println!("corpus: {} pdfs", files.len());
    println!("tables emitted by source: {by_src:?}");
    println!("uncertain table regions: {uncertain} (paragraph/list units marked table_uncertain: {uncertain_units})");
    println!("rejected candidates: {rejected:?}");
    println!(
        "table_structure requests: {treq}, words listed {twords} (mean {:.1}, max {tmax})",
        if treq > 0 {
            twords as f64 / treq as f64
        } else {
            0.0
        }
    );
    println!("  by region size (requests, words): {size_hist:?}");
    println!("positional integrity: {ok}/{tot} emitted cells made of text-layer words inside the table box");
}
