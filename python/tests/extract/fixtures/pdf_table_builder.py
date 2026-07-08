"""Hand-built single-page PDF with one REAL ruled table (explicit vector
lines, not just aligned text) — no PDF-writing dependency, same raw PDF
object construction as ``pdf_builder.py``. Ruled lines are what
``pdfplumber``'s default ``find_tables()`` strategy ("lines") detects, so
this exercises the real table-detection path, not text-alignment guessing.
"""

from __future__ import annotations

import io


def _pdf_escape(text: str) -> bytes:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)").encode("latin-1")


def build_pdf_with_table(
    rows: list[list[str]],
    *,
    col_x: list[int],
    row_y: list[int],
    text: str = "Unrelated narrative text, outside the table.",
) -> bytes:
    """A minimal, valid single-page PDF: one paragraph + one ruled table.

    ``col_x`` are the N+1 vertical line x-positions (N columns);
    ``row_y`` are the M+1 horizontal line y-positions (M rows, header first).
    ``rows`` is ``len(row_y) - 1`` rows of ``len(col_x) - 1`` cell strings.
    """
    ops: list[bytes] = [b"1 w"]
    x0, x1 = col_x[0], col_x[-1]
    for y in row_y:
        ops.append(f"{x0} {y} m {x1} {y} l S".encode())
    y0, y1 = row_y[0], row_y[-1]
    for x in col_x:
        ops.append(f"{x} {y0} m {x} {y1} l S".encode())

    for row_index, row in enumerate(rows):
        band_top = row_y[row_index]
        baseline = band_top - 14
        for col_index, cell in enumerate(row):
            x = col_x[col_index] + 8
            ops.append(
                f"BT /F1 10 Tf {x} {baseline} Td (".encode()
                + _pdf_escape(cell)
                + b") Tj ET"
            )

    ops.insert(
        0,
        b"BT /F1 12 Tf 50 "
        + str(row_y[0] + 40).encode()
        + b" Td ("
        + _pdf_escape(text)
        + b") Tj ET",
    )
    content_stream = b"\n".join(ops)

    objects: list[bytes] = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objects.append(
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
    )
    objects.append(
        f"<< /Length {len(content_stream)} >>\nstream\n".encode()
        + content_stream
        + b"\nendstream"
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
    out.write(
        (f"trailer\n<< /Size {n} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF").encode()
    )
    return out.getvalue()
