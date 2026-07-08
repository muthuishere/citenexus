//! CsvExtractor — first row is the schema (carried on each block's
//! `structure_path`); every subsequent row is a table block rendered as
//! `col: value` pairs (mirrors `extract/csv.py`, zip-shortest semantics).

use crate::types::*;

pub fn extract(text: &str, document_id: &str, source_uri: Option<String>) -> ExtractedDoc {
    let mut reader = csv::ReaderBuilder::new()
        .has_headers(false)
        .flexible(true)
        .from_reader(text.as_bytes());

    let rows: Vec<Vec<String>> = reader
        .records()
        .filter_map(|r| r.ok())
        .map(|r| r.iter().map(|f| f.to_string()).collect())
        .collect();

    let mut blocks = Vec::new();
    let mut structure = StructureType::None;
    if let Some((header, body)) = rows.split_first() {
        structure = StructureType::TableSchema;
        for (row_index, row) in body.iter().enumerate() {
            let pairs: Vec<(&String, &String)> = header.iter().zip(row.iter()).collect(); // zip-shortest, like Python's zip(strict=False)
            let rendered = pairs
                .iter()
                .map(|(col, val)| format!("{col}: {val}"))
                .collect::<Vec<_>>()
                .join(", ");
            let cells = pairs.iter().map(|(_, val)| (*val).clone()).collect();
            blocks.push(ExtractedBlock {
                order: row_index,
                kind: BlockKind::Table,
                text: rendered,
                page: None,
                bbox: None,
                level: Some(row_index as u32),
                structure_path: header.clone(),
                cells,
            });
        }
    }

    ExtractedDoc {
        document_id: document_id.to_string(),
        source_type: SourceType::Csv,
        structure_type: structure,
        source_uri,
        blocks,
        images: vec![],
    }
}
