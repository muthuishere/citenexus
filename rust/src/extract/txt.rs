//! TxtExtractor — no structure: each blank-line-separated paragraph is one
//! paragraph block (mirrors `extract/txt.py`).

use crate::types::*;

pub fn extract(text: &str, document_id: &str, source_uri: Option<String>) -> ExtractedDoc {
    let blocks = split_paragraphs(text)
        .into_iter()
        .enumerate()
        .map(|(i, chunk)| ExtractedBlock::new(i, BlockKind::Paragraph, chunk))
        .collect();
    ExtractedDoc {
        document_id: document_id.to_string(),
        source_type: SourceType::Txt,
        structure_type: StructureType::None,
        source_uri,
        blocks,
        images: vec![],
    }
}

/// Split on blank lines (`\n\s*\n`), trim, drop empties — Python's `_BLANK_LINE`.
pub fn split_paragraphs(text: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut current = String::new();
    let mut blank_run = false;
    for line in text.split('\n') {
        if line.trim().is_empty() {
            blank_run = true;
            continue;
        }
        if blank_run && !current.is_empty() {
            out.push(std::mem::take(&mut current));
        }
        blank_run = false;
        if !current.is_empty() {
            current.push('\n');
        }
        current.push_str(line);
    }
    if !current.is_empty() {
        out.push(current);
    }
    out.into_iter()
        .map(|c| c.trim().to_string())
        .filter(|c| !c.is_empty())
        .collect()
}
