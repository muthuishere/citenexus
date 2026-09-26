//! Furniture measurement over a directory of PDFs: COUNTS ONLY, no text.
//! Compares band depths and the edge-block rule on the same segments.
use std::collections::BTreeSet;
use std::path::PathBuf;

use citenexus_core::extract::pdf::furniture::{detect_with, emit_key, key};
use citenexus_core::extract::pdf::{layout, raw};

fn main() {
    let dir = PathBuf::from(std::env::args().nth(1).expect("dir"));
    let mut files: Vec<PathBuf> = std::fs::read_dir(&dir)
        .unwrap()
        .filter_map(|e| e.ok().map(|e| e.path()))
        .filter(|p| p.extension().is_some_and(|e| e.eq_ignore_ascii_case("pdf")))
        .collect();
    files.sort();
    let configs = [
        ("12% no-edge (old)", 0.12, false),
        ("12% edge", 0.12, true),
        ("8% edge", 0.08, true),
        ("8% no-edge", 0.08, false),
    ];
    let mut lines = vec![0usize; configs.len()];
    let mut units = vec![0usize; configs.len()];
    // units present in "12% no-edge" but not in "12% edge": (band, digit-masked)
    let (mut gone_top, mut gone_bottom, mut gone_masked) = (0, 0, 0);
    for f in &files {
        let Ok(r) = raw::read(&std::fs::read(f).unwrap()) else {
            continue;
        };
        let segs: Vec<_> = r.pages.iter().map(|p| layout::segments(p).0).collect();
        let input: Vec<(f64, &[layout::Segment])> = r
            .pages
            .iter()
            .zip(&segs)
            .map(|(p, s)| (p.height, s.as_slice()))
            .collect();
        let mut keysets: Vec<BTreeSet<(bool, String)>> = Vec::new();
        for (k, (_, band, edge)) in configs.iter().enumerate() {
            let det = detect_with(&input, *band, *edge);
            lines[k] += det.len();
            let ks: BTreeSet<(bool, String)> = det
                .iter()
                .map(|&(p, s)| {
                    (
                        segs[p][s].bbox[1] < r.pages[p].height / 2.0,
                        emit_key(&segs[p][s].text),
                    )
                })
                .collect();
            units[k] += ks.len();
            keysets.push(ks);
        }
        for (top, k) in keysets[0].difference(&keysets[1]) {
            if *top {
                gone_top += 1
            } else {
                gone_bottom += 1
            }
            if key(k).contains('#') {
                gone_masked += 1
            }
        }
    }
    for (k, (name, _, _)) in configs.iter().enumerate() {
        println!(
            "{name:<20} running lines {:>4}  distinct furniture units {:>4}",
            lines[k], units[k]
        );
    }
    println!("units dropped by the edge rule at 12%: top band {gone_top}, bottom band {gone_bottom}; of which carrying digits (masked match) {gone_masked}");
}
