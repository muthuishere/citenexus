//! ExtractedDoc → GitHub-flavored markdown — the Rust twin of
//! `extract/markdown.py` (the behavior reference; parity is byte-identical).
//!
//! Rules: heading → `#` × clamp(level or 1, 1, 6); paragraph/thread_turn/
//! ocr_block → text verbatim; code → fenced; slide → `## Slide {page}` + text
//! (heading omitted when `page` is unset); image → text, or the `![image]()`
//! placeholder when empty. A run of contiguous `table` blocks that share a
//! non-empty `structure_path` (their header) fuses into one GitHub-flavored
//! pipe table built from each block's `cells`; a `table` block with no header
//! falls back to its text verbatim. Blocks join with one blank line; empty
//! renderings are skipped; non-empty output ends with one newline.

use crate::types::{BlockKind, ExtractedBlock, ExtractedDoc};

/// Pipe / newline are the two characters that would break a GFM table cell.
fn escape_cell(text: &str) -> String {
    text.replace('\n', " ").replace('|', "\\|")
}

/// Render a run of table rows (all sharing `header`) as one GFM pipe table.
fn render_table(header: &[String], rows: &[&ExtractedBlock]) -> String {
    let ncols = header.len();
    let mut lines = Vec::with_capacity(rows.len() + 2);
    let head = header.iter().map(|c| escape_cell(c)).collect::<Vec<_>>();
    lines.push(format!("| {} |", head.join(" | ")));
    lines.push(format!("| {} |", vec!["---"; ncols].join(" | ")));
    for block in rows {
        let mut cells: Vec<String> = block.cells.iter().take(ncols).map(|c| escape_cell(c)).collect();
        while cells.len() < ncols {
            cells.push(String::new());
        }
        lines.push(format!("| {} |", cells.join(" | ")));
    }
    lines.join("\n")
}

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
    let blocks = &doc.blocks;
    let mut parts: Vec<String> = Vec::new();
    let mut i = 0;
    while i < blocks.len() {
        let block = &blocks[i];
        // Fuse a contiguous run of table rows sharing a header into one table.
        if block.kind == BlockKind::Table && !block.structure_path.is_empty() {
            let header = &block.structure_path;
            let mut run: Vec<&ExtractedBlock> = Vec::new();
            while i < blocks.len()
                && blocks[i].kind == BlockKind::Table
                && blocks[i].structure_path == *header
            {
                run.push(&blocks[i]);
                i += 1;
            }
            parts.push(render_table(header, &run));
            continue;
        }
        let rendered = render(block);
        if !rendered.is_empty() {
            parts.push(rendered);
        }
        i += 1;
    }
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

    fn table_row(header: &[&str], cells: &[&str]) -> ExtractedBlock {
        let mut b = block(BlockKind::Table, "ignored verbatim text");
        b.structure_path = header.iter().map(|s| s.to_string()).collect();
        b.cells = cells.iter().map(|s| s.to_string()).collect();
        b
    }

    #[test]
    fn contiguous_rows_fuse_into_one_gfm_table() {
        let blocks = vec![
            table_row(&["name", "age"], &["ada", "36"]),
            table_row(&["name", "age"], &["lin", "29"]),
        ];
        assert_eq!(
            to_markdown(&doc(blocks)),
            "| name | age |\n| --- | --- |\n| ada | 36 |\n| lin | 29 |\n"
        );
    }

    #[test]
    fn different_headers_and_short_rows_split_and_pad() {
        let blocks = vec![
            table_row(&["a", "b"], &["1"]), // short row → padded
            table_row(&["x"], &["9", "extra"]), // new header → new table; extra cell truncated
        ];
        assert_eq!(
            to_markdown(&doc(blocks)),
            "| a | b |\n| --- | --- |\n| 1 |  |\n\n| x |\n| --- |\n| 9 |\n"
        );
    }

    #[test]
    fn pipes_and_newlines_in_cells_are_escaped() {
        let blocks = vec![table_row(&["h|x", "y"], &["a|b", "c\nd"])];
        assert_eq!(
            to_markdown(&doc(blocks)),
            "| h\\|x | y |\n| --- | --- |\n| a\\|b | c d |\n"
        );
    }

    #[test]
    fn headerless_table_block_stays_verbatim() {
        assert_eq!(
            to_markdown(&doc(vec![block(BlockKind::Table, "name: ada, age: 36")])),
            "name: ada, age: 36\n"
        );
    }
}
