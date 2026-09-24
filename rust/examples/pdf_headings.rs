//! Heading diagnosis over a directory of PDFs. It prints COUNTS and FEATURE
//! HISTOGRAMS ONLY, never text or file names, and writes nothing to disk.
//!
//! ```text
//! PDFIUM_DYNAMIC_LIB_PATH=... cargo run --release --features pdf --example pdf_headings -- <dir> [--lang nl]
//! ```
//!
//! Block categories, over documents whose struct tree carries headings (S)
//! and over all documents (F):
//! - `A larger-tagged-body` (S): a strict or v1 font candidate at ≥1.15×
//!   body that the struct tree calls body text: the "80" of step 2.
//! - `B v1-font-headings` (F): headings emitted under the step-2 rule on
//!   documents that fell back to font: the "1,237" of step 2.
//! - `C tagged-headings` (S): the struct tree's heading elements.
//! - `D tagged-body` (S): everything else on those documents (reference).
//!
//! Then per policy (v1_doc | doc | per_heading), split by whether the
//! struct tree was used: headings per page and per document (median, max),
//! and heading→next-heading spans under 5 words.

use std::collections::BTreeMap;
use std::path::PathBuf;

use citenexus_core::extract::pdf::diag::{diagnose, BlockFeatures, HeadingDiag};
use citenexus_core::units::PdfOptions;

#[derive(Default)]
struct Hist {
    n: usize,
    c: BTreeMap<String, usize>,
}

impl Hist {
    fn add(&mut self, b: &BlockFeatures) {
        self.n += 1;
        let mut inc = |k: String| *self.c.entry(k).or_default() += 1;
        let r = b.size_ratio;
        inc(format!(
            "size {}",
            match r {
                r if r < 0.95 => "a:<0.95",
                r if r < 1.05 => "b:0.95-1.05",
                r if r < 1.15 => "c:1.05-1.15",
                r if r < 1.30 => "d:1.15-1.30",
                r if r < 1.60 => "e:1.30-1.60",
                _ => "f:>=1.60",
            }
        ));
        inc(format!(
            "words {}",
            match b.words {
                0..=3 => "a:1-3",
                4..=8 => "b:4-8",
                9..=15 => "c:9-15",
                16..=30 => "d:16-30",
                _ => "e:31+",
            }
        ));
        inc(format!("lines {}", b.lines.min(4)));
        let flags = [
            ("bold", b.bold),
            ("ends ':'", b.ends_colon),
            ("ends '.'", b.ends_period),
            ("ALL CAPS", b.all_caps),
            ("numbered", b.numbered),
            ("artikel", b.artikel),
            ("list", b.list),
            ("first on page", b.first_on_page),
            ("repeats across pages", b.repeats),
            ("in table", b.in_table),
            ("next block same size, not bold", b.next_same_size_body),
            ("top 15% of page", b.y_ratio < 0.15),
            ("bottom 15% of page", b.y_ratio > 0.85),
            ("starts in right half", b.x_ratio > 0.5),
            ("strict font candidate", b.font_cand),
            ("has number / § / roman", b.has_number),
        ];
        for (k, v) in flags {
            if v {
                inc(format!("~ {k}"));
            }
        }
        inc(format!(
            "role {}",
            if b.role.is_empty() {
                "(untagged doc)"
            } else {
                &b.role
            }
        ));
    }
    fn print(&self, title: &str) {
        println!("\n{title}: n={}", self.n);
        let mut roles: Vec<(&String, &usize)> = self
            .c
            .iter()
            .filter(|(k, _)| k.starts_with("role "))
            .collect();
        roles.sort_by(|a, b| b.1.cmp(a.1).then(a.0.cmp(b.0)));
        for (k, v) in &self.c {
            if !k.starts_with("role ") {
                println!(
                    "  {k:<40} {v:>6}  {:>5.1}%",
                    *v as f64 * 100.0 / self.n.max(1) as f64
                );
            }
        }
        let top: Vec<String> = roles
            .iter()
            .take(6)
            .map(|(k, v)| format!("{}={}", &k[5..], v))
            .collect();
        println!("  roles: {}", top.join(", "));
    }
}

fn median(v: &mut [usize]) -> usize {
    if v.is_empty() {
        return 0;
    }
    v.sort();
    v[v.len() / 2]
}

#[derive(Default)]
struct Pol {
    docs: usize,
    headings: usize,
    per_page: Vec<usize>,
    per_doc: Vec<usize>,
    short: usize,
    nested: usize,
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let dir = PathBuf::from(&args[0]);
    let lang = args
        .iter()
        .position(|a| a == "--lang")
        .map(|i| args[i + 1].clone())
        .or(Some("nl".into()));
    let opts = PdfOptions {
        language: lang,
        layout_text: false,
    };
    let mut files: Vec<PathBuf> = std::fs::read_dir(&dir)
        .unwrap()
        .filter_map(|e| e.ok().map(|e| e.path()))
        .filter(|p| p.extension().is_some_and(|e| e.eq_ignore_ascii_case("pdf")))
        .collect();
    files.sort();
    let diags: Vec<HeadingDiag> = files
        .iter()
        .filter_map(|f| diagnose(&std::fs::read(f).ok()?, &opts).ok())
        .collect();
    println!("documents: {}", diags.len());

    let (mut a, mut b, mut c, mut d) = (
        Hist::default(),
        Hist::default(),
        Hist::default(),
        Hist::default(),
    );
    for dg in &diags {
        let v1 = &dg.levels["v1_doc"];
        let v1_font = !dg.stats["v1_doc"].struct_tree_used;
        for (i, f) in dg.blocks.iter().enumerate() {
            if dg.struct_headings {
                if f.struct_heading.is_some() {
                    c.add(f);
                } else if (f.font_cand_v1 || f.font_cand) && f.size_ratio >= 1.15 {
                    a.add(f);
                } else {
                    d.add(f);
                }
            }
            if v1_font && v1[i].is_some() {
                b.add(f);
            }
        }
    }
    a.print("A larger-tagged-body (struct-heading docs)");
    b.print("B v1-font-headings (docs on the font path under v1)");
    c.print("C tagged-headings (struct-heading docs)");
    d.print("D tagged-body, reference (struct-heading docs)");

    // E: headings opening a FLAT short span under the shipped `doc` policy.
    let mut e = Hist::default();
    let mut e_next = Hist::default();
    for dg in &diags {
        let lv = &dg.levels["doc"];
        for &h in &dg.stats["doc"].short_flat_at {
            e.add(&dg.blocks[h]);
            if let Some(n) = (h + 1..dg.blocks.len()).find(|&j| lv[j].is_some()) {
                e_next.add(&dg.blocks[n]);
            }
        }
    }
    let mut f = Hist::default();
    let mut per_doc_ratio: Vec<(usize, usize)> = Vec::new();
    for dg in &diags {
        if dg.stats["doc"].struct_tree_used {
            continue;
        }
        let lv = &dg.levels["doc"];
        let n = lv.iter().filter(|l| l.is_some()).count();
        per_doc_ratio.push((n, dg.pages));
        for (i, l) in lv.iter().enumerate() {
            if l.is_some() {
                f.add(&dg.blocks[i]);
            }
        }
    }
    f.print("F font-only headings under `doc`");
    per_doc_ratio.sort();
    let top: Vec<String> = per_doc_ratio
        .iter()
        .rev()
        .take(5)
        .map(|(h, p)| format!("{h}h/{p}p"))
        .collect();
    println!(
        "  top docs by headings (headings/pages): {}",
        top.join(", ")
    );
    e.print("E headings opening a flat short span (policy doc)");
    let adj: usize = diags
        .iter()
        .map(|d| d.stats["doc"].short_flat_adjacent)
        .sum();
    println!("  of which directly adjacent (no block between): {adj}");
    e_next.print("E' the heading that follows them");

    // Policies, split by whether the struct tree was used under that policy.
    for pol in ["v1_doc", "doc", "per_heading"] {
        let mut groups: BTreeMap<&str, Pol> = BTreeMap::new();
        for dg in &diags {
            let st = &dg.stats[pol];
            let g = groups
                .entry(if st.struct_tree_used {
                    "struct-tree docs"
                } else {
                    "font-only docs"
                })
                .or_default();
            g.docs += 1;
            g.headings += st.headings;
            g.per_page.extend(st.per_page.iter().copied());
            g.per_doc.push(st.headings);
            g.short += st.short_spans;
            g.nested += st.short_nested;
        }
        println!("\npolicy {pol}:");
        for (k, g) in groups.iter_mut() {
            let mp = median(&mut g.per_page);
            let xp = g.per_page.iter().max().copied().unwrap_or(0);
            let md = median(&mut g.per_doc);
            let xd = g.per_doc.iter().max().copied().unwrap_or(0);
            println!(
                "  {k:<17} docs {:>3}  headings {:>5}  per page median {mp} max {xp}  per doc median {md} max {xd}  spans<5 words {} (nested {}, flat {})",
                g.docs, g.headings, g.short, g.nested, g.short - g.nested
            );
        }
    }

    // The 0.5–0.8 agreement bucket under the shipped rule: both options.
    let bucket: Vec<&HeadingDiag> = diags
        .iter()
        .filter(|d| d.agreement_rate.is_some_and(|r| (0.5..0.8).contains(&r)))
        .collect();
    let trusted = diags
        .iter()
        .filter(|d| d.stats["doc"].struct_tree_used)
        .count();
    let tagged = diags.iter().filter(|d| d.struct_headings).count();
    println!("\nstruct-heading docs {tagged}; struct tree trusted under `doc`: {trusted}");
    println!(
        "agreement bucket [0.5,0.8) under `doc`: {} docs",
        bucket.len()
    );
    for pol in ["doc", "per_heading"] {
        let (mut h, mut s, mut pp) = (0, 0, Vec::new());
        for d in &bucket {
            h += d.stats[pol].headings;
            s += d.stats[pol].short_spans;
            pp.extend(d.stats[pol].per_page.iter().copied());
        }
        let mx = pp.iter().max().copied().unwrap_or(0);
        println!(
            "  {pol:<12} headings {h:>5}  per page median {} max {mx}  spans<5 words {s}",
            median(&mut pp)
        );
    }
}
