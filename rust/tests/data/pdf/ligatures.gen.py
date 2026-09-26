"""One-off generator for ligatures.pdf (NOT run at test time).

Writes a minimal DOCX with the words "Platform", "Option", "Migration effort"
and "Trade-offs" in Carlito 12 pt (LibreOffice ships Carlito), then converts
it with LibreOffice (MPL-2.0; used only as a generator):

    python3 ligatures.gen.py <out_dir>
    soffice --headless --convert-to pdf --outdir <out_dir> <out_dir>/ligatures.docx

Carlito shapes "ff", "fi", "ft" as ligature glyphs: ONE glyph whose
ToUnicode entry maps to SEVERAL characters. The regression check is that the
round-tripped TEXT is exact (counts can come out right while the order is
wrong) and that the character boxes still advance.
"""
import sys, zipfile, os

WORDS = ["Platform", "Option", "Migration effort", "Trade-offs"]
out = sys.argv[1]
os.makedirs(out, exist_ok=True)
run = '<w:r><w:rPr><w:rFonts w:ascii="Carlito" w:hAnsi="Carlito"/><w:sz w:val="24"/></w:rPr><w:t xml:space="preserve">{}</w:t></w:r>'
paras = "".join(f"<w:p>{run.format(w)}</w:p>" for w in WORDS)
doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
       '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
       f'<w:body>{paras}</w:body></w:document>')
ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
      '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
      '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
      '<Default Extension="xml" ContentType="application/xml"/>'
      '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
      '</Types>')
rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        '</Relationships>')
with zipfile.ZipFile(os.path.join(out, "ligatures.docx"), "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("[Content_Types].xml", ct)
    z.writestr("_rels/.rels", rels)
    z.writestr("word/document.xml", doc)
