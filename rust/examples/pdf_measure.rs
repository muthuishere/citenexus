//! Measure the base PDF extractor over a directory of PDFs, printing COUNTS
//! ONLY. No file name, no text, and nothing is written to disk: it is safe to
//! point at client documents read in place.
//!
//! ```text
//! PDFIUM_DYNAMIC_LIB_PATH=... cargo run --release --features pdf --example pdf_measure -- \
//!     <originals-dir> [--lang nl] [--quotes <manifest.json> <run.jsonl>...] [--baseline-md <dir>]
//! ```
//!
//! `--quotes` re-runs spike 185's `measure_quote_support.py` logic IN MEMORY
//! against this extractor's output: of the dropped quotes (reason "not
//! supported by the cited evidence", >= 20 chars), how many are
//! token-contiguous in the cited file's text. Token view = NFKC, soft hyphen
//! removed, lower-cased, runs of letters/digits (Python `[^\W_]+`). The
//! manifest maps filename -> file_id (it replaces the script's psql lookup).
//! Non-PDF originals use the core's existing `to_markdown` path.
//! `--baseline-md <dir>` scores `<file_id>.md` files the same way (to check
//! that this port of the measure reproduces the spike's published number).

use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};

use citenexus_core::extract::pdf::{pdf_prepare, pdf_units};
use citenexus_core::units::*;
use unicode_normalization::UnicodeNormalization;

fn toks(s: &str) -> Vec<String> {
    let n: String = s
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

fn joined(t: &[String]) -> String {
    format!(" {} ", t.join(" "))
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let dir = PathBuf::from(&args[0]);
    let mut lang = Some("nl".to_string());
    let mut manifest: Option<PathBuf> = None;
    let mut runs: Vec<PathBuf> = Vec::new();
    let mut baseline: Option<PathBuf> = None;
    let mut i = 1;
    while i < args.len() {
        match args[i].as_str() {
            "--lang" => {
                lang = Some(args[i + 1].clone());
                i += 2;
            }
            "--baseline-md" => {
                baseline = Some(PathBuf::from(&args[i + 1]));
                i += 2;
            }
            "--quotes" => {
                manifest = Some(PathBuf::from(&args[i + 1]));
                i += 2;
                while i < args.len() && !args[i].starts_with("--") {
                    runs.push(PathBuf::from(&args[i]));
                    i += 1;
                }
            }
            _ => i += 1,
        }
    }
    let opts = PdfOptions {
        language: lang,
        layout_text: false,
    };

    let mut files: Vec<PathBuf> = std::fs::read_dir(&dir)
        .expect("originals dir")
        .filter_map(|e| e.ok().map(|e| e.path()))
        .filter(|p| p.is_file())
        .collect();
    files.sort();

    let mut md_by_name: BTreeMap<String, String> = BTreeMap::new();
    let (mut pdfs, mut errors, mut others) = (0, 0, 0);
    let mut routes: BTreeMap<String, usize> = BTreeMap::new();
    let (mut pages, mut markers_left, mut markers, mut joined_n, mut kept) =
        (0usize, 0usize, 0u32, 0u32, 0u32);
    let (mut furn_lines, mut furn_units) = (0u32, 0u32);
    let (mut tagged, mut struct_head, mut trusted, mut outlined) = (0, 0, 0, 0);
    let mut heading_src: BTreeMap<String, usize> = BTreeMap::new();
    let mut kinds: BTreeMap<String, usize> = BTreeMap::new();
    let mut rates: Vec<f64> = Vec::new();
    let (mut unsup, mut strong, mut weak) = (0u32, 0u32, 0u32);
    let mut order: BTreeMap<String, usize> = BTreeMap::new();
    let mut requests: BTreeMap<String, usize> = BTreeMap::new();
    let mut table_words = 0usize;
    let t0 = std::time::Instant::now();
    for f in &files {
        let name = f.file_name().unwrap().to_string_lossy().to_string();
        let ext = f
            .extension()
            .map(|e| e.to_string_lossy().to_lowercase())
            .unwrap_or_default();
        let bytes = std::fs::read(f).expect("read");
        if ext != "pdf" {
            others += 1;
            let st = citenexus_core::source_type_for_extension(&ext);
            if let Ok(doc) = citenexus_core::extract(&bytes, st, "doc", None) {
                md_by_name.insert(name, citenexus_core::to_markdown(&doc));
            }
            continue;
        }
        pdfs += 1;
        let out = match pdf_units(&bytes, &opts) {
            Ok(o) => o,
            Err(_) => {
                errors += 1;
                continue;
            }
        };
        if let Ok(prep) = pdf_prepare(&bytes, &opts) {
            for r in &prep.requests {
                *requests
                    .entry(format!("{:?}", r.kind).to_lowercase())
                    .or_default() += 1;
                table_words += r.words.len();
            }
        }
        let md: String = out
            .units
            .iter()
            .map(|u| u.markdown.as_str())
            .collect::<Vec<_>>()
            .join("\n\n");
        markers_left += md.matches('\u{2}').count();
        md_by_name.insert(name, md);
        let d = &out.document;
        pages += d.pages as usize;
        markers += d.hyphen_markers;
        joined_n += d.hyphens_joined;
        kept += d.hyphens_kept;
        furn_lines += d.furniture_lines;
        furn_units += d.furniture_units;
        tagged += d.tagged as usize;
        outlined += (d.outline_entries > 0) as usize;
        *heading_src.entry(d.heading_source.clone()).or_default() += 1;
        if d.struct_headings {
            struct_head += 1;
            if let Some(a) = &d.heading_agreement {
                trusted += a.struct_tree_trusted as usize;
                rates.push(a.rate);
                unsup += a.struct_unsupported;
                strong += a.font_untagged_strong;
                weak += a.font_untagged_weak;
            }
        }
        for p in &out.pages {
            *routes
                .entry(format!("{:?}", p.route).to_lowercase())
                .or_default() += 1;
            *order.entry(p.signals.reading_order.clone()).or_default() += 1;
        }
        for u in &out.units {
            *kinds
                .entry(format!("{:?}", u.kind).to_lowercase())
                .or_default() += 1;
        }
    }
    let secs = t0.elapsed().as_secs_f64();
    println!(
        "files: {} pdf, {} other, {} pdf errors, {} pages, {:.1}s",
        pdfs, others, errors, pages, secs
    );
    println!("tagged docs (struct tree with content): {tagged}");
    println!("docs with struct-tree headings: {struct_head}; per-document agreement test passes: {trusted}; fails: {}", struct_head - trusted);
    rates.sort_by(|a, b| a.total_cmp(b));
    let bucket = |lo: f64, hi: f64| rates.iter().filter(|&&r| r >= lo && r < hi).count();
    println!(
        "  agreement rate buckets: [0,0.5) {} | [0.5,0.8) {} | [0.8,1.0) {} | 1.0 {}",
        bucket(0.0, 0.5),
        bucket(0.5, 0.8),
        bucket(0.8, 1.0),
        rates.iter().filter(|&&r| r >= 1.0).count()
    );
    println!("  mismatch blocks: tagged-as-heading-but-body-looking {unsup}, larger-but-tagged-body {strong}, bold-body-size-tagged-body (weak) {weak}");
    println!("docs with an outline: {outlined}");
    println!("heading source per doc: {heading_src:?}");
    println!("hyphen markers: {markers} (joined {joined_n}, kept {kept}); U+0002 left in output: {markers_left}");
    println!("running header/footer lines detected: {furn_lines}; furniture units kept once: {furn_units}");
    println!("route per page: {routes:?}");
    println!("reading order per page: {order:?}");
    println!("units by kind: {kinds:?}");
    println!(
        "pdf_prepare requests by kind: {requests:?}; words listed in table requests: {table_words}"
    );

    if let Some(bdir) = &baseline {
        // baseline <file_id>.md, keyed by file_id
        let mut base: BTreeMap<String, String> = BTreeMap::new();
        for e in std::fs::read_dir(bdir).expect("baseline dir").flatten() {
            let p = e.path();
            if p.extension().is_some_and(|x| x == "md") {
                let fid = p.file_stem().unwrap().to_string_lossy().to_string();
                base.insert(
                    fid,
                    joined(&toks(&std::fs::read_to_string(&p).unwrap_or_default())),
                );
            }
        }
        if let Some(m) = &manifest {
            let (q, hit) = quote_support(m, &runs, &|fid| base.get(fid).cloned());
            println!("quote support, baseline md dir: {hit}/{q}");
        }
    }
    if let Some(m) = &manifest {
        let man: serde_json::Value =
            serde_json::from_str(&std::fs::read_to_string(m).unwrap()).unwrap();
        let mut rep: BTreeMap<String, String> = BTreeMap::new();
        for e in man.as_array().unwrap() {
            let (Some(fid), Some(name)) = (e["file_id"].as_str(), e["filename"].as_str()) else {
                continue;
            };
            // originals are stored under the manifest's filename or its path basename
            let key = md_by_name.get(name).or_else(|| {
                e["path"]
                    .as_str()
                    .and_then(|p| Path::new(p).file_name())
                    .and_then(|b| md_by_name.get(&*b.to_string_lossy()))
            });
            if let Some(md) = key {
                rep.insert(fid.to_string(), joined(&toks(md)));
            }
        }
        println!("manifest entries matched to originals: {}", rep.len());
        let (q, hit) = quote_support(m, &runs, &|fid| rep.get(fid).cloned());
        println!("quote support, this extractor: {hit}/{q}");
    }
}

/// Spike 185 `measure_quote_support.py`, the tally loop, in memory.
fn quote_support(
    manifest: &Path,
    runs: &[PathBuf],
    rep: &dyn Fn(&str) -> Option<String>,
) -> (usize, usize) {
    let man: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(manifest).unwrap()).unwrap();
    let fid_by_name: BTreeMap<String, String> = man
        .as_array()
        .unwrap()
        .iter()
        .filter_map(|e| {
            Some((
                e["filename"].as_str()?.to_string(),
                e["file_id"].as_str()?.to_string(),
            ))
        })
        .collect();
    let (mut quotes, mut hits) = (0, 0);
    for run in runs {
        for line in std::fs::read_to_string(run).unwrap().lines() {
            let Ok(r) = serde_json::from_str::<serde_json::Value>(line) else {
                continue;
            };
            for t in r["turns"].as_array().into_iter().flatten() {
                let files = &t["unit_files"];
                for d in t["dropped_claims"].as_array().into_iter().flatten() {
                    if d["reason"].as_str() != Some("not supported by the cited evidence") {
                        continue;
                    }
                    let v = d["verified_text"].as_str().unwrap_or("").trim();
                    let v = v
                        .trim_matches(|c| c == '"' || c == '“' || c == '”')
                        .trim_end_matches('.');
                    if v.chars().count() < 20 {
                        continue;
                    }
                    // Python: files.get(i) on a str-keyed dict — only string ids match.
                    let fids: BTreeSet<String> = d["cited"]
                        .as_array()
                        .into_iter()
                        .flatten()
                        .filter_map(|i| i.as_str())
                        .filter_map(|i| files.get(i).and_then(|n| n.as_str()))
                        .filter_map(|n| fid_by_name.get(n).cloned())
                        .collect();
                    if fids.is_empty() {
                        continue;
                    }
                    let q = joined(&toks(v));
                    quotes += 1;
                    if fids.iter().any(|f| rep(f).is_some_and(|c| c.contains(&q))) {
                        hits += 1;
                    }
                }
            }
        }
    }
    (quotes, hits)
}
