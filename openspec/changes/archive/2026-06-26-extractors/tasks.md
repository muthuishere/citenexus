## 1. Plain + text + shared loading (test-first)

- [x] 1.1 Write failing tests `tests/extract/test_plain.py` and
      `tests/extract/test_txt.py`: raw string → one paragraph; bytes decoded;
      `document_id` from path stem / passed id; txt blank-line paragraph split;
      `source_type`/`structure_type` correct.
- [x] 1.2 Implement `src/trustrag/extract/plain.py` (PlainExtractor + the shared
      `resolve_path`/`load_text`/`open_binary` source-loading helpers) and
      `src/trustrag/extract/txt.py` until 1.1 passes.

## 2. Markdown / CSV / HTML (test-first)

- [x] 2.1 Write failing tests `tests/extract/test_md.py`,
      `tests/extract/test_csv.py`, `tests/extract/test_html.py`: heading
      level + ancestor `structure_path`, paragraph paths, `heading_tree` vs
      `none`; csv header→`table_schema` + row table blocks; html headings/
      paragraphs + script/style stripped.
- [x] 2.2 Implement `src/trustrag/extract/md.py` (markdown-it-py),
      `src/trustrag/extract/csv.py` (stdlib csv), `src/trustrag/extract/html.py`
      (bs4) until 2.1 passes.

## 3. DOCX / PPTX (build fixtures in-test, test-first)

- [x] 3.1 Add `tests/extract/conftest.py` fixtures that build a `.docx` (two
      heading levels + body + image) and a `.pptx` (two slides + a picture) in
      memory; write failing `tests/extract/test_docx.py` and
      `tests/extract/test_pptx.py` asserting heading levels, paths, slide blocks,
      `structure_type`, and images→`ImageRef`.
- [x] 3.2 Implement `src/trustrag/extract/docx.py` (python-docx) and
      `src/trustrag/extract/pptx.py` (python-pptx) until 3.1 passes.

## 4. PDF (hermetic fixture, test-first)

- [x] 4.1 Create a hermetic single-page `tests/extract/fixtures/sample.pdf`
      (one text line, correct xref) and a failing `tests/extract/test_pdf.py`
      asserting `page=1`, the text, a 4-number bbox, and `page_layout`.
- [x] 4.2 Implement `src/trustrag/extract/pdf.py` (pdfplumber) until 4.1 passes.
      PDF stays a hermetic unit test (no `@pytest.mark.integration` needed).

## 5. Dispatch (test-first)

- [x] 5.1 Write failing `tests/extract/test_dispatch.py`: each extension → its
      extractor; unknown extension, raw string, and raw bytes → PlainExtractor;
      explicit `source_type` overrides extension; `extract(source)` convenience
      returns an `ExtractedDoc` and honours a passed `document_id`.
- [x] 5.2 Implement `src/trustrag/extract/dispatch.py` (`extractor_for` +
      `extract`) until 5.1 passes.

## 6. Gate

- [x] 6.1 `uv run pytest tests/extract -m "not integration" -q` passes.
- [x] 6.2 `uv run ruff check src/trustrag/extract tests/extract` is clean.
- [x] 6.3 `uv run mypy src/trustrag/extract tests/extract` is clean.
