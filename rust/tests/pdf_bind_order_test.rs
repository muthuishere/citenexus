//! Another pdfium-render user in the process creates its `Pdfium` first. The
//! core must then fail with a typed error, never fall back silently. This is
//! its own test binary (its own process), because the binding is global.
#![cfg(feature = "pdf")]

use citenexus_core::extract::pdf::raw::{self, PdfiumLoadError};
use pdfium_render::prelude::*;

#[test]
fn a_pdfium_created_elsewhere_first_is_a_typed_error() {
    let Ok(path) = std::env::var("PDFIUM_DYNAMIC_LIB_PATH") else {
        eprintln!("SKIP: set PDFIUM_DYNAMIC_LIB_PATH");
        return;
    };
    let path = std::path::PathBuf::from(path);
    let file = if path.is_dir() {
        Pdfium::pdfium_platform_library_name_at_path(&path)
    } else {
        path
    };
    let Ok(b) = Pdfium::bind_to_library(&file) else {
        eprintln!("SKIP: libpdfium did not load");
        return;
    };
    let _other = Pdfium::new(b);
    assert_eq!(
        raw::pdfium().err(),
        Some(PdfiumLoadError::InitializedElsewhere)
    );
    let err = raw::read(b"%PDF-1.7").unwrap_err();
    assert!(err.contains("another pdfium-render user"), "{err}");
}
