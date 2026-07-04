//! PdfExtractor — text per page + page-level bbox, via pdfium (feature `pdf`).
//!
//! Mirrors `extract/pdf.py`: one paragraph block per page (1-based `page`),
//! text from the page's text layer, and each page image as an
//! `ImageRef(page{N}-img{i})`. pdfium-render binds libpdfium dynamically at
//! runtime, so the crate compiles without it; enable the feature and ship
//! the pdfium library alongside (see pdfium-render docs).

use pdfium_render::prelude::*;

use crate::types::*;

pub fn extract(
    bytes: &[u8],
    document_id: &str,
    source_uri: Option<String>,
) -> Result<ExtractedDoc, String> {
    let pdfium = Pdfium::default();
    let document = pdfium
        .load_pdf_from_byte_slice(bytes, None)
        .map_err(|e| format!("pdfium: {e}"))?;

    let mut blocks = Vec::new();
    let mut images = Vec::new();

    for (index, page) in document.pages().iter().enumerate() {
        let number = (index + 1) as u32;
        let text = page
            .text()
            .map(|t| t.all())
            .unwrap_or_default()
            .trim()
            .to_string();
        blocks.push(ExtractedBlock {
            order: index,
            kind: BlockKind::Paragraph,
            text,
            page: Some(number),
            bbox: None, // word-derived bbox lands with the conformance pass
            level: None,
            structure_path: vec![],
        });

        let mut img_index = 0usize;
        for object in page.objects().iter() {
            if object.as_image_object().is_some() {
                let bounds = object.bounds().ok();
                images.push(ImageRef {
                    image_id: format!("page{number}-img{img_index}"),
                    page: Some(number),
                    bbox: bounds.map(|b| {
                        [
                            b.left().value as f64,
                            b.top().value as f64,
                            b.right().value as f64,
                            b.bottom().value as f64,
                        ]
                    }),
                    width: None,
                    height: None,
                    blob_key: None,
                });
                img_index += 1;
            }
        }
    }

    Ok(ExtractedDoc {
        document_id: document_id.to_string(),
        source_type: SourceType::Pdf,
        structure_type: StructureType::PageLayout,
        source_uri,
        blocks,
        images,
    })
}
