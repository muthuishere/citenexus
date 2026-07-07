//! `citenexus_to_markdown` over the C ABI: extract + emit in one call,
//! `{"markdown": ...}` on success, `{"error": ...}` on failure.

use std::ffi::{CStr, CString};
use std::io::Write;
use std::os::raw::c_char;

use citenexus_core::ffi;
use serde_json::Value;

fn take_json(ptr: *mut c_char) -> Value {
    assert!(!ptr.is_null());
    let value = {
        let s = unsafe { CStr::from_ptr(ptr) }.to_str().expect("utf-8");
        serde_json::from_str(s).expect("json")
    };
    unsafe { ffi::citenexus_free_string(ptr) };
    value
}

fn to_markdown(bytes: &[u8], source_type: &str) -> Value {
    let source_type = CString::new(source_type).unwrap();
    take_json(unsafe {
        ffi::citenexus_to_markdown(bytes.as_ptr(), bytes.len(), source_type.as_ptr())
    })
}

fn docx_bytes() -> Vec<u8> {
    let document_xml = r#"<?xml version="1.0"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Title</w:t></w:r></w:p>
    <w:p><w:r><w:t>Body </w:t></w:r><w:r><w:t>text.</w:t></w:r></w:p>
  </w:body>
</w:document>"#;
    let mut buf = Vec::new();
    {
        let mut writer = zip::ZipWriter::new(std::io::Cursor::new(&mut buf));
        let options = zip::write::SimpleFileOptions::default();
        writer.start_file("word/document.xml", options).unwrap();
        writer.write_all(document_xml.as_bytes()).unwrap();
        writer.finish().unwrap();
    }
    buf
}

#[test]
fn docx_converts_with_heading_prefixes() {
    let result = to_markdown(&docx_bytes(), "docx");
    assert_eq!(result["markdown"], "# Title\n\nBody text.\n");
}

#[test]
fn xlsx_fixture_converts_sheet_by_sheet() {
    let path = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../conformance/fixtures/sample.xlsx"
    );
    let bytes = std::fs::read(path).expect("conformance/fixtures/sample.xlsx");
    let markdown = to_markdown(&bytes, "xlsx")["markdown"]
        .as_str()
        .unwrap()
        .to_string();
    assert_eq!(
        markdown,
        "# People\n\nname: ada, age: 36, active: true\n\n\
         name: alan, age: 41.5, active: false\n\n\
         # Scores\n\nteam: red, points: 30\n"
    );
}

#[test]
fn plain_type_falls_back_to_paragraphs() {
    let result = to_markdown(b"First para.\n\nSecond para.\n", "plain");
    assert_eq!(result["markdown"], "First para.\n\nSecond para.\n");
}

#[test]
fn invalid_docx_bytes_return_error() {
    let result = to_markdown(b"not a zip archive", "docx");
    assert!(result["error"].as_str().is_some());
    assert!(result.get("markdown").is_none());
}

#[test]
fn unknown_source_type_returns_error() {
    let result = to_markdown(b"anything", "wav");
    assert!(result["error"]
        .as_str()
        .unwrap()
        .contains("unknown source_type"));
}
