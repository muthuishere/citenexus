//! The ONLY place that talks to pdfium for the structured extractor.
//!
//! One locked pass copies everything the analysis needs — characters with
//! boxes, font size/weight, generated/hyphen flags, render mode and marked
//! content IDs; image and path object bounds; the tagged structure tree; the
//! outline — into plain Rust data (`RawDoc`). Every later step is a pure
//! function over that data, which is what makes the output deterministic and
//! testable without re-entering the C library.
//!
//! Geometry is converted to a TOP-LEFT origin (y grows down) and rounded to
//! 0.01 pt here, once, so no later comparison sees raw float noise.
//!
//! Binding (`pdfium()`): libpdfium is loaded dynamically, in this order:
//! `PDFIUM_DYNAMIC_LIB_PATH` (a library file or a directory holding it), then
//! the current directory, then the system loader path. pdfium is not
//! thread-safe, so every call into it holds `PDFIUM_LOCK`.

use std::ffi::c_void;
use std::sync::{Mutex, OnceLock};

use pdfium_render::prelude::*;

/// Round to 0.01 — the single rounding step for all geometry.
pub fn r2(v: f64) -> f64 {
    let r = (v * 100.0).round() / 100.0;
    if r == 0.0 {
        0.0 // normalise -0.0 so the JSON never prints "-0.0"
    } else {
        r
    }
}

static PDFIUM: OnceLock<Result<Pdfium, String>> = OnceLock::new();
static PDFIUM_LOCK: Mutex<()> = Mutex::new(());

/// The process-wide pdfium binding, or why it could not be loaded.
pub fn pdfium() -> Result<&'static Pdfium, String> {
    PDFIUM
        .get_or_init(|| {
            let mut tried = Vec::new();
            if let Ok(p) = std::env::var("PDFIUM_DYNAMIC_LIB_PATH") {
                let path = std::path::PathBuf::from(&p);
                let file = if path.is_dir() {
                    Pdfium::pdfium_platform_library_name_at_path(&path)
                } else {
                    path
                };
                match Pdfium::bind_to_library(&file) {
                    Ok(b) => return Ok(Pdfium::new(b)),
                    Err(PdfiumError::PdfiumLibraryBindingsAlreadyInitialized) => {
                        return Ok(Pdfium::default())
                    }
                    Err(e) => tried.push(format!("{}: {e}", file.display())),
                }
            }
            match Pdfium::bind_to_library(Pdfium::pdfium_platform_library_name_at_path("./")) {
                Ok(b) => return Ok(Pdfium::new(b)),
                Err(PdfiumError::PdfiumLibraryBindingsAlreadyInitialized) => {
                    return Ok(Pdfium::default())
                }
                Err(e) => tried.push(format!("./: {e}")),
            }
            match Pdfium::bind_to_system_library() {
                Ok(b) => Ok(Pdfium::new(b)),
                Err(PdfiumError::PdfiumLibraryBindingsAlreadyInitialized) => Ok(Pdfium::default()),
                Err(e) => {
                    tried.push(format!("system: {e}"));
                    Err(format!(
                        "libpdfium not found (set PDFIUM_DYNAMIC_LIB_PATH): {}",
                        tried.join("; ")
                    ))
                }
            }
        })
        .as_ref()
        .map_err(|e| e.clone())
}

/// Run `f` with exclusive access to pdfium.
pub fn with_pdfium<T>(f: impl FnOnce(&'static Pdfium) -> Result<T, String>) -> Result<T, String> {
    let pdfium = pdfium()?;
    let _guard = PDFIUM_LOCK.lock().unwrap_or_else(|p| p.into_inner());
    f(pdfium)
}

/// One text-layer character.
#[derive(Debug, Clone, PartialEq)]
pub struct RawChar {
    pub ch: char,
    /// Tight box, top-left origin: x0 < x1, y0 (top) < y1 (bottom).
    pub x0: f64,
    pub y0: f64,
    pub x1: f64,
    pub y1: f64,
    /// Loose (advance-width) horizontal extent: word gaps are measured on
    /// these, because tight glyph boxes of "1" or "." carry wide side-bearings.
    pub lx0: f64,
    pub lx1: f64,
    /// Baseline (origin y), top-left origin.
    pub baseline: f64,
    pub size: f64,
    pub bold: bool,
    /// The glyph is rotated (|angle| > ~6 degrees): watermarks, vertical text.
    pub rotated: bool,
    /// The previous character in pdfium's stream order is whitespace.
    pub space_before: bool,
    /// pdfium synthesised it (a space or line break it inferred).
    pub generated: bool,
    /// pdfium's line-end hyphen marker (emitted as U+0002).
    pub hyphen: bool,
    pub unicode_error: bool,
    /// Text render mode 3: invisible (an OCR layer under a scan).
    pub invisible: bool,
    /// Marked-content ID of the owning text object, -1 when untagged.
    pub mcid: i32,
}

/// A structure element on one page, in pre-order.
#[derive(Debug, Clone, PartialEq)]
pub struct StructNode {
    pub kind: String,
    pub depth: u32,
    pub mcids: Vec<i32>,
}

#[derive(Debug, Clone, PartialEq, Default)]
pub struct RawPage {
    pub width: f64,
    pub height: f64,
    pub chars: Vec<RawChar>,
    /// Image object boxes `[x0, y0, x1, y1]`, top-left origin.
    pub images: Vec<[f64; 4]>,
    /// Path object boxes (ruling lines, cell borders, fills).
    pub paths: Vec<[f64; 4]>,
    pub struct_nodes: Vec<StructNode>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct OutlineEntry {
    pub title: String,
    pub page: Option<usize>,
    pub depth: u32,
}

#[derive(Debug, Clone, PartialEq, Default)]
pub struct RawDoc {
    pub pages: Vec<RawPage>,
    pub outline: Vec<OutlineEntry>,
}

impl RawDoc {
    pub fn tagged(&self) -> bool {
        self.pages.iter().any(|p| !p.struct_nodes.is_empty())
    }
}

fn utf16_buf(fetch: impl Fn(*mut c_void, u64) -> u64) -> String {
    let n = fetch(std::ptr::null_mut(), 0) as usize;
    if n < 2 {
        return String::new();
    }
    let mut buf = vec![0u16; n / 2 + 1];
    fetch(buf.as_mut_ptr() as *mut c_void, (buf.len() * 2) as u64);
    let end = buf.iter().position(|&c| c == 0).unwrap_or(buf.len());
    String::from_utf16_lossy(&buf[..end])
}

const MAX_OUTLINE: usize = 10_000;
const MAX_STRUCT_DEPTH: u32 = 64;
const MAX_STRUCT_NODES: usize = 100_000;

/// Read `bytes` into a `RawDoc`.
pub fn read(bytes: &[u8]) -> Result<RawDoc, String> {
    with_pdfium(|pdfium| {
        let b = pdfium.bindings();
        unsafe {
            let doc = b.FPDF_LoadMemDocument64(bytes, None);
            if doc.is_null() {
                return Err(format!(
                    "pdfium: could not load document (error {})",
                    b.FPDF_GetLastError()
                ));
            }
            let out = read_doc(b, doc);
            b.FPDF_CloseDocument(doc);
            Ok(out)
        }
    })
}

unsafe fn read_doc(b: &dyn PdfiumLibraryBindings, doc: FPDF_DOCUMENT) -> RawDoc {
    let mut raw = RawDoc::default();
    let count = b.FPDF_GetPageCount(doc).max(0);
    for index in 0..count {
        let page = b.FPDF_LoadPage(doc, index);
        if page.is_null() {
            raw.pages.push(RawPage::default());
            continue;
        }
        raw.pages.push(read_page(b, page));
        b.FPDF_ClosePage(page);
    }
    read_outline(b, doc, std::ptr::null_mut(), 0, &mut raw.outline);
    raw
}

unsafe fn read_page(b: &dyn PdfiumLibraryBindings, page: FPDF_PAGE) -> RawPage {
    let width = b.FPDF_GetPageWidthF(page) as f64;
    let height = b.FPDF_GetPageHeightF(page) as f64;
    let mut out = RawPage {
        width: r2(width),
        height: r2(height),
        ..Default::default()
    };

    let tp = b.FPDFText_LoadPage(page);
    if !tp.is_null() {
        let n = b.FPDFText_CountChars(tp).max(0);
        for i in 0..n {
            let code = b.FPDFText_GetUnicode(tp, i);
            let ch = char::from_u32(code).unwrap_or('\u{FFFD}');
            let (mut l, mut r, mut bo, mut t) = (0f64, 0f64, 0f64, 0f64);
            let has_box = b.FPDFText_GetCharBox(tp, i, &mut l, &mut r, &mut bo, &mut t) != 0;
            let generated = b.FPDFText_IsGenerated(tp, i) == 1;
            let hyphen = b.FPDFText_IsHyphen(tp, i) == 1 || code == 2;
            let size = b.FPDFText_GetFontSize(tp, i);
            let weight = b.FPDFText_GetFontWeight(tp, i);
            let mut flags = 0;
            let name_len = b.FPDFText_GetFontInfo(tp, i, std::ptr::null_mut(), 0, &mut flags);
            let mut name = String::new();
            if name_len > 0 {
                let mut buf = vec![0u8; name_len as usize];
                b.FPDFText_GetFontInfo(
                    tp,
                    i,
                    buf.as_mut_ptr() as *mut c_void,
                    name_len,
                    &mut flags,
                );
                let end = buf.iter().position(|&c| c == 0).unwrap_or(buf.len());
                name = String::from_utf8_lossy(&buf[..end]).to_string();
            }
            // Flag bit 19 (0x40000) is ForceBold in the PDF font descriptor.
            let lname = name.to_ascii_lowercase();
            let bold = weight >= 600
                || (flags & 0x40000) != 0
                || lname.contains("bold")
                || lname.contains("black")
                || lname.contains("heavy")
                || lname.contains("semibold");
            let obj = b.FPDFText_GetTextObject(tp, i);
            let mcid = if obj.is_null() {
                -1
            } else {
                b.FPDFPageObj_GetMarkedContentID(obj)
            };
            let invisible = !obj.is_null() && b.FPDFTextObj_GetTextRenderMode(obj) == 3;
            let unicode_error = b.FPDFText_HasUnicodeMapError(tp, i) == 1;
            let (mut ox, mut oy) = (0f64, 0f64);
            b.FPDFText_GetCharOrigin(tp, i, &mut ox, &mut oy);
            let angle = b.FPDFText_GetCharAngle(tp, i) as f64;
            let rotated = angle > 0.1 && angle < std::f64::consts::TAU - 0.1;
            let space_before = out
                .chars
                .last()
                .is_some_and(|c: &RawChar| c.ch.is_whitespace());
            let mut loose = FS_RECTF {
                left: 0.0,
                top: 0.0,
                right: 0.0,
                bottom: 0.0,
            };
            let has_loose = b.FPDFText_GetLooseCharBox(tp, i, &mut loose) != 0;
            let (x0, x1, y0, y1) = if has_box {
                (r2(l), r2(r), r2(height - t), r2(height - bo))
            } else {
                (0.0, 0.0, 0.0, 0.0)
            };
            out.chars.push(RawChar {
                ch,
                x0,
                y0,
                x1,
                y1,
                lx0: if has_loose { r2(loose.left as f64) } else { x0 },
                lx1: if has_loose {
                    r2(loose.right as f64)
                } else {
                    x1
                },
                baseline: r2(height - oy),
                size: r2(size),
                bold,
                rotated,
                space_before,
                generated,
                hyphen,
                unicode_error,
                invisible,
                mcid,
            });
        }
        b.FPDFText_ClosePage(tp);
    }

    let objects = b.FPDFPage_CountObjects(page).max(0);
    for i in 0..objects {
        let obj = b.FPDFPage_GetObject(page, i);
        if obj.is_null() {
            continue;
        }
        let kind = b.FPDFPageObj_GetType(obj) as u32;
        if kind != FPDF_PAGEOBJ_IMAGE && kind != FPDF_PAGEOBJ_PATH {
            continue;
        }
        let (mut l, mut bo, mut r, mut t) = (0f32, 0f32, 0f32, 0f32);
        if b.FPDFPageObj_GetBounds(obj, &mut l, &mut bo, &mut r, &mut t) == 0 {
            continue;
        }
        let bx = [
            r2(l as f64),
            r2(height - t as f64),
            r2(r as f64),
            r2(height - bo as f64),
        ];
        if kind == FPDF_PAGEOBJ_IMAGE {
            out.images.push(bx);
        } else {
            out.paths.push(bx);
        }
    }

    let tree = b.FPDF_StructTree_GetForPage(page);
    if !tree.is_null() {
        let kids = b.FPDF_StructTree_CountChildren(tree).max(0);
        for k in 0..kids {
            let el = b.FPDF_StructTree_GetChildAtIndex(tree, k);
            read_struct(b, el, 0, &mut out.struct_nodes);
        }
        b.FPDF_StructTree_Close(tree);
    }
    out
}

unsafe fn read_struct(
    b: &dyn PdfiumLibraryBindings,
    el: FPDF_STRUCTELEMENT,
    depth: u32,
    out: &mut Vec<StructNode>,
) {
    if el.is_null() || depth > MAX_STRUCT_DEPTH || out.len() >= MAX_STRUCT_NODES {
        return;
    }
    let kind = utf16_buf(|buf, len| b.FPDF_StructElement_GetType(el, buf, len as _));
    let mut mcids = Vec::new();
    let n = b.FPDF_StructElement_GetMarkedContentIdCount(el);
    for i in 0..n.max(0) {
        let id = b.FPDF_StructElement_GetMarkedContentIdAtIndex(el, i);
        if id >= 0 {
            mcids.push(id);
        }
    }
    out.push(StructNode { kind, depth, mcids });
    let kids = b.FPDF_StructElement_CountChildren(el).max(0);
    for k in 0..kids {
        let child = b.FPDF_StructElement_GetChildAtIndex(el, k);
        read_struct(b, child, depth + 1, out);
    }
}

unsafe fn read_outline(
    b: &dyn PdfiumLibraryBindings,
    doc: FPDF_DOCUMENT,
    parent: FPDF_BOOKMARK,
    depth: u32,
    out: &mut Vec<OutlineEntry>,
) {
    if depth > 16 {
        return;
    }
    let mut bm = b.FPDFBookmark_GetFirstChild(doc, parent);
    while !bm.is_null() && out.len() < MAX_OUTLINE {
        let title = utf16_buf(|buf, len| b.FPDFBookmark_GetTitle(bm, buf, len as _));
        let dest = b.FPDFBookmark_GetDest(doc, bm);
        let page = if dest.is_null() {
            None
        } else {
            let p = b.FPDFDest_GetDestPageIndex(doc, dest);
            (p >= 0).then_some(p as usize)
        };
        out.push(OutlineEntry {
            title: title.trim().to_string(),
            page,
            depth,
        });
        read_outline(b, doc, bm, depth + 1, out);
        bm = b.FPDFBookmark_GetNextSibling(doc, bm);
    }
}
