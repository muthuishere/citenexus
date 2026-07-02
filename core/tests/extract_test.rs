//! Extraction semantics — must mirror the Python extractors exactly
//! (the in-repo Python parity test is the final arbiter).

use std::io::Write;

use trustrag_core::types::*;
use trustrag_core::{extract, source_type_for_extension};

fn run(bytes: &[u8], st: SourceType) -> ExtractedDoc {
    extract(bytes, st, "doc", None).expect("extract failed")
}

// ------------------------------------------------------------------ txt ----

#[test]
fn txt_paragraph_per_blank_line_chunk() {
    let doc = run(b"First paragraph.\n\nSecond one\nspans lines.\n\n\n", SourceType::Txt);
    assert_eq!(doc.structure_type, StructureType::None);
    let texts: Vec<&str> = doc.blocks.iter().map(|b| b.text.as_str()).collect();
    assert_eq!(texts, vec!["First paragraph.", "Second one\nspans lines."]);
    assert!(doc.blocks.iter().all(|b| b.kind == BlockKind::Paragraph));
    assert_eq!(doc.blocks[1].order, 1);
}

// ------------------------------------------------------------------ csv ----

#[test]
fn csv_header_is_schema_rows_are_table_blocks() {
    let doc = run(b"name,age\nada,36\nalan,41\n", SourceType::Csv);
    assert_eq!(doc.structure_type, StructureType::TableSchema);
    assert_eq!(doc.blocks.len(), 2);
    assert_eq!(doc.blocks[0].text, "name: ada, age: 36");
    assert_eq!(doc.blocks[0].kind, BlockKind::Table);
    assert_eq!(
        doc.blocks[0].structure_path,
        vec!["name".to_string(), "age".to_string()]
    );
    assert_eq!(doc.blocks[1].level, Some(1));
}

// ------------------------------------------------------------------- md ----

#[test]
fn md_headings_build_ancestor_paths() {
    let src = b"# Title\n\nIntro para.\n\n## Section\n\nBody para.\n";
    let doc = run(src, SourceType::Md);
    assert_eq!(doc.structure_type, StructureType::HeadingTree);
    let kinds: Vec<BlockKind> = doc.blocks.iter().map(|b| b.kind).collect();
    assert_eq!(
        kinds,
        vec![
            BlockKind::Heading,
            BlockKind::Paragraph,
            BlockKind::Heading,
            BlockKind::Paragraph
        ]
    );
    // "Section" is nested under "Title"; its body carries both ancestors.
    assert_eq!(
        doc.blocks[2].structure_path,
        vec!["Title".to_string()]
    );
    assert_eq!(
        doc.blocks[3].structure_path,
        vec!["Title".to_string(), "Section".to_string()]
    );
}

#[test]
fn md_sibling_heading_pops_the_stack() {
    let src = b"## A\n\n## B\n\npara.\n";
    let doc = run(src, SourceType::Md);
    assert_eq!(doc.blocks[1].structure_path, Vec::<String>::new()); // B: A was popped
    assert_eq!(doc.blocks[2].structure_path, vec!["B".to_string()]);
}

// ------------------------------------------------------------------ html ----

#[test]
fn html_walks_headings_and_paragraphs_skipping_script_style() {
    let src = br#"<html><body>
        <h1>Policy</h1>
        <script>var junk = 1;</script>
        <p>Employees accrue leave.</p>
        <h2>Remote</h2>
        <p>Needs <b>approval</b>.</p>
        <p>   </p>
    </body></html>"#;
    let doc = run(src, SourceType::Html);
    assert_eq!(doc.structure_type, StructureType::HeadingTree);
    let texts: Vec<&str> = doc.blocks.iter().map(|b| b.text.as_str()).collect();
    assert_eq!(
        texts,
        vec!["Policy", "Employees accrue leave.", "Remote", "Needsapproval."]
    );
    // bs4 get_text(strip=True) parity: node texts stripped then concatenated.
    assert_eq!(
        doc.blocks[3].structure_path,
        vec!["Policy".to_string(), "Remote".to_string()]
    );
}

// ----------------------------------------------------------------- ooxml ----

fn zip_of(entries: &[(&str, &str)]) -> Vec<u8> {
    let mut buf = Vec::new();
    {
        let mut writer = zip::ZipWriter::new(std::io::Cursor::new(&mut buf));
        let options = zip::write::SimpleFileOptions::default();
        for (name, content) in entries {
            writer.start_file(*name, options).unwrap();
            writer.write_all(content.as_bytes()).unwrap();
        }
        writer.finish().unwrap();
    }
    buf
}

#[test]
fn docx_headings_and_paragraphs_with_images() {
    let document_xml = r#"<?xml version="1.0"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Title</w:t></w:r></w:p>
    <w:p><w:r><w:t>Body </w:t></w:r><w:r><w:t>text.</w:t></w:r></w:p>
    <w:p><w:r><w:t>   </w:t></w:r></w:p>
  </w:body>
</w:document>"#;
    let rels_xml = r#"<?xml version="1.0"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId7" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/image1.png"/>
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"#;
    let bytes = zip_of(&[
        ("word/document.xml", document_xml),
        ("word/_rels/document.xml.rels", rels_xml),
    ]);
    let doc = run(&bytes, SourceType::Docx);
    assert_eq!(doc.blocks.len(), 2); // blank paragraph skipped
    assert_eq!(doc.blocks[0].kind, BlockKind::Heading);
    assert_eq!(doc.blocks[0].level, Some(1));
    assert_eq!(doc.blocks[1].text, "Body text.");
    assert_eq!(
        doc.blocks[1].structure_path,
        vec!["Title".to_string()]
    );
    assert_eq!(doc.images.len(), 1);
    assert_eq!(doc.images[0].image_id, "rId7");
}

#[test]
fn pptx_one_slide_block_per_slide_with_pictures() {
    let slide1 = r#"<?xml version="1.0"?>
<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
       xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
  <p:cSld><p:spTree>
    <p:sp><p:txBody><a:p><a:r><a:t>Hello</a:t></a:r></a:p><a:p><a:r><a:t>World</a:t></a:r></a:p></p:txBody></p:sp>
    <p:pic><p:nvPicPr><p:cNvPr id="42" name="Picture 1"/></p:nvPicPr></p:pic>
  </p:spTree></p:cSld>
</p:sld>"#;
    let slide2 = r#"<?xml version="1.0"?>
<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
       xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
  <p:cSld><p:spTree>
    <p:sp><p:txBody><a:p><a:r><a:t>Second</a:t></a:r></a:p></p:txBody></p:sp>
  </p:spTree></p:cSld>
</p:sld>"#;
    let bytes = zip_of(&[
        ("ppt/slides/slide1.xml", slide1),
        ("ppt/slides/slide2.xml", slide2),
    ]);
    let doc = run(&bytes, SourceType::Pptx);
    assert_eq!(doc.structure_type, StructureType::SlideSequence);
    assert_eq!(doc.blocks.len(), 2);
    assert_eq!(doc.blocks[0].kind, BlockKind::Slide);
    assert_eq!(doc.blocks[0].text, "Hello\nWorld");
    assert_eq!(doc.blocks[0].page, Some(1));
    assert_eq!(doc.blocks[1].text, "Second");
    assert_eq!(doc.images.len(), 1);
    assert_eq!(doc.images[0].image_id, "slide1-42");
}

// -------------------------------------------------------------- dispatch ----

#[test]
fn unknown_extension_falls_back_to_plain() {
    assert_eq!(source_type_for_extension(".xyz"), SourceType::Plain);
    assert_eq!(source_type_for_extension("md"), SourceType::Md);
    let doc = run(b"just text", SourceType::Plain);
    assert_eq!(doc.source_type, SourceType::Plain);
    assert_eq!(doc.blocks[0].text, "just text");
}

// ------------------------------------------------------------------ json ----

#[test]
fn json_shape_matches_python_field_names() {
    let doc = run(b"hello", SourceType::Txt);
    let json = serde_json::to_value(&doc).unwrap();
    assert_eq!(json["source_type"], "txt");
    assert_eq!(json["structure_type"], "none");
    assert_eq!(json["blocks"][0]["kind"], "paragraph");
    assert!(json["blocks"][0]["page"].is_null());
    assert_eq!(json["blocks"][0]["order"], 0);
}
