## 1. Python reference emitter (test-first)

- [x] 1.1 Failing tests `python/tests/extract/test_markdown.py`: heading
      levels render + clamp (2/null/9 → `##`/`#`/`######`), paragraph/table/
      thread_turn/ocr_block verbatim, code fenced, slide → `## Slide {page}`
      + text, image → text-or-`![image]()`, blocks joined by `\n\n`, single
      trailing `\n`, zero blocks → `""`, determinism (render twice, equal).
- [x] 1.2 Implement `python/src/citenexus/extract/markdown.py`
      (`to_markdown(ExtractedDoc) -> str`, pure, total over `BlockKind`);
      export from `citenexus.extract`.

## 2. xlsx extractor (test-first, both sides of the parity seam)

- [x] 2.1 Failing tests `python/tests/extract/test_xlsx.py`: two-sheet
      workbook → per-sheet heading + `col: value` table blocks (`page` =
      sheet index, header on `structure_path`), empty workbook → headings
      only, zip-shortest rows; conformance fixture `.xlsx` added.
- [x] 2.2 Implement `python/src/citenexus/extract/xlsx.py` (`openpyxl`),
      add `SourceType.xlsx` + `.xlsx` dispatch mapping; dep in pyproject.
- [x] 2.3 Rust twin `rust/src/extract/xlsx.rs` (`calamine`), `SourceType::Xlsx`
      + extension mapping in `extract/mod.rs`; unit tests mirror 2.1.

## 3. Rust twin emitter (test-first)

- [x] 3.1 Failing Rust unit tests mirroring 1.1 in `rust/src/emit/markdown.rs`.
- [x] 3.2 Implement `rust/src/emit/mod.rs` + `emit/markdown.rs`
      (`to_markdown(&ExtractedDoc) -> String`); wire into `lib.rs`.

## 4. C ABI front door

- [x] 4.1 Rust test: `citenexus_to_markdown(bytes, len, source_type)` over
      docx + xlsx fixtures → `{"markdown": ...}`; invalid docx bytes →
      `{"error": ...}`; unknown/plain type falls back to plain-text markdown.
- [x] 4.2 Implement the FFI fn in `rust/src/ffi.rs` (extract dispatch →
      emitter; string released by `citenexus_free_string`); document it in
      `rust/README.md`'s C ABI block + status table.

## 5. Parity (Python is the arbiter)

- [x] 5.1 Extend `python/tests/core/test_rust_parity.py`: for every
      conformance fixture (now including `.xlsx`), Python
      `extract(...)`/`to_markdown(extract(...))` == Rust-FFI ExtractedDoc/
      markdown, byte-identical (pdf cases follow the existing `pdf`-feature
      skip logic).

## 6. Bindings

- [x] 6.1 Go: `ToMarkdown(data []byte, sourceType string)` in
      `golang/core/core.go` + fixture test in `core_test.go`.
- [x] 6.2 TS: `toMarkdown(buf, sourceType)` in `js/src/core/core.ts`
      (koffi symbol + wrapper, same error surface as `extract`) + test.

## 7. Gate

- [x] 7.1 Scoped lint/typecheck/tests green in all three languages
      (`task core:test`, python suite, js suite); CHANGELOG entry.
