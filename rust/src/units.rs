//! The structured-document unit contract (ADR-0017 decisions 1, 6, 8, 10).
//!
//! One `DocUnit` is one block of a converted document — a heading, a
//! paragraph, a list, a table, a running header/footer line kept once as
//! furniture, or an image region — with its page, its bbox where known, its
//! markdown, and the provenance that says how it was produced. PDF (the pdfium
//! base extractor and, later, the model-assisted assemble path) and OOXML
//! (docx/pptx, `route = ooxml`) both emit this shape, so every binding sees one
//! contract.
//!
//! **Serialization is part of the contract.** Fields serialize in declaration
//! order (serde derives do not reorder), enums as `snake_case` strings, and
//! absent optionals as `null` — the same convention as `types.rs`. Do not
//! reorder fields; append new ones at the end with `#[serde(default)]` so old
//! payloads still deserialize.

use serde::{Deserialize, Serialize};

use crate::types::BBox;

/// What a unit is. Closed set (ADR-0017 decision 10).
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum UnitKind {
    Heading,
    Paragraph,
    List,
    Table,
    /// A running header/footer line, kept ONCE per document (not deleted) so
    /// text like "last updated <date>" stays citable.
    Furniture,
    /// An image region. On a text-layer page it is never merged into, and
    /// never overrides, text-layer content (ADR-0017 decision 9).
    Image,
}

/// How the page (or, for OOXML, the document) was classified — the router's
/// verdict (ADR-0017 decision 2). `Ooxml` marks units that came from DOCX/PPTX
/// structure rather than from a PDF page.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Route {
    /// Running text, one font family/size band, no table evidence.
    Plain,
    /// Text with structure worth keeping: headings, lists, several font bands,
    /// or multiple columns.
    Formatted,
    /// Ruling lines or aligned column tracks: table evidence on the page.
    Table,
    /// A text-layer page where image objects cover a large share of the page.
    Image,
    /// No usable text layer: a scan (or an unsound text layer).
    Scan,
    /// DOCX/PPTX: structure read from the OOXML itself, no page routing.
    Ooxml,
}

/// Where a table's grid came from (ADR-0017 decision 6).
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TableSource {
    /// The tagged-PDF structure tree (`/Table`→`/TR`→`/TH`/`/TD`).
    StructTree,
    /// A ruled grid built from path segments and thin rectangles.
    Ruled,
    /// A grid inferred from aligned column tracks (borderless).
    Tracks,
    /// A grid returned by an injected model over text-layer word IDs.
    ModelGrid,
    /// OOXML table markup (`w:tbl`, `a:tbl`).
    Ooxml,
}

/// Which source decided a heading's level.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum HeadingSource {
    /// Tagged-PDF `/H1`..`/H6` (or `/H`) structure elements.
    StructTree,
    /// The PDF outline (bookmarks).
    Outline,
    /// A numbering pattern ("1.2", "§ 3", "I.3").
    Numbering,
    /// Font-size / weight clustering.
    Font,
    /// OOXML heading styles / title placeholders.
    Style,
}

/// How a unit was produced (ADR-0017 decision 6). Every unit carries one.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Provenance {
    /// The page's (or document's) route.
    pub route: Route,
    /// Set on `table` units only.
    #[serde(default)]
    pub table_source: Option<TableSource>,
    /// The text was written by a vision model (no text layer under it).
    #[serde(default)]
    pub vision_transcribed: bool,
    /// The table's grid scored low or a check downgraded it.
    #[serde(default)]
    pub table_uncertain: bool,
    /// The deterministic check that failed when a fallback to base text
    /// happened (e.g. `"geometry"`, `"digit_bag"`), else `null`.
    #[serde(default)]
    pub failed_check: Option<String>,
    /// Set on `heading` units only: which source decided the level.
    #[serde(default)]
    pub heading_source: Option<HeadingSource>,
    /// At least one line-end hyphen was joined in this unit, so the printed
    /// form differs from `markdown` (a quote may still match the printed form).
    #[serde(default)]
    pub joined_hyphen: bool,
}

impl Provenance {
    /// A provenance with only the route set.
    pub fn new(route: Route) -> Self {
        Self {
            route,
            table_source: None,
            vision_transcribed: false,
            table_uncertain: false,
            failed_check: None,
            heading_source: None,
            joined_hyphen: false,
        }
    }
}

/// One unit of a converted document (ADR-0017 decisions 1 and 10).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct DocUnit {
    /// 1-based page (PDF, PPTX slide); `null` where the format has no pages.
    #[serde(default)]
    pub page: Option<u32>,
    /// `[x0, y0, x1, y1]` in PDF points, **top-left origin** (y grows down),
    /// rounded to 0.01 so the JSON is byte-stable. `null` when unknown.
    #[serde(default)]
    pub bbox: Option<BBox>,
    pub kind: UnitKind,
    /// Heading level (1..6) for `heading`; `null` otherwise.
    #[serde(default)]
    pub level: Option<u32>,
    /// The unit's markdown (a heading carries its `#` prefix).
    pub markdown: String,
    pub provenance: Provenance,
}

/// ADR-0017 names the PDF unit `PdfUnit`; it is the same shape as every other
/// format's unit.
pub type PdfUnit = DocUnit;

// ---------------------------------------------------------------------------
// The PDF envelope: options in, units + per-page routing + document signals
// out. Not behind the `pdf` feature, so bindings can name the types either way.
// ---------------------------------------------------------------------------

/// Options for `pdf_units` (JSON over the C ABI; every field optional).
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct PdfOptions {
    /// BCP-47-ish language of the document ("nl", "en"); drives the hyphen
    /// keep-lists. Unknown or absent → the union of every list.
    #[serde(default)]
    pub language: Option<String>,
    /// Include each page's `pdftotext -layout`-style text in `pages[]`.
    #[serde(default)]
    pub layout_text: bool,
}

/// The evidence behind one page's route (ADR-0017 decision 2). Shares are in
/// 0..1, rounded to 4 decimals.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PdfPageSignals {
    /// Visible (non-generated, non-space) text-layer characters.
    pub chars: u32,
    /// U+FFFD / private-use / control / unicode-map-error share.
    pub bad_char_share: f64,
    /// Render-mode-3 (invisible, OCR-layer) share.
    pub invisible_share: f64,
    /// Glyphs drawn twice at the same spot (doubled layer) share.
    pub duplicate_share: f64,
    /// The text layer can be trusted as ground truth.
    pub text_sound: bool,
    /// Share of the page covered by image objects.
    pub image_coverage: f64,
    pub images: u32,
    /// Thin, long horizontal / vertical path objects.
    pub ruling_lines_h: u32,
    pub ruling_lines_v: u32,
    /// Left edges shared by ≥3 multi-segment lines.
    pub column_tracks: u32,
    /// Lines with ≥2 segments (a gap wider than 1.5 × font size).
    pub multi_segment_lines: u32,
    /// 1, or 2 when most lines split into two segments at ≤2 tracks.
    pub text_columns: u32,
    /// Distinct font sizes on the page (0.5 pt buckets).
    pub font_sizes: u32,
    /// `struct_tree` | `rule_based` | `xycut` | `none`.
    pub reading_order: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PdfPageInfo {
    /// 1-based.
    pub page: u32,
    pub width: f64,
    pub height: f64,
    pub route: Route,
    pub signals: PdfPageSignals,
    /// Only with `PdfOptions::layout_text`.
    #[serde(default)]
    pub layout_text: Option<String>,
}

/// How the document's headings were decided (the per-document rule).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct HeadingAgreement {
    /// Pages with a struct-tree heading or a font-evidence heading.
    pub compared_pages: u32,
    /// Of those, pages with no tagged heading printed as body text and no
    /// clearly larger line tagged as body text.
    pub agreeing_pages: u32,
    /// agreeing / compared, rounded to 4 decimals (1.0 when nothing compared).
    pub rate: f64,
    /// The struct tree was trusted for the WHOLE document.
    pub struct_tree_trusted: bool,
    /// Tagged heading blocks printed like body text (not larger, not bold).
    #[serde(default)]
    pub struct_unsupported: u32,
    /// Clearly larger short blocks (≥1.15 × body) tagged as body text.
    #[serde(default)]
    pub font_untagged_strong: u32,
    /// Bold body-size short blocks tagged as body text (weak; not counted
    /// against the tags).
    #[serde(default)]
    pub font_untagged_weak: u32,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PdfDocumentSignals {
    pub pages: u32,
    /// The document has a structure tree with content on at least one page.
    pub tagged: bool,
    /// The structure tree carries at least one heading element.
    pub struct_headings: bool,
    pub outline_entries: u32,
    /// `struct_tree` | `font` (outline/numbering refine levels) | `none`.
    pub heading_source: String,
    /// Present when the struct tree carries headings.
    #[serde(default)]
    pub heading_agreement: Option<HeadingAgreement>,
    /// pdfium U+0002 hyphen markers seen / joined / kept as printed.
    pub hyphen_markers: u32,
    pub hyphens_joined: u32,
    pub hyphens_kept: u32,
    /// Running header/footer line occurrences detected, and the furniture
    /// units they collapsed to (each distinct line kept once).
    pub furniture_lines: u32,
    pub furniture_units: u32,
}

/// Everything `pdf_units` returns.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PdfUnitsOutput {
    pub units: Vec<DocUnit>,
    pub pages: Vec<PdfPageInfo>,
    pub document: PdfDocumentSignals,
}
