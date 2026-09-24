//! Counts-only measurement of `ooxml_units` over a directory of DOCX/PPTX
//! files (ADR-0017 decision 8). Prints NUMBERS ONLY — never file names or
//! text — so it can run over client originals in place.
//!
//! `cargo run --release --example ooxml_measure -- <dir>`

use std::collections::BTreeMap;
use std::io::Read;

use citenexus_core::ooxml_units;
use citenexus_core::types::SourceType;
use citenexus_core::units::UnitKind;

/// Merge markers in the raw XML (the ground truth the output is judged by).
fn merged_cells(bytes: &[u8], docx: bool) -> usize {
    let mut archive = zip::ZipArchive::new(std::io::Cursor::new(bytes)).unwrap();
    let names: Vec<String> = archive.file_names().map(str::to_string).collect();
    let mut n = 0;
    for name in names {
        let wanted = if docx {
            name == "word/document.xml"
        } else {
            name.starts_with("ppt/slides/slide") && name.ends_with(".xml")
        };
        if !wanted {
            continue;
        }
        let mut xml = String::new();
        archive
            .by_name(&name)
            .unwrap()
            .read_to_string(&mut xml)
            .unwrap();
        if docx {
            n += xml.matches("<w:vMerge").count();
            n += xml
                .match_indices("<w:gridSpan w:val=\"")
                .filter(|(i, m)| !xml[i + m.len()..].starts_with("1\""))
                .count();
        } else {
            for key in ["gridSpan=\"", "rowSpan=\""] {
                n += xml
                    .match_indices(key)
                    .filter(|(i, m)| !xml[i + m.len()..].starts_with("1\""))
                    .count();
            }
            n += xml.matches("hMerge=\"1\"").count() + xml.matches("vMerge=\"1\"").count();
        }
    }
    n
}

/// A list line's marker class: native decimal (`3.`), a literal label after
/// `- ` (`- b.`, `- (ii)`, `- 2.b`), or a plain bullet. Heuristic on the
/// emitted markdown: a literal label is a first token ending in `.` or `)`,
/// or `(…)`, or a dotted number — how `ooxml_units` writes labels.
fn marker_class(line: &str) -> &'static str {
    let t = line.trim_start();
    if t.split(' ').next().is_some_and(|m| {
        m.len() > 1 && m[..m.len() - 1].bytes().all(|b| b.is_ascii_digit()) && m.ends_with(['.', ')'])
    }) {
        return "decimal";
    }
    let Some(rest) = t.strip_prefix("- ") else { return "other" };
    let tok = rest.split(' ').next().unwrap_or("").replace('\\', "");
    let short = tok.chars().count() <= 8;
    let labelish = (tok.starts_with('(') && tok.ends_with(')'))
        || ((tok.ends_with('.') || tok.ends_with(')')) && tok.len() > 1)
        || (tok.contains('.') && tok.chars().any(|c| c.is_ascii_digit()));
    if short && labelish && tok.chars().any(|c| c.is_alphanumeric()) {
        "labelled"
    } else {
        "bullet"
    }
}

fn main() {
    let dir = std::env::args().nth(1).expect("usage: ooxml_measure <dir>");
    let mut files: Vec<_> = std::fs::read_dir(&dir)
        .unwrap()
        .flatten()
        .map(|e| e.path())
        .filter(|p| {
            matches!(
                p.extension()
                    .and_then(|e| e.to_str())
                    .map(str::to_ascii_lowercase)
                    .as_deref(),
                Some("docx") | Some("pptx")
            )
        })
        .collect();
    files.sort();
    println!("idx kind units tables rows cells merged_src blank_rows headings_by_level lists list_items decimal_items labelled_items bullet_items unknown_format_units furniture paragraphs deterministic");
    let mut totals: BTreeMap<&str, usize> = BTreeMap::new();
    for (i, path) in files.iter().enumerate() {
        let bytes = std::fs::read(path).unwrap();
        let docx = path.extension().unwrap().to_ascii_lowercase() == "docx";
        let hint = if docx {
            SourceType::Docx
        } else {
            SourceType::Pptx
        };
        let units = match ooxml_units(&bytes, hint) {
            Ok(u) => u,
            Err(_) => {
                println!("{i} {} ERROR", if docx { "docx" } else { "pptx" });
                continue;
            }
        };
        let again = ooxml_units(&bytes, hint).unwrap();
        let deterministic =
            serde_json::to_string(&units).unwrap() == serde_json::to_string(&again).unwrap();
        let (mut tables, mut rows, mut cells, mut blank) = (0, 0, 0, 0);
        let mut levels: BTreeMap<u32, usize> = BTreeMap::new();
        let (mut lists, mut items, mut furniture, mut paras) = (0, 0, 0, 0);
        let (mut dec, mut lab, mut bul, mut unk) = (0, 0, 0, 0);
        for u in &units {
            match u.kind {
                UnitKind::Table => {
                    tables += 1;
                    for line in u.markdown.lines() {
                        if line.starts_with("| ---") || line.starts_with("|---") {
                            continue;
                        }
                        rows += 1;
                        let inner = line.trim().trim_start_matches('|').trim_end_matches('|');
                        let parts: Vec<&str> = inner.split(" | ").collect();
                        cells += parts.len();
                        if parts.iter().all(|c| c.trim().is_empty()) {
                            blank += 1;
                        }
                    }
                }
                UnitKind::Heading => *levels.entry(u.level.unwrap_or(0)).or_default() += 1,
                UnitKind::List => {
                    lists += 1;
                    items += u.markdown.lines().count();
                    if u.provenance.failed_check.as_deref() == Some("list_label_unknown_format") {
                        unk += 1;
                    }
                    for line in u.markdown.lines() {
                        match marker_class(line) {
                            "decimal" => dec += 1,
                            "labelled" => lab += 1,
                            _ => bul += 1,
                        }
                    }
                }
                UnitKind::Furniture => furniture += 1,
                UnitKind::Paragraph => paras += 1,
                UnitKind::Image | UnitKind::ImageDescription => {}
            }
        }
        let merged = merged_cells(&bytes, docx);
        let lv: Vec<String> = levels.iter().map(|(l, n)| format!("h{l}={n}")).collect();
        println!(
            "{i} {} {} {tables} {rows} {cells} {merged} {blank} [{}] {lists} {items} {dec} {lab} {bul} {unk} {furniture} {paras} {deterministic}",
            if docx { "docx" } else { "pptx" },
            units.len(),
            lv.join(",")
        );
        for (k, v) in [
            ("tables", tables),
            ("rows", rows),
            ("cells", cells),
            ("merged_src", merged),
            ("blank_rows", blank),
            ("lists", lists),
            ("list_items", items),
            ("decimal_items", dec),
            ("labelled_items", lab),
            ("bullet_items", bul),
            ("unknown_format_units", unk),
            ("furniture", furniture),
            ("paragraphs", paras),
            ("nondeterministic", usize::from(!deterministic)),
        ] {
            *totals.entry(k).or_default() += v;
        }
        for (l, n) in levels {
            *totals
                .entry(["h0", "h1", "h2", "h3", "h4", "h5", "h6"][l.min(6) as usize])
                .or_default() += n;
        }
    }
    println!("TOTAL files={} {:?}", files.len(), totals);
}
