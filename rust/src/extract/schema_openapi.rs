//! SchemaOpenapiExtractor — one verbatim EU per OpenAPI/JSON-Schema object.
//!
//! Byte-parity twin of the Python reference `extract/schema_openapi.py`. A
//! deterministic, span-preserving JSON scanner (no re-serialization) locates the
//! schema objects and emits one `code` block per object whose `text` is the
//! verbatim `"key": value` source span, carrying its 1-based line range so the
//! schema EU cites `file:Lx-Ly`. `structure_type = table_schema` (reused).
//!
//! Recognised objects (one EU each, document order): `paths."/x"` (endpoints),
//! `components.schemas.X` (components), `definitions.X` / `$defs.X` (JSON-Schema).
//! Emits EUs only, no edges. Non-JSON input or no recognised section → plain.

use crate::types::*;

fn line_at(data: &[u8], offset: usize) -> u32 {
    (data[..offset.min(data.len())].iter().filter(|&&b| b == b'\n').count() + 1) as u32
}

fn skip_ws(data: &[u8], mut i: usize) -> usize {
    let n = data.len();
    while i < n && data[i].is_ascii_whitespace() {
        i += 1;
    }
    i
}

/// `data[i]` is `"`; return the index just past the closing quote.
fn parse_string(data: &[u8], mut i: usize) -> usize {
    let n = data.len();
    i += 1;
    while i < n {
        let c = data[i];
        if c == b'\\' {
            i += 2;
            continue;
        }
        if c == b'"' {
            return i + 1;
        }
        i += 1;
    }
    i
}

/// Return the index just past the JSON value beginning at `data[i]`.
fn skip_value(data: &[u8], i: usize) -> usize {
    let n = data.len();
    let mut i = skip_ws(data, i);
    if i >= n {
        return i;
    }
    let c = data[i];
    if c == b'"' {
        return parse_string(data, i);
    }
    if c == b'{' || c == b'[' {
        let mut depth = 0i32;
        while i < n {
            let c = data[i];
            if c == b'"' {
                i = parse_string(data, i);
                continue;
            }
            if c == b'{' || c == b'[' {
                depth += 1;
            } else if c == b'}' || c == b']' {
                depth -= 1;
                if depth == 0 {
                    return i + 1;
                }
            }
            i += 1;
        }
        return i;
    }
    while i < n && data[i] != b',' && data[i] != b'}' && data[i] != b']' && !data[i].is_ascii_whitespace() {
        i += 1;
    }
    i
}

/// Immediate members of the object at `data[obj_start] == '{'` as
/// `(key, entry_start, value_start, entry_end)` in document order.
fn members(data: &[u8], obj_start: usize) -> Vec<(String, usize, usize, usize)> {
    let n = data.len();
    let mut out = Vec::new();
    let mut i = obj_start + 1;
    while i < n {
        i = skip_ws(data, i);
        if i >= n || data[i] == b'}' {
            break;
        }
        if data[i] == b',' {
            i += 1;
            continue;
        }
        if data[i] != b'"' {
            break;
        }
        let key_start = i;
        let key_end = parse_string(data, i);
        let key = String::from_utf8_lossy(&data[key_start + 1..key_end - 1]).into_owned();
        i = skip_ws(data, key_end);
        if i >= n || data[i] != b':' {
            break;
        }
        let value_start = skip_ws(data, i + 1);
        let value_end = skip_value(data, value_start);
        out.push((key, key_start, value_start, value_end));
        i = value_end;
    }
    out
}

/// Every recognised schema object as `(name, entry_start, entry_end)` in order.
fn find_objects(data: &[u8]) -> Vec<(String, usize, usize)> {
    let i = skip_ws(data, 0);
    if i >= data.len() || data[i] != b'{' {
        return vec![];
    }
    let mut out = Vec::new();
    for (key, _kstart, vstart, _vend) in members(data, i) {
        if data[vstart] != b'{' {
            continue;
        }
        if key == "paths" {
            for (pk, ps, _pv, pe) in members(data, vstart) {
                out.push((pk, ps, pe));
            }
        } else if key == "components" {
            for (ck, _cks, cvs, _cve) in members(data, vstart) {
                if ck == "schemas" && data[cvs] == b'{' {
                    for (sk, ss, _sv, se) in members(data, cvs) {
                        out.push((sk, ss, se));
                    }
                }
            }
        } else if key == "definitions" || key == "$defs" {
            for (dk, ds, _dv, de) in members(data, vstart) {
                out.push((dk, ds, de));
            }
        }
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

/// Extract `text` as an OpenAPI/JSON-Schema document into one EU per object.
pub fn extract(text: &str, document_id: &str, source_uri: Option<String>) -> ExtractedDoc {
    let data = text.as_bytes();
    let objects = find_objects(data);
    if objects.is_empty() {
        return plain_fallback(text, document_id, source_uri);
    }
    let mut blocks = Vec::new();
    for (order, (name, start, end)) in objects.into_iter().enumerate() {
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
        source_type: SourceType::SchemaOpenapi,
        structure_type: StructureType::TableSchema,
        source_uri,
        blocks,
        images: vec![],
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const OPENAPI: &str = "{\n  \"openapi\": \"3.0.0\",\n  \"paths\": {\n    \"/orders\": {\n\
      \"post\": {}\n    }\n  },\n  \"components\": {\n    \"schemas\": {\n\
      \"Order\": { \"type\": \"object\" }\n    }\n  }\n}\n";

    #[test]
    fn endpoint_becomes_verbatim_eu() {
        let doc = extract(OPENAPI, "doc", None);
        assert_eq!(doc.source_type, SourceType::SchemaOpenapi);
        assert_eq!(doc.structure_type, StructureType::TableSchema);
        let endpoint = doc
            .blocks
            .iter()
            .find(|b| b.structure_path == vec!["/orders".to_string()])
            .unwrap();
        assert_eq!(endpoint.kind, BlockKind::Code);
        assert!(endpoint.text.starts_with("\"/orders\""));
    }

    #[test]
    fn component_schema_becomes_verbatim_eu() {
        let doc = extract(OPENAPI, "doc", None);
        let order = doc
            .blocks
            .iter()
            .find(|b| b.structure_path == vec!["Order".to_string()])
            .unwrap();
        assert!(order.text.contains("\"type\": \"object\""));
    }

    #[test]
    fn non_json_falls_back_to_plain() {
        let doc = extract("openapi: 3.0.0\npaths:\n", "doc", None);
        assert_eq!(doc.source_type, SourceType::Plain);
        assert_eq!(doc.structure_type, StructureType::None);
    }
}
