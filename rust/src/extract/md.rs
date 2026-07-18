//! MdExtractor — headings become heading blocks (level + ancestor
//! `structure_path`); paragraphs carry the enclosing heading path
//! (mirrors `extract/md.py`).

use pulldown_cmark::{Event, HeadingLevel, Parser, Tag, TagEnd};

use crate::types::*;

fn level_of(level: HeadingLevel) -> u32 {
    match level {
        HeadingLevel::H1 => 1,
        HeadingLevel::H2 => 2,
        HeadingLevel::H3 => 3,
        HeadingLevel::H4 => 4,
        HeadingLevel::H5 => 5,
        HeadingLevel::H6 => 6,
    }
}

pub fn extract(text: &str, document_id: &str, source_uri: Option<String>) -> ExtractedDoc {
    let mut blocks: Vec<ExtractedBlock> = Vec::new();
    let mut stack: Vec<(u32, String)> = Vec::new(); // (level, heading text)
    let mut order = 0usize;
    let mut has_heading = false;

    // Collector state: Some(kind) while inside a heading/paragraph.
    enum In {
        Heading(u32),
        Paragraph,
    }
    let mut current: Option<(In, String)> = None;

    for event in Parser::new(text) {
        match event {
            Event::Start(Tag::Heading { level, .. }) => {
                current = Some((In::Heading(level_of(level)), String::new()));
            }
            Event::Start(Tag::Paragraph) => {
                current = Some((In::Paragraph, String::new()));
            }
            Event::Text(t) | Event::Code(t) => {
                if let Some((_, buf)) = current.as_mut() {
                    buf.push_str(&t);
                }
            }
            Event::SoftBreak | Event::HardBreak => {
                if let Some((_, buf)) = current.as_mut() {
                    buf.push('\n');
                }
            }
            Event::End(TagEnd::Heading(_)) => {
                if let Some((In::Heading(level), buf)) = current.take() {
                    let content = buf.trim().to_string();
                    while stack.last().is_some_and(|(l, _)| *l >= level) {
                        stack.pop();
                    }
                    let ancestors: Vec<String> = stack.iter().map(|(_, t)| t.clone()).collect();
                    blocks.push(ExtractedBlock {
                        order,
                        kind: BlockKind::Heading,
                        text: content.clone(),
                        page: None,
                        bbox: None,
                        level: Some(level),
                        start_line: None,
                        end_line: None,
                        structure_path: ancestors,
                        cells: vec![],
                    });
                    stack.push((level, content));
                    has_heading = true;
                    order += 1;
                }
            }
            Event::End(TagEnd::Paragraph) => {
                if let Some((In::Paragraph, buf)) = current.take() {
                    let content = buf.trim().to_string();
                    if !content.is_empty() {
                        blocks.push(ExtractedBlock {
                            order,
                            kind: BlockKind::Paragraph,
                            text: content,
                            page: None,
                            bbox: None,
                            level: None,
                            start_line: None,
                            end_line: None,
                            structure_path: stack.iter().map(|(_, t)| t.clone()).collect(),
                            cells: vec![],
                        });
                        order += 1;
                    }
                }
            }
            _ => {}
        }
    }

    let structure = if has_heading {
        StructureType::HeadingTree
    } else {
        StructureType::None
    };
    ExtractedDoc {
        document_id: document_id.to_string(),
        source_type: SourceType::Md,
        structure_type: structure,
        source_uri,
        blocks,
        images: vec![],
    }
}
