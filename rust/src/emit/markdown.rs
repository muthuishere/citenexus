//! ExtractedDoc → GitHub-flavored markdown — the Rust twin of
//! `extract/markdown.py` (the behavior reference; parity is byte-identical).
//!
//! Rules: heading → `#` × clamp(level or 1, 1, 6); paragraph/table/
//! thread_turn/ocr_block → text verbatim; code → fenced; slide →
//! `## Slide {page}` + text (heading omitted when `page` is unset); image →
//! text, or the `![image]()` placeholder when empty. Blocks join with one
//! blank line; empty renderings are skipped; non-empty output ends with one
//! newline.

use crate::types::{BlockKind, ExtractedBlock, ExtractedDoc};

fn render(block: &ExtractedBlock) -> String {
    match block.kind {
        BlockKind::Heading => {
            let level = block.level.unwrap_or(1).clamp(1, 6) as usize;
            format!("{} {}", "#".repeat(level), block.text)
        }
        BlockKind::Code => {
            if block.text.is_empty() {
                String::new()
            } else {
                format!("```\n{}\n```", block.text)
            }
        }
        BlockKind::Slide => match block.page {
            None => block.text.clone(),
            Some(page) => {
                if block.text.is_empty() {
                    format!("## Slide {page}")
                } else {
                    format!("## Slide {page}\n\n{}", block.text)
                }
            }
        },
        BlockKind::Image => {
            if block.text.is_empty() {
                "![image]()".to_string()
            } else {
                block.text.clone()
            }
        }
        BlockKind::Paragraph | BlockKind::Table | BlockKind::ThreadTurn | BlockKind::OcrBlock => {
            block.text.clone()
        }
    }
}

/// Render `doc`'s blocks, in document order, to markdown.
pub fn to_markdown(doc: &ExtractedDoc) -> String {
    let parts: Vec<String> = doc
        .blocks
        .iter()
        .map(render)
        .filter(|part| !part.is_empty())
        .collect();
    if parts.is_empty() {
        String::new()
    } else {
        format!("{}\n", parts.join("\n\n"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::{SourceType, StructureType};

    fn doc(blocks: Vec<ExtractedBlock>) -> ExtractedDoc {
        ExtractedDoc {
            document_id: "doc".to_string(),
            source_type: SourceType::Txt,
            structure_type: StructureType::None,
            source_uri: None,
            blocks,
            images: vec![],
        }
    }

    fn block(kind: BlockKind, text: &str) -> ExtractedBlock {
        ExtractedBlock::new(0, kind, text)
    }

    #[test]
    fn heading_levels_render_and_clamp() {
        let mut two = block(BlockKind::Heading, "Two");
        two.level = Some(2);
        let default = block(BlockKind::Heading, "Default");
        let mut nine = block(BlockKind::Heading, "Nine");
        nine.level = Some(9);
        assert_eq!(
            to_markdown(&doc(vec![two, default, nine])),
            "## Two\n\n# Default\n\n###### Nine\n"
        );
    }

    #[test]
    fn verbatim_kinds() {
        let blocks = vec![
            block(BlockKind::Paragraph, "A paragraph."),
            block(BlockKind::Table, "name: ada, age: 36"),
            block(BlockKind::ThreadTurn, "reply text"),
            block(BlockKind::OcrBlock, "scanned words"),
        ];
        assert_eq!(
            to_markdown(&doc(blocks)),
            "A paragraph.\n\nname: ada, age: 36\n\nreply text\n\nscanned words\n"
        );
    }

    #[test]
    fn code_is_fenced() {
        assert_eq!(
            to_markdown(&doc(vec![block(BlockKind::Code, "x = 1\ny = 2")])),
            "```\nx = 1\ny = 2\n```\n"
        );
    }

    #[test]
    fn slide_heading_from_page() {
        let mut paged = block(BlockKind::Slide, "Title frame\nBody frame");
        paged.page = Some(1);
        let unpaged = block(BlockKind::Slide, "No page slide");
        assert_eq!(
            to_markdown(&doc(vec![paged, unpaged])),
            "## Slide 1\n\nTitle frame\nBody frame\n\nNo page slide\n"
        );
    }

    #[test]
    fn image_text_or_placeholder() {
        let blocks = vec![
            block(BlockKind::Image, "figure caption"),
            block(BlockKind::Image, ""),
        ];
        assert_eq!(to_markdown(&doc(blocks)), "figure caption\n\n![image]()\n");
    }

    #[test]
    fn empty_text_blocks_are_skipped() {
        let blocks = vec![
            block(BlockKind::Paragraph, "kept"),
            block(BlockKind::Paragraph, ""),
            block(BlockKind::Paragraph, "also kept"),
        ];
        assert_eq!(to_markdown(&doc(blocks)), "kept\n\nalso kept\n");
    }

    #[test]
    fn empty_document_renders_empty() {
        assert_eq!(to_markdown(&doc(vec![])), "");
    }
}
