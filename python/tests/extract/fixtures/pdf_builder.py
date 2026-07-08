"""Hand-built single-page PDF with one real embedded JPEG image.

No PDF-writing library is in the dependency tree, so this constructs the raw
PDF byte structure directly: a page with one ``/DCTDecode`` (JPEG) image
XObject. ``DCTDecode`` streams are stored verbatim by the PDF format (the JPEG
codec is its own container) — `pdfminer`'s ``PDFStream.get_data()`` returns
them untouched, so the bytes decode with Pillow with no extra reconstruction.
This keeps the extractor's real byte-extraction path exercised end-to-end,
hermetically, with no network and no extra dependency.
"""

from __future__ import annotations

import io

from PIL import Image


def _jpeg_bytes(width: int = 40, height: int = 30) -> bytes:
    image = Image.new("RGB", (width, height), color=(200, 30, 30))
    buf = io.BytesIO()
    image.save(buf, format="JPEG")
    return buf.getvalue()


def build_pdf_with_image(text: str = "Hello PDF with image") -> bytes:
    """A minimal, valid single-page PDF containing one real JPEG image XObject."""
    jpeg = _jpeg_bytes()
    width, height = Image.open(io.BytesIO(jpeg)).size

    content_stream = (
        f"BT /F1 12 Tf 50 700 Td ({text}) Tj ET q 100 0 0 100 50 500 cm /Im1 Do Q".encode()
    )

    objects: list[bytes] = []

    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objects.append(
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 6 0 R >> /XObject << /Im1 4 0 R >> >> "
        b"/Contents 5 0 R >>"
    )
    objects.append(
        (
            f"<< /Type /XObject /Subtype /Image /Width {width} /Height {height} "
            f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode "
            f"/Length {len(jpeg)} >>\nstream\n"
        ).encode()
        + jpeg
        + b"\nendstream"
    )
    objects.append(
        f"<< /Length {len(content_stream)} >>\nstream\n".encode() + content_stream + b"\nendstream"
    )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets: list[int] = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{index} 0 obj\n".encode())
        out.write(body)
        out.write(b"\nendobj\n")

    xref_offset = out.tell()
    n = len(objects) + 1
    out.write(f"xref\n0 {n}\n".encode())
    out.write(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write((f"trailer\n<< /Size {n} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF").encode())
    return out.getvalue()
