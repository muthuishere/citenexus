//! ADR-0017 decision 8: DOCX/PPTX → `DocUnit`s from their own OOXML
//! structure, deterministically, no model. Every fixture here is synthetic —
//! built by hand as a zip in the test.

use std::io::Write;

use citenexus_core::ooxml_units;
use citenexus_core::types::SourceType;
use citenexus_core::units::*;

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

const W: &str = r#"xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships""#;

fn document(body: &str) -> String {
    format!(
        r#"<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {W}><w:body>{body}</w:body></w:document>"#
    )
}

fn para(style: Option<&str>, text: &str) -> String {
    let ppr = style
        .map(|s| format!(r#"<w:pPr><w:pStyle w:val="{s}"/></w:pPr>"#))
        .unwrap_or_default();
    format!(r#"<w:p>{ppr}<w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>"#)
}

fn docx(body: &str) -> Vec<u8> {
    zip_of(&[("word/document.xml", &document(body))])
}

fn units(bytes: &[u8], hint: SourceType) -> Vec<DocUnit> {
    ooxml_units(bytes, hint).expect("ooxml_units failed")
}

fn kinds(us: &[DocUnit]) -> Vec<UnitKind> {
    us.iter().map(|u| u.kind).collect()
}

// ------------------------------------------------------------ tables ----

fn tc(props: &str, text: &str) -> String {
    let body = if text.is_empty() {
        "<w:p/>".to_string()
    } else {
        format!("<w:p><w:r><w:t>{text}</w:t></w:r></w:p>")
    };
    format!("<w:tc><w:tcPr>{props}</w:tcPr>{body}</w:tc>")
}

/// Conformance vector (consumer ask): a DOCX table with BOTH a horizontal
/// merge (`w:gridSpan`) and a vertical merge (`w:vMerge` restart/continue),
/// a `w:tblHeader` row and an all-blank row that must not be emitted.
#[test]
fn docx_table_with_grid_span_and_vmerge() {
    let body = format!(
        r#"<w:tbl><w:tblGrid><w:gridCol/><w:gridCol/><w:gridCol/></w:tblGrid>
<w:tr><w:trPr><w:tblHeader/></w:trPr>{}{}</w:tr>
<w:tr>{}{}{}</w:tr>
<w:tr>{}{}{}</w:tr>
<w:tr>{}{}{}</w:tr>
</w:tbl>"#,
        tc("", "Name"),
        tc(r#"<w:gridSpan w:val="2"/>"#, "Period"),
        tc(r#"<w:vMerge w:val="restart"/>"#, "Alpha"),
        tc("", "Q1"),
        tc("", "7.000,00"),
        tc("<w:vMerge/>", ""),
        tc("", "Q2"),
        tc("", "5.100,00"),
        tc("", ""),
        tc("", ""),
        tc("", ""),
    );
    let us = units(&docx(&body), SourceType::Docx);
    assert_eq!(us.len(), 1, "{us:#?}");
    let t = &us[0];
    assert_eq!(t.kind, UnitKind::Table);
    assert_eq!(
        t.markdown,
        "| Name | Period |  |\n| --- | --- | --- |\n| Alpha | Q1 | 7.000,00 |\n|  | Q2 | 5.100,00 |"
    );
    assert_eq!(t.provenance.route, Route::Ooxml);
    assert_eq!(t.provenance.table_source, Some(TableSource::Ooxml));
    // merged cells render once at their anchor; continuations are empty and
    // the table says so.
    assert!(t.provenance.table_uncertain);
    assert_eq!(t.page, None);
    assert_eq!(t.level, None);
}

#[test]
fn docx_plain_table_is_not_uncertain_and_escapes_pipes() {
    let body = format!(
        "<w:tbl><w:tblGrid><w:gridCol/><w:gridCol/></w:tblGrid><w:tr>{}{}</w:tr><w:tr>{}{}</w:tr></w:tbl>",
        tc("", "k"),
        tc("", "v"),
        tc("", "a|b"),
        tc("", "1"),
    );
    let us = units(&docx(&body), SourceType::Docx);
    assert_eq!(us[0].markdown, "| k | v |\n| --- | --- |\n| a\\|b | 1 |");
    assert!(!us[0].provenance.table_uncertain);
}

#[test]
fn docx_nested_table_is_emitted_after_its_parent_with_provenance() {
    let inner = format!(
        "<w:tbl><w:tblGrid><w:gridCol/><w:gridCol/></w:tblGrid><w:tr>{}{}</w:tr><w:tr>{}{}</w:tr></w:tbl>",
        tc("", "x"),
        tc("", "y"),
        tc("", "1"),
        tc("", "2"),
    );
    let body = format!(
        "<w:tbl><w:tblGrid><w:gridCol/><w:gridCol/></w:tblGrid><w:tr>{}{}</w:tr><w:tr><w:tc><w:p><w:r><w:t>see</w:t></w:r></w:p>{inner}</w:tc>{}</w:tr></w:tbl>{}",
        tc("", "A"),
        tc("", "B"),
        tc("", "b2"),
        para(None, "After."),
    );
    let us = units(&docx(&body), SourceType::Docx);
    assert_eq!(
        kinds(&us),
        vec![UnitKind::Table, UnitKind::Table, UnitKind::Paragraph]
    );
    assert_eq!(us[0].markdown, "| A | B |\n| --- | --- |\n| see | b2 |");
    assert!(us[0].provenance.table_uncertain);
    assert_eq!(us[1].markdown, "| x | y |\n| --- | --- |\n| 1 | 2 |");
    assert_eq!(
        us[1].provenance.failed_check.as_deref(),
        Some("nested_table")
    );
    assert!(us[1].provenance.table_uncertain);
}

#[test]
fn docx_single_cell_table_becomes_a_paragraph() {
    let body = format!(
        "<w:tbl><w:tblGrid><w:gridCol/></w:tblGrid><w:tr>{}</w:tr></w:tbl>",
        tc("", "Boxed note.")
    );
    let us = units(&docx(&body), SourceType::Docx);
    assert_eq!(kinds(&us), vec![UnitKind::Paragraph]);
    assert_eq!(us[0].markdown, "Boxed note.");
}

// ----------------------------------------------------------- headings ----

const STYLES: &str = r#"<?xml version="1.0" encoding="UTF-8"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:style w:type="paragraph" w:default="1" w:styleId="Standaard"><w:name w:val="Normal"/></w:style>
  <w:style w:type="paragraph" w:styleId="Titel"><w:name w:val="Title"/><w:basedOn w:val="Standaard"/></w:style>
  <w:style w:type="paragraph" w:styleId="Kop1"><w:name w:val="heading 1"/><w:basedOn w:val="Standaard"/><w:pPr><w:outlineLvl w:val="0"/></w:pPr></w:style>
  <w:style w:type="paragraph" w:styleId="Kop2"><w:name w:val="heading 2"/><w:basedOn w:val="Standaard"/><w:pPr><w:outlineLvl w:val="1"/></w:pPr></w:style>
  <w:style w:type="paragraph" w:styleId="Kop3"><w:name w:val="heading 3"/><w:basedOn w:val="Standaard"/><w:pPr><w:outlineLvl w:val="2"/></w:pPr></w:style>
  <w:style w:type="paragraph" w:styleId="ArtikelKop"><w:name w:val="Artikel kop"/><w:basedOn w:val="Kop3"/></w:style>
  <w:style w:type="paragraph" w:styleId="Kopvaninhoudsopgave"><w:name w:val="TOC Heading"/><w:basedOn w:val="Kop1"/><w:pPr><w:outlineLvl w:val="9"/></w:pPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="Not a heading"/></w:style>
</w:styles>"#;

/// Conformance vector (consumer ask): a heading hierarchy H1 > H2 > H3 with
/// localized style ids (Dutch `Kop1`…), a custom style that inherits its level
/// through `basedOn`, and a style whose outline level 9 means body text.
#[test]
fn docx_heading_hierarchy_resolves_through_styles_xml() {
    let body = [
        para(Some("Titel"), "Huurovereenkomst"),
        para(Some("Kop1"), "Algemeen"),
        para(Some("Kop2"), "Definities"),
        para(Some("Kop3"), "Huurprijs"),
        para(Some("ArtikelKop"), "Artikel 4"),
        para(Some("Kopvaninhoudsopgave"), "Inhoud"),
        para(Some("Heading2"), "Styled by id only"),
        para(None, "Body text."),
    ]
    .concat();
    let bytes = zip_of(&[
        ("word/document.xml", &document(&body)),
        ("word/styles.xml", STYLES),
    ]);
    let us = units(&bytes, SourceType::Docx);
    let got: Vec<(UnitKind, Option<u32>, &str)> = us
        .iter()
        .map(|u| (u.kind, u.level, u.markdown.as_str()))
        .collect();
    assert_eq!(
        got,
        vec![
            (UnitKind::Heading, Some(1), "# Huurovereenkomst"),
            (UnitKind::Heading, Some(1), "# Algemeen"),
            (UnitKind::Heading, Some(2), "## Definities"),
            (UnitKind::Heading, Some(3), "### Huurprijs"),
            (UnitKind::Heading, Some(3), "### Artikel 4"),
            (UnitKind::Paragraph, None, "Inhoud"),
            // the style id says Heading2 but styles.xml says it is not one
            (UnitKind::Paragraph, None, "Styled by id only"),
            (UnitKind::Paragraph, None, "Body text."),
        ]
    );
    for u in us.iter().filter(|u| u.kind == UnitKind::Heading) {
        assert_eq!(u.provenance.heading_source, Some(HeadingSource::Style));
        assert_eq!(u.provenance.route, Route::Ooxml);
    }
    assert!(us
        .iter()
        .filter(|u| u.kind != UnitKind::Heading)
        .all(|u| u.provenance.heading_source.is_none()));
}

#[test]
fn docx_heading_style_id_fallback_without_styles_xml() {
    let body = [para(Some("Heading2"), "Two"), para(Some("Title"), "T")].concat();
    let us = units(&docx(&body), SourceType::Docx);
    assert_eq!(us[0].markdown, "## Two");
    assert_eq!(us[0].level, Some(2));
    assert_eq!(us[1].markdown, "# T");
}

#[test]
fn docx_direct_outline_level_makes_a_heading() {
    let body = r#"<w:p><w:pPr><w:outlineLvl w:val="1"/></w:pPr><w:r><w:t>Direct</w:t></w:r></w:p>"#;
    let us = units(&docx(body), SourceType::Docx);
    assert_eq!(us[0].markdown, "## Direct");
}

// -------------------------------------------------------------- lists ----

const NUMBERING: &str = r#"<?xml version="1.0" encoding="UTF-8"?>
<w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:abstractNum w:abstractNumId="10">
    <w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/></w:lvl>
    <w:lvl w:ilvl="1"><w:numFmt w:val="bullet"/></w:lvl>
    <w:lvl w:ilvl="2"><w:start w:val="1"/><w:numFmt w:val="lowerLetter"/></w:lvl>
  </w:abstractNum>
  <w:abstractNum w:abstractNumId="20">
    <w:lvl w:ilvl="0"><w:numFmt w:val="bullet"/></w:lvl>
  </w:abstractNum>
  <w:num w:numId="1"><w:abstractNumId w:val="10"/></w:num>
  <w:num w:numId="2"><w:abstractNumId w:val="20"/></w:num>
  <w:num w:numId="3"><w:abstractNumId w:val="10"/><w:lvlOverride w:ilvl="0"><w:startOverride w:val="5"/></w:lvlOverride></w:num>
</w:numbering>"#;

fn item(num: &str, ilvl: u32, text: &str) -> String {
    format!(
        r#"<w:p><w:pPr><w:numPr><w:ilvl w:val="{ilvl}"/><w:numId w:val="{num}"/></w:numPr></w:pPr><w:r><w:t>{text}</w:t></w:r></w:p>"#
    )
}

#[test]
fn docx_numbered_and_nested_lists_from_numbering_xml() {
    let styles = r#"<?xml version="1.0"?><w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:style w:type="paragraph" w:styleId="Lijstopsommingsteken"><w:name w:val="List Bullet"/><w:pPr><w:numPr><w:numId w:val="2"/></w:numPr></w:pPr></w:style>
    </w:styles>"#;
    let body = [
        item("1", 0, "One"),
        item("1", 1, "Sub a"),
        item("1", 2, "Deep i"),
        item("1", 1, "Sub b"),
        item("1", 0, "Two"),
        para(None, "Between."),
        item("2", 0, "Bullet"),
        para(Some("Lijstopsommingsteken"), "Via style"),
        para(None, "Gap."),
        item("3", 0, "Five"),
        item("3", 0, "Six"),
        item("0", 0, "numId 0 is not a list"),
    ]
    .concat();
    let bytes = zip_of(&[
        ("word/document.xml", &document(&body)),
        ("word/numbering.xml", NUMBERING),
        ("word/styles.xml", styles),
    ]);
    let us = units(&bytes, SourceType::Docx);
    let got: Vec<(UnitKind, &str)> = us.iter().map(|u| (u.kind, u.markdown.as_str())).collect();
    assert_eq!(
        got,
        vec![
            // lowerLetter renders its real label, never "1."
            (
                UnitKind::List,
                "1. One\n   - Sub a\n     - a. Deep i\n   - Sub b\n2. Two"
            ),
            (UnitKind::Paragraph, "Between."),
            (UnitKind::List, "- Bullet\n- Via style"),
            (UnitKind::Paragraph, "Gap."),
            (UnitKind::List, "5. Five\n6. Six"),
            (UnitKind::Paragraph, "numId 0 is not a list"),
        ]
    );
}

// ------------------------------------------------- headers / footers ----

#[test]
fn docx_headers_and_footers_are_furniture_kept_once() {
    let rels = r#"<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rId9" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>
      <Relationship Id="rId8" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header2.xml"/>
      <Relationship Id="rId7" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/>
    </Relationships>"#;
    let hdr = |t: &str| {
        format!(
            r#"<?xml version="1.0"?><w:hdr {W}><w:p><w:r><w:t>{t}</w:t></w:r></w:p><w:p/></w:hdr>"#
        )
    };
    let ftr = format!(
        r#"<?xml version="1.0"?><w:ftr {W}><w:p><w:r><w:t>Laatst bijgewerkt 1 januari 2026</w:t></w:r></w:p></w:ftr>"#
    );
    let body = [para(None, "Body.")].concat();
    let bytes = zip_of(&[
        ("word/document.xml", &document(&body)),
        ("word/_rels/document.xml.rels", rels),
        ("word/header1.xml", &hdr("Vertrouwelijk")),
        ("word/header2.xml", &hdr("Vertrouwelijk")),
        ("word/footer1.xml", &ftr),
    ]);
    let us = units(&bytes, SourceType::Docx);
    let got: Vec<(UnitKind, &str)> = us.iter().map(|u| (u.kind, u.markdown.as_str())).collect();
    assert_eq!(
        got,
        vec![
            (UnitKind::Furniture, "Vertrouwelijk"),
            (UnitKind::Paragraph, "Body."),
            (UnitKind::Furniture, "Laatst bijgewerkt 1 januari 2026"),
        ]
    );
}

// -------------------------------------------------------- hyphenation ----

#[test]
fn docx_soft_hyphens_vanish_real_compounds_survive() {
    let body = r#"
<w:p><w:r><w:t>Ver&#xAD;zekering</w:t></w:r></w:p>
<w:p><w:r><w:t>Arbeids</w:t></w:r><w:r><w:softHyphen/></w:r><w:r><w:t>overeenkomst</w:t></w:r></w:p>
<w:p><w:r><w:t>e</w:t></w:r><w:r><w:noBreakHyphen/></w:r><w:r><w:t>mail</w:t></w:r></w:p>
<w:p><w:r><w:t>long-term in- en verkoop</w:t></w:r></w:p>
<w:p><w:r><w:t>Huur &amp; service &lt;incl.&gt;</w:t></w:r></w:p>
<w:p><w:r><w:t>kept</w:t></w:r><w:r><w:delText>deleted</w:delText></w:r><w:r><w:instrText> PAGE </w:instrText></w:r></w:p>"#;
    let us = units(&docx(body), SourceType::Docx);
    let got: Vec<&str> = us.iter().map(|u| u.markdown.as_str()).collect();
    assert_eq!(
        got,
        vec![
            "Verzekering",
            "Arbeidsovereenkomst",
            "e-mail",
            "long-term in- en verkoop",
            "Huur & service <incl.>",
            "kept",
        ]
    );
}

#[test]
fn docx_reading_order_is_document_order_and_sdt_is_unwrapped() {
    let table = format!(
        "<w:tbl><w:tblGrid><w:gridCol/><w:gridCol/></w:tblGrid><w:tr>{}{}</w:tr><w:tr>{}{}</w:tr></w:tbl>",
        tc("", "a"),
        tc("", "b"),
        tc("", "1"),
        tc("", "2"),
    );
    let body = format!(
        "{}{table}<w:sdt><w:sdtContent>{}</w:sdtContent></w:sdt>{}",
        para(Some("Heading1"), "H"),
        para(None, "In a content control."),
        para(None, "Last."),
    );
    let us = units(&docx(&body), SourceType::Docx);
    assert_eq!(
        kinds(&us),
        vec![
            UnitKind::Heading,
            UnitKind::Table,
            UnitKind::Paragraph,
            UnitKind::Paragraph
        ]
    );
    assert_eq!(us[2].markdown, "In a content control.");
}

// --------------------------------------------------------------- pptx ----

const P: &str = r#"xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships""#;

fn slide(tree: &str) -> String {
    format!(
        r#"<?xml version="1.0"?><p:sld {P}><p:cSld><p:spTree>{tree}</p:spTree></p:cSld></p:sld>"#
    )
}

fn title_shape(ph: &str, text: &str) -> String {
    format!(
        r#"<p:sp><p:nvSpPr><p:cNvPr id="2" name="Title"/><p:cNvSpPr/><p:nvPr><p:ph type="{ph}"/></p:nvPr></p:nvSpPr><p:spPr><a:xfrm><a:off x="12700" y="25400"/><a:ext cx="1270000" cy="127000"/></a:xfrm></p:spPr><p:txBody><a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:txBody></p:sp>"#
    )
}

fn atc(attrs: &str, text: &str) -> String {
    format!(r#"<a:tc {attrs}><a:txBody><a:p><a:r><a:t>{text}</a:t></a:r></a:p></a:txBody></a:tc>"#)
}

fn pptx_fixture() -> Vec<u8> {
    let table = format!(
        r#"<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="4" name="Table"/></p:nvGraphicFramePr><p:xfrm><a:off x="127000" y="254000"/><a:ext cx="2540000" cy="1270000"/></p:xfrm><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/table"><a:tbl><a:tblPr firstRow="1"/><a:tblGrid><a:gridCol w="1"/><a:gridCol w="1"/><a:gridCol w="1"/></a:tblGrid>
<a:tr h="1">{}{}{}</a:tr>
<a:tr h="1">{}{}{}</a:tr>
<a:tr h="1">{}{}{}</a:tr>
<a:tr h="1">{}{}{}</a:tr>
</a:tbl></a:graphicData></a:graphic></p:graphicFrame>"#,
        atc("", "Item"),
        atc(r#"gridSpan="2""#, "Amount"),
        atc(r#"hMerge="1""#, ""),
        atc(r#"rowSpan="2""#, "Rent"),
        atc("", "Jan"),
        atc("", "1.200"),
        atc(r#"vMerge="1""#, ""),
        atc("", "Feb"),
        atc("", "1.250"),
        atc("", ""),
        atc("", ""),
        atc("", ""),
    );
    let body = r#"<p:sp><p:nvSpPr><p:cNvPr id="3" name="Body"/><p:cNvSpPr/><p:nvPr><p:ph idx="1"/></p:nvPr></p:nvSpPr><p:spPr/><p:txBody>
<a:p><a:pPr><a:buAutoNum type="arabicPeriod"/></a:pPr><a:r><a:t>First</a:t></a:r></a:p>
<a:p><a:pPr lvl="1"><a:buChar char="•"/></a:pPr><a:r><a:t>Nested</a:t></a:r></a:p>
<a:p><a:pPr><a:buAutoNum type="arabicPeriod"/></a:pPr><a:r><a:t>Second</a:t></a:r></a:p>
<a:p><a:pPr><a:buNone/></a:pPr><a:r><a:t>Plain line</a:t></a:r></a:p>
</p:txBody></p:sp>"#;
    let grouped = r#"<p:grpSp><p:nvGrpSpPr><p:cNvPr id="9" name="G"/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="1270000" y="1270000"/><a:ext cx="254000" cy="254000"/><a:chOff x="0" y="0"/><a:chExt cx="127000" cy="127000"/></a:xfrm></p:grpSpPr>
<p:sp><p:nvSpPr><p:cNvPr id="10" name="Note"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr><a:xfrm><a:off x="12700" y="12700"/><a:ext cx="12700" cy="12700"/></a:xfrm></p:spPr><p:txBody><a:p><a:r><a:t>Grouped note</a:t></a:r></a:p></p:txBody></p:sp>
</p:grpSp>
<p:sp><p:nvSpPr><p:cNvPr id="11" name="Footer"/><p:cNvSpPr/><p:nvPr><p:ph type="ftr"/></p:nvPr></p:nvSpPr><p:spPr/><p:txBody><a:p><a:r><a:t>Vertrouwelijk</a:t></a:r></a:p></p:txBody></p:sp>
<p:sp><p:nvSpPr><p:cNvPr id="12" name="Num"/><p:cNvSpPr/><p:nvPr><p:ph type="sldNum"/></p:nvPr></p:nvSpPr><p:spPr/><p:txBody><a:p><a:fld type="slidenum"><a:t>1</a:t></a:fld></a:p></p:txBody></p:sp>"#;
    // File names are deliberately out of deck order: the deck order lives in
    // presentation.xml's sldIdLst, not in the slide file numbers.
    let first = slide(&format!(
        "{}{table}{grouped}",
        title_shape("ctrTitle", "Deck")
    ));
    let second = slide(&format!(
        "{}{body}<p:sp><p:nvSpPr><p:cNvPr id=\"11\" name=\"Footer\"/><p:cNvSpPr/><p:nvPr><p:ph type=\"ftr\"/></p:nvPr></p:nvSpPr><p:spPr/><p:txBody><a:p><a:r><a:t>Vertrouwelijk</a:t></a:r></a:p></p:txBody></p:sp>",
        title_shape("title", "Agenda")
    ));
    let pres = format!(
        r#"<?xml version="1.0"?><p:presentation {P}><p:sldIdLst><p:sldId id="256" r:id="rId3"/><p:sldId id="257" r:id="rId2"/></p:sldIdLst></p:presentation>"#
    );
    let rels = r#"<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide1.xml"/>
      <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="/ppt/slides/slide2.xml"/>
    </Relationships>"#;
    zip_of(&[
        ("ppt/presentation.xml", &pres),
        ("ppt/_rels/presentation.xml.rels", rels),
        ("ppt/slides/slide1.xml", &second),
        ("ppt/slides/slide2.xml", &first),
    ])
}

#[test]
fn pptx_titles_tables_lists_in_slide_then_shape_order() {
    let us = units(&pptx_fixture(), SourceType::Pptx);
    let got: Vec<(Option<u32>, UnitKind, &str)> = us
        .iter()
        .map(|u| (u.page, u.kind, u.markdown.as_str()))
        .collect();
    assert_eq!(
        got,
        vec![
            (Some(1), UnitKind::Heading, "# Deck"),
            (
                Some(1),
                UnitKind::Table,
                "| Item | Amount |  |\n| --- | --- | --- |\n| Rent | Jan | 1.200 |\n|  | Feb | 1.250 |"
            ),
            (Some(1), UnitKind::Paragraph, "Grouped note"),
            (Some(1), UnitKind::Furniture, "Vertrouwelijk"),
            (Some(2), UnitKind::Heading, "# Agenda"),
            (Some(2), UnitKind::List, "1. First\n   - Nested\n2. Second"),
            (Some(2), UnitKind::Paragraph, "Plain line"),
        ]
    );
    let heading = &us[0];
    assert_eq!(heading.level, Some(1));
    assert_eq!(
        heading.provenance.heading_source,
        Some(HeadingSource::Style)
    );
    // EMU / 12700 = points; top-left origin like the slide itself.
    assert_eq!(heading.bbox, Some([1.0, 2.0, 101.0, 12.0]));
    let table = &us[1];
    assert_eq!(table.provenance.table_source, Some(TableSource::Ooxml));
    assert!(table.provenance.table_uncertain);
    assert_eq!(table.bbox, Some([10.0, 20.0, 210.0, 120.0]));
    // group transform: child space 0..10pt maps onto 100..120pt (scale 2).
    assert_eq!(us[2].bbox, Some([102.0, 102.0, 104.0, 104.0]));
    assert!(us.iter().all(|u| u.provenance.route == Route::Ooxml));
}

#[test]
fn pptx_falls_back_to_file_order_without_presentation_xml() {
    let bytes = zip_of(&[
        (
            "ppt/slides/slide10.xml",
            &slide(&title_shape("title", "Ten")),
        ),
        (
            "ppt/slides/slide2.xml",
            &slide(&title_shape("title", "Two")),
        ),
    ]);
    let us = units(&bytes, SourceType::Pptx);
    let got: Vec<(Option<u32>, &str)> = us.iter().map(|u| (u.page, u.markdown.as_str())).collect();
    assert_eq!(got, vec![(Some(1), "# Two"), (Some(2), "# Ten")]);
}

// ------------------------------------------------------- list labels ----
//
// A list label is a citation anchor ("artikel 3 lid b", "sub ii"): it must be
// the document's own label, never a renumbered "1.". Pure-decimal labels use
// markdown's own ordered marker; every other label is literal text after a
// "- " marker (escaped so it stays literal), keeping the nesting.

fn numbering_doc(numbering: &str, body: &str, styles: Option<&str>) -> Vec<u8> {
    let numbering = format!(
        r#"<?xml version="1.0"?><w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">{numbering}</w:numbering>"#
    );
    let doc = document(body);
    let mut entries = vec![
        ("word/document.xml", doc.as_str()),
        ("word/numbering.xml", numbering.as_str()),
    ];
    if let Some(st) = styles {
        entries.push(("word/styles.xml", st));
    }
    zip_of(&entries)
}

fn lvl(ilvl: u32, fmt: &str, text: &str, extra: &str) -> String {
    format!(
        r#"<w:lvl w:ilvl="{ilvl}"><w:start w:val="1"/><w:numFmt w:val="{fmt}"/><w:lvlText w:val="{text}"/>{extra}</w:lvl>"#
    )
}

fn list_md(bytes: &[u8]) -> Vec<(UnitKind, String)> {
    units(bytes, SourceType::Docx)
        .into_iter()
        .map(|u| (u.kind, u.markdown))
        .collect()
}

#[test]
fn docx_lower_letter_upper_roman_and_parenthesised_lower_roman() {
    let numbering = format!(
        r#"<w:abstractNum w:abstractNumId="1">{}</w:abstractNum>
<w:abstractNum w:abstractNumId="2"><w:lvl w:ilvl="0"><w:start w:val="3"/><w:numFmt w:val="upperRoman"/><w:lvlText w:val="%1."/></w:lvl></w:abstractNum>
<w:abstractNum w:abstractNumId="3">{}</w:abstractNum>
<w:num w:numId="1"><w:abstractNumId w:val="1"/></w:num>
<w:num w:numId="2"><w:abstractNumId w:val="2"/></w:num>
<w:num w:numId="3"><w:abstractNumId w:val="3"/></w:num>"#,
        lvl(0, "lowerLetter", "%1.", ""),
        lvl(0, "lowerRoman", "(%1)", ""),
    );
    let body = [
        item("1", 0, "eerste"),
        item("1", 0, "tweede"),
        para(None, "-"),
        item("2", 0, "three"),
        item("2", 0, "four"),
        para(None, "-"),
        item("3", 0, "one"),
        item("3", 0, "two"),
        item("3", 0, "three"),
        item("3", 0, "four"),
    ]
    .concat();
    let got = list_md(&numbering_doc(&numbering, &body, None));
    let lists: Vec<&str> = got
        .iter()
        .filter(|(k, _)| *k == UnitKind::List)
        .map(|(_, m)| m.as_str())
        .collect();
    assert_eq!(
        lists,
        vec![
            "- a. eerste\n- b. tweede",
            "- III. three\n- IV. four",
            "- (i) one\n- (ii) two\n- (iii) three\n- (iv) four",
        ]
    );
}

#[test]
fn docx_multi_level_label_2_b() {
    let numbering = format!(
        r#"<w:abstractNum w:abstractNumId="1">{}{}</w:abstractNum><w:num w:numId="1"><w:abstractNumId w:val="1"/></w:num>"#,
        lvl(0, "decimal", "%1.", ""),
        lvl(1, "lowerLetter", "%1.%2", ""),
    );
    let body = [
        item("1", 0, "A"),
        item("1", 1, "B"),
        item("1", 1, "C"),
        item("1", 0, "D"),
        item("1", 1, "E"),
    ]
    .concat();
    let got = list_md(&numbering_doc(&numbering, &body, None));
    assert_eq!(
        got,
        vec![(
            UnitKind::List,
            "1. A\n   - 1.a B\n   - 1.b C\n2. D\n   - 2.a E".to_string()
        )]
    );
}

#[test]
fn docx_numbered_heading_restarts_its_sub_levels() {
    // "Artikel %1" numbers the heading itself; its sub-level restarts after
    // every heading, except a level with lvlRestart=0 which never restarts.
    let numbering = format!(
        r#"<w:abstractNum w:abstractNumId="1">{}{}{}</w:abstractNum><w:num w:numId="5"><w:abstractNumId w:val="1"/></w:num>"#,
        lvl(0, "decimal", "Artikel %1", ""),
        lvl(1, "lowerLetter", "%2.", ""),
        lvl(2, "decimal", "[%3]", r#"<w:lvlRestart w:val="0"/>"#),
    );
    let heading = |t: &str| {
        format!(
            r#"<w:p><w:pPr><w:pStyle w:val="Heading1"/><w:numPr><w:ilvl w:val="0"/><w:numId w:val="5"/></w:numPr></w:pPr><w:r><w:t>{t}</w:t></w:r></w:p>"#
        )
    };
    let body = [
        heading("Scope"),
        item("5", 1, "x"),
        item("5", 1, "y"),
        item("5", 2, "note"),
        heading("Rent"),
        item("5", 1, "z"),
        item("5", 2, "note2"),
    ]
    .concat();
    let got = list_md(&numbering_doc(&numbering, &body, None));
    assert_eq!(
        got,
        vec![
            (UnitKind::Heading, "# Artikel 1 Scope".to_string()),
            (
                UnitKind::List,
                "- a. x\n- b. y\n  - \\[1\\] note".to_string()
            ),
            (UnitKind::Heading, "# Artikel 2 Rent".to_string()),
            (UnitKind::List, "- a. z\n  - \\[2\\] note2".to_string()),
        ]
    );
}

#[test]
fn docx_start_override_restarts_and_shared_abstract_continues() {
    let numbering = format!(
        r#"<w:abstractNum w:abstractNumId="1">{}</w:abstractNum>
<w:num w:numId="1"><w:abstractNumId w:val="1"/></w:num>
<w:num w:numId="2"><w:abstractNumId w:val="1"/></w:num>
<w:num w:numId="3"><w:abstractNumId w:val="1"/><w:lvlOverride w:ilvl="0"><w:startOverride w:val="4"/></w:lvlOverride></w:num>"#,
        lvl(0, "lowerLetter", "%1)", ""),
    );
    let body = [
        item("1", 0, "p"),
        item("1", 0, "q"),
        para(None, "-"),
        // a second num on the same abstract continues the sequence (Word)
        item("2", 0, "r"),
        para(None, "-"),
        // startOverride restarts it at d
        item("3", 0, "s"),
        item("3", 0, "t"),
    ]
    .concat();
    let lists: Vec<String> = list_md(&numbering_doc(&numbering, &body, None))
        .into_iter()
        .filter(|(k, _)| *k == UnitKind::List)
        .map(|(_, m)| m)
        .collect();
    assert_eq!(lists, vec!["- a) p\n- b) q", "- c) r", "- d) s\n- e) t"]);
}

#[test]
fn docx_unknown_number_format_is_decimal_and_marked() {
    let numbering = format!(
        r#"<w:abstractNum w:abstractNumId="1">{}</w:abstractNum><w:num w:numId="1"><w:abstractNumId w:val="1"/></w:num>"#,
        lvl(0, "chineseCounting", "%1.", ""),
    );
    let body = [item("1", 0, "x"), item("1", 0, "y")].concat();
    let us = units(&numbering_doc(&numbering, &body, None), SourceType::Docx);
    assert_eq!(us.len(), 1);
    assert_eq!(us[0].markdown, "1. x\n2. y");
    assert_eq!(
        us[0].provenance.failed_check.as_deref(),
        Some("list_label_unknown_format")
    );
}

#[test]
fn docx_known_formats_are_not_marked() {
    let numbering = format!(
        r#"<w:abstractNum w:abstractNumId="1">{}</w:abstractNum><w:num w:numId="1"><w:abstractNumId w:val="1"/></w:num>"#,
        lvl(0, "decimalZero", "%1.", ""),
    );
    let us = units(
        &numbering_doc(&numbering, &item("1", 0, "x"), None),
        SourceType::Docx,
    );
    assert_eq!(us[0].markdown, "01. x");
    assert_eq!(us[0].provenance.failed_check, None);
}

#[test]
fn pptx_auto_number_schemes_render_real_labels() {
    let para = |ty: &str, lvl: u32, text: &str| {
        format!(
            r#"<a:p><a:pPr lvl="{lvl}"><a:buAutoNum type="{ty}"/></a:pPr><a:r><a:t>{text}</a:t></a:r></a:p>"#
        )
    };
    let shape = |paras: &str| {
        format!(
            r#"<p:sp><p:nvSpPr><p:cNvPr id="3" name="Body"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr/><p:txBody>{paras}</p:txBody></p:sp>"#
        )
    };
    let tree = [
        shape(
            &[
                para("alphaLcPeriod", 0, "a1"),
                para("alphaLcPeriod", 0, "a2"),
            ]
            .concat(),
        ),
        shape(
            &[
                para("romanUcPeriod", 0, "r1"),
                para("romanUcPeriod", 0, "r2"),
            ]
            .concat(),
        ),
        shape(
            &[
                para("arabicParenR", 0, "n1"),
                para("alphaLcParenBoth", 1, "sub"),
            ]
            .concat(),
        ),
        shape(&para("circleNumDbPlain", 0, "odd")),
    ]
    .concat();
    let bytes = zip_of(&[("ppt/slides/slide1.xml", &slide(&tree))]);
    let us = units(&bytes, SourceType::Pptx);
    let got: Vec<(&str, Option<&str>)> = us
        .iter()
        .map(|u| (u.markdown.as_str(), u.provenance.failed_check.as_deref()))
        .collect();
    assert_eq!(
        got,
        vec![
            ("- a. a1\n- b. a2", None),
            ("- I. r1\n- II. r2", None),
            ("1) n1\n   - (a) sub", None),
            ("1. odd", Some("list_label_unknown_format")),
        ]
    );
}

// -------------------------------------------------- errors / dispatch ----

#[test]
fn rejects_non_zip_and_non_ooxml_hints() {
    assert!(ooxml_units(b"not a zip", SourceType::Docx).is_err());
    assert!(ooxml_units(&docx(&para(None, "x")), SourceType::Pdf).is_err());
    // a wrong-but-OOXML hint is corrected by the package's own parts
    let us = units(&docx(&para(None, "x")), SourceType::Pptx);
    assert_eq!(us[0].markdown, "x");
}

// -------------------------------------------------------- determinism ----

#[test]
fn byte_identical_output_across_runs() {
    let body = [
        para(Some("Heading1"), "H"),
        item("1", 0, "One"),
        para(None, "P"),
    ]
    .concat();
    let d = zip_of(&[
        ("word/document.xml", &document(&body)),
        ("word/numbering.xml", NUMBERING),
        ("word/styles.xml", STYLES),
    ]);
    for (bytes, hint) in [(d, SourceType::Docx), (pptx_fixture(), SourceType::Pptx)] {
        let a = serde_json::to_string(&units(&bytes, hint)).unwrap();
        let b = serde_json::to_string(&units(&bytes, hint)).unwrap();
        assert_eq!(a.as_bytes(), b.as_bytes());
    }
}

// ---------------------------------------------------------------- ffi ----

#[test]
fn ffi_ooxml_units_returns_a_json_array() {
    use citenexus_core::ffi::{citenexus_free_string, citenexus_ooxml_units};
    use std::ffi::{CStr, CString};
    let bytes = docx(&para(Some("Heading1"), "Hello"));
    let st = CString::new("docx").unwrap();
    let out = unsafe {
        let ptr = citenexus_ooxml_units(bytes.as_ptr(), bytes.len(), st.as_ptr());
        let s = CStr::from_ptr(ptr).to_str().unwrap().to_string();
        citenexus_free_string(ptr);
        s
    };
    assert_eq!(
        out,
        r##"[{"page":null,"bbox":null,"kind":"heading","level":1,"markdown":"# Hello","provenance":{"route":"ooxml","table_source":null,"vision_transcribed":false,"table_uncertain":false,"failed_check":null,"heading_source":"style","joined_hyphen":false,"vision_disputed":false,"header_flattened":false,"model_verdict":null}}]"##
    );
    let bad = CString::new("xlsx").unwrap();
    let err = unsafe {
        let ptr = citenexus_ooxml_units(bytes.as_ptr(), bytes.len(), bad.as_ptr());
        let s = CStr::from_ptr(ptr).to_str().unwrap().to_string();
        citenexus_free_string(ptr);
        s
    };
    assert!(err.starts_with(r#"{"error":"#), "{err}");
}
