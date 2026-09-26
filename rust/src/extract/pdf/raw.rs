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

/// Why libpdfium could not be bound.
#[derive(Debug, Clone, PartialEq)]
pub enum PdfiumLoadError {
    /// No libpdfium was found in any of the places `pdfium()` looks.
    NotFound(String),
    /// Another pdfium-render user in this process created its `Pdfium`
    /// first. pdfium-render 0.9.4 then refuses a second binding, and the core
    /// needs its own raw bindings (`FPDFText_*`), so it stops rather than
    /// guess: bind the PDF core before any other pdfium-render user.
    InitializedElsewhere,
}

impl std::fmt::Display for PdfiumLoadError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            PdfiumLoadError::NotFound(tried) => write!(
                f,
                "libpdfium not found (set PDFIUM_DYNAMIC_LIB_PATH): {tried}"
            ),
            PdfiumLoadError::InitializedElsewhere => f.write_str(
                "pdfium was initialized by another pdfium-render user in this process \
                 before the PDF core: the core cannot obtain its own raw bindings",
            ),
        }
    }
}

impl std::error::Error for PdfiumLoadError {}

/// The high-level `Pdfium` plus the core's own raw bindings to the same
/// library. pdfium-render 0.9.4 keeps its accessor crate-private, so the core
/// binds the library twice BEFORE `Pdfium::new`: one binding goes to
/// `Pdfium::new` (which runs `FPDF_InitLibrary` once), the other is kept here
/// for the `FPDFText_*` / `FPDF_*` calls. Both are handles to the same loaded
/// library.
pub struct Bound {
    pub pdfium: Pdfium,
    pub raw: Box<dyn PdfiumLibraryBindings>,
}

static PDFIUM: OnceLock<Result<Bound, PdfiumLoadError>> = OnceLock::new();
static PDFIUM_LOCK: Mutex<()> = Mutex::new(());

enum Attempt {
    Bound(Bound),
    Elsewhere,
    Failed(String),
}

fn bind_twice(bind: impl Fn() -> Result<Box<dyn PdfiumLibraryBindings>, PdfiumError>) -> Attempt {
    match (bind(), bind()) {
        (Ok(raw), Ok(b)) => Attempt::Bound(Bound {
            pdfium: Pdfium::new(b),
            raw,
        }),
        (Err(PdfiumError::PdfiumLibraryBindingsAlreadyInitialized), _)
        | (_, Err(PdfiumError::PdfiumLibraryBindingsAlreadyInitialized)) => Attempt::Elsewhere,
        (Err(e), _) | (_, Err(e)) => Attempt::Failed(e.to_string()),
    }
}

/// The process-wide pdfium binding, or why it could not be loaded.
pub fn pdfium() -> Result<&'static Bound, PdfiumLoadError> {
    PDFIUM
        .get_or_init(|| {
            let mut tried = Vec::new();
            let mut attempt = |label: String, a: Attempt| match a {
                Attempt::Bound(b) => Some(Ok(b)),
                Attempt::Elsewhere => Some(Err(PdfiumLoadError::InitializedElsewhere)),
                Attempt::Failed(e) => {
                    tried.push(format!("{label}: {e}"));
                    None
                }
            };
            if let Ok(p) = std::env::var("PDFIUM_DYNAMIC_LIB_PATH") {
                let path = std::path::PathBuf::from(&p);
                let file = if path.is_dir() {
                    Pdfium::pdfium_platform_library_name_at_path(&path)
                } else {
                    path
                };
                let a = bind_twice(|| Pdfium::bind_to_library(&file));
                if let Some(r) = attempt(file.display().to_string(), a) {
                    return r;
                }
            }
            let here = Pdfium::pdfium_platform_library_name_at_path("./");
            if let Some(r) = attempt("./".into(), bind_twice(|| Pdfium::bind_to_library(&here))) {
                return r;
            }
            if let Some(r) = attempt("system".into(), bind_twice(Pdfium::bind_to_system_library)) {
                return r;
            }
            Err(PdfiumLoadError::NotFound(tried.join("; ")))
        })
        .as_ref()
        .map_err(|e| e.clone())
}

/// Run `f` with exclusive access to pdfium.
pub fn with_pdfium<T>(f: impl FnOnce(&'static Bound) -> Result<T, String>) -> Result<T, String> {
    let bound = pdfium().map_err(|e| e.to_string())?;
    let _guard = PDFIUM_LOCK.lock().unwrap_or_else(|p| p.into_inner());
    f(bound)
}

/// Ascent and descent of the stated box, as a fraction of the font size
/// (Helvetica AFM: cap height 718, descender -207). pdfium's own ascent and
/// descent come from the substituted font face, so they are NOT used.
pub const STATED_ASCENT: f64 = 0.72;
pub const STATED_DESCENT: f64 = 0.21;

/// One text-layer character.
#[derive(Debug, Clone, PartialEq)]
pub struct RawChar {
    pub ch: char,
    /// The STATED box, top-left origin: x0 < x1, y0 (top) < y1 (bottom). It is
    /// built only from geometry the PDF itself states: the character origin,
    /// the advance width (the font's /Widths or the standard-14 AFM metrics),
    /// the character matrix and the font size, with a size-derived ascent and
    /// descent (`STATED_ASCENT`, `STATED_DESCENT`). Every layout decision and
    /// every emitted bbox reads this box, so the output does not depend on the
    /// font the platform substitutes for a non-embedded font.
    pub x0: f64,
    pub y0: f64,
    pub x1: f64,
    pub y1: f64,
    /// The tight rendered glyph box `[x0, y0, x1, y1]`. It depends on the
    /// glyph outlines, i.e. on the platform's substitute font when the PDF
    /// does not embed its font (up to ~0.6 pt between macOS and Linux on the
    /// same pdfium), so it decides only "is there ink at all".
    pub ink: [f64; 4],
    /// Baseline (origin y), top-left origin.
    pub baseline: f64,
    /// EFFECTIVE font size in points: the `Tf` size times the em height of
    /// the character matrix (text matrix x CTM). A PDF that sets `Tf 1` and
    /// scales text with `Tm` has `FPDFText_GetFontSize` = 1 for 8 pt text;
    /// every size-relative threshold (word and column gaps, block merging,
    /// heading size, bands, row gaps) reads this value.
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
    /// Table-cell `RowSpan` / `ColSpan` attributes (1 when absent).
    pub rowspan: u32,
    pub colspan: u32,
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
    with_pdfium(|bound| {
        let b = bound.raw.as_ref();
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

/// Stated-geometry inputs of one character, kept until the page is read.
struct Pending {
    ox: f64,
    oy: f64,
    m: [f64; 4],
    size: f64,
    adv: Option<f64>,
    loose_adv: f64,
    obj: usize,
}

/// Fill each character's stated box. A ligature expanded by its ToUnicode
/// entry ("tf" -> 't','f' on ONE origin) has no per-character width, so its
/// characters share pdfium's loose advance; so does a character whose code
/// the font cannot map back.
fn stated_boxes(chars: &mut [RawChar], pending: &[Pending], left: f64, top: f64) {
    let n = pending.len().min(chars.len());
    let same_origin = |i: usize, j: usize| {
        pending[i].obj == pending[j].obj
            && pending[i].obj != 0
            && (pending[i].ox - pending[j].ox).abs() < 0.01
            && (pending[i].oy - pending[j].oy).abs() < 0.01
    };
    for i in 0..n {
        let p = &pending[i];
        let c = &chars[i];
        if c.generated {
            let (x, y) = (r2(p.ox - left), r2(top - p.oy));
            chars[i].x0 = x;
            chars[i].x1 = x;
            chars[i].y0 = y;
            chars[i].y1 = y;
            continue;
        }
        let expanded = (i > 0 && !chars[i - 1].generated && same_origin(i - 1, i))
            || (i + 1 < n && !chars[i + 1].generated && same_origin(i, i + 1));
        let adv = match p.adv {
            Some(a) if !expanded => a,
            _ => p.loose_adv,
        };
        let [a, b, cc, d] = p.m;
        let (asc, desc) = (STATED_ASCENT * p.size, -STATED_DESCENT * p.size);
        let (mut x0, mut y0, mut x1, mut y1) = (f64::MAX, f64::MAX, f64::MIN, f64::MIN);
        for t in [0.0, adv] {
            for s in [desc, asc] {
                let x = p.ox + t * a + s * cc - left;
                let y = top - (p.oy + t * b + s * d);
                x0 = x0.min(x);
                x1 = x1.max(x);
                y0 = y0.min(y);
                y1 = y1.max(y);
            }
        }
        chars[i].x0 = r2(x0);
        chars[i].y0 = r2(y0);
        chars[i].x1 = r2(x1);
        chars[i].y1 = r2(y1);
    }
}

unsafe fn read_page(b: &dyn PdfiumLibraryBindings, page: FPDF_PAGE) -> RawPage {
    let width = b.FPDF_GetPageWidthF(page) as f64;
    let height = b.FPDF_GetPageHeightF(page) as f64;
    // Coordinates are made relative to the VISIBLE page box (CropBox ∩
    // MediaBox), which need not start at (0, 0): x' = x - left, y' = top - y.
    // Every band, margin and region downstream is measured from this box,
    // never from the ink extent.
    let mut pb = FS_RECTF {
        left: 0.0,
        top: height as f32,
        right: width as f32,
        bottom: 0.0,
    };
    if b.FPDF_GetPageBoundingBox(page, &mut pb) == 0 {
        pb = FS_RECTF {
            left: 0.0,
            top: height as f32,
            right: width as f32,
            bottom: 0.0,
        };
    }
    let (left, top) = (pb.left as f64, pb.top as f64);
    let mut out = RawPage {
        width: r2(width),
        height: r2(height),
        ..Default::default()
    };

    let tp = b.FPDFText_LoadPage(page);
    let mut pending: Vec<Pending> = Vec::new();
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
            let mode = if obj.is_null() {
                -1
            } else {
                b.FPDFTextObj_GetTextRenderMode(obj)
            };
            let invisible = mode == 3;
            // Render mode 2 (fill, then stroke the outline): synthetic bold, the
            // way a PDF writer emboldens a font it has no bold face for.
            let bold = bold || mode == 2;
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
            let ink = if has_box {
                [r2(l - left), r2(top - t), r2(r - left), r2(top - bo)]
            } else {
                [0.0; 4]
            };
            // The character matrix (text matrix x CTM, with Tz folded in):
            // the advance runs along (a, b), the em height along (c, d).
            let mut m = FS_MATRIX {
                a: 1.0,
                b: 0.0,
                c: 0.0,
                d: 1.0,
                e: 0.0,
                f: 0.0,
            };
            if b.FPDFText_GetMatrix(tp, i, &mut m) == 0 {
                m = FS_MATRIX {
                    a: 1.0,
                    b: 0.0,
                    c: 0.0,
                    d: 1.0,
                    e: 0.0,
                    f: 0.0,
                };
            }
            let m = [m.a as f64, m.b as f64, m.c as f64, m.d as f64];
            let em = m[2].hypot(m[3]);
            let em = if em.is_finite() && em > 1e-6 { em } else { 1.0 };
            // Advance in text space: the width the font states for this
            // character (FPDFText_GetFontSize is the Tf size, unscaled).
            let mut w_em = 0f32;
            let font = if obj.is_null() {
                std::ptr::null_mut()
            } else {
                b.FPDFTextObj_GetFont(obj)
            };
            let w_ok = !font.is_null() && b.FPDFFont_GetGlyphWidth(font, code, 1.0, &mut w_em) != 0;
            let adv = if w_ok && w_em.is_finite() && w_em > 0.0 {
                Some(w_em as f64 * size)
            } else {
                None
            };
            // pdfium's loose right edge, projected back to text space: the
            // fallback advance (ligature expansions, unmapped codes).
            let loose_adv = if has_loose && m[0].abs() > 1e-6 {
                ((loose.right as f64 - ox) / m[0]).max(0.0)
            } else {
                0.0
            };
            pending.push(Pending {
                ox,
                oy,
                m,
                size,
                adv,
                loose_adv,
                obj: obj as usize,
            });
            out.chars.push(RawChar {
                ch,
                x0: 0.0,
                y0: 0.0,
                x1: 0.0,
                y1: 0.0,
                ink,
                baseline: r2(top - oy),
                size: r2(size * em),
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
        stated_boxes(&mut out.chars, &pending, left, top);
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
            r2(l as f64 - left),
            r2(top - t as f64),
            r2(r as f64 - left),
            r2(top - bo as f64),
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
    let (mut rowspan, mut colspan) = (1u32, 1u32);
    if kind == "TD" || kind == "TH" {
        let n_attr = b.FPDF_StructElement_GetAttributeCount(el).max(0);
        for a in 0..n_attr.min(16) {
            let attr = b.FPDF_StructElement_GetAttributeAtIndex(el, a);
            if attr.is_null() {
                continue;
            }
            for (name, slot) in [("RowSpan", &mut rowspan), ("ColSpan", &mut colspan)] {
                let v = b.FPDF_StructElement_Attr_GetValue(attr, name);
                let mut f = 0f32;
                if !v.is_null()
                    && b.FPDF_StructElement_Attr_GetNumberValue(v, &mut f) != 0
                    && (1.0..=1000.0).contains(&f)
                {
                    *slot = f.round() as u32;
                }
            }
        }
    }
    out.push(StructNode {
        kind,
        depth,
        mcids,
        rowspan,
        colspan,
    });
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
