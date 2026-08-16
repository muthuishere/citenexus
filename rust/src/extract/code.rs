//! CodeExtractor — one verbatim Evidence Unit per top-level code symbol.
//!
//! tree-sitter (Rust) finds the symbol spans; we emit one `code` block per
//! function / method / class / type / const/var declaration, `text` = the
//! verbatim source span (byte-exact), carrying the 1-based line range so the EU
//! cites `file:Lx-Ly`. File preamble (package/imports) is preserved as a leading
//! block so nothing is dropped. `structure_type = code_ast`.
//!
//! Language is detected from the source content (single `code` source type), so
//! this is one code path — the Python reference (`extract/code.py`) uses the SAME
//! grammar version (0.25) and detection, so the output is byte-identical (proven
//! by `tests/core/test_rust_code_parity.py`). Unknown/unsupported source falls
//! back to plain text — never an error ("no structure → plain, not failure").

use tree_sitter::{Node, Parser};

use crate::types::*;

/// The languages the extractor parses. Everything else falls back to plain.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Lang {
    Python,
    Go,
}

/// Detect the source language from content — identical logic to the Python
/// reference. Go always carries a `package` clause; Python never does.
fn detect_language(text: &str) -> Option<Lang> {
    let lines: Vec<&str> = text.lines().collect();
    for line in &lines {
        if line.trim_start().starts_with("package ") {
            return Some(Lang::Go);
        }
    }
    for line in &lines {
        let s = line.trim_start();
        if s.starts_with("def ")
            || s.starts_with("class ")
            || s.starts_with("async def ")
            || s.starts_with("import ")
            || s.starts_with("from ")
        {
            return Some(Lang::Python);
        }
    }
    None
}

/// A symbol span discovered in the parse tree, in source order.
struct Symbol {
    start_byte: usize,
    end_byte: usize,
    start_row: usize,
    end_row: usize,
    path: Vec<String>,
}

fn field_name<'a>(node: Node, source: &'a str) -> Option<&'a str> {
    node.child_by_field_name("name")
        .map(|n| &source[n.start_byte()..n.end_byte()])
}

fn make_symbol(node: Node, path: Vec<String>) -> Symbol {
    Symbol {
        start_byte: node.start_byte(),
        end_byte: node.end_byte(),
        start_row: node.start_position().row,
        end_row: node.end_position().row,
        path,
    }
}

/// The name for a Go grouped declaration (`type ( ... )`, `const ( ... )`): the
/// first spec's name, else the declaration keyword.
fn first_spec_name<'a>(node: Node, source: &'a str, spec_kind: &str) -> Option<&'a str> {
    let mut cursor = node.walk();
    for child in node.named_children(&mut cursor) {
        if child.kind() == spec_kind {
            if let Some(name) = field_name(child, source) {
                return Some(name);
            }
        }
    }
    None
}

fn collect_python(root: Node, source: &str) -> Vec<Symbol> {
    let mut out = Vec::new();
    let mut cursor = root.walk();
    for child in root.named_children(&mut cursor) {
        match child.kind() {
            "function_definition" | "class_definition" => {
                push_python_definition(child, source, &mut out);
            }
            "decorated_definition" => {
                if let Some(def) = child.child_by_field_name("definition") {
                    // Span = the decorated_definition (decorators included), name
                    // from the inner definition.
                    push_python_definition_spanned(child, def, source, &mut out);
                }
            }
            _ => {}
        }
    }
    out
}

fn push_python_definition(node: Node, source: &str, out: &mut Vec<Symbol>) {
    push_python_definition_spanned(node, node, source, out);
}

/// `span_node` supplies the byte/line range (decorators included); `def_node` is
/// the underlying function/class used for the name and class-body recursion.
fn push_python_definition_spanned(
    span_node: Node,
    def_node: Node,
    source: &str,
    out: &mut Vec<Symbol>,
) {
    out.push(make_symbol(span_node, vec![]));
    if def_node.kind() == "class_definition" {
        let class_name = field_name(def_node, source).unwrap_or("").to_string();
        if let Some(body) = def_node.child_by_field_name("body") {
            let mut cursor = body.walk();
            for member in body.named_children(&mut cursor) {
                match member.kind() {
                    "function_definition" => {
                        out.push(make_symbol(member, vec![class_name.clone()]));
                    }
                    "decorated_definition" => {
                        if let Some(def) = member.child_by_field_name("definition") {
                            if def.kind() == "function_definition" {
                                out.push(make_symbol(member, vec![class_name.clone()]));
                            }
                        }
                    }
                    _ => {}
                }
            }
        }
    }
}

fn collect_go(root: Node, source: &str) -> Vec<Symbol> {
    let mut out = Vec::new();
    let mut cursor = root.walk();
    for child in root.named_children(&mut cursor) {
        match child.kind() {
            "function_declaration" | "method_declaration" => {
                out.push(make_symbol(child, vec![]));
            }
            "type_declaration" => {
                let _ = first_spec_name(child, source, "type_spec");
                out.push(make_symbol(child, vec![]));
            }
            "const_declaration" => {
                let _ = first_spec_name(child, source, "const_spec");
                out.push(make_symbol(child, vec![]));
            }
            "var_declaration" => {
                let _ = first_spec_name(child, source, "var_spec");
                out.push(make_symbol(child, vec![]));
            }
            _ => {}
        }
    }
    out
}

/// Fall back to plain text — a single paragraph block with the whole source,
/// byte-identical to the Python `PlainExtractor` reference.
fn plain_fallback(text: &str, document_id: &str, source_uri: Option<String>) -> ExtractedDoc {
    ExtractedDoc {
        document_id: document_id.to_string(),
        source_type: SourceType::Plain,
        structure_type: StructureType::None,
        source_uri,
        blocks: vec![ExtractedBlock::new(0, BlockKind::Paragraph, text)],
        images: vec![],
    }
}

/// Extract `text` as source code into one EU per top-level symbol. Falls back to
/// plain text when the language is unknown or the parser is unavailable.
pub fn extract(text: &str, document_id: &str, source_uri: Option<String>) -> ExtractedDoc {
    let Some(lang) = detect_language(text) else {
        return plain_fallback(text, document_id, source_uri);
    };
    let language = match lang {
        Lang::Python => tree_sitter_python::LANGUAGE,
        Lang::Go => tree_sitter_go::LANGUAGE,
    };
    let mut parser = Parser::new();
    if parser.set_language(&language.into()).is_err() {
        return plain_fallback(text, document_id, source_uri);
    }
    let Some(tree) = parser.parse(text, None) else {
        return plain_fallback(text, document_id, source_uri);
    };
    let root = tree.root_node();
    let mut symbols = match lang {
        Lang::Python => collect_python(root, text),
        Lang::Go => collect_go(root, text),
    };
    symbols.sort_by_key(|s| s.start_byte);

    let mut blocks: Vec<ExtractedBlock> = Vec::new();
    let mut order = 0usize;

    // Preamble: everything before the first symbol (package clause / imports).
    let first_start = symbols.first().map(|s| s.start_byte).unwrap_or(text.len());
    let preamble = text[..first_start].trim_end();
    if !preamble.is_empty() {
        let end_row = preamble.matches('\n').count();
        blocks.push(code_block(order, preamble, 0, 1, end_row + 1, vec![]));
        order += 1;
    }

    for sym in &symbols {
        let symbol_text = &text[sym.start_byte..sym.end_byte];
        let level = sym.path.len() as u32;
        blocks.push(code_block(
            order,
            symbol_text,
            level,
            sym.start_row + 1,
            sym.end_row + 1,
            sym.path.clone(),
        ));
        order += 1;
    }

    if blocks.is_empty() {
        return plain_fallback(text, document_id, source_uri);
    }

    ExtractedDoc {
        document_id: document_id.to_string(),
        source_type: SourceType::Code,
        structure_type: StructureType::CodeAst,
        source_uri,
        blocks,
        images: vec![],
    }
}

fn code_block(
    order: usize,
    text: &str,
    level: u32,
    start_line: usize,
    end_line: usize,
    path: Vec<String>,
) -> ExtractedBlock {
    ExtractedBlock {
        order,
        kind: BlockKind::Code,
        text: text.to_string(),
        page: None,
        bbox: None,
        level: Some(level),
        start_line: Some(start_line as u32),
        end_line: Some(end_line as u32),
        structure_path: path,
        cells: vec![],
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const PY: &str = "import os\n\ndef tokenize(text):\n    return text.split()\n\n\
class Parser:\n    def parse(self, x):\n        return x\n";
    const GO: &str = "package main\n\nimport \"fmt\"\n\nfunc Tokenize(s string) []string {\n\
\treturn nil\n}\n\ntype Parser struct {\n\tname string\n}\n\n\
func (p *Parser) Parse() {\n\tfmt.Println(p.name)\n}\n";

    #[test]
    fn python_function_is_a_verbatim_symbol_block() {
        let doc = extract(PY, "doc", None);
        assert_eq!(doc.source_type, SourceType::Code);
        assert_eq!(doc.structure_type, StructureType::CodeAst);
        let func = doc
            .blocks
            .iter()
            .find(|b| b.text.starts_with("def tokenize"))
            .unwrap();
        assert_eq!(func.kind, BlockKind::Code);
        assert_eq!(func.text, "def tokenize(text):\n    return text.split()");
        assert_eq!(func.start_line, Some(3));
        assert!(func.structure_path.is_empty());
    }

    #[test]
    fn python_method_records_enclosing_class() {
        let doc = extract(PY, "doc", None);
        let method = doc
            .blocks
            .iter()
            .find(|b| b.text.starts_with("def parse"))
            .unwrap();
        assert_eq!(method.structure_path, vec!["Parser".to_string()]);
        assert_eq!(method.level, Some(1));
    }

    #[test]
    fn preamble_is_preserved_as_leading_block() {
        let doc = extract(GO, "doc", None);
        let preamble = &doc.blocks[0];
        assert_eq!(preamble.start_line, Some(1));
        assert!(preamble.text.contains("package main"));
        assert!(preamble.text.contains("import \"fmt\""));
    }

    #[test]
    fn go_top_level_declarations_each_become_a_block() {
        let doc = extract(GO, "doc", None);
        assert!(doc.blocks.iter().any(|b| b.text.starts_with("func Tokenize")));
        assert!(doc.blocks.iter().any(|b| b.text.starts_with("type Parser struct")));
        assert!(doc.blocks.iter().any(|b| b.text.starts_with("func (p *Parser) Parse")));
    }

    #[test]
    fn unsupported_language_falls_back_to_plain() {
        let doc = extract("fn main() { println!(\"hi\"); }\n", "doc", None);
        assert_eq!(doc.source_type, SourceType::Plain);
        assert_eq!(doc.structure_type, StructureType::None);
        assert_eq!(doc.blocks.len(), 1);
        assert_eq!(doc.blocks[0].kind, BlockKind::Paragraph);
    }
}
