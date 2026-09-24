//! Table acceptance measurement through the Rust output. It prints COUNTS,
//! SHAPES and SCORES ONLY: no cell values, no file names (tables are T1..Tn).
//!
//! ```text
//! # deterministic (runs pdf_units, no model):
//! PDFIUM_DYNAMIC_LIB_PATH=... cargo run --profile measure --features pdf --example pdf_tables -- \
//!     --originals <dir> --manifest <originals_manifest.json> \
//!     --gt-map <measure_tables.py | map.json> --gt <gt-md-dir> [--lang nl] [--no-corpus]
//! # scoring ALREADY-ASSEMBLED output (the host ran PdfPrepare -> models ->
//! # PdfAssemble and wrote <file_id>.json per file, the PdfUnitsOutput JSON):
//!     --assembled <dir> --gt-map <...> --gt <dir> [--originals <dir> --manifest <json>]
//! ```
//! `--gt-corrections <json>` applies a GT overlay before scoring:
//! `{"<gt file>.md": [{"table":0,"row":r,"col":c,"value":"…"} | {"from":"…","to":"…"}]}`.
//! (`--originals`/`--manifest` add positional integrity; the old positional
//! form `<originals> <manifest> <measure_tables.py> <gt-dir>` still works.)
//! Disputed vision text is excluded from scoring (`vision::citable_text`).
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
use citenexus_core::extract::pdf::{diag, pdf_prepare, pdf_units, raw, tables};
use citenexus_core::units::*;
use citenexus_core::vision;
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

/// Apply a GT corrections overlay (`--gt-corrections`) to one GT file's
/// tables. Each entry addresses a cell either by position
/// `{"table": 0, "row": r, "col": c, "value": "…"}` (0-based, separator row
/// not counted) or by its exact text `{"from": "…", "to": "…"}` (every cell
/// equal to `from` after trimming).
fn correct(gts: &mut [Vec<Vec<String>>], entries: &[serde_json::Value]) -> usize {
    let mut applied = 0;
    for e in entries {
        if let (Some(r), Some(c)) = (e["row"].as_u64(), e["col"].as_u64()) {
            let t = e["table"].as_u64().unwrap_or(0) as usize;
            if let Some(cell) = gts
                .get_mut(t)
                .and_then(|t| t.get_mut(r as usize))
                .and_then(|row| row.get_mut(c as usize))
            {
                *cell = e["value"].as_str().unwrap_or_default().to_string();
                applied += 1;
            }
        } else if let (Some(from), Some(to)) = (e["from"].as_str(), e["to"].as_str()) {
            for cell in gts.iter_mut().flatten().flatten() {
                if cell.trim() == from.trim() {
                    *cell = to.to_string();
                    applied += 1;
                }
            }
        }
    }
    applied
}

fn score_tables(gts: Vec<Vec<Vec<String>>>, cand_md: &str) -> Score {
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

/// The GT map: `measure_tables.py` (its `GT = {...}` dict is parsed) or a
/// JSON object `{"<gt file>.md": "<file_id>", ...}`.
fn gt_map(path: &Path) -> Vec<(String, String)> {
    let src = std::fs::read_to_string(path).expect("GT map");
    if path.extension().is_some_and(|e| e == "json") {
        let v: serde_json::Value = serde_json::from_str(&src).expect("GT map JSON");
        let mut out: Vec<(String, String)> = v
            .as_object()
            .expect("GT map: a JSON object")
            .iter()
            .map(|(k, v)| (k.clone(), v.as_str().unwrap_or_default().to_string()))
            .collect();
        out.sort();
        return out;
    }
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

/// Cells of emitted TEXT-LAYER tables (struct/ruled/tracks/model grid; not
/// vision) made of text-layer words inside the table box: (ok, total). Per
/// cell, every token must be a text-layer word inside the box, each used at
/// most once within that cell (a flattened header label legitimately repeats
/// across the sub-header cells it spans; the geometry gate proves placement).
fn integrity(bytes: &[u8], opts: &PdfOptions, out: &PdfUnitsOutput) -> (usize, usize) {
    let words = diag::page_words(bytes, opts).unwrap_or_default();
    // rotated labels (`tables::fill_rotated`): a cell may be exactly one run
    // of the page's own rotated characters, within LABEL_REACH of the table
    let runs: Vec<Vec<tables::RotRun>> = raw::read(bytes)
        .map(|r| r.pages.iter().map(tables::rotated_runs).collect())
        .unwrap_or_default();
    let (mut ok, mut total) = (0, 0);
    for u in out
        .units
        .iter()
        .filter(|u| u.kind == UnitKind::Table && !u.provenance.vision_transcribed)
    {
        let (Some(p), Some(b)) = (u.page, u.bbox) else {
            continue;
        };
        let Some(page_words) = words.get((p - 1) as usize) else {
            continue;
        };
        let mut pool: BTreeMap<String, usize> = BTreeMap::new();
        for w in page_words {
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
            let reach = tables::LABEL_REACH;
            let label = runs.get((p - 1) as usize).is_some_and(|rs| {
                rs.iter().any(|r| {
                    let (cx, cy) = ((r.bbox[0] + r.bbox[2]) / 2.0, (r.bbox[1] + r.bbox[3]) / 2.0);
                    r.text.trim() == cell
                        && cx >= b[0] - reach
                        && cx <= b[2] + reach
                        && cy >= b[1] - reach
                        && cy <= b[3] + reach
                })
            });
            if label {
                ok += 1;
                continue;
            }
            let mut local = pool.clone();
            let good = cell.split_whitespace().all(|tok| match local.get_mut(tok) {
                Some(n) if *n > 0 => {
                    *n -= 1;
                    true
                }
                _ => false,
            });
            ok += good as usize;
        }
    }
    (ok, total)
}

/// Citable markdown of a whole output (disputed vision text excluded).
fn citable_markdown(out: &PdfUnitsOutput) -> String {
    out.units
        .iter()
        .map(|u| vision::citable_text(&u.markdown))
        .collect::<Vec<_>>()
        .join("\n\n")
}

struct Args {
    corrections: Option<PathBuf>,
    originals: Option<PathBuf>,
    manifest: Option<PathBuf>,
    gt_map: PathBuf,
    gt: PathBuf,
    assembled: Option<PathBuf>,
    lang: Option<String>,
    corpus: bool,
}

fn args() -> Args {
    let a: Vec<String> = std::env::args().skip(1).collect();
    let flag = |name: &str| a.iter().position(|x| x == name).map(|i| a[i + 1].clone());
    // legacy positional form: <originals> <manifest> <measure_tables.py> <gt-dir>
    if a.len() >= 4 && !a[0].starts_with("--") {
        return Args {
            corrections: flag("--gt-corrections").map(PathBuf::from),
            originals: Some(PathBuf::from(&a[0])),
            manifest: Some(PathBuf::from(&a[1])),
            gt_map: PathBuf::from(&a[2]),
            gt: PathBuf::from(&a[3]),
            assembled: flag("--assembled").map(PathBuf::from),
            lang: flag("--lang").or(Some("nl".into())),
            corpus: !a.iter().any(|x| x == "--no-corpus"),
        };
    }
    Args {
        corrections: flag("--gt-corrections").map(PathBuf::from),
        originals: flag("--originals").map(PathBuf::from),
        manifest: flag("--manifest").map(PathBuf::from),
        gt_map: PathBuf::from(flag("--gt-map").expect("--gt-map <measure_tables.py | map.json>")),
        gt: PathBuf::from(flag("--gt").expect("--gt <dir of hand-written GT .md>")),
        assembled: flag("--assembled").map(PathBuf::from),
        lang: flag("--lang").or(Some("nl".into())),
        corpus: !a.iter().any(|x| x == "--no-corpus") && flag("--assembled").is_none(),
    }
}

fn main() {
    let args = args();
    let opts = PdfOptions {
        language: args.lang.clone(),
        ..Default::default()
    };
    let man: serde_json::Value = args
        .manifest
        .as_ref()
        .map(|m| serde_json::from_str(&std::fs::read_to_string(m).unwrap()).unwrap())
        .unwrap_or(serde_json::Value::Null);
    let original_of = |fid: &str| -> Option<Vec<u8>> {
        let dir = args.originals.as_ref()?;
        let e = man.as_array()?.iter().find(|e| e["file_id"] == fid)?;
        let p = e["path"].as_str().or(e["filename"].as_str())?;
        std::fs::read(dir.join(Path::new(p).file_name()?)).ok()
    };
    let output_of = |fid: &str| -> Result<PdfUnitsOutput, String> {
        match &args.assembled {
            Some(dir) => {
                let raw = std::fs::read_to_string(dir.join(format!("{fid}.json")))
                    .map_err(|_| "assembled file missing".to_string())?;
                serde_json::from_str(&raw).map_err(|e| format!("assembled JSON: {e}"))
            }
            None => pdf_units(&original_of(fid).ok_or("original missing")?, &opts),
        }
    };

    let mode = if args.assembled.is_some() {
        "assembled (host model output)"
    } else {
        "deterministic (no model)"
    };
    let gt = gt_map(&args.gt_map);
    // {"<gt file>.md": [entry, …]} — see `correct`
    let corrections: serde_json::Value = args
        .corrections
        .as_ref()
        .map(|p| {
            serde_json::from_str(&std::fs::read_to_string(p).expect("--gt-corrections"))
                .expect("corrections JSON")
        })
        .unwrap_or(serde_json::Value::Null);
    let mut corrected = 0;
    let (mut cells, mut cell_tot, mut rows, mut row_tot) = (0, 0, 0, 0);
    let (mut integ_ok, mut integ_tot, mut vision_tables) = (0, 0, 0);
    println!("mode: {mode}; GT tables: {}", gt.len());
    for (k, (gtf, fid)) in gt.iter().enumerate() {
        let gt_md = std::fs::read_to_string(args.gt.join(gtf)).unwrap_or_default();
        let (md, note) = match output_of(fid) {
            Ok(out) => {
                let srcs: Vec<String> = out
                    .units
                    .iter()
                    .filter(|u| {
                        u.kind == UnitKind::Table
                            || (u.provenance.vision_transcribed && u.markdown.contains('|'))
                    })
                    .map(
                        |u| match (u.provenance.table_source, u.provenance.vision_transcribed) {
                            (_, true) => "vision".to_string(),
                            (Some(s), _) => format!("{s:?}").to_lowercase(),
                            (None, _) => "?".into(),
                        },
                    )
                    .collect();
                vision_tables += srcs.iter().filter(|s| *s == "vision").count();
                if let Some(bytes) = original_of(fid) {
                    let (o, t) = integrity(&bytes, &opts, &out);
                    integ_ok += o;
                    integ_tot += t;
                }
                let routes: Vec<String> = out
                    .pages
                    .iter()
                    .map(|p| format!("{:?}", p.route).to_lowercase())
                    .collect();
                (
                    citable_markdown(&out),
                    format!("tables {srcs:?} routes {routes:?}"),
                )
            }
            Err(e) => (String::new(), e),
        };
        let mut gts = tables(&gt_md);
        if let Some(entries) = corrections.get(gtf.as_str()).and_then(|v| v.as_array()) {
            corrected += correct(&mut gts, entries);
        }
        let s = score_tables(gts, &md);
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
    let with = if args.corrections.is_some() {
        format!(" (GT corrections applied: {corrected} cells)")
    } else {
        String::new()
    };
    println!("TOTAL {mode}: cells {cells}/{cell_tot}, rows {rows}/{row_tot}{with}");
    if args.originals.is_some() {
        println!("positional integrity (GT files, text-layer tables): {integ_ok}/{integ_tot} cells made of text-layer words inside the table box (or one rotated label run); vision tables (not text-layer, not counted): {vision_tables}");
    } else {
        println!("positional integrity: not computed (pass --originals and --manifest)");
    }

    if !args.corpus {
        return;
    }
    let Some(dir) = args.originals.as_ref() else {
        return;
    };
    let mut files: Vec<PathBuf> = std::fs::read_dir(dir)
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
    let (mut leader_reqs, mut leader_words) = (0usize, 0usize);
    let mut leader_shapes: BTreeMap<&str, usize> = BTreeMap::new();
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
                let leaders = r
                    .words
                    .iter()
                    .filter(|w| citenexus_core::checks::is_leader(&w.text))
                    .count();
                let dotty = r
                    .words
                    .iter()
                    .filter(|w| w.text.chars().filter(|c| *c == '.').count() >= 5)
                    .count();
                for w in r
                    .words
                    .iter()
                    .filter(|w| w.text.chars().filter(|c| *c == '.').count() >= 5)
                {
                    let t = &w.text;
                    let shape = if citenexus_core::checks::is_leader(t) {
                        "pure leader"
                    } else if t
                        .trim_end_matches(|c: char| c.is_ascii_digit())
                        .chars()
                        .all(|c| c == '.')
                    {
                        "dots then digits"
                    } else if t
                        .trim_start_matches(|c: char| c.is_alphanumeric())
                        .chars()
                        .all(|c| c == '.')
                    {
                        "text then dots"
                    } else {
                        "mixed"
                    };
                    *leader_shapes.entry(shape).or_default() += 1;
                }
                if leaders > 0 || dotty > 0 {
                    leader_reqs += 1;
                    leader_words += r.words.len();
                }
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
    println!("  requests containing leader-like words (5+ dots): {leader_reqs} ({leader_words} words); shapes {leader_shapes:?}");
    println!("positional integrity (corpus): {ok}/{tot} emitted cells made of text-layer words inside the table box (or one rotated label run)");
}
