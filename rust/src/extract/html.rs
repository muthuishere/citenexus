//! HtmlExtractor — walk h1–h6 + p in document order; script/style subtrees
//! dropped; headings maintain the ancestor stack (mirrors `extract/html.py`).

use scraper::{ElementRef, Html, Selector};

use crate::types::*;

/// BeautifulSoup `get_text(strip=True)` parity: every descendant text node,
/// each stripped, concatenated — but nothing under `<script>`/`<style>`
/// (Python decomposes those subtrees before extraction).
fn element_text(el: ElementRef) -> String {
    fn walk(node: ego_tree::NodeRef<scraper::Node>, out: &mut Vec<String>) {
        for child in node.children() {
            match child.value() {
                scraper::Node::Text(t) => {
                    let trimmed = t.trim();
                    if !trimmed.is_empty() {
                        out.push(trimmed.to_string());
                    }
                }
                scraper::Node::Element(e) => {
                    let name = e.name();
                    if name != "script" && name != "style" {
                        walk(child, out);
                    }
                }
                _ => {}
            }
        }
    }
    let mut parts = Vec::new();
    walk(*el, &mut parts);
    parts.join("")
}

pub fn extract(text: &str, document_id: &str, source_uri: Option<String>) -> ExtractedDoc {
    let document = Html::parse_document(text);
    let selector = Selector::parse("h1, h2, h3, h4, h5, h6, p").expect("static selector");

    let mut blocks: Vec<ExtractedBlock> = Vec::new();
    let mut stack: Vec<(u32, String)> = Vec::new();
    let mut order = 0usize;
    let mut has_heading = false;

    for el in document.select(&selector) {
        let content = element_text(el);
        if content.is_empty() {
            continue;
        }
        let name = el.value().name();
        if let Some(level_char) = name.strip_prefix('h').and_then(|s| s.chars().next()) {
            if name.len() == 2 && level_char.is_ascii_digit() {
                let level = level_char.to_digit(10).unwrap_or(1);
                while stack.last().is_some_and(|(l, _)| *l >= level) {
                    stack.pop();
                }
                blocks.push(ExtractedBlock {
                    order,
                    kind: BlockKind::Heading,
                    text: content.clone(),
                    page: None,
                    bbox: None,
                    level: Some(level),
                    structure_path: stack.iter().map(|(_, t)| t.clone()).collect(),
                });
                stack.push((level, content));
                has_heading = true;
                order += 1;
                continue;
            }
        }
        blocks.push(ExtractedBlock {
            order,
            kind: BlockKind::Paragraph,
            text: content,
            page: None,
            bbox: None,
            level: None,
            structure_path: stack.iter().map(|(_, t)| t.clone()).collect(),
        });
        order += 1;
    }

    let structure = if has_heading {
        StructureType::HeadingTree
    } else {
        StructureType::None
    };
    ExtractedDoc {
        document_id: document_id.to_string(),
        source_type: SourceType::Html,
        structure_type: structure,
        source_uri,
        blocks,
        images: vec![],
    }
}
