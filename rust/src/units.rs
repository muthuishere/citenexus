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
