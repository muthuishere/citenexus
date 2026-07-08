//! XlsxExtractor — the Rust twin of `extract/xlsx.py` (calamine-backed).
//!
//! Each sheet: one heading block (its name, `page` = 1-based sheet index),
//! then one table block per data row rendered as `col: value` pairs zipped
//! (shortest) against the sheet's first-row header, the header carried on
//! `structure_path`. Cell rendering must stay byte-identical with the Python
//! reference: empty → "", bool → true/false, integral numbers → integer
//! digits, datetimes → `YYYY-MM-DD HH:MM:SS`, everything else → its string
//! form.

use std::io::Cursor;

use calamine::{Data, Reader, Xlsx};

use crate::types::*;

fn cell_text(value: &Data) -> String {
    match value {
        Data::Empty => String::new(),
        Data::String(s) => s.clone(),
        Data::Bool(b) => if *b { "true" } else { "false" }.to_string(),
        Data::Int(i) => i.to_string(),
        Data::Float(f) => {
            if f.fract() == 0.0 && f.abs() < i64::MAX as f64 {
                format!("{}", *f as i64)
            } else {
                format!("{f}")
            }
        }
        Data::DateTime(dt) => match dt.as_datetime() {
            Some(naive) => naive.format("%Y-%m-%d %H:%M:%S").to_string(),
            None => format!("{}", dt.as_f64()),
        },
        Data::DateTimeIso(s) | Data::DurationIso(s) => s.clone(),
        Data::Error(e) => format!("{e}"),
    }
}

pub fn extract(
    bytes: &[u8],
    document_id: &str,
    source_uri: Option<String>,
) -> Result<ExtractedDoc, String> {
    let mut workbook: Xlsx<_> = Xlsx::new(Cursor::new(bytes)).map_err(|e| format!("xlsx: {e}"))?;

    let mut blocks: Vec<ExtractedBlock> = Vec::new();
    let mut order = 0usize;
    let sheet_names = workbook.sheet_names().to_vec();
    for (sheet_index, name) in sheet_names.iter().enumerate() {
        let page = (sheet_index + 1) as u32;
        blocks.push(ExtractedBlock {
            order,
            kind: BlockKind::Heading,
            text: name.clone(),
            page: Some(page),
            bbox: None,
            level: Some(1),
            structure_path: vec![],
            cells: vec![],
        });
        order += 1;

        let range = workbook
            .worksheet_range(name)
            .map_err(|e| format!("xlsx: {e}"))?;
        let mut rows = range.rows();
        let Some(first) = rows.next() else { continue };
        let mut header: Vec<String> = first.iter().map(cell_text).collect();
        while header.last().is_some_and(String::is_empty) {
            header.pop();
        }
        if header.is_empty() {
            continue;
        }

        let mut row_index = 0u32;
        for row in rows {
            let values: Vec<String> = row.iter().map(cell_text).collect();
            if values.iter().all(String::is_empty) {
                continue;
            }
            let pairs: Vec<(&String, &String)> = header.iter().zip(values.iter()).collect();
            let rendered = pairs
                .iter()
                .map(|(col, val)| format!("{col}: {val}"))
                .collect::<Vec<_>>()
                .join(", ");
            let cells = pairs.iter().map(|(_, val)| (*val).clone()).collect();
            blocks.push(ExtractedBlock {
                order,
                kind: BlockKind::Table,
                text: rendered,
                page: Some(page),
                bbox: None,
                level: Some(row_index),
                structure_path: header.clone(),
                cells,
            });
            order += 1;
            row_index += 1;
        }
    }

    let has_rows = blocks.iter().any(|b| b.kind == BlockKind::Table);
    Ok(ExtractedDoc {
        document_id: document_id.to_string(),
        source_type: SourceType::Xlsx,
        structure_type: if has_rows {
            StructureType::TableSchema
        } else {
            StructureType::None
        },
        source_uri,
        blocks,
        images: vec![],
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture() -> Vec<u8> {
        let path = concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../conformance/fixtures/sample.xlsx"
        );
        std::fs::read(path).expect("conformance/fixtures/sample.xlsx")
    }

    #[test]
    fn two_sheets_extract_sheet_scoped_rows() {
        let doc = extract(&fixture(), "doc", None).unwrap();
        assert_eq!(doc.source_type, SourceType::Xlsx);
        assert_eq!(doc.structure_type, StructureType::TableSchema);

        let kinds: Vec<BlockKind> = doc.blocks.iter().map(|b| b.kind).collect();
        assert_eq!(
            kinds,
            vec![
                BlockKind::Heading,
                BlockKind::Table,
                BlockKind::Table,
                BlockKind::Heading,
                BlockKind::Table,
            ]
        );
        let orders: Vec<usize> = doc.blocks.iter().map(|b| b.order).collect();
        assert_eq!(orders, vec![0, 1, 2, 3, 4]);

        assert_eq!(doc.blocks[0].text, "People");
        assert_eq!(doc.blocks[0].level, Some(1));
        assert_eq!(doc.blocks[0].page, Some(1));
        assert_eq!(doc.blocks[1].text, "name: ada, age: 36, active: true");
        assert_eq!(doc.blocks[1].structure_path, vec!["name", "age", "active"]);
        assert_eq!(doc.blocks[1].level, Some(0));
        assert_eq!(doc.blocks[2].text, "name: alan, age: 41.5, active: false");
        assert_eq!(doc.blocks[2].level, Some(1));
        assert_eq!(doc.blocks[3].text, "Scores");
        assert_eq!(doc.blocks[3].page, Some(2));
        assert_eq!(doc.blocks[4].text, "team: red, points: 30");
        assert_eq!(doc.blocks[4].page, Some(2));
    }

    #[test]
    fn invalid_bytes_error() {
        assert!(extract(b"not a workbook", "doc", None).is_err());
    }
}
