//! Extraction dispatch — the Rust twin of `extract/dispatch.py`.
//!
//! A known `SourceType` selects the extractor; unknown types fall back to
//! plain text (one paragraph block per blank-line chunk, like txt but with
//! `source_type=plain`). Binary types (docx/pptx/pdf/xlsx/image) take bytes;
//! text types decode UTF-8 lossily first (Python reads text files as UTF-8 too).

pub mod csv;
pub mod html;
pub mod image;
pub mod md;
pub mod ooxml;
#[cfg(feature = "pdf")]
pub mod pdf;
pub mod txt;
pub mod xlsx;

use crate::types::*;

fn plain(text: &str, document_id: &str, source_uri: Option<String>) -> ExtractedDoc {
    let mut doc = txt::extract(text, document_id, source_uri);
    doc.source_type = SourceType::Plain;
    doc
}

/// Extract `bytes` as `source_type` into an `ExtractedDoc`.
pub fn extract(
    bytes: &[u8],
    source_type: SourceType,
    document_id: &str,
    source_uri: Option<String>,
) -> Result<ExtractedDoc, String> {
    let text = || String::from_utf8_lossy(bytes).to_string();
    match source_type {
        SourceType::Txt => Ok(txt::extract(&text(), document_id, source_uri)),
        SourceType::Md => Ok(md::extract(&text(), document_id, source_uri)),
        SourceType::Html => Ok(html::extract(&text(), document_id, source_uri)),
        SourceType::Csv => Ok(csv::extract(&text(), document_id, source_uri)),
        SourceType::Docx => ooxml::extract_docx(bytes, document_id, source_uri),
        SourceType::Pptx => ooxml::extract_pptx(bytes, document_id, source_uri),
        SourceType::Xlsx => xlsx::extract(bytes, document_id, source_uri),
        #[cfg(feature = "pdf")]
        SourceType::Pdf => pdf::extract(bytes, document_id, source_uri),
        #[cfg(not(feature = "pdf"))]
        SourceType::Pdf => Err("pdf support requires the `pdf` feature".to_string()),
        SourceType::Image => Ok(image::extract(bytes, document_id, source_uri)),
        SourceType::Plain => Ok(plain(&text(), document_id, source_uri)),
    }
}

/// Extension → SourceType, mirroring `dispatch._BY_EXTENSION` (unknown → Plain).
pub fn source_type_for_extension(ext: &str) -> SourceType {
    match ext.trim_start_matches('.').to_ascii_lowercase().as_str() {
        "txt" => SourceType::Txt,
        "md" | "markdown" => SourceType::Md,
        "csv" => SourceType::Csv,
        "html" | "htm" => SourceType::Html,
        "docx" => SourceType::Docx,
        "pptx" => SourceType::Pptx,
        "xlsx" => SourceType::Xlsx,
        "pdf" => SourceType::Pdf,
        _ => SourceType::Plain,
    }
}
