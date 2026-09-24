//! DOCX / PPTX → `DocUnit`s from the package's own OOXML structure
//! (ADR-0017 decision 8). Deterministic, no model, `route = ooxml`.
//!
//! This is the structured twin of `extract/ooxml.rs` (which keeps the Python
//! `ExtractedDoc` parity shape and is left untouched). Everything here is read
//! straight from the XML parts; nothing is inferred from layout.
//!
//! **DOCX** (`word/document.xml`, in document order):
//! - `w:p` → `heading` | `list` | `paragraph`. A heading's level comes from, in
//!   order: the paragraph's own `w:outlineLvl`; then the style chain in
//!   `styles.xml` (`w:pStyle` → `w:basedOn` → …, the default paragraph style
//!   when there is no `w:pStyle`), where each style is asked for `w:outlineLvl`
//!   first and its built-in `w:name` (`heading N`, `Title`) second — so
//!   localized ids (`Kop1`) and custom styles based on a heading resolve, and an
//!   explicit outline level 9 means body text even under a heading-based
//!   style; the style id pattern (`Heading2`, `Title`) is used only when the
//!   style is absent from `styles.xml`. `Title` is level 1. Levels 7–9 are
//!   clamped to 6 (markdown has six).
//! - Lists: `w:numPr` on the paragraph or inherited from its style chain,
//!   resolved through `numbering.xml` (`w:num` → `w:abstractNum`, one
//!   `w:numStyleLink` hop, `w:lvlOverride`). Every item carries the
//!   document's REAL label — a label is a citation anchor ("artikel 3 lid b",
//!   "sub ii") — built from `w:lvlText` (`%1.`, `(%1)`, `%1.%2`) with each
//!   `%N` rendered in that level's `w:numFmt` (decimal, decimalZero,
//!   lower/upperLetter as a, …, z, aa, lower/upperRoman; `w:isLgl` forces
//!   other levels to decimal). A pure-decimal label (`3.`, `3)`) is a native
//!   markdown ordered marker; any other label is literal text after `- `,
//!   markdown-escaped, so nesting survives (`- b. text`, `- (ii) text`,
//!   `- 2.b text`). An unknown `numFmt` renders the decimal value and the unit
//!   gets `failed_check = "list_label_unknown_format"` — never a silent `1.`.
//!   Counting: `w:start`; counters are per abstract list (nums sharing an
//!   abstractNum continue one sequence, as Word does); a `w:startOverride`
//!   restarts the sequence the first time its num is used; a deeper level
//!   restarts after a shallower one is used unless `w:lvlRestart` says
//!   otherwise (`0` = never). Numbered headings keep their label
//!   (`# Artikel 3 Huurprijs`) and advance the counters, so sub-levels restart
//!   under them. `numFmt=bullet` renders `-`; `numFmt=none` and `numId=0` are
//!   not lists. Consecutive list paragraphs form ONE `list` unit; an item
//!   nests under the nearest preceding item of a shallower level, indented to
//!   that parent's content column.
//! - `w:tbl` → a pipe table (see "tables" below). Tables nested in a cell are
//!   lifted out: each becomes its own `table` unit right after its parent, with
//!   `failed_check = "nested_table"`; both tables are `table_uncertain`. A 1×1
//!   table (a boxed note) is emitted as a paragraph.
//! - `w:sdt`, `w:customXml`, `w:ins` are unwrapped; `w:del`/`w:delText` and
//!   field instructions (`w:instrText`) are dropped; `mc:AlternateContent`
//!   reads only its first `mc:Choice` (the fallback duplicates it). Text boxes
//!   (`w:txbxContent`) are emitted right after the paragraph that anchors them.
//! - Headers/footers (`header*.xml`/`footer*.xml` referenced from
//!   `document.xml.rels`) become `furniture` units, each distinct line kept
//!   ONCE: headers before the body, footers after it.
//! - Hyphens: U+00AD and `w:softHyphen` are optional break points and vanish
//!   (the word is joined as written); `w:noBreakHyphen` is a real hyphen and
//!   renders `-`. A literal `-` is never touched, so "e-mail" and
//!   "in- en verkoop" survive. No `joined_hyphen` is set: nothing is joined
//!   across a printed line end.
//! - DOCX has no pages: `page` and `bbox` are `null`.
//!
//! **PPTX**: slides in `presentation.xml` `p:sldIdLst` order (file-name order
//! only when that is missing), `page` = 1-based slide position, shapes in
//! `p:spTree` order (groups recursed). A `title`/`ctrTitle` placeholder is a
//! level-1 heading; `a:tbl` is a table (`gridSpan`/`rowSpan`/`hMerge`/`vMerge`);
//! paragraphs with an explicit `a:buAutoNum`/`a:buChar` are list items (an
//! `a:buAutoNum@type` renders its real label: arabic/alphaLc/alphaUc/romanLc/
//! romanUc × Period/ParenR/ParenBoth/Plain; any other scheme falls back to `N.`
//! with `failed_check = "list_label_unknown_format"`), other
//! paragraphs of a shape form one paragraph unit. `ftr`/`dt`/`hdr` placeholders
//! are furniture kept once per deck; `sldNum` is dropped (it is `page`).
//! `bbox` comes from `a:xfrm` (EMU / 12700 = points, top-left origin, group
//! transforms applied, rotation ignored); placeholders that inherit their
//! position from the layout have `bbox = null`.
//!
//! **Tables.** The grid is the table's own (`w:tblGrid` / `a:tblGrid`,
//! widened if a row is longer). A merged region's value appears ONCE, in its
//! anchor (top-left) cell; the cells it covers render empty and the table is
//! marked `table_uncertain`, so an empty cell may be a merge continuation.
//! Repeating the value instead would state it more times than the document
//! does. The first emitted row is the markdown header row (markdown needs
//! one); `w:tblHeader` rows after the first render as body rows. Rows whose
//! every cell is empty, and columns empty in every row, are not emitted — no
//! value is lost. `|` is escaped, cell paragraphs are joined with a space.
//!
//! **Determinism:** document order only, `BTreeMap`/`Vec` everywhere, no clock,
//! bboxes rounded to 0.01 — same bytes in, same JSON out.

use std::collections::{BTreeMap, BTreeSet};
use std::io::{Cursor, Read};

use quick_xml::encoding::Decoder;
use quick_xml::events::{BytesStart, Event};
use quick_xml::{Reader, XmlVersion};
use zip::ZipArchive;

use crate::types::{BBox, SourceType};
use crate::units::{DocUnit, HeadingSource, Provenance, Route, TableSource, UnitKind};

// ------------------------------------------------------------ mini DOM ----

#[derive(Debug, Default)]
struct El {
    name: String,
    attrs: Vec<(String, String)>,
    children: Vec<Node>,
}

#[derive(Debug)]
enum Node {
    El(El),
    Text(String),
}

fn local_of(qname: &[u8]) -> String {
    let s = String::from_utf8_lossy(qname);
    match s.rfind(':') {
        Some(i) => s[i + 1..].to_string(),
        None => s.to_string(),
    }
}

impl El {
    fn from_start(e: &BytesStart, decoder: Decoder) -> El {
        let attrs = e
            .attributes()
            .with_checks(false)
            .flatten()
            .map(|a| {
                let key = String::from_utf8_lossy(a.key.as_ref()).to_string();
                let value = a
                    .decoded_and_normalized_value(XmlVersion::Implicit1_0, decoder)
                    .map(|v| v.to_string())
                    .unwrap_or_else(|_| String::from_utf8_lossy(&a.value).to_string());
                (key, value)
            })
            .collect();
        El {
            name: local_of(e.name().as_ref()),
            attrs,
            children: Vec::new(),
        }
    }

    /// Attribute by LOCAL name (`w:val` → `val`).
    fn attr(&self, local: &str) -> Option<&str> {
        self.attrs
            .iter()
            .find(|(k, _)| k.rsplit(':').next() == Some(local))
            .map(|(_, v)| v.as_str())
    }

    /// Attribute by exact qualified name (`r:id`).
    fn attr_q(&self, qname: &str) -> Option<&str> {
        self.attrs
            .iter()
            .find(|(k, _)| k == qname)
            .map(|(_, v)| v.as_str())
    }

    fn val(&self) -> Option<&str> {
        self.attr("val")
    }

    fn kids(&self) -> impl Iterator<Item = &El> {
        self.children.iter().filter_map(|n| match n {
            Node::El(e) => Some(e),
            Node::Text(_) => None,
        })
    }

    fn kids_named<'a>(&'a self, name: &'a str) -> impl Iterator<Item = &'a El> {
        self.kids().filter(move |e| e.name == name)
    }

    fn child(&self, name: &str) -> Option<&El> {
        self.kids().find(|e| e.name == name)
    }

    fn path(&self, names: &[&str]) -> Option<&El> {
        let mut cur = self;
        for n in names {
            cur = cur.child(n)?;
        }
        Some(cur)
    }

    fn num_attr(&self, local: &str) -> Option<f64> {
        self.attr(local)?
            .trim()
            .parse::<i64>()
            .ok()
            .map(|v| v as f64)
    }
}

fn truthy(v: Option<&str>) -> bool {
    matches!(v, Some("1") | Some("true") | Some("on"))
}

fn resolve_entity(name: &str) -> Option<char> {
    match name {
        "amp" => Some('&'),
        "lt" => Some('<'),
        "gt" => Some('>'),
        "quot" => Some('"'),
        "apos" => Some('\''),
        _ => None,
    }
}

/// Parse one XML part into a tree. Only text inside `t` elements (`w:t`,
/// `a:t`) is kept — every other text node is inter-element whitespace or text
/// we deliberately drop (`w:delText`, `w:instrText`).
fn parse_xml(xml: &str) -> Result<El, String> {
    let mut reader = Reader::from_str(xml);
    reader.config_mut().trim_text(false);
    let mut stack: Vec<El> = vec![El {
        name: "#root".into(),
        ..El::default()
    }];

    fn push_text(stack: &mut [El], s: &str) {
        let top = stack.last_mut().expect("root");
        if top.name != "t" || s.is_empty() {
            return;
        }
        if let Some(Node::Text(prev)) = top.children.last_mut() {
            prev.push_str(s);
        } else {
            top.children.push(Node::Text(s.to_string()));
        }
    }

    loop {
        match reader.read_event() {
            Ok(Event::Start(e)) => stack.push(El::from_start(&e, reader.decoder())),
            Ok(Event::Empty(e)) => {
                let el = El::from_start(&e, reader.decoder());
                stack.last_mut().expect("root").children.push(Node::El(el));
            }
            Ok(Event::End(_)) => {
                if stack.len() > 1 {
                    let el = stack.pop().expect("len>1");
                    stack.last_mut().expect("root").children.push(Node::El(el));
                }
            }
            Ok(Event::Text(t)) => {
                if let Ok(s) = t.decode() {
                    push_text(&mut stack, &s);
                }
            }
            Ok(Event::CData(c)) => {
                if let Ok(s) = c.decode() {
                    push_text(&mut stack, &s);
                }
            }
            Ok(Event::GeneralRef(r)) => {
                let resolved = match r.resolve_char_ref() {
                    Ok(Some(ch)) => Some(ch),
                    _ => r.decode().ok().and_then(|n| resolve_entity(&n)),
                };
                if let Some(ch) = resolved {
                    push_text(&mut stack, ch.encode_utf8(&mut [0u8; 4]));
                }
            }
            Ok(Event::Eof) => break,
            Err(e) => return Err(format!("xml: {e}")),
            _ => {}
        }
    }
    while stack.len() > 1 {
        let el = stack.pop().expect("len>1");
        stack.last_mut().expect("root").children.push(Node::El(el));
    }
    Ok(stack.pop().expect("root"))
}

// --------------------------------------------------------------- zip ----

struct Package<'a> {
    archive: ZipArchive<Cursor<&'a [u8]>>,
}

impl<'a> Package<'a> {
    fn open(bytes: &'a [u8]) -> Result<Self, String> {
        ZipArchive::new(Cursor::new(bytes))
            .map(|archive| Package { archive })
            .map_err(|e| format!("not an OOXML zip: {e}"))
    }

    fn has(&self, name: &str) -> bool {
        self.archive.index_for_name(name).is_some()
    }

    fn names(&self) -> Vec<String> {
        self.archive.file_names().map(str::to_string).collect()
    }

    fn read(&mut self, name: &str) -> Option<String> {
        let mut file = self.archive.by_name(name).ok()?;
        let mut out = String::new();
        file.read_to_string(&mut out).ok()?;
        Some(out)
    }

    fn xml(&mut self, name: &str) -> Option<El> {
        self.read(name).and_then(|s| parse_xml(&s).ok())
    }
}

/// Resolve a relationship `Target` against the directory of its source part.
fn join_part(base_dir: &str, target: &str) -> String {
    if let Some(abs) = target.strip_prefix('/') {
        return abs.to_string();
    }
    let mut parts: Vec<&str> = base_dir.split('/').filter(|s| !s.is_empty()).collect();
    for seg in target.split('/') {
        match seg {
            "" | "." => {}
            ".." => {
                parts.pop();
            }
            s => parts.push(s),
        }
    }
    parts.join("/")
}

/// `(Id, Type, Target)` of every relationship in a `.rels` part, in file order.
fn relationships(rels: &El) -> Vec<(String, String, String)> {
    let mut out = Vec::new();
    for r in rels.kids().flat_map(|root| root.kids_named("Relationship")) {
        if let (Some(id), Some(ty), Some(target)) = (r.attr("Id"), r.attr("Type"), r.attr("Target"))
        {
            out.push((id.to_string(), ty.to_string(), target.to_string()));
        }
    }
    out
}

/// Trailing number of a part name (`header12.xml` → 12), for stable ordering.
fn part_number(name: &str) -> u64 {
    let stem = name.rsplit('/').next().unwrap_or(name);
    let stem = stem.split('.').next().unwrap_or(stem);
    let digits: String = stem
        .chars()
        .rev()
        .take_while(|c| c.is_ascii_digit())
        .collect::<Vec<_>>()
        .into_iter()
        .rev()
        .collect();
    digits.parse().unwrap_or(0)
}

// ------------------------------------------------------------- text ----

/// Collect the visible text of a paragraph-like element. Text boxes found
/// inside are returned separately so they become their own units.
fn collect_text<'a>(el: &'a El, out: &mut String, boxes: &mut Vec<&'a El>) {
    for node in &el.children {
        match node {
            Node::Text(s) => {
                if el.name == "t" {
                    out.push_str(s)
                }
            }
            Node::El(e) => match e.name.as_str() {
                "t" => collect_text(e, out, boxes),
                "tab" | "ptab" => out.push(' '),
                "br" | "cr" => out.push('\n'),
                "noBreakHyphen" => out.push('-'),
                "softHyphen" => {}
                "pPr" | "rPr" | "delText" | "instrText" | "del" | "moveFrom" | "endParaRPr"
                | "Fallback" => {}
                "txbxContent" => boxes.push(e),
                "AlternateContent" => {
                    if let Some(choice) = e.child("Choice").or_else(|| e.child("Fallback")) {
                        collect_text(choice, out, boxes);
                    }
                }
                _ => collect_text(e, out, boxes),
            },
        }
    }
}

/// Soft hyphens are invisible break opportunities: drop them. Then trim.
fn clean(text: &str) -> String {
    text.replace('\u{00AD}', "").trim().to_string()
}

/// One line: newlines (from `w:br`) folded to spaces.
fn one_line(text: &str) -> String {
    text.split(['\n', '\r'])
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .collect::<Vec<_>>()
        .join(" ")
}

// ------------------------------------------------------------- units ----

fn prov() -> Provenance {
    Provenance::new(Route::Ooxml)
}

fn unit(page: Option<u32>, bbox: Option<BBox>, kind: UnitKind, markdown: String) -> DocUnit {
    DocUnit {
        page,
        bbox,
        kind,
        level: None,
        markdown,
        provenance: prov(),
    }
}

fn heading_unit(page: Option<u32>, bbox: Option<BBox>, level: u32, text: &str) -> DocUnit {
    let level = level.clamp(1, 6);
    let mut p = prov();
    p.heading_source = Some(HeadingSource::Style);
    DocUnit {
        page,
        bbox,
        kind: UnitKind::Heading,
        level: Some(level),
        markdown: format!("{} {}", "#".repeat(level as usize), one_line(text)),
        provenance: p,
    }
}

/// How a list item is marked. A list label is a citation anchor ("artikel 3
/// lid b", "sub ii"), so it is always the document's OWN label:
/// - `Native("3.")` — a pure-decimal label (`N.` / `N)`) IS a markdown ordered
///   marker, so it is used as one;
/// - `Literal("b.")` — any other label ("b.", "(ii)", "2.b", "Artikel 3") is
///   written as literal text after a `- ` marker, markdown-escaped, so the
///   nesting survives and the label is never renumbered;
/// - `Bullet` — `-`.
#[derive(Clone, Debug, PartialEq)]
enum Marker {
    Bullet,
    Native(String),
    Literal(String),
}

impl Marker {
    fn from_label(label: String) -> Marker {
        let label = label.trim().to_string();
        if label.is_empty() {
            return Marker::Bullet;
        }
        let digits = label.trim_end_matches(['.', ')']);
        let punct = label.len() - digits.len();
        if punct == 1
            && !digits.is_empty()
            && digits.len() <= 9
            && digits.bytes().all(|b| b.is_ascii_digit())
        {
            Marker::Native(label)
        } else {
            Marker::Literal(label)
        }
    }

    /// The label as the document prints it (headings carry it verbatim).
    fn label(&self) -> Option<&str> {
        match self {
            Marker::Bullet => None,
            Marker::Native(l) | Marker::Literal(l) => Some(l),
        }
    }
}

/// Backslash-escape the markdown-significant characters of a literal label.
fn escape_label(label: &str) -> String {
    let mut out = String::with_capacity(label.len());
    for ch in label.chars() {
        if matches!(
            ch,
            '\\' | '*' | '_' | '[' | ']' | '<' | '>' | '#' | '|' | '`'
        ) {
            out.push('\\');
        }
        out.push(ch);
    }
    out
}

/// Builds one markdown list from consecutive items, nesting each item under
/// its parent's content column (valid CommonMark nesting).
#[derive(Default)]
struct ListBuilder {
    lines: Vec<String>,
    /// Open items: (source level, content column).
    cols: Vec<(usize, usize)>,
    bbox: Option<BBox>,
    /// Some label used a number format we cannot render; it fell back to the
    /// decimal value and the unit says so (`failed_check`).
    unknown_format: bool,
}

impl ListBuilder {
    fn push(&mut self, level: usize, marker: &Marker, text: &str) {
        // parent = nearest open item at a shallower level; a list may start at
        // any level (e.g. ilvl 1 under a numbered heading) and skip levels
        while self.cols.last().is_some_and(|(l, _)| *l >= level) {
            self.cols.pop();
        }
        let indent = self.cols.last().map_or(0, |(_, col)| *col);
        let (md_marker, literal) = match marker {
            Marker::Bullet => ("-".to_string(), String::new()),
            Marker::Native(l) => (l.clone(), String::new()),
            Marker::Literal(l) => ("-".to_string(), format!("{} ", escape_label(l))),
        };
        self.lines.push(format!(
            "{}{} {}{}",
            " ".repeat(indent),
            md_marker,
            literal,
            one_line(text)
        ));
        self.cols
            .push((level, indent + md_marker.chars().count() + 1));
    }

    fn flush(&mut self, page: Option<u32>, units: &mut Vec<DocUnit>) {
        if !self.lines.is_empty() {
            let md = self.lines.join("\n");
            let mut u = unit(page, self.bbox, UnitKind::List, md);
            if self.unknown_format {
                u.provenance.failed_check = Some(UNKNOWN_FORMAT.to_string());
            }
            units.push(u);
        }
        *self = ListBuilder::default();
    }
}

const UNKNOWN_FORMAT: &str = "list_label_unknown_format";

/// Word's repeated-letter style: 1→a … 26→z, 27→aa, 28→bb.
fn letters(n: i64, upper: bool) -> Option<String> {
    if n < 1 {
        return None;
    }
    let idx = ((n - 1) % 26) as u8;
    let times = ((n - 1) / 26 + 1) as usize;
    let ch = (if upper { b'A' } else { b'a' } + idx) as char;
    Some(ch.to_string().repeat(times))
}

fn roman(n: i64, upper: bool) -> Option<String> {
    if !(1..=3999).contains(&n) {
        return None;
    }
    const TABLE: [(i64, &str); 13] = [
        (1000, "m"),
        (900, "cm"),
        (500, "d"),
        (400, "cd"),
        (100, "c"),
        (90, "xc"),
        (50, "l"),
        (40, "xl"),
        (10, "x"),
        (9, "ix"),
        (5, "v"),
        (4, "iv"),
        (1, "i"),
    ];
    let mut n = n;
    let mut out = String::new();
    for (v, s) in TABLE {
        while n >= v {
            out.push_str(s);
            n -= v;
        }
    }
    Some(if upper { out.to_uppercase() } else { out })
}

/// A counter value in a number format → `(text, known)`. An unknown format
/// (or a value the format cannot express) falls back to the decimal value
/// with `known = false` — never silently.
fn format_number(n: i64, fmt: &str) -> (String, bool) {
    let rendered = match fmt {
        "decimal" | "bullet" => Some(n.to_string()),
        "decimalZero" => Some(if (0..10).contains(&n) {
            format!("0{n}")
        } else {
            n.to_string()
        }),
        "lowerLetter" => letters(n, false),
        "upperLetter" => letters(n, true),
        "lowerRoman" => roman(n, false),
        "upperRoman" => roman(n, true),
        "none" => Some(String::new()),
        _ => None,
    };
    match rendered {
        Some(r) => (r, true),
        None => (n.to_string(), false),
    }
}

/// PPTX `a:buAutoNum@type` → label text. Covers the five scripts DrawingML
/// shares with Word (arabic, alphaLc/Uc, romanLc/Uc) in their four
/// punctuations (Period, ParenR, ParenBoth, Plain); anything else falls back
/// to `N.` with `known = false`.
fn pptx_label(scheme: &str, n: i64) -> (String, bool) {
    const BASES: [(&str, &str); 5] = [
        ("alphaLc", "lowerLetter"),
        ("alphaUc", "upperLetter"),
        ("arabic", "decimal"),
        ("romanLc", "lowerRoman"),
        ("romanUc", "upperRoman"),
    ];
    for (base, fmt) in BASES {
        let Some(punct) = scheme.strip_prefix(base) else {
            continue;
        };
        let (value, ok) = format_number(n, fmt);
        let label = match punct {
            "Period" => format!("{value}."),
            "ParenR" => format!("{value})"),
            "ParenBoth" => format!("({value})"),
            "Plain" => value,
            _ => continue,
        };
        return (label, ok);
    }
    (format!("{n}."), false)
}

// ------------------------------------------------------------ tables ----

/// One grid cell. A cell covered by a merge anchored elsewhere carries no
/// text of its own (the anchor holds the value).
struct Cell {
    text: String,
}

struct Grid {
    rows: Vec<Vec<Cell>>,
    cols: usize,
    merged: bool,
}

fn escape_cell(text: &str) -> String {
    one_line(text).replace('|', "\\|")
}

enum Rendered {
    Empty,
    Single(String),
    Table(String),
}

impl Grid {
    fn render(mut self) -> Rendered {
        let width = self
            .rows
            .iter()
            .map(Vec::len)
            .max()
            .unwrap_or(0)
            .max(self.cols);
        for row in &mut self.rows {
            while row.len() < width {
                row.push(Cell {
                    text: String::new(),
                });
            }
        }
        let text_of: Vec<Vec<String>> = self
            .rows
            .iter()
            .map(|r| r.iter().map(|c| escape_cell(&c.text)).collect())
            .collect();
        let rows: Vec<&Vec<String>> = text_of
            .iter()
            .filter(|r| r.iter().any(|c| !c.is_empty()))
            .collect();
        let keep_cols: Vec<usize> = (0..width)
            .filter(|&c| rows.iter().any(|r| !r[c].is_empty()))
            .collect();
        if rows.is_empty() || keep_cols.is_empty() {
            return Rendered::Empty;
        }
        if rows.len() == 1 && keep_cols.len() == 1 && self.rows.len() == 1 && width == 1 {
            return Rendered::Single(rows[0][keep_cols[0]].replace("\\|", "|"));
        }
        let line = |r: &Vec<String>| {
            let cells: Vec<&str> = keep_cols.iter().map(|&c| r[c].as_str()).collect();
            format!("| {} |", cells.join(" | "))
        };
        let mut out = vec![line(rows[0])];
        out.push(format!(
            "|{}",
            keep_cols.iter().map(|_| " --- |").collect::<String>()
        ));
        for r in &rows[1..] {
            out.push(line(r));
        }
        Rendered::Table(out.join("\n"))
    }
}

fn table_units(
    grid: Grid,
    nested: bool,
    has_nested: bool,
    page: Option<u32>,
    bbox: Option<BBox>,
    units: &mut Vec<DocUnit>,
) {
    let merged = grid.merged;
    match grid.render() {
        Rendered::Empty => {}
        Rendered::Single(text) => {
            if !text.is_empty() {
                units.push(unit(page, bbox, UnitKind::Paragraph, text));
            }
        }
        Rendered::Table(md) => {
            let mut u = unit(page, bbox, UnitKind::Table, md);
            u.provenance.table_source = Some(TableSource::Ooxml);
            u.provenance.table_uncertain = merged || nested || has_nested;
            if nested {
                u.provenance.failed_check = Some("nested_table".to_string());
            }
            units.push(u);
        }
    }
}

// -------------------------------------------------------------- docx ----

#[derive(Default)]
struct StyleDef {
    name: String,
    based_on: Option<String>,
    outline: Option<u32>,
    num_id: Option<String>,
    ilvl: Option<u32>,
}

#[derive(Default)]
struct Styles {
    by_id: BTreeMap<String, StyleDef>,
    default_para: Option<String>,
}

impl Styles {
    fn parse(root: Option<El>) -> Styles {
        let mut s = Styles::default();
        let Some(root) = root else { return s };
        for style in root.kids().flat_map(|r| r.kids_named("style")) {
            if style.attr("type").is_some_and(|t| t != "paragraph") {
                continue;
            }
            let Some(id) = style.attr("styleId") else {
                continue;
            };
            if style.attr("default").is_some_and(|d| truthy(Some(d))) {
                s.default_para = Some(id.to_string());
            }
            let ppr = style.child("pPr");
            let num_pr = ppr.and_then(|p| p.child("numPr"));
            s.by_id.insert(
                id.to_string(),
                StyleDef {
                    name: style
                        .child("name")
                        .and_then(El::val)
                        .unwrap_or_default()
                        .to_string(),
                    based_on: style.child("basedOn").and_then(El::val).map(str::to_string),
                    outline: ppr
                        .and_then(|p| p.child("outlineLvl"))
                        .and_then(El::val)
                        .and_then(|v| v.parse().ok()),
                    num_id: num_pr
                        .and_then(|n| n.child("numId"))
                        .and_then(El::val)
                        .map(str::to_string),
                    ilvl: num_pr
                        .and_then(|n| n.child("ilvl"))
                        .and_then(El::val)
                        .and_then(|v| v.parse().ok()),
                },
            );
        }
        s
    }

    fn chain(&self, id: Option<&str>) -> Vec<&StyleDef> {
        let mut out = Vec::new();
        let mut seen = BTreeSet::new();
        let mut cur = id.map(str::to_string).or_else(|| self.default_para.clone());
        while let Some(c) = cur {
            if !seen.insert(c.clone()) || out.len() > 32 {
                break;
            }
            match self.by_id.get(&c) {
                Some(def) => {
                    cur = def.based_on.clone();
                    out.push(def);
                }
                None => break,
            }
        }
        out
    }

    fn heading_level(&self, style: Option<&str>, direct_outline: Option<u32>) -> Option<u32> {
        let from_outline = |o: u32| if o < 9 { Some(o + 1) } else { None };
        if let Some(o) = direct_outline {
            return from_outline(o);
        }
        for def in self.chain(style) {
            if let Some(o) = def.outline {
                return from_outline(o);
            }
            if let Some(l) = name_level(&def.name) {
                return Some(l);
            }
        }
        match style {
            Some(id) if !self.by_id.contains_key(id) => name_level(id),
            _ => None,
        }
    }

    fn numbering(&self, style: Option<&str>) -> (Option<String>, Option<u32>) {
        let mut num = None;
        let mut ilvl = None;
        for def in self.chain(style) {
            if num.is_none() {
                num = def.num_id.clone();
            }
            if ilvl.is_none() {
                ilvl = def.ilvl;
            }
        }
        (num, ilvl)
    }
}

/// Built-in heading names (`heading 1`, `Heading1`, `Title`) → level.
fn name_level(name: &str) -> Option<u32> {
    let lower = name.trim().to_ascii_lowercase();
    if lower == "title" {
        return Some(1);
    }
    let tail = lower.strip_prefix("heading")?.trim();
    match tail.parse::<u32>() {
        Ok(n) if (1..=9).contains(&n) => Some(n),
        _ => None,
    }
}

#[derive(Clone)]
struct LvlDef {
    /// `w:numFmt` (default `decimal`).
    fmt: String,
    /// `w:lvlText` (`%1.`, `(%1)`, `%1.%2`); `None` when absent.
    text: Option<String>,
    start: i64,
    /// `w:lvlRestart`: restart after a use of this 1-based level or any
    /// shallower one; `0` = never. `None` = after any shallower level.
    restart: Option<u32>,
    /// `w:isLgl`: other levels' numbers render as decimals in this label.
    is_lgl: bool,
}

fn lvl_def(lvl: &El) -> LvlDef {
    let num = |name: &str| {
        lvl.child(name)
            .and_then(El::val)
            .and_then(|v| v.trim().parse::<i64>().ok())
    };
    LvlDef {
        fmt: lvl
            .child("numFmt")
            .and_then(El::val)
            .unwrap_or("decimal")
            .to_string(),
        text: lvl.child("lvlText").and_then(El::val).map(str::to_string),
        start: num("start").unwrap_or(1),
        restart: num("lvlRestart").and_then(|v| u32::try_from(v).ok()),
        is_lgl: lvl
            .child("isLgl")
            .is_some_and(|e| !matches!(e.val(), Some("0") | Some("false"))),
    }
}

#[derive(Default)]
struct Numbering {
    /// numId → (abstractNumId, ilvl → (startOverride, lvl override))
    nums: BTreeMap<String, (String, BTreeMap<u32, (Option<i64>, Option<LvlDef>)>)>,
    /// abstractNumId → (ilvl → def, numStyleLink)
    abstracts: BTreeMap<String, (BTreeMap<u32, LvlDef>, Option<String>)>,
}

impl Numbering {
    fn parse(root: Option<El>) -> Numbering {
        let mut n = Numbering::default();
        let Some(root) = root else { return n };
        for top in root.kids() {
            for abs in top.kids_named("abstractNum") {
                let Some(id) = abs.attr("abstractNumId") else {
                    continue;
                };
                let mut levels = BTreeMap::new();
                for lvl in abs.kids_named("lvl") {
                    if let Some(i) = lvl.attr("ilvl").and_then(|v| v.parse().ok()) {
                        levels.insert(i, lvl_def(lvl));
                    }
                }
                let link = abs
                    .child("numStyleLink")
                    .and_then(El::val)
                    .map(str::to_string);
                n.abstracts.insert(id.to_string(), (levels, link));
            }
            for num in top.kids_named("num") {
                let (Some(id), Some(abs)) = (
                    num.attr("numId"),
                    num.child("abstractNumId").and_then(El::val),
                ) else {
                    continue;
                };
                let mut overrides = BTreeMap::new();
                for o in num.kids_named("lvlOverride") {
                    if let Some(i) = o.attr("ilvl").and_then(|v| v.parse().ok()) {
                        let start = o
                            .child("startOverride")
                            .and_then(El::val)
                            .and_then(|v| v.parse().ok());
                        overrides.insert(i, (start, o.child("lvl").map(lvl_def)));
                    }
                }
                n.nums.insert(id.to_string(), (abs.to_string(), overrides));
            }
        }
        n
    }

    /// The abstract list a num instance counts in, following one
    /// `numStyleLink` hop (style → its numId → that abstract).
    fn abstract_of(&self, num_id: &str, styles: &Styles) -> Option<String> {
        let (abs_id, _) = self.nums.get(num_id)?;
        let (levels, link) = self.abstracts.get(abs_id)?;
        if levels.is_empty() {
            if let Some(style_num) = link
                .as_ref()
                .and_then(|l| styles.by_id.get(l))
                .and_then(|s| s.num_id.as_ref())
            {
                if let Some((abs2, _)) = self.nums.get(style_num) {
                    return Some(abs2.clone());
                }
            }
        }
        Some(abs_id.clone())
    }

    fn level(&self, num_id: &str, ilvl: u32, styles: &Styles) -> Option<LvlDef> {
        let (_, overrides) = self.nums.get(num_id)?;
        if let Some((_, Some(d))) = overrides.get(&ilvl) {
            return Some(d.clone());
        }
        let abs = self.abstract_of(num_id, styles)?;
        self.abstracts.get(&abs)?.0.get(&ilvl).cloned()
    }

    fn start_overrides(&self, num_id: &str) -> Vec<(u32, i64)> {
        self.nums
            .get(num_id)
            .map(|(_, o)| {
                o.iter()
                    .filter_map(|(l, (s, _))| s.map(|s| (*l, s)))
                    .collect()
            })
            .unwrap_or_default()
    }
}

struct Docx {
    styles: Styles,
    numbering: Numbering,
    /// Current value per level, per ABSTRACT list: num instances that share an
    /// abstractNum continue one sequence (Word); a `startOverride` restarts it
    /// the first time its num is used.
    counters: BTreeMap<String, [Option<i64>; 10]>,
    started_nums: BTreeSet<String>,
}

impl Docx {
    fn blocks(&mut self, container: &El, list: &mut ListBuilder, units: &mut Vec<DocUnit>) {
        for child in container.kids() {
            match child.name.as_str() {
                "p" => self.paragraph(child, list, units),
                "tbl" => {
                    list.flush(None, units);
                    self.table(child, false, units);
                }
                "sdt" => {
                    if let Some(c) = child.child("sdtContent") {
                        self.blocks(c, list, units);
                    }
                }
                "customXml" | "ins" | "moveTo" | "smartTag" => self.blocks(child, list, units),
                "AlternateContent" => {
                    if let Some(c) = child.child("Choice").or_else(|| child.child("Fallback")) {
                        self.blocks(c, list, units);
                    }
                }
                _ => {}
            }
        }
    }

    fn paragraph(&mut self, p: &El, list: &mut ListBuilder, units: &mut Vec<DocUnit>) {
        let ppr = p.child("pPr");
        let style = ppr.and_then(|x| x.child("pStyle")).and_then(El::val);
        let outline = ppr
            .and_then(|x| x.child("outlineLvl"))
            .and_then(El::val)
            .and_then(|v| v.parse().ok());
        let mut raw = String::new();
        let mut boxes = Vec::new();
        collect_text(p, &mut raw, &mut boxes);
        let text = clean(&raw);

        if !text.is_empty() {
            let numbered = self.list_item(ppr, style);
            if let Some(level) = self.styles.heading_level(style, outline) {
                list.flush(None, units);
                // a numbered heading ("Artikel 3") keeps its label; its number
                // also advanced the counters, so sub-levels restart under it
                let text = match numbered.as_ref().and_then(|(_, m, _)| m.label()) {
                    Some(label) => format!("{label} {text}"),
                    None => text,
                };
                let mut u = heading_unit(None, None, level, &text);
                if numbered.as_ref().is_some_and(|(_, _, unknown)| *unknown) {
                    u.provenance.failed_check = Some(UNKNOWN_FORMAT.to_string());
                }
                units.push(u);
            } else if let Some((depth, marker, unknown)) = numbered {
                list.push(depth, &marker, &text);
                list.unknown_format |= unknown;
            } else {
                list.flush(None, units);
                units.push(unit(None, None, UnitKind::Paragraph, text));
            }
        }
        for b in boxes {
            list.flush(None, units);
            self.blocks(b, list, units);
        }
    }

    /// `(ilvl, marker, unknown_format)` when the paragraph is numbered.
    /// Advances the counters (headings included).
    fn list_item(
        &mut self,
        ppr: Option<&El>,
        style: Option<&str>,
    ) -> Option<(usize, Marker, bool)> {
        let num_pr = ppr.and_then(|x| x.child("numPr"));
        let direct_num = num_pr
            .and_then(|n| n.child("numId"))
            .and_then(El::val)
            .map(str::to_string);
        let direct_ilvl: Option<u32> = num_pr
            .and_then(|n| n.child("ilvl"))
            .and_then(El::val)
            .and_then(|v| v.parse().ok());
        let (style_num, style_ilvl) = self.styles.numbering(style);
        let num_id = direct_num.or(style_num)?;
        if num_id == "0" {
            return None;
        }
        let ilvl = direct_ilvl.or(style_ilvl).unwrap_or(0).min(9);
        let def = self.numbering.level(&num_id, ilvl, &self.styles)?;
        if def.fmt == "none" {
            return None;
        }
        let abs = self.numbering.abstract_of(&num_id, &self.styles)?;
        let levels: Vec<Option<LvlDef>> = (0..10u32)
            .map(|l| self.numbering.level(&num_id, l, &self.styles))
            .collect();
        let counters = self.counters.entry(abs).or_insert([None; 10]);
        if self.started_nums.insert(num_id.clone()) {
            for (l, start) in self.numbering.start_overrides(&num_id) {
                if let Some(c) = counters.get_mut(l as usize) {
                    *c = Some(start - 1);
                }
            }
        }
        let i = ilvl as usize;
        counters[i] = Some(counters[i].map(|c| c + 1).unwrap_or(def.start));
        for (d, c) in counters.iter_mut().enumerate().skip(i + 1) {
            let restart = levels[d].as_ref().and_then(|x| x.restart);
            let reset = match restart {
                None => true,
                Some(0) => false,
                Some(r) => (ilvl) < r,
            };
            if reset {
                *c = None;
            }
        }
        if def.fmt == "bullet" {
            return Some((i, Marker::Bullet, false));
        }

        let template = def.text.clone().unwrap_or_else(|| format!("%{}.", i + 1));
        let mut label = String::new();
        let mut unknown = false;
        let mut chars = template.chars().peekable();
        while let Some(ch) = chars.next() {
            let level_ref = if ch == '%' {
                chars
                    .peek()
                    .and_then(|d| d.to_digit(10))
                    .filter(|d| (1..=9).contains(d))
            } else {
                None
            };
            let Some(k) = level_ref else {
                label.push(ch);
                continue;
            };
            chars.next();
            let l = (k - 1) as usize;
            let ldef = levels[l].as_ref();
            let value = counters[l].unwrap_or_else(|| ldef.map(|x| x.start).unwrap_or(1));
            let fmt = if def.is_lgl && l != i {
                "decimal"
            } else {
                ldef.map(|x| x.fmt.as_str()).unwrap_or("decimal")
            };
            let (text, known) = format_number(value, fmt);
            unknown |= !known;
            label.push_str(&text);
        }
        Some((i, Marker::from_label(label), unknown))
    }

    /// All paragraph text of a cell (joined by spaces); nested tables are
    /// returned for separate emission.
    fn cell_text<'a>(cell: &'a El, parts: &mut Vec<String>, nested: &mut Vec<&'a El>) {
        for child in cell.kids() {
            match child.name.as_str() {
                "p" => {
                    let mut raw = String::new();
                    let mut boxes = Vec::new();
                    collect_text(child, &mut raw, &mut boxes);
                    let t = clean(&raw);
                    if !t.is_empty() {
                        parts.push(t);
                    }
                    for b in boxes {
                        Self::cell_text(b, parts, nested);
                    }
                }
                "tbl" => nested.push(child),
                "sdt" => {
                    if let Some(c) = child.child("sdtContent") {
                        Self::cell_text(c, parts, nested);
                    }
                }
                "customXml" | "ins" | "moveTo" => Self::cell_text(child, parts, nested),
                "AlternateContent" => {
                    if let Some(c) = child.child("Choice").or_else(|| child.child("Fallback")) {
                        Self::cell_text(c, parts, nested);
                    }
                }
                _ => {}
            }
        }
    }

    fn table(&mut self, tbl: &El, nested_flag: bool, units: &mut Vec<DocUnit>) {
        fn rows_of<'a>(el: &'a El, out: &mut Vec<&'a El>) {
            for c in el.kids() {
                match c.name.as_str() {
                    "tr" => out.push(c),
                    "sdt" => {
                        if let Some(sc) = c.child("sdtContent") {
                            rows_of(sc, out)
                        }
                    }
                    "customXml" => rows_of(c, out),
                    _ => {}
                }
            }
        }
        fn cells_of<'a>(el: &'a El, out: &mut Vec<&'a El>) {
            for c in el.kids() {
                match c.name.as_str() {
                    "tc" => out.push(c),
                    "sdt" => {
                        if let Some(sc) = c.child("sdtContent") {
                            cells_of(sc, out)
                        }
                    }
                    "customXml" => cells_of(c, out),
                    _ => {}
                }
            }
        }
        let grid_cols = tbl
            .child("tblGrid")
            .map(|g| g.kids_named("gridCol").count())
            .unwrap_or(0);
        let mut grid = Grid {
            rows: Vec::new(),
            cols: grid_cols,
            merged: false,
        };
        let mut nested: Vec<&El> = Vec::new();
        let mut trs = Vec::new();
        rows_of(tbl, &mut trs);
        for tr in trs {
            let trpr = tr.child("trPr");
            let skip = |name: &str| -> usize {
                trpr.and_then(|t| t.child(name))
                    .and_then(El::val)
                    .and_then(|v| v.parse().ok())
                    .unwrap_or(0)
            };
            let mut row: Vec<Cell> = Vec::new();
            for _ in 0..skip("gridBefore") {
                row.push(Cell {
                    text: String::new(),
                });
            }
            let mut tcs = Vec::new();
            cells_of(tr, &mut tcs);
            for tc in tcs {
                let tcpr = tc.child("tcPr");
                let span: usize = tcpr
                    .and_then(|t| t.child("gridSpan"))
                    .and_then(El::val)
                    .and_then(|v| v.parse().ok())
                    .unwrap_or(1)
                    .max(1);
                let v_continue = tcpr
                    .and_then(|t| t.child("vMerge"))
                    .is_some_and(|v| v.val() != Some("restart"));
                // legacy horizontal merge (w:hMerge) — continuation cells
                let h_continue = tcpr
                    .and_then(|t| t.child("hMerge"))
                    .is_some_and(|v| v.val() != Some("restart"));
                let mut parts = Vec::new();
                Self::cell_text(tc, &mut parts, &mut nested);
                if span > 1 || v_continue || h_continue {
                    grid.merged = true;
                }
                row.push(Cell {
                    text: parts.join(" "),
                });
                for _ in 1..span {
                    row.push(Cell {
                        text: String::new(),
                    });
                }
            }
            for _ in 0..skip("gridAfter") {
                row.push(Cell {
                    text: String::new(),
                });
            }
            grid.rows.push(row);
        }
        table_units(grid, nested_flag, !nested.is_empty(), None, None, units);
        for n in nested {
            self.table(n, true, units);
        }
    }
}

/// Every distinct non-empty line of a header/footer part.
fn furniture_lines(el: &El, out: &mut Vec<String>) {
    for child in el.kids() {
        if child.name == "p" {
            let mut raw = String::new();
            let mut boxes = Vec::new();
            collect_text(child, &mut raw, &mut boxes);
            let t = one_line(&clean(&raw));
            if !t.is_empty() {
                out.push(t);
            }
            for b in boxes {
                furniture_lines(b, out);
            }
        } else {
            furniture_lines(child, out);
        }
    }
}

fn docx_units(pkg: &mut Package) -> Result<Vec<DocUnit>, String> {
    let document = pkg
        .read("word/document.xml")
        .ok_or("missing word/document.xml")?;
    let document = parse_xml(&document)?;
    let mut docx = Docx {
        styles: Styles::parse(pkg.xml("word/styles.xml")),
        numbering: Numbering::parse(pkg.xml("word/numbering.xml")),
        counters: BTreeMap::new(),
        started_nums: BTreeSet::new(),
    };

    // header/footer parts referenced by the main document, in part-number order
    let mut headers: Vec<String> = Vec::new();
    let mut footers: Vec<String> = Vec::new();
    if let Some(rels) = pkg.xml("word/_rels/document.xml.rels") {
        for (_, ty, target) in relationships(&rels) {
            let part = join_part("word", &target);
            if ty.ends_with("/header") {
                headers.push(part);
            } else if ty.ends_with("/footer") {
                footers.push(part);
            }
        }
    }
    for list in [&mut headers, &mut footers] {
        list.sort_by(|a, b| (part_number(a), a.as_str()).cmp(&(part_number(b), b.as_str())));
        list.dedup();
    }
    let mut seen = BTreeSet::new();
    let mut furniture = |parts: &[String], pkg: &mut Package| -> Vec<DocUnit> {
        let mut out = Vec::new();
        for part in parts {
            let Some(root) = pkg.xml(part) else { continue };
            let mut lines = Vec::new();
            furniture_lines(&root, &mut lines);
            for l in lines {
                if seen.insert(l.clone()) {
                    out.push(unit(None, None, UnitKind::Furniture, l));
                }
            }
        }
        out
    };

    let mut units = furniture(&headers, pkg);
    let mut list = ListBuilder::default();
    if let Some(body) = document.path(&["document", "body"]) {
        docx.blocks(body, &mut list, &mut units);
    }
    list.flush(None, &mut units);
    units.extend(furniture(&footers, pkg));
    Ok(units)
}

// -------------------------------------------------------------- pptx ----

/// Affine child→slide mapping per axis: `X = a * x + b` (EMU).
#[derive(Clone, Copy)]
struct Xf {
    ax: f64,
    bx: f64,
    ay: f64,
    by: f64,
}

const EMU_PER_POINT: f64 = 12700.0;

fn round2(v: f64) -> f64 {
    let r = (v * 100.0).round() / 100.0;
    if r == 0.0 {
        0.0
    } else {
        r
    }
}

impl Xf {
    const IDENTITY: Xf = Xf {
        ax: 1.0,
        bx: 0.0,
        ay: 1.0,
        by: 0.0,
    };

    fn off_ext(xfrm: &El) -> Option<(f64, f64, f64, f64)> {
        let off = xfrm.child("off")?;
        let ext = xfrm.child("ext")?;
        Some((
            off.num_attr("x")?,
            off.num_attr("y")?,
            ext.num_attr("cx")?,
            ext.num_attr("cy")?,
        ))
    }

    fn group(&self, xfrm: Option<&El>) -> Xf {
        let Some(x) = xfrm else { return *self };
        let Some((ox, oy, cx, cy)) = Self::off_ext(x) else {
            return *self;
        };
        let ch_off = x.child("chOff");
        let ch_ext = x.child("chExt");
        let (chx, chy) = (
            ch_off.and_then(|c| c.num_attr("x")).unwrap_or(ox),
            ch_off.and_then(|c| c.num_attr("y")).unwrap_or(oy),
        );
        let (chcx, chcy) = (
            ch_ext.and_then(|c| c.num_attr("cx")).unwrap_or(cx),
            ch_ext.and_then(|c| c.num_attr("cy")).unwrap_or(cy),
        );
        let kx = if chcx > 0.0 { cx / chcx } else { 1.0 };
        let ky = if chcy > 0.0 { cy / chcy } else { 1.0 };
        Xf {
            ax: self.ax * kx,
            bx: self.ax * (ox - chx * kx) + self.bx,
            ay: self.ay * ky,
            by: self.ay * (oy - chy * ky) + self.by,
        }
    }

    fn bbox(&self, xfrm: Option<&El>) -> Option<BBox> {
        let (x, y, cx, cy) = Self::off_ext(xfrm?)?;
        let p = |v: f64| round2(v / EMU_PER_POINT);
        Some([
            p(self.ax * x + self.bx),
            p(self.ay * y + self.by),
            p(self.ax * (x + cx) + self.bx),
            p(self.ay * (y + cy) + self.by),
        ])
    }
}

fn a_paragraph_text(p: &El) -> String {
    let mut raw = String::new();
    let mut boxes = Vec::new();
    collect_text(p, &mut raw, &mut boxes);
    clean(&raw)
}

struct Pptx {
    seen_furniture: BTreeSet<String>,
}

impl Pptx {
    fn tree(&mut self, tree: &El, xf: Xf, page: u32, units: &mut Vec<DocUnit>) {
        for c in tree.kids() {
            match c.name.as_str() {
                "sp" => self.shape(c, xf, page, units),
                "grpSp" => {
                    let g = c.child("grpSpPr").and_then(|p| p.child("xfrm"));
                    self.tree(c, xf.group(g), page, units);
                }
                "graphicFrame" => {
                    if let Some(tbl) = c.path(&["graphic", "graphicData", "tbl"]) {
                        let bbox = xf.bbox(c.child("xfrm"));
                        table_units(pptx_grid(tbl), false, false, Some(page), bbox, units);
                    }
                }
                "AlternateContent" => {
                    if let Some(ch) = c.child("Choice").or_else(|| c.child("Fallback")) {
                        self.tree(ch, xf, page, units);
                    }
                }
                _ => {}
            }
        }
    }

    fn shape(&mut self, sp: &El, xf: Xf, page: u32, units: &mut Vec<DocUnit>) {
        let Some(body) = sp.child("txBody") else {
            return;
        };
        let ph = sp.path(&["nvSpPr", "nvPr", "ph"]);
        let ph_type = ph.map(|p| p.attr("type").unwrap_or("body"));
        let bbox = xf.bbox(sp.child("spPr").and_then(|s| s.child("xfrm")));
        let paras: Vec<&El> = body.kids_named("p").collect();

        match ph_type {
            Some("title") | Some("ctrTitle") => {
                let text: Vec<String> = paras
                    .iter()
                    .map(|p| a_paragraph_text(p))
                    .filter(|t| !t.is_empty())
                    .collect();
                if !text.is_empty() {
                    units.push(heading_unit(Some(page), bbox, 1, &text.join(" ")));
                }
                return;
            }
            Some("sldNum") => return,
            Some("ftr") | Some("dt") | Some("hdr") => {
                for p in &paras {
                    let t = one_line(&a_paragraph_text(p));
                    if !t.is_empty() && self.seen_furniture.insert(t.clone()) {
                        units.push(unit(Some(page), bbox, UnitKind::Furniture, t));
                    }
                }
                return;
            }
            _ => {}
        }

        let mut list = ListBuilder {
            bbox,
            ..ListBuilder::default()
        };
        let mut plain: Vec<String> = Vec::new();
        let mut counters: [Option<i64>; 10] = [None; 10];
        let flush_plain = |plain: &mut Vec<String>, units: &mut Vec<DocUnit>| {
            if !plain.is_empty() {
                units.push(unit(
                    Some(page),
                    bbox,
                    UnitKind::Paragraph,
                    plain.join("\n"),
                ));
                plain.clear();
            }
        };
        for p in paras {
            let text = a_paragraph_text(p);
            if text.is_empty() {
                continue;
            }
            let ppr = p.child("pPr");
            let lvl: usize = ppr
                .and_then(|x| x.attr("lvl"))
                .and_then(|v| v.parse().ok())
                .unwrap_or(0usize)
                .min(9);
            let auto = ppr.and_then(|x| x.child("buAutoNum"));
            let bullet = ppr.and_then(|x| x.child("buChar")).is_some();
            if let Some(a) = auto {
                flush_plain(&mut plain, units);
                let start: i64 = a.attr("startAt").and_then(|v| v.parse().ok()).unwrap_or(1);
                let n = counters[lvl].map(|c| c + 1).unwrap_or(start);
                counters[lvl] = Some(n);
                for c in counters.iter_mut().skip(lvl + 1) {
                    *c = None;
                }
                let (label, known) = pptx_label(a.attr("type").unwrap_or("arabicPeriod"), n);
                list.unknown_format |= !known;
                list.push(lvl, &Marker::from_label(label), &text);
            } else if bullet {
                flush_plain(&mut plain, units);
                for c in counters.iter_mut().skip(lvl + 1) {
                    *c = None;
                }
                list.push(lvl, &Marker::Bullet, &text);
            } else {
                list.flush(Some(page), units);
                list.bbox = bbox;
                counters = [None; 10];
                plain.push(text);
            }
        }
        list.flush(Some(page), units);
        flush_plain(&mut plain, units);
    }
}

fn pptx_grid(tbl: &El) -> Grid {
    let cols = tbl
        .child("tblGrid")
        .map(|g| g.kids_named("gridCol").count())
        .unwrap_or(0);
    let mut grid = Grid {
        rows: Vec::new(),
        cols,
        merged: false,
    };
    for tr in tbl.kids_named("tr") {
        let mut row = Vec::new();
        for tc in tr.kids_named("tc") {
            let continuation = truthy(tc.attr("hMerge")) || truthy(tc.attr("vMerge"));
            let spans = tc
                .attr("gridSpan")
                .and_then(|v| v.parse::<u32>().ok())
                .unwrap_or(1)
                > 1
                || tc
                    .attr("rowSpan")
                    .and_then(|v| v.parse::<u32>().ok())
                    .unwrap_or(1)
                    > 1;
            if continuation || spans {
                grid.merged = true;
            }
            let text: Vec<String> = tc
                .child("txBody")
                .map(|b| {
                    b.kids_named("p")
                        .map(a_paragraph_text)
                        .filter(|t| !t.is_empty())
                        .collect()
                })
                .unwrap_or_default();
            row.push(Cell {
                text: text.join(" "),
            });
        }
        grid.rows.push(row);
    }
    grid
}

/// Slide part names in deck order.
fn slide_order(pkg: &mut Package) -> Vec<String> {
    let mut ordered = Vec::new();
    if let (Some(pres), Some(rels)) = (
        pkg.xml("ppt/presentation.xml"),
        pkg.xml("ppt/_rels/presentation.xml.rels"),
    ) {
        let targets: BTreeMap<String, String> = relationships(&rels)
            .into_iter()
            .map(|(id, _, target)| (id, join_part("ppt", &target)))
            .collect();
        if let Some(list) = pres.path(&["presentation", "sldIdLst"]) {
            for s in list.kids_named("sldId") {
                if let Some(part) = s.attr_q("r:id").and_then(|id| targets.get(id)) {
                    if pkg.has(part) && !ordered.contains(part) {
                        ordered.push(part.clone());
                    }
                }
            }
        }
    }
    if ordered.is_empty() {
        let mut by_number: Vec<(u64, String)> = pkg
            .names()
            .into_iter()
            .filter(|n| {
                n.starts_with("ppt/slides/slide") && n.ends_with(".xml") && !n.contains("/_rels/")
            })
            .map(|n| (part_number(&n), n))
            .collect();
        by_number.sort();
        ordered = by_number.into_iter().map(|(_, n)| n).collect();
    }
    ordered
}

fn pptx_units(pkg: &mut Package) -> Result<Vec<DocUnit>, String> {
    let slides = slide_order(pkg);
    let mut units = Vec::new();
    let mut pptx = Pptx {
        seen_furniture: BTreeSet::new(),
    };
    for (i, part) in slides.iter().enumerate() {
        let Some(xml) = pkg.read(part) else { continue };
        let root = parse_xml(&xml)?;
        if let Some(tree) = root.path(&["sld", "cSld", "spTree"]) {
            pptx.tree(tree, Xf::IDENTITY, (i + 1) as u32, &mut units);
        }
    }
    Ok(units)
}

// ---------------------------------------------------------------- api ----

/// DOCX/PPTX bytes → structured `DocUnit`s (ADR-0017 decision 8).
///
/// `kind_hint` must be `Docx` or `Pptx`; the package's own main part decides
/// when the hint is the other OOXML kind. Output is byte-deterministic.
pub fn ooxml_units(bytes: &[u8], kind_hint: SourceType) -> Result<Vec<DocUnit>, String> {
    if !matches!(kind_hint, SourceType::Docx | SourceType::Pptx) {
        return Err(format!(
            "ooxml_units: source_type must be docx or pptx, got {kind_hint:?}"
        ));
    }
    let mut pkg = Package::open(bytes)?;
    let is_docx = pkg.has("word/document.xml");
    let is_pptx = pkg.has("ppt/presentation.xml")
        || pkg
            .names()
            .iter()
            .any(|n| n.starts_with("ppt/slides/slide"));
    match (kind_hint, is_docx, is_pptx) {
        (SourceType::Docx, true, _) | (SourceType::Pptx, true, false) => docx_units(&mut pkg),
        (SourceType::Pptx, _, true) | (SourceType::Docx, false, true) => pptx_units(&mut pkg),
        _ => Err("ooxml_units: no word/document.xml or ppt/slides in package".to_string()),
    }
}
