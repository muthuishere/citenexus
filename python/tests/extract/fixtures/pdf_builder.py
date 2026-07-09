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


def build_pdf_with_image(
    text: str = "Hello PDF with image", display_size: tuple[int, int] = (220, 220)
) -> bytes:
    """A minimal, valid single-page PDF containing one real JPEG image XObject.

    ``display_size`` is the ``cm``-transform size (PDF points) the image is
    placed at on the 612x792pt page — the default (220x220, area_ratio ~0.10)
    clears the §9 pre-filter's ``min_area_ratio`` (0.05) as a "meaningful
    figure"; pass something small (e.g. ``(40, 40)``, ratio ~0.004) to build a
    decoration-sized image that the pre-filter should skip.
    """
    jpeg = _jpeg_bytes()
    width, height = Image.open(io.BytesIO(jpeg)).size
    disp_w, disp_h = display_size

    content_stream = (
        f"BT /F1 12 Tf 50 700 Td ({text}) Tj ET "
        f"q {disp_w} 0 0 {disp_h} 50 480 cm /Im1 Do Q".encode()
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
