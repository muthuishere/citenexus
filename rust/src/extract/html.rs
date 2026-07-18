//! HtmlExtractor — walk h1–h6 + p + ul/ol in document order; script/style
//! subtrees dropped; headings maintain the ancestor stack; `<a href>` becomes
//! `[text](href)` inline; a top-level list becomes one block of `- ` / `N. `
//! lines from its direct `<li>` children. Mirrors `extract/html.py`.

use scraper::{ElementRef, Html, Selector};

use crate::types::*;

/// Rich inline text of an element: BeautifulSoup `get_text(strip=True)` parity
/// (every descendant text node stripped, concatenated, nothing under
/// `<script>`/`<style>`) EXCEPT that an `<a href>` is rendered as
/// `[inner](href)` and not descended into. With no links this reduces to the
/// old plain-text concatenation, so existing behavior is unchanged.
fn rich_text(el: ElementRef) -> String {
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
                    if name == "script" || name == "style" {
                        continue;
                    }
                    if name == "a" {
                        if let Some(href) = e.attr("href") {
                            let child_ref = ElementRef::wrap(child).expect("element node");
                            let inner = rich_text(child_ref);
                            if !inner.is_empty() {
                                out.push(format!("[{inner}]({href})"));
                            }
                            continue;
                        }
                    }
                    walk(child, out);
                }
                _ => {}
            }
        }
    }
    let mut parts = Vec::new();
    walk(*el, &mut parts);
    parts.join("")
}

/// True when `el` sits inside a list (`ul`/`ol`/`li`) — such elements are
/// rendered as part of their enclosing list, never as standalone blocks.
fn inside_list(el: ElementRef) -> bool {
    el.ancestors().any(|n| {
        n.value()
            .as_element()
            .is_some_and(|e| matches!(e.name(), "ul" | "ol" | "li"))
    })
}

/// Render a `ul`/`ol` from its direct `<li>` children; `None` when it has no
/// non-empty items. Unordered → `- item`; ordered → `1. item`, `2. item`, …
fn render_list(list: ElementRef) -> Option<String> {
    let ordered = list.value().name() == "ol";
    let mut lines: Vec<String> = Vec::new();
    for child in list.children() {
        let Some(li) = ElementRef::wrap(child) else {
            continue;
        };
        if li.value().name() != "li" {
            continue;
        }
        let item = rich_text(li);
        if item.is_empty() {
            continue;
        }
        if ordered {
            lines.push(format!("{}. {item}", lines.len() + 1));
        } else {
            lines.push(format!("- {item}"));
        }
    }
    if lines.is_empty() {
        None
    } else {
        Some(lines.join("\n"))
    }
}

pub fn extract(text: &str, document_id: &str, source_uri: Option<String>) -> ExtractedDoc {
    let document = Html::parse_document(text);
    let selector = Selector::parse("h1, h2, h3, h4, h5, h6, p, ul, ol").expect("static selector");

    let mut blocks: Vec<ExtractedBlock> = Vec::new();
    let mut stack: Vec<(u32, String)> = Vec::new();
    let mut order = 0usize;
    let mut has_heading = false;

    for el in document.select(&selector) {
        // Elements inside a list are rendered by their enclosing list block.
        if inside_list(el) {
            continue;
        }
        let name = el.value().name();
        let structure_path: Vec<String> = stack.iter().map(|(_, t)| t.clone()).collect();

        if name == "ul" || name == "ol" {
            if let Some(rendered) = render_list(el) {
                blocks.push(ExtractedBlock {
                    order,
                    kind: BlockKind::Paragraph,
                    text: rendered,
                    page: None,
                    bbox: None,
                    level: None,
                    start_line: None,
                    end_line: None,
                    structure_path,
                    cells: vec![],
                });
                order += 1;
            }
            continue;
        }

        let content = rich_text(el);
        if content.is_empty() {
            continue;
        }
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
                    start_line: None,
                    end_line: None,
                    structure_path,
                    cells: vec![],
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
            start_line: None,
            end_line: None,
            structure_path,
            cells: vec![],
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

#[cfg(test)]
mod tests {
    use super::*;

    fn texts(html: &str) -> Vec<String> {
        extract(html, "doc", None)
            .blocks
            .into_iter()
            .map(|b| b.text)
            .collect()
    }

    #[test]
    fn anchor_with_href_renders_inline_link() {
        assert_eq!(
            texts(r#"<p>go <a href="https://x.test">here</a></p>"#),
            vec!["go[here](https://x.test)"]
        );
    }

    #[test]
    fn anchor_without_href_is_plain() {
        assert_eq!(texts("<p>plain <a>anchor</a> word</p>"), vec!["plainanchorword"]);
    }

    #[test]
    fn unordered_and_ordered_lists() {
        assert_eq!(
            texts("<ul><li>alpha</li><li>beta</li></ul>"),
            vec!["- alpha\n- beta"]
        );
        assert_eq!(
            texts("<ol><li>one</li><li></li><li>three</li></ol>"),
            vec!["1. one\n2. three"]
        );
    }

    #[test]
    fn list_item_p_not_duplicated_and_keeps_link() {
        assert_eq!(
            texts(r#"<ul><li><p>wrapped <a href="/x">link</a></p></li></ul>"#),
            vec!["- wrapped[link](/x)"]
        );
    }
}
