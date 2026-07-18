//! SchemaSqlExtractor — one verbatim Evidence Unit per SQL `CREATE TABLE`.
//!
//! The byte-parity twin of the Python reference `extract/schema_sql.py`: a
//! deterministic, model-free DDL scanner finds each `CREATE TABLE` statement and
//! emits one `code` block whose `text` is the verbatim source span (byte-exact,
//! including the trailing `;`), carrying the 1-based line range so the schema EU
//! cites `file:Lx-Ly`. `structure_type = table_schema` (reused — no new type).
//!
//! The extractor emits EUs only, no edges — `ExtractedDoc` has no edge channel.
//! FK edges come from an injected schema distiller (Python example code). A source
//! with no `CREATE TABLE` degrades to plain text — never an error.

use crate::types::*;

const QUOTE_OPENERS: &[u8] = b"\"`[";

fn is_word_byte(b: u8) -> bool {
    b.is_ascii_alphanumeric() || b == b'_'
}

/// `data[i..i+kw.len()]` equals ASCII-lowercase `kw`, case-insensitively.
fn eq_ci(data: &[u8], i: usize, kw: &[u8]) -> bool {
    if i + kw.len() > data.len() {
        return false;
    }
    data[i..i + kw.len()].eq_ignore_ascii_case(kw)
}

/// `kw` matches at `i` on ASCII word boundaries (a whole keyword).
fn word_at(data: &[u8], i: usize, kw: &[u8]) -> bool {
    if !eq_ci(data, i, kw) {
        return false;
    }
    if i > 0 && is_word_byte(data[i - 1]) {
        return false;
    }
    let end = i + kw.len();
    end >= data.len() || !is_word_byte(data[end])
}

/// 1-based line number of byte `offset`.
fn line_at(data: &[u8], offset: usize) -> u32 {
    (data[..offset.min(data.len())].iter().filter(|&&b| b == b'\n').count() + 1) as u32
}

/// Index just past a quoted run starting at `data[i]` (a quote/bracket).
fn skip_quoted(data: &[u8], mut i: usize) -> usize {
    let n = data.len();
    let opener = data[i];
    let close = if opener == b'[' { b']' } else { opener };
    i += 1;
    while i < n {
        let c = data[i];
        if c == close {
            if close != b']' && i + 1 < n && data[i + 1] == close {
                i += 2; // doubled delimiter → escaped literal
                continue;
            }
            return i + 1;
        }
        i += 1;
    }
    i
}

/// Skip whitespace, `-- line` comments and `/* block */` comments.
fn skip_ws_and_comments(data: &[u8], mut i: usize) -> usize {
    let n = data.len();
    while i < n {
        if data[i].is_ascii_whitespace() {
            i += 1;
        } else if data[i] == b'-' && i + 1 < n && data[i + 1] == b'-' {
            while i < n && data[i] != b'\n' {
                i += 1;
            }
        } else if data[i] == b'/' && i + 1 < n && data[i + 1] == b'*' {
            i += 2;
            while i + 1 < n && !(data[i] == b'*' && data[i + 1] == b'/') {
                i += 1;
            }
            i += 2;
        } else {
            break;
        }
    }
    i
}

/// Read a (possibly schema-qualified / quoted) table name; return its last
/// segment plus the index just past it.
fn read_name(data: &[u8], mut i: usize) -> (String, usize) {
    let n = data.len();
    let mut last = String::new();
    while i < n {
        if QUOTE_OPENERS.contains(&data[i]) {
            let end = skip_quoted(data, i);
            last = String::from_utf8_lossy(&data[i + 1..end - 1]).into_owned();
            i = end;
        } else {
            let start = i;
            while i < n && is_word_byte(data[i]) {
                i += 1;
            }
            if i == start {
                break;
            }
            last = String::from_utf8_lossy(&data[start..i]).into_owned();
        }
        if i < n && data[i] == b'.' {
            i += 1;
            continue;
        }
        break;
    }
    (last, i)
}

/// From just past the table name, return the index just past the terminating `;`
/// (or end of input), balancing the column-definition parentheses.
fn statement_end(data: &[u8], mut i: usize) -> usize {
    let n = data.len();
    i = skip_ws_and_comments(data, i);
    if i < n && data[i] == b'(' {
        let mut depth = 0i32;
        while i < n {
            let c = data[i];
            if QUOTE_OPENERS.contains(&c) || c == b'\'' {
                i = skip_quoted(data, i);
                continue;
            }
            if c == b'-' && i + 1 < n && data[i + 1] == b'-' {
                i = skip_ws_and_comments(data, i);
                continue;
            }
            if c == b'/' && i + 1 < n && data[i + 1] == b'*' {
                i = skip_ws_and_comments(data, i);
                continue;
            }
            if c == b'(' {
                depth += 1;
            } else if c == b')' {
                depth -= 1;
                if depth == 0 {
                    i += 1;
                    break;
                }
            }
            i += 1;
        }
    }
    while i < n && data[i] != b';' {
        if QUOTE_OPENERS.contains(&data[i]) || data[i] == b'\'' {
            i = skip_quoted(data, i);
            continue;
        }
        i += 1;
    }
    if i < n && data[i] == b';' {
        i += 1;
    }
    i
}

/// Every `CREATE TABLE` statement as `(start, end, name)` in source order.
fn find_tables(data: &[u8]) -> Vec<(usize, usize, String)> {
    let n = data.len();
    let mut out = Vec::new();
    let mut i = 0;
    while i < n {
        if word_at(data, i, b"create") {
            let j = skip_ws_and_comments(data, i + 6);
            if word_at(data, j, b"table") {
                let mut k = skip_ws_and_comments(data, j + 5);
                if word_at(data, k, b"if") {
                    k = skip_ws_and_comments(data, k + 2);
                    if word_at(data, k, b"not") {
                        k = skip_ws_and_comments(data, k + 3);
                        if word_at(data, k, b"exists") {
                            k = skip_ws_and_comments(data, k + 6);
                        }
                    }
                }
                let (name, k) = read_name(data, k);
                let end = statement_end(data, k);
                out.push((i, end, name));
                i = end;
                continue;
            }
        }
        i += 1;
    }
    out
}

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

/// Extract `text` as SQL DDL into one verbatim EU per table.
pub fn extract(text: &str, document_id: &str, source_uri: Option<String>) -> ExtractedDoc {
    let data = text.as_bytes();
    let tables = find_tables(data);
    if tables.is_empty() {
        return plain_fallback(text, document_id, source_uri);
    }
    let mut blocks = Vec::new();
    for (order, (start, end, name)) in tables.into_iter().enumerate() {
        let path = if name.is_empty() { vec![] } else { vec![name] };
        blocks.push(ExtractedBlock {
            order,
            kind: BlockKind::Code,
            text: String::from_utf8_lossy(&data[start..end]).into_owned(),
            page: None,
            bbox: None,
            level: Some(0),
            start_line: Some(line_at(data, start)),
            end_line: Some(line_at(data, start.max(end.saturating_sub(1)))),
            structure_path: path,
            cells: vec![],
        });
    }
    ExtractedDoc {
        document_id: document_id.to_string(),
        source_type: SourceType::SchemaSql,
        structure_type: StructureType::TableSchema,
        source_uri,
        blocks,
        images: vec![],
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const SQL: &str = "-- users schema\nCREATE TABLE accounts (\n    id INTEGER PRIMARY KEY,\n\
    name TEXT NOT NULL\n);\n\nCREATE TABLE IF NOT EXISTS orders (\n    id INTEGER PRIMARY KEY,\n\
    account_id INTEGER REFERENCES accounts(id)\n);\n";

    #[test]
    fn table_becomes_verbatim_schema_eu() {
        let doc = extract(SQL, "doc", None);
        assert_eq!(doc.source_type, SourceType::SchemaSql);
        assert_eq!(doc.structure_type, StructureType::TableSchema);
        let accounts = &doc.blocks[0];
        assert_eq!(accounts.kind, BlockKind::Code);
        assert_eq!(accounts.structure_path, vec!["accounts".to_string()]);
        assert!(accounts.text.starts_with("CREATE TABLE accounts ("));
        assert!(accounts.text.ends_with(");"));
        assert_eq!(accounts.start_line, Some(2));
    }

    #[test]
    fn if_not_exists_and_qualified_names_are_handled() {
        let doc = extract(SQL, "doc", None);
        let orders = &doc.blocks[1];
        assert_eq!(orders.structure_path, vec!["orders".to_string()]);
        assert!(orders.text.starts_with("CREATE TABLE IF NOT EXISTS orders"));
    }

    #[test]
    fn no_tables_falls_back_to_plain() {
        let doc = extract("SELECT * FROM t;\n", "doc", None);
        assert_eq!(doc.source_type, SourceType::Plain);
        assert_eq!(doc.structure_type, StructureType::None);
    }
}
