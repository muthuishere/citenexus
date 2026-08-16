//! OOXML-direct docx + pptx extraction — ZIP + streaming XML, no office libs.
//!
//! Mirrors `extract/docx.py` and `extract/pptx.py`:
//! - **docx**: each `w:p` paragraph; `Heading N`-styled paragraphs build the
//!   heading tree (ancestor `structure_path`), body paragraphs carry the path;
//!   image relationships become `ImageRef`s (id = relationship id).
//! - **pptx**: each slide is ONE `slide` block — its text frames joined by
//!   `\n` (paragraphs within a frame also `\n`-joined, python-pptx parity);
//!   `page` is the 1-based slide number; pictures become
//!   `ImageRef(slide{page}-{shapeId})`.

use std::io::{Cursor, Read};

use quick_xml::events::Event;
use quick_xml::Reader;
use zip::ZipArchive;

use crate::types::*;

fn read_zip_entry(archive: &mut ZipArchive<Cursor<&[u8]>>, name: &str) -> Option<String> {
    let mut file = archive.by_name(name).ok()?;
    let mut out = String::new();
    file.read_to_string(&mut out).ok()?;
    Some(out)
}

fn local_name(qname: &[u8]) -> &[u8] {
    match qname.iter().position(|&b| b == b':') {
        Some(idx) => &qname[idx + 1..],
        None => qname,
    }
}

// ---------------------------------------------------------------- docx ----

/// `Heading 1`…`Heading 9` / styleId `Heading1`… → numeric level (Python parity).
fn heading_level(style: &str) -> Option<u32> {
    let tail = style.strip_prefix("Heading")?.trim();
    if tail.is_empty() {
        return Some(1);
    }
    tail.parse().ok().or(Some(1))
}

/// One `w:p`: its concatenated `w:t` text + the `w:pStyle` value.
struct DocxParagraph {
    text: String,
    style: String,
}

fn docx_paragraphs(xml: &str) -> Vec<DocxParagraph> {
    let mut reader = Reader::from_str(xml);
    reader.config_mut().trim_text(false);
    let mut paragraphs = Vec::new();
    let mut current: Option<DocxParagraph> = None;
    let mut in_text = false;
    let mut buf = Vec::new();

    loop {
        match reader.read_event_into(&mut buf) {
            Ok(Event::Start(e)) => match local_name(e.name().as_ref()) {
                b"p" => {
                    current = Some(DocxParagraph {
                        text: String::new(),
                        style: String::new(),
                    })
                }
                b"t" => in_text = current.is_some(),
                _ => {}
            },
            Ok(Event::Empty(e)) => {
                if local_name(e.name().as_ref()) == b"pStyle" {
                    if let Some(p) = current.as_mut() {
                        for attr in e.attributes().flatten() {
                            if local_name(attr.key.as_ref()) == b"val" {
                                p.style = String::from_utf8_lossy(&attr.value).to_string();
                            }
                        }
                    }
                }
            }
            Ok(Event::Text(t)) => {
                if in_text {
                    if let (Some(p), Ok(text)) = (current.as_mut(), t.decode()) {
                        p.text.push_str(&text);
                    }
                }
            }
            Ok(Event::End(e)) => match local_name(e.name().as_ref()) {
                b"t" => in_text = false,
                b"p" => {
                    if let Some(p) = current.take() {
                        paragraphs.push(p);
                    }
                }
                _ => {}
            },
            Ok(Event::Eof) => break,
            Err(_) => break,
            _ => {}
        }
        buf.clear();
    }
    paragraphs
}

fn docx_image_rels(rels_xml: &str) -> Vec<ImageRef> {
    let mut reader = Reader::from_str(rels_xml);
    let mut images = Vec::new();
    let mut buf = Vec::new();
    loop {
        match reader.read_event_into(&mut buf) {
            Ok(Event::Empty(e)) | Ok(Event::Start(e))
                if local_name(e.name().as_ref()) == b"Relationship" =>
            {
                let (mut id, mut is_image) = (None, false);
                for attr in e.attributes().flatten() {
                    match attr.key.as_ref() {
                        b"Id" => id = Some(String::from_utf8_lossy(&attr.value).to_string()),
                        b"Type" => {
                            is_image = String::from_utf8_lossy(&attr.value).contains("image")
                        }
                        _ => {}
                    }
                }
                if let (Some(image_id), true) = (id, is_image) {
                    images.push(ImageRef {
                        image_id,
                        page: None,
                        bbox: None,
                        width: None,
                        height: None,
                        blob_key: None,
                    });
                }
            }
            Ok(Event::Eof) => break,
            Err(_) => break,
            _ => {}
        }
        buf.clear();
    }
    images
}

pub fn extract_docx(
    bytes: &[u8],
    document_id: &str,
    source_uri: Option<String>,
) -> Result<ExtractedDoc, String> {
    let mut archive =
        ZipArchive::new(Cursor::new(bytes)).map_err(|e| format!("not a docx zip: {e}"))?;
    let xml = read_zip_entry(&mut archive, "word/document.xml")
        .ok_or("missing word/document.xml")?;

    let mut blocks: Vec<ExtractedBlock> = Vec::new();
    let mut stack: Vec<(u32, String)> = Vec::new();
    let mut order = 0usize;

    for para in docx_paragraphs(&xml) {
        let content = para.text.trim().to_string();
        if content.is_empty() {
            continue;
        }
        match heading_level(&para.style) {
            Some(level) => {
                while stack.last().is_some_and(|(l, _)| *l >= level) {
                    stack.pop();
                }
                blocks.push(ExtractedBlock {
                    order,
                    kind: BlockKind::Heading,
                    text: content.clone(),
                    page: None,
                    bbox: None,
                    level: Some(level),
                    start_line: None,
                    end_line: None,
                    structure_path: stack.iter().map(|(_, t)| t.clone()).collect(),
                    cells: vec![],
                });
                stack.push((level, content));
            }
            None => blocks.push(ExtractedBlock {
                order,
                kind: BlockKind::Paragraph,
                text: content,
                page: None,
                bbox: None,
                level: None,
                start_line: None,
                end_line: None,
                structure_path: stack.iter().map(|(_, t)| t.clone()).collect(),
                cells: vec![],
            }),
        }
        order += 1;
    }

    let images = read_zip_entry(&mut archive, "word/_rels/document.xml.rels")
        .map(|rels| docx_image_rels(&rels))
        .unwrap_or_default();

    Ok(ExtractedDoc {
        document_id: document_id.to_string(),
        source_type: SourceType::Docx,
        structure_type: StructureType::HeadingTree,
        source_uri,
        blocks,
        images,
    })
}

// ---------------------------------------------------------------- pptx ----

/// One slide's text frames (each frame's paragraphs `\n`-joined) + pictures.
fn pptx_slide(xml: &str, page: u32) -> (Vec<String>, Vec<ImageRef>) {
    let mut reader = Reader::from_str(xml);
    let mut frames: Vec<String> = Vec::new();
    let mut images: Vec<ImageRef> = Vec::new();

    let mut in_tx_body = false;
    let mut frame_paragraphs: Vec<String> = Vec::new();
    let mut paragraph = String::new();
    let mut in_a_t = false;
    let mut in_pic = false;
    let mut buf = Vec::new();

    loop {
        match reader.read_event_into(&mut buf) {
            Ok(Event::Start(e)) => match local_name(e.name().as_ref()) {
                b"txBody" => {
                    in_tx_body = true;
                    frame_paragraphs.clear();
                }
                b"p" if in_tx_body => paragraph.clear(),
                b"t" if in_tx_body => in_a_t = true,
                b"pic" => in_pic = true,
                b"cNvPr" if in_pic => {
                    for attr in e.attributes().flatten() {
                        if attr.key.as_ref() == b"id" {
                            let shape_id = String::from_utf8_lossy(&attr.value).to_string();
                            images.push(ImageRef {
                                image_id: format!("slide{page}-{shape_id}"),
                                page: Some(page),
                                bbox: None,
                                width: None,
                                height: None,
                                blob_key: None,
                            });
                        }
                    }
                }
                _ => {}
            },
            Ok(Event::Empty(e)) => {
                if local_name(e.name().as_ref()) == b"cNvPr" && in_pic {
                    for attr in e.attributes().flatten() {
                        if attr.key.as_ref() == b"id" {
                            let shape_id = String::from_utf8_lossy(&attr.value).to_string();
                            images.push(ImageRef {
                                image_id: format!("slide{page}-{shape_id}"),
                                page: Some(page),
                                bbox: None,
                                width: None,
                                height: None,
                                blob_key: None,
                            });
                        }
                    }
                }
            }
            Ok(Event::Text(t)) => {
                if in_a_t {
                    if let Ok(text) = t.decode() {
                        paragraph.push_str(&text);
                    }
                }
            }
            Ok(Event::End(e)) => match local_name(e.name().as_ref()) {
                b"t" => in_a_t = false,
                b"p" if in_tx_body => frame_paragraphs.push(std::mem::take(&mut paragraph)),
                b"txBody" => {
                    in_tx_body = false;
                    let frame_text = frame_paragraphs.join("\n").trim().to_string();
                    if !frame_text.is_empty() {
                        frames.push(frame_text);
                    }
                }
                b"pic" => in_pic = false,
                _ => {}
            },
            Ok(Event::Eof) => break,
            Err(_) => break,
            _ => {}
        }
        buf.clear();
    }
    (frames, images)
}

pub fn extract_pptx(
    bytes: &[u8],
    document_id: &str,
    source_uri: Option<String>,
) -> Result<ExtractedDoc, String> {
    let mut archive =
        ZipArchive::new(Cursor::new(bytes)).map_err(|e| format!("not a pptx zip: {e}"))?;

    // Slides sorted by their number: ppt/slides/slide{N}.xml.
    let mut slide_names: Vec<(u32, String)> = (0..archive.len())
        .filter_map(|i| archive.by_index(i).ok().map(|f| f.name().to_string()))
        .filter_map(|name| {
            let n: u32 = name
                .strip_prefix("ppt/slides/slide")?
                .strip_suffix(".xml")?
                .parse()
                .ok()?;
            Some((n, name))
        })
        .collect();
    slide_names.sort();

    let mut blocks = Vec::new();
    let mut images = Vec::new();
    for (index, (_, name)) in slide_names.iter().enumerate() {
        let page = (index + 1) as u32;
        let xml = read_zip_entry(&mut archive, name).unwrap_or_default();
        let (frames, slide_images) = pptx_slide(&xml, page);
        images.extend(slide_images);
        blocks.push(ExtractedBlock {
            order: index,
            kind: BlockKind::Slide,
            text: frames.join("\n"),
            page: Some(page),
            bbox: None,
            level: Some(index as u32),
            start_line: None,
            end_line: None,
            structure_path: vec![],
            cells: vec![],
        });
    }

    Ok(ExtractedDoc {
        document_id: document_id.to_string(),
        source_type: SourceType::Pptx,
        structure_type: StructureType::SlideSequence,
        source_uri,
        blocks,
        images,
    })
}
