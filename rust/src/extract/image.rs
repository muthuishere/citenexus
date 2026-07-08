//! ImageExtractor — a standalone image file → one `image` block whose text is a
//! self-contained base64 `data:` URI, or the empty placeholder when the format
//! is unrecognized or the payload exceeds the inline cap. The Rust twin of
//! `extract/image.py`; both emit byte-identical `ExtractedDoc` JSON.
//!
//! The cap keeps a scanned page from ballooning the markdown into megabytes: at
//! or below `MAX_INLINE_BYTES` the bytes are inlined; above it (or for an
//! unknown magic) the block text is empty, which the emitter renders as the
//! `![image]()` placeholder.

use crate::types::*;

/// Largest raw image inlined as a data-URI (256 KiB); larger → placeholder.
const MAX_INLINE_BYTES: usize = 256 * 1024;

const B64: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

/// Standard base64 (RFC 4648, `+/` alphabet, `=` padding, no line breaks).
fn base64_encode(data: &[u8]) -> String {
    let mut out = String::with_capacity(data.len().div_ceil(3) * 4);
    for chunk in data.chunks(3) {
        let b0 = chunk[0] as u32;
        let b1 = *chunk.get(1).unwrap_or(&0) as u32;
        let b2 = *chunk.get(2).unwrap_or(&0) as u32;
        let n = (b0 << 16) | (b1 << 8) | b2;
        out.push(B64[((n >> 18) & 63) as usize] as char);
        out.push(B64[((n >> 12) & 63) as usize] as char);
        out.push(if chunk.len() > 1 {
            B64[((n >> 6) & 63) as usize] as char
        } else {
            '='
        });
        out.push(if chunk.len() > 2 {
            B64[(n & 63) as usize] as char
        } else {
            '='
        });
    }
    out
}

/// Recognize the image type from its magic bytes → the `image/<mime>` subtype.
fn sniff_mime(bytes: &[u8]) -> Option<&'static str> {
    if bytes.starts_with(&[0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]) {
        Some("png")
    } else if bytes.starts_with(&[0xFF, 0xD8, 0xFF]) {
        Some("jpeg")
    } else if bytes.starts_with(b"GIF87a") || bytes.starts_with(b"GIF89a") {
        Some("gif")
    } else if bytes.len() >= 12 && &bytes[0..4] == b"RIFF" && &bytes[8..12] == b"WEBP" {
        Some("webp")
    } else {
        None
    }
}

pub fn extract(bytes: &[u8], document_id: &str, source_uri: Option<String>) -> ExtractedDoc {
    let text = match sniff_mime(bytes) {
        Some(mime) if bytes.len() <= MAX_INLINE_BYTES => {
            format!("![image](data:image/{mime};base64,{})", base64_encode(bytes))
        }
        _ => String::new(),
    };
    let block = ExtractedBlock {
        order: 0,
        kind: BlockKind::Image,
        text,
        page: None,
        bbox: None,
        level: None,
        structure_path: vec![],
        cells: vec![],
    };
    ExtractedDoc {
        document_id: document_id.to_string(),
        source_type: SourceType::Image,
        structure_type: StructureType::None,
        source_uri,
        blocks: vec![block],
        images: vec![],
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const PNG: &[u8] = &[0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 0x01, 0x02];

    #[test]
    fn base64_matches_known_vectors() {
        assert_eq!(base64_encode(b""), "");
        assert_eq!(base64_encode(b"f"), "Zg==");
        assert_eq!(base64_encode(b"fo"), "Zm8=");
        assert_eq!(base64_encode(b"foo"), "Zm9v");
        assert_eq!(base64_encode(b"foob"), "Zm9vYg==");
        assert_eq!(base64_encode(b"foobar"), "Zm9vYmFy");
    }

    #[test]
    fn png_inlines_as_data_uri() {
        let doc = extract(PNG, "doc", None);
        assert_eq!(doc.source_type, SourceType::Image);
        assert_eq!(doc.blocks.len(), 1);
        assert_eq!(
            doc.blocks[0].text,
            format!("![image](data:image/png;base64,{})", base64_encode(PNG))
        );
    }

    #[test]
    fn unknown_magic_becomes_placeholder() {
        let doc = extract(b"not an image", "doc", None);
        assert_eq!(doc.blocks[0].text, "");
    }

    #[test]
    fn oversize_image_becomes_placeholder() {
        let mut big = vec![0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A];
        big.resize(MAX_INLINE_BYTES + 1, 0);
        let doc = extract(&big, "doc", None);
        assert_eq!(doc.blocks[0].text, "");
    }
}
