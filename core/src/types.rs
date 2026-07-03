//! The `ExtractedDoc` contract — field-for-field the Python `extract/types.py`.
//!
//! These serialize to the SAME JSON the Python extractors produce (the
//! conformance arbiter), so every binding sees identical documents. Optional
//! fields serialize as `null`, matching pydantic's `model_dump`.

use serde::{Deserialize, Serialize};

/// A bounding box as `[x0, y0, x1, y1]` in page coordinates.
pub type BBox = [f64; 4];

/// The closed set of block kinds (Python `BlockKind`).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum BlockKind {
    Heading,
    Paragraph,
    Table,
    Code,
    Image,
    Slide,
    ThreadTurn,
    OcrBlock,
}

/// The closed set of source types (Python `SourceType`).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SourceType {
    Pdf,
    Docx,
    Pptx,
    Html,
    Md,
    Txt,
    Csv,
    Image,
    Plain,
}

/// The closed set of structure types (Python `StructureType`).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum StructureType {
    HeadingTree,
    CodeAst,
    SlideSequence,
    TableSchema,
    ThreadOrder,
    PageLayout,
    None,
}

/// One extracted block (Python `ExtractedBlock`).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExtractedBlock {
    pub order: usize,
    pub kind: BlockKind,
    pub text: String,
    #[serde(default)]
    pub page: Option<u32>,
    #[serde(default)]
    pub bbox: Option<BBox>,
    #[serde(default)]
    pub level: Option<u32>,
    /// Ancestor heading path — Python defaults this to `()`, so it is a plain
    /// (possibly empty) list here, never null.
    #[serde(default)]
    pub structure_path: Vec<String>,
}

impl ExtractedBlock {
    pub fn new(order: usize, kind: BlockKind, text: impl Into<String>) -> Self {
        Self {
            order,
            kind,
            text: text.into(),
            page: None,
            bbox: None,
            level: None,
            structure_path: vec![],
        }
    }
}

/// A meaningful image asset (Python `ImageRef`).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ImageRef {
    pub image_id: String,
    #[serde(default)]
    pub page: Option<u32>,
    #[serde(default)]
    pub bbox: Option<BBox>,
    #[serde(default)]
    pub width: Option<u32>,
    #[serde(default)]
    pub height: Option<u32>,
    #[serde(default)]
    pub blob_key: Option<String>,
}

/// The extraction result (Python `ExtractedDoc`).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExtractedDoc {
    pub document_id: String,
    pub source_type: SourceType,
    pub structure_type: StructureType,
    #[serde(default)]
    pub source_uri: Option<String>,
    pub blocks: Vec<ExtractedBlock>,
    #[serde(default)]
    pub images: Vec<ImageRef>,
}
