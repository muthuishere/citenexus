# PDF → markdown: state of the art, and what to borrow into the Rust core

**Date:** 2026-09-24 · **Tree:** `feat/pdf-markdown` @ `f5665e9` (`docs(site): five false claims on the published home page`)
**Also read:** spike 185 in the Volentis worktree `agent-a7d0b2cbb460cc8c1` @ `406a320d7`
(`apps/rag_api/docs/spikes/185-markdown-converter-bakeoff/`: `build_final.py`, `check.py`,
`test_check.py`, `prompts.json`, `results.md`), and rag_api's `app/ingestion/detection.py` at the same commit.
**Scope:** research only. No product code, no ADR. The spike's `data/` (client documents) was not opened.
Every synthetic probe below was run on invented text.

> **How to read this.** It is a **point-in-time audit**. Nothing here is a capability claim about
> CiteNexus. Tools move weekly: Xberg shipped 24 releases in two months, and Marker rewrote itself in July.
> Re-check any version, licence or number before it goes into an ADR.
> - Numbers are copied from the source named next to them. **Self-reported** means the tool's authors ran it.
> - **(unverified)** means only a second-hand source was seen.
> - **(anecdotal)** marks community reports that no benchmark backs.
>
> The framing (owner, 2026-09-24): **we adopt no tool wholesale.** We lift specific *parts* into our
> own pdfium Rust core. §8 is therefore a ranked **borrow list**, not a tool choice.

---

## 0. The answer in one screen

**The single biggest weakness in spike 185:** its gate checks **vocabulary, not placement**, and the
models **write** the text instead of **pointing at** the text layer. I ran the spike's own `check.gate`
at the *strict* text-LLM thresholds (coverage ≥0.98, novelty ≤0.02) on synthetic pages. It **accepts** all of these:
- two amounts swapped between table rows;
- `€ 7.000,00` rewritten as `€ 70.000,0`;
- `€ 5.100,00` rewritten as `€ 100`;
- an empty cell filled with a value and a label that already appear elsewhere on the page;
- a "geen" (no/not) moved from one sentence to another (§5, W1).

Every one of those is a confidently-wrong table. The leading text-layer systems avoid the whole class
**by construction**: they fill every cell and region with the PDF's own characters, and use a model
only to decide *structure*. Examples are Marker v2's `table_recon.py`, LlamaIndex's LiteParse, Xberg's
native tables, opendataloader-pdf, and the TFLOP "layout pointer" paper.

**Recommendation:**
1. **Keep the spike's per-page routing, injected models and provenance.** Nobody else verifies model
   output against the text layer at all (§4), so the idea is ahead of the field.
2. **Change the model's job.** On pages with a text layer, the model (text LLM or vision) proposes a
   *grid* or *structure*. The Rust core fills the cells from pdfium character runs, and the gate checks
   *geometry*: every cell's characters must sit in one row band and one column band. "Numbers ⊆ text
   layer" becomes true by construction, not by a bag-of-words test.
3. **Borrow the deterministic parts** that already exist under permissive licences, most of them in
   Rust on pdfium:
   - LiteParse's page-complexity router and header/footer detector (Apache-2.0, Rust, pdfium);
   - Marker's text-layer table grid search with a scored VLM fallback (Apache-2.0);
   - Xberg's word-box table reconstruction, fake-table validators and hyphen "witnesses" (MIT, pinned commit);
   - Docling's rule-based reading order and text-quality score (MIT);
   - ParseBench's digit bag and GriTS (Apache-2.0 / MIT) for the gate.
4. **Add the tagged-PDF structure tree** as the first table and heading source. pdfium exposes it
   (`FPDF_StructTree_*`, with RowSpan/ColSpan attributes). The spike ignores it.
5. **Do not take Xberg as a dependency.** Its default PDF engine is no longer pdfium, its pdfium backend
   does no tables, and its licence changed twice in 2026 (§2).

---

## 1. State of the art in 2026 (question 1)

### 1.1 Per tool

| tool | latest (date) | licence code / weights | text layer or pure vision | layout / reading order | tables | headings | hyphenation | headers / footers | scans |
|---|---|---|---|---|---|---|---|---|---|
| **Docling** (standard) | 2.130.0 (2026-09-22) | MIT / Heron Apache-2.0; TableFormer CDLA-P-2.0 or Apache-2.0 | **text layer** (docling-parse), OCR on bitmaps | Heron RT-DETRv2 (17 classes); **rule-based** reading order `reading_order_rb.py` | TableFormer (OTSL + cell bbox), cells **matched to PDF text**; card: 93.6 TEDS | flat by default; opt-in levels from bookmarks → numbering → font ("a wrong level is worse than a missing one") | `sanitize_text` drops line-end hyphen between alphanumerics; continuation merge docling#3888 (also merges real compounds) | page-header/footer → `FURNITURE` layer, dropped from markdown by default | EasyOCR / Tesseract / RapidOCR / … |
| **GraniteDocling-258M** | 2025-09-17 | Apache-2.0 | pure vision (DocTags) | in-model | in-model, OTSL | in-model | implicit | in-model | yes |
| **MinerU 4.0 / MinerU2.5(-Pro)** | 4.0.7 (2026-09-23) | code: "MinerU Open Source License" (Apache-2.0 + thresholds of 100M MAU or $20M/month revenue, and attribution) since v3.1.0 / 2.5-2509 weights **AGPL-3.0**, 2.5-Pro Apache-2.0 | tiers: *flash* native text (DocVortex, pypdfium2), *standard* VLM | PP-DocLayoutV2 ONNX; the VLM predicts order with layout | SLANet+ (borderless), UNet lines (ruled), or VLM OTSL | LLM-aided `title_leveling.py` (optional) | no rule found (unverified) | discarded blocks | PP-OCRv6 |
| **PaddleOCR-VL 1.0/1.5/1.6** | 1.6 (2026-05-28) | Apache-2.0 / Apache-2.0 | pure vision (appears so; unverified) | PP-DocLayoutV2/V3: RT-DETR + **pointer network for reading order** | 0.9B VLM per crop | post-processor | PaddleX `s.replace("-\n","")`, which strips every line-end hyphen | dropped via `markdown_ignore_labels` | yes |
| **Marker v2** | 2.0.0 (2026-07-20) | **Apache-2.0 since 2026-07-17** / OpenRAIL-M (free under $5M) | **text layer first** (pdftext on pypdfium2); VLM only for garbled or scan pages, equations and low-confidence tables | RF-DETR (fast) or Surya (balanced) | **`table_recon.py`: deterministic grid search from text spans, scored; VLM crop fallback below a score** | KMeans on line heights, 4 levels | pdftext handles pdfium's `\x02`; cross-column continuation merge | `ignoretext.py` fuzzy repeats (≥0.2 of pages, ≥3, fuzz ≥90) | VLM |
| **Nougat** | 0.1.0 (2023) | MIT / **CC-BY-NC** | pure vision | none | in-model | in-model | — | — | yes |
| **olmOCR 2** | 0.4.27 (2026-03-12) | Apache-2.0 / Apache-2.0 | v1 **anchored** the prompt with text-layer blocks; **v2 dropped anchoring**; poppler `pdftotext` fallback | in-model | in-model | in-model | — | model trained to omit them | yes |
| **Mistral OCR 4 / 4.1** | ocr-4-1 (2026-07-16) | proprietary API | not documented | `include_blocks` returns bbox + label + order | markdown or HTML | — | not documented | `extract_header`/`extract_footer` | yes |
| **Azure Document Intelligence Layout** | v4.0 `2024-11-30` GA | proprietary | not documented | roles: title, sectionHeading, pageHeader/Footer, pageNumber | HTML with rowspan/colspan; multi-page tables **not** merged | levels 1–6 | not documented | kept as `<!-- PageHeader="…" -->` comments | yes |
| **markitdown** | 0.1.8 (2026-09-21) | MIT | text layer (pdfminer + pdfplumber) | none | borderless-form heuristic (x-gap clustering) | none | none | none | LLM plugin |

Sources: [Docling](https://github.com/docling-project/docling),
[heading levels](https://docling-project.github.io/docling/usage/heading_levels/),
[page_assemble_model.py](https://github.com/docling-project/docling/blob/main/docling/models/stages/page_assemble/page_assemble_model.py),
[content_layer.py](https://github.com/docling-project/docling-core/blob/main/docling_core/types/doc/common/content_layer.py),
[Heron paper arXiv 2509.11720](https://arxiv.org/html/2509.11720v1),
[GraniteDocling card](https://huggingface.co/ibm-granite/granite-docling-258M),
[MinerU 4.0.0 release](https://github.com/opendatalab/MinerU/releases/tag/mineru-4.0.0-released),
[MinerU LICENSE.md](https://github.com/opendatalab/MinerU/blob/master/LICENSE.md),
[MinerU2.5 arXiv 2509.22186](https://arxiv.org/html/2509.22186),
[MinerU2.5-Pro arXiv 2604.04771](https://arxiv.org/abs/2604.04771),
[PaddleOCR-VL arXiv 2510.14528](https://arxiv.org/html/2510.14528),
[PaddleOCR-VL-1.5 arXiv 2601.21957](https://arxiv.org/abs/2601.21957),
[PaddleOCR-VL pipeline docs](https://github.com/paddlepaddle/paddleocr/blob/main/docs/version3.x/pipeline_usage/PaddleOCR-VL.en.md),
[PaddleX markdown_format_funcs.py:290](https://github.com/PaddlePaddle/PaddleX/blob/develop/paddlex/inference/common/result/converter/markdown_format_funcs.py),
[Marker](https://github.com/datalab-to/marker) and [v2.0.0 release](https://github.com/datalab-to/marker/releases/tag/v2.0.0),
[pdftext postprocessing.py](https://github.com/datalab-to/pdftext/blob/master/pdftext/postprocessing.py),
[Nougat](https://github.com/facebookresearch/nougat) and [arXiv 2308.13418](https://arxiv.org/abs/2308.13418),
[olmOCR](https://github.com/allenai/olmocr), [olmOCR arXiv 2502.18443](https://arxiv.org/html/2502.18443v2), [olmOCR 2 arXiv 2510.19817](https://arxiv.org/abs/2510.19817),
[Mistral changelog](https://docs.mistral.ai/resources/changelogs), [Mistral OCR 4 blog](https://mistral.ai/news/ocr-4/),
[Azure Layout](https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/prebuilt/layout) and [markdown elements](https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/concept/markdown-elements?view=doc-intel-4.0.0),
[markitdown _pdf_converter.py](https://github.com/microsoft/markitdown/blob/main/packages/markitdown/src/markitdown/converters/_pdf_converter.py).

### 1.2 Published benchmarks

**OmniDocBench v1.6_full.** Source: the [README leaderboard](https://github.com/opendatalab/OmniDocBench) at `f133a71e`, 2026-09-11.
- v1.6 was released 2026-04-10 with 1,651 pages.
- The README also mentions a v1.7 update (2026-04-30), but the table caption still reads v1.6.
- Overall = ((1−TextEdit)·100 + TableTEDS + FormulaCDM)/3.

| model | Overall | TextEdit↓ | Formula CDM | Table TEDS | TEDS-S | Read-order↓ |
|---|---:|---:|---:|---:|---:|---:|
| TeleOCR 1.2B | 96.91 | 0.0267 | 96.59 | 96.82 | 98.18 | 0.118 |
| PaddleOCR-VL-1.6 | 96.34 | 0.0326 | 97.53 | 94.76 | 97.10 | 0.128 |
| MinerU2.5-Pro | 95.75 | 0.036 | 97.45 | 93.42 | 95.92 | 0.120 |
| PaddleOCR-VL-1.5 | 94.93 | 0.038 | 96.89 | 91.67 | 94.37 | 0.130 |
| MinerU-2.5 | 93.04 | 0.045 | 95.77 | 87.88 | 91.47 | 0.130 |
| Gemini 3 Pro | 92.91 | 0.064 | 95.99 | 89.15 | 92.96 | 0.165 |
| MinerU-Pipeline | 86.47 | 0.055 | 83.07 | 81.88 | 88.68 | 0.153 |
| olmOCR 7B | 85.74 | 0.139 | 88.10 | 83.00 | 87.17 | 0.216 |
| Mistral OCR (2503) | 85.66 | 0.097 | 89.91 | 76.78 | 80.93 | 0.171 |
| Marker 1.8.2 | 78.44 | 0.157 | 85.24 | 65.77 | 73.24 | 0.243 |

Other v1.6 rows from the same README (reported by the sweep): GLM-OCR 95.22, DeepSeek-OCR-2 90.25,
dots.ocr 90.77, Dolphin-v2 89.50, MonkeyOCR-pro-3B 88.57, OpenDoc-0.1B 90.67.
- An independent reproduction of PaddleOCR-VL-1.6 got **95.25, not 96.34**. The issue is open, with no maintainer reply ([#258](https://github.com/opendatalab/OmniDocBench/issues/258), 2026-09-20).

**Why OmniDocBench says little about our problem:**
- It is scored from page **images**, so text-layer pipelines run in OCR mode.
- Headers, footers and page numbers are "abandon" classes and are not scored.
- Text is evaluated in Chinese and English only.
- The dataset is research and non-commercial only.

**olmOCR-bench.** Source: the [bench README](https://github.com/allenai/olmocr/blob/main/olmocr/bench/README.md).
- About 1,400 single-page PDFs and more than 7,000 pass/fail unit tests.
- `*` means self-reported by the model's authors; Ai2 reproduced the other rows.

| system | ArXiv | OldScanMath | Tables | OldScans | Hdr/Ftr | MultiCol | LongTiny | Base | Overall |
|---|---|---|---|---|---|---|---|---|---|
| Chandra 0.1.0* | 82.2 | 80.3 | 88.0 | 50.4 | 90.8 | 81.2 | 92.3 | 99.9 | 83.1±0.9 |
| Infinity-Parser 7B* | 84.4 | 83.8 | 85.0 | 47.9 | 88.7 | 84.2 | 86.4 | 99.8 | 82.5 |
| olmOCR v0.4.0 | 83.0 | 82.3 | 84.9 | 47.7 | 96.1 | 83.7 | 81.9 | 99.7 | 82.4±1.1 |
| PaddleOCR-VL* | 85.7 | 71.0 | 84.1 | 37.8 | 97.0 | 79.9 | 85.7 | 98.5 | 80.0±1.0 |
| Marker 1.10.1 | 83.8 | 66.8 | 72.9 | 33.5 | 86.6 | 80.0 | 85.7 | 99.3 | 76.1±1.1 |
| DeepSeek-OCR | 77.2 | 73.6 | 80.2 | 33.3 | 96.1 | 66.4 | 79.4 | 99.8 | 75.7±1.0 |
| MinerU 2.5.4* | 76.6 | 54.6 | 84.9 | 33.7 | 96.6 | 78.2 | 83.5 | 93.7 | 75.2±1.1 |
| Mistral OCR API (2503) | 77.2 | 67.5 | 60.6 | 29.3 | 93.6 | 71.3 | 77.1 | 99.4 | 72.0±1.1 |

More self-reported olmOCR-bench scores:
- Mistral OCR 4: 85.20 ([blog](https://mistral.ai/news/ocr-4/)). The OmniDocBench 93.07 in the same post names no version, so it cannot be compared.
- Chandra 2: 85.8 ([chandra README](https://github.com/datalab-to/chandra)).
- Marker v2 ([README](https://github.com/datalab-to/marker)):

  | Marker v2 mode | overall | digital-only |
  |---|---:|---:|
  | balanced | 76.0 | 83.5 |
  | fast | 66.6 | — |
  | no-OCR | 43.6 | 55.8 |

  The same Marker table reports docling at 50.3, which is a competitor's run.
- LiteParse's own run: 39.6, or 42.2 with OCR ([LiteParse](https://github.com/run-llama/liteparse)).

olmOCR-bench folds every hyphen variant to ASCII `-` and is position-insensitive, so **no public benchmark rewards dehyphenation**.

**Model-free benchmarks (opendataloader-bench, 200 PDFs).** Every published number is vendor-run on
different versions, and they contradict each other:

| published by | numbers |
|---|---|
| opendataloader | liteparse 0.576 |
| LiteParse | LiteParse 0.886, opendataloader 0.842 |
| pdf-inspector | pdf-inspector 0.875, liteparse 0.873 |

Do not quote any of them without naming the run.

### 1.3 What the leaders have in common
- **The benchmark leaders are pure-vision GPU VLMs** (0.9B–7B). The benchmarks score images, so they
  cannot show what a text layer is worth.
- **The text-layer tools converge on "text layer first, model on exception"**: Docling standard, Marker v2,
  MinerU flash, LiteParse, Xberg and opendataloader. Marker v2 **replaced its table model** with
  deterministic text-layer reconstruction (commit `5f63811a`, 2026-07-03) and calls a VLM only when the
  grid's score is low.
- **Anchoring the prompt with the text layer barely helped.**
  - olmOCR v1 anchoring scored 75.5 vs 74.7 without, on olmOCR-bench (as reproduced in the [MonkeyOCR README](https://github.com/Yuliang-Liu/MonkeyOCR) at `7aace39c`).
  - olmOCR v2 dropped anchoring (`olmocr/pipeline.py`).
  - A study of Arabic manuscripts ([arXiv 2608.22366](https://arxiv.org/abs/2608.22366)) found that an OCR prior **hurts** when that OCR is wrong.
  - Conclusion: use the text layer as the **source and the check**, not as a hint.

---

## 2. Rust options (question 2)

**What CiteNexus has today** (`f5665e9`):
- `rust/src/extract/pdf.rs:28-33` takes `page.text().all()`, one flat paragraph per page, and sets `bbox: None` (`:39`).
- `Pdfium::default()` binds libpdfium dynamically (`:18`), behind the `pdf` cargo feature (`rust/Cargo.toml`, `pdfium-render = "0.9"`).
- Nothing under `rust/src/` handles U+0002 (grep).

That is exactly the flat, headingless, hyphen-marker-leaking output rag_go reported.

| library | version (date) | licence code / weights | native deps | CPU-only | FFI / cdylib fit | Linux amd64 container | tables | verdict |
|---|---|---|---|---|---|---|---|---|
| **pdfium-render** (our base) | 0.9.4 (2026-09-06; the repo pins 0.9 and the lock has 0.9.2) | MIT OR Apache-2.0 | libpdfium: [bblanchon chromium/8066](https://github.com/bblanchon/pdfium-binaries) `pdfium-linux-x64.tgz` 3.7 MB (glibc), musl 7.3 MB; pdfium BSD-3 | yes | yes | trivial; pin the binary | none (primitives only) | **keep** |
| **Xberg** (ex-Kreuzberg) | 1.2.9 (2026-09-24) | MIT; **was Elastic-2.0 for 4.8.0–4.10rc (Apr–Jul 2026)** / Heron and Paddle Apache-2.0, TATR MIT, fetched from HF at runtime | default engine is **xberg-native-pdf** (a pure-Rust pdf_oxide fork); pdfium is an opt-in dlopen; ORT for layout; vendored Tesseract | yes | async (tokio) API; own C FFI is glibc-only | CLI 56.5 MB; FFI tarball 381 MB; `ort-bundled` needs glibc ≥2.38 | 3 deterministic tiers + opt-in TATR/SLANeXt matched to native words | **borrow parts, don't depend** |
| **LiteParse v2** (LlamaIndex) | 2.14.7 (2026-09-22) | Apache-2.0 | **Rust on PDFium**, no ML; Tesseract or HTTP OCR optional | yes | Rust | small | ruled grid + inferred column tracks (`tables.rs`, 6.5k lines) | **borrow parts** (closest to our core) |
| **docling.rs** | 1.69.1 (2026-09-23) | MIT / Heron Apache-2.0, TableFormer CDLA-P-2.0/Apache | pdfium (rendering), `ort`, lopdf | yes | has a C ABI crate | amd64 images published | Heron + TableFormer ONNX + cell matching | **borrow parts**; young (3 months), single maintainer |
| **pdf_oxide** | 0.3.78 (2026-09-08) | MIT/Apache-2.0 (the name is trademarked) | none, pure Rust | yes | cdylib + C ABI | 11.4 MB lib | ruling lines + span clustering (4k+ LOC) | borrow ideas; not a second parser |
| **ferrules** | 0.1.11 (2026-02-18) | **GPL-3.0** / YOLOv8-DocLayNet **AGPL** | pdfium, ORT | yes | — | — | lattice / stream / TATR | **banned**; don't even read it (clean-room risk) |
| **extractous** | 0.3.0 (2024-12-21) | Apache-2.0 | GraalVM `libtika_native`, Tesseract | yes | links a large dylib | 42 MB wheel | none | stale; no |
| **lopdf** | 0.45.0 (2026-09-08) | MIT | none | yes | yes | trivial | none | fallback object parser only |
| **ort + ONNX models** | ort 2.0.0-rc.13; ONNX Runtime 1.30.0 (11 MB tgz) | MIT/Apache-2.0 | onnxruntime .so (use `load-dynamic`) | yes | yes | +11 MB and the models | see below | optional; later |

**ONNX models we could run via `ort`** (weights licence first):

| model | weights licence | size | use |
|---|---|---|---|
| TATR (Table Transformer) | **MIT** | int8 ~30 MB | table structure detection |
| SLANet_plus | Apache-2.0 | 7.8 MB | table structure (borderless) |
| PP-LCNet table classifier | Apache-2.0 | 6.8 MB | wired vs wireless table |
| Docling Heron RT-DETRv2 | Apache-2.0 | 169–172 MB; int8 68 MB | layout |
| PP-DocLayoutV3 | Apache-2.0 | 131.7 MB | layout **plus reading order** |
| TableFormer | CDLA-P-2.0 / Apache-2.0 (the per-file split is unverified) | 3 graphs, ~200 MB | table structure |

**Banned weights:**
- Anything from Ultralytics YOLO: AGPL, including DocLayout-YOLO and yolo-doclaynet.
- MinerU2.5-2509: AGPL.
- The Surya layout model: CC-BY-NC-SA per its card.
- Marker, Surya and Chandra weights: OpenRAIL-M with revenue caps; Chandra adds a non-compete.

**Xberg, evaluated concretely** (`xberg-io/xberg` @ `b4331e0`).
- **API.** `xberg::extract(ExtractInput::from_uri(..), &ExtractionConfig) -> Result<ExtractionResult>` is `async`.
- **Table type.** `Table { cells: Vec<Vec<String>>, markdown, page_number, bounding_box }` (`types/tables.rs:12-41`).
- **Default table method, deterministic.** Three tiers in `pdf/native/table.rs`: a strict ruled grid, a relaxed ruled grid, then text-heuristic reconstruction (`table_core.rs`). About 4.8k lines of validators in `pdf/table_reconstruct.rs` reject fake tables built from prose.
- **Opt-in model method.** `layout-detection` runs RT-DETR layout, then **TATR** structure by default (SLANeXt optional). Predicted cells are **matched to native PDF words**, so born-digital pages need no OCR (`pdf/structure/regions/table_recognition.rs:92-104`).
- **Models** are downloaded from Hugging Face at runtime, pinned by SHA-256 (`layout/model_manager.rs`).
- **Binary size.** The CLI is 56.5 MB (gnu) and the FFI tarball 381 MB (contents unverified). The crate itself is 4.9 MB.
- **Its pdfium backend "does no table detection, no layout, no OCR"** (`extractors/pdf/pdfium_engine.rs:1-17`).
- **Why not a dependency:**
  - Its default engine is not pdfium, and its pdfium backend skips the tables we would want it for.
  - Licence churn: MIT → ELv2 → MIT in 2026 ([crates.io history](https://crates.io/api/v1/crates/kreuzberg/versions)); stale ELv2 text is still in `ATTRIBUTIONS.md`.
  - 24 releases in 2 months, with breaking renames.
  - A tokio/reqwest/hf-hub runtime download path, which conflicts with "the host owns the network".
- **Its MIT code at `b4331e0` is the best-organised set of borrowable deterministic parts found** (§8).

**The one warning from docling.rs.** It **retired pdfium's text path** for a lopdf glyph parser. Its reason:
pdfium's glyph boxes do not match docling-parse on generated spaces, combining marks and ligatures
([PDF_CONFORMANCE.md](https://github.com/docling-project/docling.rs/blob/master/docs/PDF_CONFORMANCE.md)).
- That was about **byte-conformance with Python docling**, not about correctness.
- For us it means one concrete thing: **treat pdfium's generated characters explicitly** (`FPDFText_IsGenerated`, the `0x2` hyphen, generated spaces and CRLF), and never feed them to the gate as if they were printed.

---

## 3. What we can do deterministically from pdfium characters (question 3)

pdfium already gives us the inputs. pdfium-render 0.9.2 `PdfPageTextChar` exposes:
- `tight_bounds`/`loose_bounds`, `origin`, `angle`;
- `scaled_font_size`, `font_weight`, `font_is_bold_reenforced`, `font_is_italic`;
- `render_mode` (render mode 3 is invisible text, i.e. an OCR layer);
- `is_generated`, and `is_hyphen` (behind the pdfium-version feature).

It also gives page path objects (`segments`, `fill_mode`) for ruling lines, and raw bindings for the
tagged structure tree: `FPDF_StructTree_GetForPage`, `FPDF_StructElement_GetType`,
`…GetMarkedContentID`, `…Attr_*` (RowSpan/ColSpan), `GetActualText`, `GetLang`.
These are in the pdfium-render 0.9.2 source in `~/.cargo/registry` and in [fpdf_text.h](https://pdfium.googlesource.com/pdfium/+/refs/heads/main/public/fpdf_text.h).

| capability | deterministic recipe | best permissive reference to borrow | needs a model? |
|---|---|---|---|
| **Hyphen join** | pdfium marks a line-end `-`/U+00AD with `set_char_type(kHyphen); set_unicode(0x2)` and **suppresses the line break** ([cpdf_textpage.cpp](https://pdfium.googlesource.com/pdfium/+/refs/heads/main/core/fpdftext/cpdf_textpage.cpp), `ProcessGenerateCharacter`; `IsHyphenCode` = 0x2D, 0xAD only). Join, *unless* (a) the next token is a coordinating conjunction ("in- en verkoop"); (b) the next character is upper-case or a digit ("Noord-Holland"); (c) the **same document** contains the hyphenated form unbroken ("e-mail", "long-term"), a "witness". Rule (c) is what the spike lacks: its regex joins `e\x02mail`→`email` and `long\x02term`→`longterm` (probe, §5 W9). Keep a `joined_hyphen` provenance bit so a quote can still match the printed form. | pdftext `handle_hyphens` (Apache); Xberg `collect_hyphen_witnesses` / `should_preserve_lexical_hyphen` (`pdf/structure/pipeline.rs:5635-5891`, MIT) | no |
| **Lines, columns** | cluster chars into words (gap > k·font size), words into lines (baseline overlap), lines into blocks (Docstrum or XY-cut) | [XY-Cut++, arXiv 2504.10258](https://arxiv.org/abs/2504.10258) (98.8 BLEU on DocBench-100), Apache port in opendataloader `XYCutPlusPlusSorter.java`; pdf_oxide `pipeline/reading_order/xycut.rs` (MIT) | no |
| **Reading order** | **tagged PDF: pre-order walk of `/StructTreeRoot`** (pdf_oxide `ReadingOrder::Structure`, [v0.3.75](https://github.com/yfedoseev/pdf_oxide/releases)); untagged: rule-based up/down adjacency | docling `reading_order_rb.py` (MIT), already ported to Rust in docling.rs `reading_order.rs` (MIT) | no. PP-DocLayoutV2/V3 learn it, but that is optional |
| **Ruled tables** | horizontal/vertical path segments **and thin filled rectangles** → snap (tolerance) → join → intersections → cells → fill from chars | pdfplumber `lines` strategy (Nurminen thesis; [MIT](https://github.com/jsvine/pdfplumber)); LiteParse `tables.rs` (Apache, Rust, pdfium); Xberg `pdf/native/table.rs` tiers | no |
| **Borderless tables** | column tracks from x-alignment of word edges across ≥3 lines, rows from baselines; **score the candidate grid**; reject prose-shaped grids | Marker `processors/table_recon.py` (Apache: garble check, header band, projection-profile grid search, score, VLM fallback below 0.75); Xberg `table_core.rs` + `table_reconstruct.rs` validators (MIT) | only when the score is low |
| **Tagged tables** | `/Table`→`/TR`→`/TH`/`/TD` + RowSpan/ColSpan attributes; map MCIDs to chars | pdfium raw bindings (above); pdf_oxide shows the MCID-to-span map (Word-tagged headings recover the full hierarchy) | no |
| **Headings** | 1) struct-tree `/H1..H6`; 2) PDF outline/bookmarks; 3) numbering patterns (§, 1.1, I.3); 4) font-size/weight clustering. Emit a level only when sources agree (Docling's "wrong level worse than none") | docling heading_levels / docling.rs `heading_hierarchy.rs`, `outline.rs` (MIT); Xberg `pdf/hierarchy/clustering.rs` (MIT) | no |
| **Running headers/footers** | a line in the top/bottom **~12% band**, digits → `#`, repeated on ≥half the pages; compare ±1 **and ±2** pages (odd/even); cap per band so data-bearing letterheads survive; **keep one copy** as tagged furniture (the spike's "laatst bijgewerkt" lesson) | LiteParse `markdown_layout/repetition.rs` (Apache); opendataloader `HeaderFooterProcessor.java` (Apache); [Lin 2003, page association](https://www.spiedigitallibrary.org/conference-proceedings-of-spie/5010/0000/Header-and-footer-extraction-by-page-association/10.1117/12.472833.short) | no |
| **Text-layer soundness** | U+FFFD / private-use / `GLYPH<…>` share, `HasUnicodeMapError`, duplicated OCR layer, invisible (render mode 3) or low-contrast text | Docling `rate_text_quality` (MIT); Marker garble check >2% PUA/FFFD (Apache); opendataloader `HiddenTextProcessor` (contrast < 1.2) | no |
| **Page routing** | reasons per page: scanned / no-text / sparse / embedded-images / garbled / vector-text; ruled-grid present; ≥3 aligned-gap lines; list markers | LiteParse `is-complex` reasons (Apache); opendataloader `TriageProcessor.java:633-706` (conservative: false positives allowed, misses not) | no |
| **Where a model is genuinely needed** | (1) scans and image regions without a text layer; (2) borderless tables whose best deterministic grid scores low; (3) figure descriptions; (4) optionally layout on untagged complex pages | TATR int8 (MIT) or SLANet_plus (Apache) matched to native words; the injected vision model for scans | yes |

**The spike's "layout-preserving text layer" came from GPL and AGPL tools.** `build_final.py:layout_text`
shells out to poppler `pdftotext -layout` (GPL-2.0-only OR GPL-3.0-only), and the routing signals come
from PyMuPDF (AGPL): `find_tables`, `get_drawings`, `get_pixmap`, `get_text(clip=…)` in rag_api
`app/ingestion/detection.py`. **None of that exists in our core.**
- The `-layout` text is a *rendering* of positions into spaces. We should give the model the **positioned
  lines** (or the deterministic candidate grid) instead of re-deriving spaces.
- `detection.py`'s grid heuristic counts only `"l"` drawing items (`:56-63`), not rectangles. Word and
  Excel exports often draw cell borders as thin filled rectangles, which is why pdfplumber's `lines`
  strategy also uses rectangle edges. This is a plausible cause of the "7 of 14 table documents
  detected" miss rate in results.md §5 (unverified; not measured).

---

## 4. How the leaders verify model output (question 4)

**Nobody we found checks model output against the PDF text layer.**
- olmOCR uses the text layer as a prompt prior (v1) and as a **fallback** when the model fails (pdftotext, `is_fallback=True`). It never compares the two.
- Marker's LLM processors check **shape only**:
  - table HTML must parse, have more than one cell, and end in `</table>`;
  - math output shorter than 0.6× the input is rejected;
  - page correction checks that block IDs are the same set.
- Docling's confidence report grades layout, OCR and text parse; `table_score` is "not yet implemented".
- Vendor APIs (Mistral 4.1, Azure, Textract, Google) return **model confidences** and **span/offset provenance**, not checks.

The spike's gate is therefore **novel**, and there is no external evidence that it beats alternatives.
It must be measured on our own fixtures.

| mechanism | who | deterministic? | what it catches | vs ours |
|---|---|---|---|---|
| Text-layer-sourced cells (text never generated) | Marker v2 `table_recon.py`, LiteParse, Xberg native, opendataloader; TFLOP "layout pointer" ([arXiv 2501.11800](https://arxiv.org/abs/2501.11800); code **CC-BY-NC**, idea only) | yes | every substitution, rounding, invented digit, by construction | **stronger**; it removes the class instead of testing for it |
| Span/offset provenance (every output span → offsets into the text) | Azure `spans`, Google `TextAnchor`, Textract geometry, Mistral blocks | yes (structure) | makes every value citable to a location | we record per-page provenance only |
| Sequence alignment of output to text-layer tokens (Needleman–Wunsch) | [local-llm-pdf-ocr](https://github.com/ahnafnafee/local-llm-pdf-ocr) (MIT) | yes | order changes, moved values; gives a bbox per output span | **stronger** than bag-of-words |
| Multiset coverage/novelty (Counter, not set) | Unstructured SCORE, [arXiv 2509.19345](https://arxiv.org/abs/2509.19345), [code](https://github.com/Unstructured-IO/unstructured-eval-metrics) `content_scoring.py` (Apache) | yes | duplication, loops, spanned-cell repeats | ours uses **sets** (`check.py:words`) |
| Digit-frequency bag Σmin/Σexpected, HTML-attribute digits excluded | ParseBench `BagOfDigitPercentRule`, [arXiv 2604.08538](https://arxiv.org/html/2604.08538v2) (Apache) | yes | "6→8" substitutions, dropped digits | complements ours |
| Grid similarity (GriTS: 2D most-similar substructure; Con/Top/Loc) | [arXiv 2203.12555](https://arxiv.org/abs/2203.12555), `microsoft/table-transformer/src/grits.py` (MIT; drop the `fitz` import, which is AGPL) | yes | cell placement, merged or split rows | replaces "more rows wins" |
| Header-keyed record match | ParseBench TableRecordMatch (Apache) | yes | transposed or dropped headers | we have none |
| Neighbour tests (up/down/left/right/heading) | olmOCR-bench `TableTest` ([tests.py](https://github.com/allenai/olmocr/blob/main/olmocr/bench/tests.py), Apache) | yes | cell displacement | we have none |
| Loop / truncation guard (finish_reason, repeated n-gram tail >30, length ≥0.6×) | olmOCR `pipeline.py` + `repeatdetect.py`; Marker `llm_mathblock.py` | yes | degenerate generation | we have none |
| Retry at a rising temperature schedule, then fall back to the text layer | olmOCR `TEMPERATURE_BY_ATTEMPT` | yes (policy) | transient loops | we fall back immediately (fine) |
| Text-layer soundness before trusting it as ground truth | Docling `rate_text_quality`; Marker duplicate-layer detector | yes | a garbled layer that makes a wrong output pass or a right one fail | **we have none** |
| Model self-confidence or self-scores | Marker "score < 4", Mistral/Azure confidences | no | — | don't use as a gate |

**Where number checks fail** (from the verification sweep; some are my own analysis):
- NFKC is needed for superscript and full-width digits. Minus is U+2212 or an en dash. Separators include NBSP and thin space. Indian grouping is `1,00,000`. Negatives can be `(1.234)`.
- Footnote markers get glued to numbers (`2019¹`→`20191`).
- Dates get re-formatted, and bags hide day/month swaps.
- Models add numbers legitimately: list markers (already handled), `colspan="2"` attributes, LaTeX.
- Roman ↔ Arabic in either direction.
- Merged cells duplicated into each spanned cell pass a **set** check.
- **Swaps are invisible to any bag.**

Source for the observation that meaning-changing entity errors barely move CER/WER:
[arXiv 2607.24077](https://arxiv.org/html/2607.24077v3) (median CER 1.72% but mean 11.17%, so a few pages fail catastrophically).

---

## 5. Where spike 185 is weaker than the state of the art (question 5)

Ranked by damage to "never wrong". Each item has the fix.

**W1. The gate checks vocabulary, not placement. (The biggest weakness.)**
- `check.gate` compares **sets** of words and **sets** of digit strings.
- `numbers()` adds *every* bare digit run and every separator-stripped reading of the text layer. So `€ 5.100,00` licenses `5`, `100`, `0` and `510000`, and `_canon` discards the separator position.
- Probe results, synthetic page, strict thresholds 0.98/0.02, spike `check.py` @ `406a320d7`:

  | edit | strict gate |
  |---|---|
  | two amounts swapped across rows | **accept** |
  | `7.000,00`→`70.000,0` | **accept** |
  | `5.100,00`→`100` | **accept** |
  | "geen" moved to the other sentence | **accept** |
  | empty cell filled with an existing value and label | **accept** |
  | "geen" dropped | reject (cov 0.941); but it **passes** the vision thresholds (≥0.90) |

- The spike's own data shows this in practice: on the salaried-partner table, the vision grid "disagreed
  on 4 of 18 cells, passed the number check, and **replaced** gpt-oss", and came out worse (results.md §4).
- **Fix:**
  - (a) make cells text-layer-sourced (W2);
  - (b) align output to text-layer tokens (Needleman–Wunsch/LCS), and require each number to align to an
    occurrence **of the same value with the same separators, in the same row band and column band**;
  - (c) use multisets; canonicalise numbers *with* decimal position (locale-aware parse to a value, not a digit string);
  - (d) move to per-block coverage, not per-page.

**W2. The model writes the text; it should point at it.**
- Both paths regenerate the whole page. The text LLM rewrites the layout text layer; vision transcribes the image.
- The cost is already visible: FINAL loses 3 of 468 quotes and 8 of the hyphen-only 202 against plain dehyphenated text (results.md §3), from the model "re-wrapping" sentences.
- The text-layer leaders (Marker v2, LiteParse, Xberg, opendataloader, docling TableFormer cell matching) never let a model emit cell text on a page with a text layer.
- **Fix:** the model returns structure over IDs: line/word IDs → row/column, or a grid whose cells Rust re-fills from the matched characters.
  - A vision grid on a text-layer page is used only as a **structure hypothesis**, then projected onto pdfium characters.
  - Vision-*transcribed* text is kept only where there is no text layer (the scan / `vision_transcribed` case).

**W3. The measured stack is not the stack we will build.**
- 127/149 was produced with PyMuPDF (AGPL) detection, rendering and region text, poppler `pdftotext -layout` (GPL), and rag_api's `detection.py`.
- None of these may ship in the core. Every signal must be rebuilt on pdfium, and the acceptance number re-measured.
- **Fix:** treat 127/149 and 32/36 as the bar to re-earn on the pdfium stack, not as a property the design inherits.

**W4. The evidence is thin.**
- There are 149 cells and 36 rows in 7 tables. It was one run of non-deterministic models.
- The results say the answer-level change is "a wash within single-run noise", and cnx185v's 127 vs full-page vision's 126 is inside that noise.
- **Fix:**
  - Add a synthetic, redistributable conformance set with explicit hard cases: swapped cells, spanned cells, wrapped cells, borderless, two-column, Roman numbering, running headers, soft hyphens and compounds, a scan.
  - Write olmOCR-bench-style unit tests (presence, absence, order, cell-neighbour).
  - Keep Lex5 as a private acceptance run only.

**W5. "More rows wins" rewards the wrong thing.**
- Splitting a wrapped multi-line cell into extra rows, or a looping model, both *add* rows.
- **Fix:** choose between the grids by GriTS agreement and by geometric consistency with the text layer (each cell's characters inside one row band and one column band), not by count.

**W6. No text-layer soundness check.**
- The gate trusts the text layer as ground truth.
- A garbled layer (ToUnicode errors, U+FFFD, duplicated OCR layer, invisible or white text) makes wrong output pass or right output fail. anymd's 4,139 U+FFFD on the same corpus (results.md §7) shows these files exist.
- **Fix:** Docling-style `rate_text_quality` plus pdfium `HasUnicodeMapError`, render mode 3 and a contrast check. A page that fails routes as a *scan*, with provenance.

**W7. Scans are accepted unchecked.**
- A page with fewer than 30 non-space characters accepts any non-empty vision output (`check.py:gate`). There is no loop guard.
- **Fix:**
  - olmOCR's loop/truncation guards.
  - Two-reading agreement where it is affordable: two vision passes, or vision vs an OCR engine; flag disagreements.
  - Per-region `vision_transcribed` provenance (already planned). Consider refusing to *cite* vision-only numbers, not just flagging them.

**W8. Header/footer detection ignores position and odd/even layouts.**
- `running_words` is line-level, exact after digit masking, anywhere on the page, and needs ≥3 pages.
- **Fix:** borrow LiteParse's top/bottom band and letterhead cap, and opendataloader's ±1/±2-page pairing.

**W9. Dehyphenation is a Dutch regex and joins real compounds.**
- `_CONJ` is `en|of|tot|t/m`. Probes: `e\x02mail`→`email`, `co\x02operatie`→`cooperatie`, `long\x02term`→`longterm`.
- **Fix:** document-wide witnesses (Xberg), a conjunction list per language (from the CiteNexus language detector), and a provenance bit.

**W10. The structure tree is unused.**
- Tagged PDFs carry `/Table`/`/TR`/`/TD` and `/H1..` for free, and pdfium exposes them.
- How many Lex5 PDFs are tagged is **unknown** (not measured). Measure it first (`FPDF_StructTree_GetForPage` non-null and non-empty); it decides how much of the table problem is model-free.

**W11. Coverage is per page.**
- A page-level 0.98 lets one small block be dropped or invented on a long page.
- **Fix:** coverage per block or per table.

**What the spike gets right, and the field does not:**
- Refusing to let model output replace the base text without a deterministic check.
- Explicit fallback to the base text.
- Per-page provenance flags (`table_source`, `vision_transcribed`, `table_uncertain`).
- Prompts as config.
- Keeping running headers once instead of deleting them. Azure's `<!-- PageHeader -->` convention is the same idea.
- Its central insight: dehyphenation, not the converter, was the dominant loss (78 → 286 of 468 quotes).

---

## 6. Community verdict

The sources for this section:
- 29 Hacker News comment trees (Algolia API);
- 16 Reddit threads (r/LocalLLaMA, r/Rag, r/LangChain), read through chrome-agent in read-only mode;
- 4 leaderboards.

Everything below is **anecdotal** unless a benchmark is named. The two most detailed Reddit bake-offs
were posted by a vendor (hexread.com), who disclosed it. **No Dutch-specific thread was found.** The
European-language evidence is thin, and covers German, French, Danish and Hebrew.

### 6.1 Which tools win, and which part gets the credit

| tool | what practitioners credit | what fails | threads |
|---|---|---|---|
| **Docling** | Its **layout model (Heron)**. Kreuzberg/Xberg took it into Rust: "their layout model… is excellent" ([r/LocalLLaMA 1s0f5ar](https://www.reddit.com/r/LocalLLaMA/comments/1s0f5ar/kreuzberg_v450_we_loved_doclings_model_so_much/)). Common RAG default: "docling + markdown chunking" ([r/LangChain 1syu7vg](https://www.reddit.com/r/LangChain/comments/1syu7vg/pdf_parsing_for_rag_is_still_a_mess_in_2026_whats/)). | **TableFormer on custom-formatted tables** ([r/Rag 1vmi1xy](https://www.reddit.com/r/Rag/comments/1vmi1xy/no_one_knows_how_to_parse_tables_for_rag/), [r/Rag 1sk0reu](https://www.reddit.com/r/Rag/comments/1sk0reu/highprecision_table_extraction_from_complex_pdfs/)); multi-column ([HN 46315728](https://news.ycombinator.com/item?id=46315728)); speed (disputed) | ~14 |
| **Marker / Surya** | "solved a table conversion without LLM that docling wasn't able to" ([HN 43290561](https://news.ycombinator.com/item?id=43290561)); "preserves table structure" ([r/Rag 1oiylhk](https://www.reddit.com/r/Rag/comments/1oiylhk/best_open_source_pdf_parsers/)) | inline math (disputed by the author) | ~9 |
| **MinerU** | quality, and bboxes per block ([HN 45674352](https://news.ycombinator.com/item?id=45674352)) | **silently dropped an IBAN as "page furniture"**, and it can't be switched off; every heading becomes `#` ([r/LocalLLaMA 1vecxhw](https://www.reddit.com/r/LocalLLaMA/comments/1vecxhw/i_compared_mineru_granitedocling_and_paddleocrvl/)) | ~9 |
| **PaddleOCR (classic) / PP-DocLayoutV3** | **PP-OCR boxes**, "at a fraction of a fraction of the compute" ([r/LocalLLaMA 1sk6kst](https://www.reddit.com/r/LocalLLaMA/comments/1sk6kst/what_is_the_best_open_source_ocr_in_2026/)); **the PP-DocLayoutV3 slicer** that GLM-OCR and PaddleOCR-VL share, with XY-cut as the lower-tech alternative ([HN 48654714](https://news.ycombinator.com/item?id=48654714)) | invented "Maulevrier" for "Maude" ([r/LocalLLaMA 1vh7bxu](https://www.reddit.com/r/LocalLLaMA/comments/1vh7bxu/i_compared_even_more_parsers_on_14_pdfparsing/)); high-resolution input misses text | ~12 |
| **GLM-OCR** (MIT weights) | top recommendation in 1sk6kst; beat TableFormer on custom tables (1vmi1xy) | benchmark split: OmniDocBench 95.22 but **ParseBench 29.6** (grounding 0) | ~4 |
| **Chandra-2** | "14 of 14 faithful"; **skipped an illegible stain instead of guessing** (1vh7bxu) | weights OpenRAIL-M with a non-compete; 91 s/page on an L4 | ~4 |
| **Mistral OCR** | cheap, fast, good on old typeset scans ([HN 49291086](https://news.ycombinator.com/item?id=49291086)) | **OCR 4.0 "completely making up new sentences in the middle of a page"** ([HN 49294642](https://news.ycombinator.com/item?id=49294642)); back-translated Hebrew ([HN 43283252](https://news.ycombinator.com/item?id=43283252)) | ~8 |
| **LightOnOCR-2-1B** (Apache) | best speed and accuracy in one production report; the **only strong model whose HF tags include `nl`** | stopped mid-page; wrote fluent wrong text over a stain (1vh7bxu) | ~2 |
| **Xberg** | the closest analogue to a Rust core | on born-digital PDFs, where no OCR runs, **tables and column order fail** (1vecxhw); self-published benchmarks called "sus" ([r/LocalLLaMA 1r59th1](https://www.reddit.com/r/LocalLLaMA/comments/1r59th1/kreuzberg_v430_and_benchmarks/)) | ~4 |
| **markitdown** | — | "just uses pdfminer"; ParseBench **18.63** | 2 |
| **Nougat** | — | not mentioned once in 2025–26 | 0 |

### 6.2 A leaderboard the SOTA sweep lacked: ParseBench

[ParseBench](https://github.com/run-llama/ParseBench) ([arXiv 2604.08538](https://arxiv.org/abs/2604.08538)):
- About 2,078 pages of insurance, finance and government documents, with 169k rules.
- Vendor-published by LlamaIndex, whose LlamaParse Agentic Plus tops it at 90.20.
- Visual grounding counts toward the score, so OCR-only models without boxes are penalised.

Rows that matter here ([leaderboard.csv](https://raw.githubusercontent.com/run-llama/ParseBench/main/leaderboard.csv)):

| row | overall | tables | note |
|---|---:|---:|---|
| MinerU2.5-Pro-2605 | 72.78 | — | best open-weight |
| Chandra-2 | 70.1 | 89.2 | |
| PaddleOCR-VL-1.6 | 67.43 | — | |
| **PyMuPDF4LLM** | **53.49** | **72.0** | **best pure text-layer row** (AGPL, banned for us) |
| Docling-models | 50.65 | 66.41 | |
| LiteParse | 36.9 | — | |
| OpenDataLoader | 29.4 | — | |
| markitdown | 18.63 | 15.77 | |

The lesson is that a deterministic text-layer parser *can* reach 72 on tables. The permissive Rust/Java
ones we would borrow from are not there yet. That is why §8 #8 keeps a model fallback, and why our own
fixtures must decide.

**Other leaderboards:**
- [OCR Arena](https://www.ocrarena.ai/leaderboard) is human preference, not correctness ("Nicely formatted incorrect data is still incorrect", [HN 46044660](https://news.ycombinator.com/item?id=46044660)).
- [IDP Leaderboard](https://idp-leaderboard.org/) is run by Nanonets, which also leads it.
- The OmniDocBench v1.6 top 5 also includes **OvisOCR2 96.47**, which the §1.2 excerpt omits.

### 6.3 Warnings that recur, and which of our parts answers each

| warning (anecdotal) | examples | our answer |
|---|---|---|
| **VLMs "correct" numbers** | a line item changed so the total adds up ([HN 43164117](https://news.ycombinator.com/item?id=43164117)); 1.001E-11 read as 1.001E-04 and rows mixed up ([HN 46044660](https://news.ycombinator.com/item?id=46044660)); "over 50% hallucinated values in complex financial tables" ([HN 43201001](https://news.ycombinator.com/item?id=43201001)) | borrow #1 and #5. A bag check would pass a row mix-up; §5 W1 |
| **Silent drops** | footers, footnotes, line items, page ends: [1vecxhw](https://www.reddit.com/r/LocalLLaMA/comments/1vecxhw/), [HN 46977346](https://news.ycombinator.com/item?id=46977346), [HN 42976697](https://news.ycombinator.com/item?id=42976697), 1vh7bxu. "Parser accuracy and text survival are not the same measurement" ([r/Rag 1v94yfz](https://www.reddit.com/r/Rag/comments/1v94yfz/if_you_were_building_a_fully_local_rag_system_for/)) | per-block coverage (#5); furniture kept as tagged metadata, never deleted (#14) |
| **Fluent fabrication over illegible regions** | [HN 42956082](https://news.ycombinator.com/item?id=42956082), [HN 42959916](https://news.ycombinator.com/item?id=42959916) | scans stay `vision_transcribed`; don't cite vision-only numbers (W7) |
| **Repetition loops, especially in markdown tables** | [HN 43164117](https://news.ycombinator.com/item?id=43164117), [HN 42953438](https://news.ycombinator.com/item?id=42953438) | #12 guards |
| **Unwanted translation** of non-English pages | [HN 43283252](https://news.ycombinator.com/item?id=43283252), [HN 48650741](https://news.ycombinator.com/item?id=48650741), [HN 45839252](https://news.ycombinator.com/item?id=45839252) | coverage and novelty catch it on text-layer pages; for scans, check the output language (CiteNexus already has lid.176) |
| **Practitioners' own verification** | quote-exists-in-source ([HN 49292754](https://news.ycombinator.com/item?id=49292754)); 2–3 models compared ([HN 42956144](https://news.ycombinator.com/item?id=42956144)); classic OCR + LLM fixer ([HN 46332411](https://news.ycombinator.com/item?id=46332411)) | the same instincts as spike 185; #1 and #5 make them structural |

**Community verdict:**
- The practitioners who report the best *faithfulness* on real documents either take text from the text
  layer or classic OCR boxes, using a model only for layout or structure (Marker, PaddleOCR classic + fixer,
  Docling's layout model), or use a VLM and **verify it externally** (a second model, or a quote-exists check).
- Nobody reports a tool they trust unverified on financial tables.
- For Dutch, there is no benchmark and no thread. Our Lex5 fixtures are the only evidence we will have.

---

## 7. Comparison table (wider sweep)

For each project: licence, runtime, whether it uses the text layer, its table method, a published number where one exists, and its last activity (GitHub `pushed_at` or the HF model date, fetched 2026-09-24).

| project | licence code / weights | runtime | text layer? | tables | published number (source) | last | take? |
|---|---|---|---|---|---|---|---|
| Docling | MIT / Apache, CDLA-P | CPU | yes | TableFormer + cell match | olmOCR-B 50.3 (competitor run) | 2026-09-22 | parts (MIT) |
| docling.rs | MIT / as above | CPU | yes (lopdf) | TableFormer ONNX | 9/17 byte-exact vs docling (own) | 2026-09-23 | parts |
| Marker v2 + pdftext | Apache / OpenRAIL-M | CPU (+GPU) | **yes** | text-layer grid search + VLM fallback | olmOCR-B 76.0 balanced, 83.5 digital (own) | 2026-09-13 | **parts** |
| LiteParse v2 | Apache | CPU, **Rust + pdfium** | **yes** | ruled + inferred tracks | ODL-bench 0.886 (own) | 2026-09-22 | **parts** |
| opendataloader-pdf | Apache (veraPDF MPL) | CPU, Java | yes | ruling lines + clustering; hybrid backend | ODL-bench hybrid 0.907 (own) | 2026-09-22 | parts (algorithms) |
| Xberg | MIT / Apache, MIT | CPU | yes | 3 deterministic tiers + TATR | vendor, 60 docs, no table metric | 2026-09-24 | parts (pinned) |
| pdf-inspector (Firecrawl) | MIT | CPU, Rust | yes | rect + alignment heuristics | ODL-bench 0.875, TEDS 0.814 (own) | 2026-09-23 | ideas |
| pdf_oxide | MIT/Apache | CPU, Rust | yes | ruling + spans | parse rate only (own) | 2026-09-22 | ideas (struct tree) |
| oxidize-pdf | MIT | CPU, Rust | yes | — | — | 2026-09-24 | no |
| pdf-extract (crate) | MIT | CPU, Rust | yes | none | — | 2026-09-16 | no |
| **deepdiy/pdf2md** | README MIT, but **links MuPDF (AGPL)** / YOLO26n-DocLayNet **AGPL** | CPU, Rust + ncnn | yes (MuPDF lines assigned to boxes) | **none**: tables saved as PNG crops | none; feature checklist only | 2026-05-18 (4 commits, 28★) | **ideas only** |
| MinerU 4 / 2.5-Pro | custom Apache+ / AGPL (2509), Apache (Pro) | GPU (flash CPU) | flash only | SLANet+/UNet or VLM | ODB 95.75 (Pro) | 2026-09-24 | Paddle models directly, not MinerU code |
| PaddleOCR-VL 1.6 | Apache / Apache | GPU | no | VLM per crop | ODB 96.34 (repro 95.25) | 2026-08-11 | layout/order model only, maybe |
| OpenDoc-0.1B (OpenOCR) | Apache / Apache | CPU-plausible | no | 0.1B recogniser | ODB v1.6 90.67 | 2026-09-21 | watch |
| GLM-OCR 1.3B | MIT (HF) | GPU | no | VLM | ODB 95.22 | 2026-09-11 | host-side model option |
| TeleOCR 1.2B | not checked | GPU | no | VLM | ODB 96.91 | — | not checked |
| olmOCR 2 | Apache / Apache | GPU 7B | v1 only | VLM | olmOCR-B 82.4 | 2026-03-25 | guards + bench design |
| Chandra 2 | Apache / OpenRAIL + non-compete | GPU | no | VLM | olmOCR-B 85.8 (own) | 2026-06-26 | no (weights) |
| Mistral OCR 4.1 | proprietary API | API | ? | VLM | olmOCR-B 85.20 (own) | 2026-07-16 | host-side option |
| dots.ocr | MIT + agreement / MIT | GPU | no | VLM with bbox | ODB 90.77 | 2026-03-24 | bbox-output idea |
| DeepSeek-OCR(-2) | MIT / MIT, Apache | GPU | no | VLM | olmOCR-B 75.7; ODB 90.25 | 2026-02 | host-side option |
| Dolphin 1.5 / v2 | Qwen Research repo; HF MIT / none | GPU | no | anchor-then-parse | ODB 89.50 (v2) | 2026-03-25 | no (licence unclear) |
| MonkeyOCR | Apache / v1 non-commercial | GPU | no | VLM | ODB 88.57 (pro-3B) | 2026-07-20 | no |
| Nanonets-OCR2-3B | Qwen-research base (unverified) | GPU | no | VLM | olmOCR-B 69.5 | 2025-10-16 | no |
| SmolDocling / GraniteDocling | CDLA-P / Apache | CPU-feasible | no | OTSL | FinTabNet 0.97/0.96 (card) | 2025-09 | host-side option |
| GOT-OCR2 | no repo licence / Apache | GPU | no | VLM | — | 2025-02 | no |
| Nougat | MIT / **CC-BY-NC** | GPU | no | VLM | own arXiv set only | 2025-02 | no |
| zerox | MIT; needs ghostscript (AGPL) or poppler (GPL) | API | no | VLM | none | 2025-05 (stale) | no |
| unstructured | Apache / unverified | CPU/GPU | yes | model | ODL-bench hi_res 0.841 | 2026-09-24 | SCORE metric only |
| surya / texify | Apache / OpenRAIL-M; texify **GPL, archived** | GPU | no | model | — | 2026-09-11 | no |
| pymupdf4llm | **AGPL** | CPU | yes | heuristic | ODL-bench 0.732 | 2026-09-23 | **banned** |
| markitdown | MIT | CPU | yes | x-gap heuristic | spike: 84/149 cells | 2026-09-21 | no |
| pdfplumber / Camelot / Tabula | MIT / MIT (ghostscript optional, AGPL) / MIT | CPU | yes | lines/text strategies; lattice/stream | — | 2026-08 / 2026-09 / 2025-03 | **algorithms** (Nurminen) |
| pdfminer.six / pypdfium2 | MIT / Apache-or-BSD | CPU | yes | — | — | 2026 | no |
| RapidTable (SLANet ONNX) | Apache / Apache | CPU, 0.15 s/table (own) | needs OCR boxes | image → structure | — | 2026-04 | model option |
| TATR | MIT / MIT | CPU | no | DETR structure | — | archived 2024-06 | model option (int8 30 MB) |
| anymd (Go) | MIT | CPU | yes | none | spike: glyph-order bug on 14/69 | 2026-09-09 | no |
| gopdf (Go) | MIT | CPU | yes | header anchors + gaps | — | 2026-09-24 | no |
| unipdf (Go) | commercial | CPU | yes | yes | — | 2026-09 | no |
| ferrules | **GPL-3.0** / AGPL | CPU | yes | lattice/stream/TATR | — | 2026-04 | **banned** |
| DocLayout-YOLO / Ultralytics | **AGPL** | — | — | — | — | — | **banned** |

**deepdiy/pdf2md in detail** ([repo](https://github.com/deepdiy/pdf2md) @ `38f352f`).
- **Stack.** About 1,050 lines of Rust. The `mupdf 0.6` crate statically links MuPDF (AGPL), so the MIT licence file is misleading. The Ultralytics `yolo26n-doclaynet` ncnn model has `license: AGPL-3.0` in its `metadata.yaml`.
- **Layout.** Renders the page at 72 DPI and detects the 11 DocLayNet classes.
- **Text.** MuPDF lines are assigned to the smallest box that contains the line's centre (`pdf2md.rs:534-547`). **Lines outside every box are dropped silently.**
- **Reading order.** Zone cutting plus a two-column test (`:387-518`); three or more columns are not handled.
- **Headings.** Only `#` and `##`.
- **Tables, formulas, pictures.** Saved as PNG crops, so no table text at all.
- **Other gaps.** Page headers are emitted as images on every page. No hyphenation handling, no OCR, no benchmarks.
- **Maintenance.** Created and last pushed 2026-05-18; the build hardcodes `/opt/homebrew`.
- **What to take (ideas only):**
  - "detector types the region, the text layer fills it", which gives numbers ⊆ text layer by construction;
  - the orphan-line accounting it lacks, which *is* our coverage gate;
  - detect at 72 DPI and render high DPI only for crops.

**Papers worth knowing:**
- [XY-Cut++](https://arxiv.org/abs/2504.10258) for reading order.
- [TFLOP](https://arxiv.org/abs/2501.11800): the model points at text boxes. Code is CC-BY-NC, so idea only.
- [SPRINT](https://arxiv.org/abs/2503.11932): script-agnostic table structure, MIT, multilingual MUSTARD set; relevant to Tamil and Telugu.
- [GriTS](https://arxiv.org/abs/2203.12555).
- [Consensus Entropy](https://arxiv.org/abs/2504.11101): training-free agreement across several VLMs.
- [KIE-HVQA](https://arxiv.org/abs/2506.20168) on OCR hallucination.

---

## 8. Recommendations for CiteNexus: the BORROW LIST

Ranked by (value to "never wrong") ÷ (effort). "Det." means deterministic. Effort estimates are rough.
Every licence must be re-checked at the pinned commit before code is copied. Where we *port* rather than
copy, keep the upstream notice (MIT/Apache attribution) in `rust/NOTICE`.

| # | part | where it lives | det./model | licence code / weights | fit in our pdfium core, effort | evidence it beats alternatives |
|---|---|---|---|---|---|---|
| 1 | **Structure-not-text contract**: the model returns a grid over text-layer word IDs (or a grid Rust re-fills from matched characters); vision text is used only where there is no text layer | idea: TFLOP ([arXiv 2501.11800](https://arxiv.org/abs/2501.11800)); implementations: Xberg `pdf/structure/regions/table_recognition.rs:92-104`, docling TableFormer cell matching, Marker `table_recon.py` | det. assembly around an injected model | Xberg MIT; docling MIT; TFLOP idea only (code CC-BY-NC) | Changes the two-phase request/response schema; 1–2 weeks | removes W1's whole error class by construction; TFLOP reports SOTA on PubTabNet/FinTabNet (paper) |
| 2 | **pdfium U+0002 hyphen join with witnesses** | pdfium `cpdf_textpage.cpp` `ProcessGenerateCharacter`; pdftext `handle_hyphens`; Xberg `pipeline.rs:5635-5891` | det. | Apache / MIT | ~2 days; fixes a reported gap | spike: +208/468 quotes from dehyphenation alone |
| 3 | **Page-complexity router with reasons** | LiteParse `extract.rs` `is-complex`; opendataloader `TriageProcessor.java:633-706` | det. | Apache / Apache | Maps onto plain / formatted / table / image / scan; exposes signals; ~1 week | ODL-bench hybrid 0.907 vs local 0.831 (own run) |
| 4 | **Text-layer soundness gate** | Docling `rate_text_quality` (`page_preprocessing_model.py`); Marker `table_recon.py:40-48`; opendataloader `HiddenTextProcessor.java`; pdfium `HasUnicodeMapError`, render mode | det. | MIT / Apache / Apache | ~2 days | shipped in Docling and Marker; no published accuracy |
| 5 | **Alignment gate**: multiset coverage + digit bag + NW/LCS alignment + locale-aware value parsing + per-block coverage + row/column band geometry | SCORE `content_scoring.py`; ParseBench `rules_bag.py`; local-llm-pdf-ocr (NW); ours for geometry | det. | Apache / Apache / MIT | Replaces `check.py`'s sets; ~1 week; conformance vectors in `conformance/cases/` | closes the W1 probes (all accepted today) |
| 6 | **Tagged-PDF structure tree** (reading order, headings, tables with spans) | pdfium `FPDF_StructTree_*` / `FPDF_StructElement_Attr_*` raw bindings; pdf_oxide `ReadingOrder::Structure` for the approach | det. | BSD-3 (pdfium) / MIT-Apache | ~1 week; measure the tagged share first | pdf_oxide v0.3.75 notes: Word-tagged docs recover the full heading hierarchy |
| 7 | **Header/footer detector** (band + repetition + ±2-page pairing + letterhead cap, keep once as furniture) | LiteParse `markdown_layout/repetition.rs`; opendataloader `HeaderFooterProcessor.java`; Xberg `classify.rs:1745` | det. | Apache / Apache / MIT | ~2 days | LiteParse olmOCR-B headers_footers 55.8 with no OCR (own); Marker's fuzzy version 95.9 (own) |
| 8 | **Deterministic tables**: ruled grid (lines **and** rects) + inferred column tracks + scored grid search + fake-table validators; score below threshold → model | LiteParse `tables.rs`; Marker `table_recon.py` + `table.py:109-126`; Xberg `table_core.rs`, `table_reconstruct.rs` | det. | Apache / Apache / MIT | 2–3 weeks | Marker **replaced its table model** with this (v2); LiteParse TEDS 0.818 (own); Marker no-OCR tables 46.1 vs 73.4 balanced, so keep the model fallback |
| 9 | **Reading order**: struct tree → docling rule-based → XY-Cut++ fallback | docling `reading_order_rb.py`, docling.rs `reading_order.rs`; opendataloader `XYCutPlusPlusSorter.java` | det. | MIT / Apache | ~1 week | XY-Cut++ 98.8 BLEU on DocBench-100 (paper) |
| 10 | **Heading levels**: struct tree → outline → numbering → font clustering; emit only on agreement | docling heading_levels, docling.rs `heading_hierarchy.rs`/`outline.rs`; Xberg `clustering.rs` | det. | MIT | ~3 days | docling's documented rationale; no benchmark |
| 11 | **Grid selection by GriTS + neighbour tests**, replacing "more rows wins" | `table-transformer/src/grits.py` (`factored_2dmss`, `align_1d`); olmOCR-bench `TableTest` | det. | MIT (drop `fitz`) / Apache | ~250 LOC | GriTS paper: direct grid metric vs indirect TEDS/adjacency |
| 12 | **Model-output guards**: finish_reason, repeated n-gram tail, length floor; retries at a rising temperature before fallback | olmOCR `pipeline.py`, `repeatdetect.py`, `bench/tests.py BaselineTest`; Marker `llm_mathblock.py` | det. | Apache | ~1 day | used as olmOCR's RL reward and bench gate |
| 13 | **Optional small table model** (later, only if #8's score misses too often): TATR int8 or SLANet_plus via `ort`, cells matched to native words | Xberg `layout/models/tatr.rs` (pre/post, MIT); HF `microsoft/table-transformer-structure-recognition`; PaddlePaddle SLANet_plus | model | MIT / **MIT** (TATR); Apache / Apache (SLANet_plus 7.8 MB) | +11 MB ORT + 8–30 MB model; 1–2 weeks; or keep it host-side behind the model seam | no independent TEDS on our docs; measure first |
| 14 | **Furniture as tagged metadata, not deletion** | Azure markdown `<!-- PageHeader="…" -->` | format | n/a | ~1 day | keeps "laatst bijgewerkt <date>" citable |
| 15 | **Conformance design**: olmOCR-bench-style unit tests (present / absent / order / cell-neighbour) on synthetic PDFs | `olmocr/bench/tests.py` | det. | Apache (check the bench *data* licence separately) | fits `conformance/cases/` | olmOCR 2 trains on exactly these tests |

**Don't take:**
- **Xberg as a dependency.** Its default engine isn't pdfium, its pdfium backend does no tables, the licence changed twice in 2026, it has an async + HF-download runtime, and its churn is high. Take its MIT code at a pinned commit instead.
- **Anything AGPL or GPL.** PyMuPDF, pymupdf4llm and MuPDF (so pdf2md's binary), poppler `pdftotext` (the spike's layout text), ghostscript, ferrules, texify, Ultralytics / DocLayout-YOLO / yolo-doclaynet weights, and MinerU2.5-2509 weights.
- **Non-commercial or restricted weights.** Nougat (CC-BY-NC), the Surya layout model (CC-BY-NC-SA), Marker/Surya/Chandra (OpenRAIL-M caps; Chandra adds a non-compete), Qwen2.5-VL-3B derivatives (Nanonets-OCR, likely Dolphin-v2), MonkeyOCR v1, and TFLOP code.
- **MinerU wrapper code.** It carries custom Apache+ terms. Take the Paddle models directly.
- **"More rows wins".** It rewards splitting and looping; see #11.
- **Model self-scores and confidences as a gate.** A self-grade is not evidence.
- **Anchoring the prompt with the text layer** as the defence. It measured +0.8 on olmOCR-bench and was dropped by its authors; use the text layer as source and check (#1, #5).
- **PaddleX's `-\n` strip and Docling's unconditional continuation merge.** Both destroy real compounds.
- **Big VLM recognisers inside the core** (PaddleOCR-VL, MinerU2.5-Pro, olmOCR 2). They stay host-side behind the injected model seam (ADR-0014; the two-phase design).

**The order for the build:**
1. **Measure the tagged share of Lex5 first.** It is a one-evening probe.
2. Then **#2 → #4 → #3 → #7 → #9/#10**: base-extractor quality, no models.
3. Then **#5 + #1**, the new gate and contract; port spike 185's 11 tests as conformance vectors plus the W1 probes as *must-reject* cases.
4. Then **#8** (deterministic tables).
5. Then the model hooks.
6. **#13 only if measured necessary.**
7. **Acceptance:** re-earn ≥127/149 cells and 32/36 rows on the pdfium stack.

---

## 9. Sources

Primary sources used above, grouped. Commit SHAs are those read on 2026-09-24.

**pdfium and the current core**
- pdfium `core/fpdftext/cpdf_textpage.cpp`: https://pdfium.googlesource.com/pdfium/+/refs/heads/main/core/fpdftext/cpdf_textpage.cpp
- `public/fpdf_text.h`: https://pdfium.googlesource.com/pdfium/+/refs/heads/main/public/fpdf_text.h
- `public/fpdf_structtree.h`: https://pdfium.googlesource.com/pdfium/+/refs/heads/main/public/fpdf_structtree.h
- pdfium-binaries chromium/8066: https://github.com/bblanchon/pdfium-binaries
- pdfium-render: https://github.com/ajrcarey/pdfium-render
- CiteNexus `rust/src/extract/pdf.rs` and `rust/Cargo.toml` @ `f5665e9`

**Spike 185** (Volentis worktree @ `406a320d7`, read in place, not copied): `check.py`, `test_check.py`, `build_final.py`, `prompts.json`, `results.md`; rag_api `app/ingestion/detection.py`.

**Tools and repos**
- Docling: https://github.com/docling-project/docling
  - model catalog: https://docling-project.github.io/docling/usage/model_catalog/
  - confidence scores: https://docling-project.github.io/docling/concepts/confidence_scores/
- docling.rs: https://github.com/docling-project/docling.rs
- Heron: https://huggingface.co/docling-project/docling-layout-heron and https://arxiv.org/html/2509.11720v1
- GraniteDocling: https://huggingface.co/ibm-granite/granite-docling-258M
- MinerU: https://github.com/opendatalab/MinerU; DocVortex: https://github.com/myhloli/DocVortex
- PaddleOCR: https://github.com/PaddlePaddle/PaddleOCR; PaddleX: https://github.com/PaddlePaddle/PaddleX
- Marker: https://github.com/datalab-to/marker; pdftext: https://github.com/datalab-to/pdftext; chandra: https://github.com/datalab-to/chandra; surya: https://github.com/datalab-to/surya
- Nougat: https://github.com/facebookresearch/nougat
- olmOCR: https://github.com/allenai/olmocr
- Mistral: https://docs.mistral.ai/capabilities/document_ai/basic_ocr, https://docs.mistral.ai/resources/changelogs, https://mistral.ai/news/ocr-4/
- Azure: https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/prebuilt/layout, https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/concept/accuracy-confidence
- Google Document AI: https://docs.cloud.google.com/document-ai/docs/reference/rest/v1/Document
- AWS Textract: https://docs.aws.amazon.com/textract/latest/dg/API_Block.html
- markitdown: https://github.com/microsoft/markitdown
- Xberg: https://github.com/xberg-io/xberg (@ `b4331e0`); Kreuzberg LTS: https://github.com/kreuzberg-dev/kreuzberg-lts; benchmarks: https://xberg.io/benchmarks
- LiteParse: https://github.com/run-llama/liteparse (@ `b754dc3d`)
- opendataloader-pdf: https://github.com/opendataloader-project/opendataloader-pdf (@ `323578b`)
- pdf-inspector: https://github.com/firecrawl/pdf-inspector
- pdf_oxide: https://github.com/yfedoseev/pdf_oxide and https://github.com/yfedoseev/pdf_oxide/releases
- ferrules: https://github.com/AmineDiro/ferrules; extractous: https://github.com/yobix-ai/extractous; lopdf: https://github.com/J-F-Liu/lopdf
- ort: https://github.com/pykeio/ort; ONNX Runtime: https://github.com/microsoft/onnxruntime/releases
- oar-ocr: https://github.com/GreatV/oar-ocr; ocrs: https://github.com/robertknight/ocrs
- TATR: https://github.com/microsoft/table-transformer, https://huggingface.co/microsoft/table-transformer-structure-recognition
- RapidTable: https://github.com/RapidAI/RapidTable
- DocLayout-YOLO: https://github.com/opendatalab/DocLayout-YOLO; yolo-doclaynet: https://huggingface.co/hantian/yolo-doclaynet; Ultralytics: https://github.com/ultralytics/ultralytics
- pdf2md: https://github.com/deepdiy/pdf2md (@ `38f352f`)
- zerox: https://github.com/getomni-ai/zerox; unstructured: https://github.com/Unstructured-IO/unstructured; SCORE code: https://github.com/Unstructured-IO/unstructured-eval-metrics
- pymupdf4llm: https://github.com/pymupdf/pymupdf4llm; pdfplumber: https://github.com/jsvine/pdfplumber; Camelot: https://github.com/camelot-dev/camelot; Tabula: https://github.com/tabulapdf/tabula-java
- dots.ocr: https://github.com/studio-dots-ai/dots.ocr; MonkeyOCR: https://github.com/Yuliang-Liu/MonkeyOCR; Dolphin: https://github.com/bytedance/Dolphin
- Nanonets: https://huggingface.co/nanonets/Nanonets-OCR2-3B; DeepSeek-OCR: https://github.com/deepseek-ai/DeepSeek-OCR; GOT-OCR2: https://github.com/Ucas-HaoranWei/GOT-OCR2.0
- GLM-OCR: https://huggingface.co/zai-org/GLM-OCR; OpenDoc: https://github.com/Topdu/OpenOCR/blob/main/docs/opendoc.md
- local-llm-pdf-ocr: https://github.com/ahnafnafee/local-llm-pdf-ocr
- anymd: https://github.com/muthuishere/anymd; gopdf: https://github.com/razvandimescu/gopdf; unipdf: https://github.com/unidoc/unipdf
- PdfPig layout wiki: https://github.com/UglyToad/PdfPig/wiki/Document-Layout-Analysis
- poppler licence: https://en.wikipedia.org/wiki/Poppler_(software)

**Benchmarks and papers**
- OmniDocBench: https://github.com/opendatalab/OmniDocBench (paper https://arxiv.org/html/2412.07626; issue #258)
- olmOCR-bench: https://github.com/allenai/olmocr/blob/main/olmocr/bench/README.md
- olmOCR papers: https://arxiv.org/html/2502.18443v2, https://arxiv.org/abs/2510.19817
- MinerU2.5: https://arxiv.org/html/2509.22186; MinerU2.5-Pro: https://arxiv.org/abs/2604.04771
- PaddleOCR-VL: https://arxiv.org/html/2510.14528; PaddleOCR-VL-1.5: https://arxiv.org/abs/2601.21957
- ParseBench: https://arxiv.org/html/2604.08538v2; SCORE: https://arxiv.org/abs/2509.19345
- GriTS: https://arxiv.org/abs/2203.12555; TEDS: https://arxiv.org/abs/1911.10683
- TFLOP: https://arxiv.org/abs/2501.11800; SPRINT: https://arxiv.org/abs/2503.11932; UniTable: https://arxiv.org/abs/2403.04822
- XY-Cut++: https://arxiv.org/abs/2504.10258; Breuel 2002: https://link.springer.com/chapter/10.1007/3-540-45869-7_23
- Lin 2003 (headers/footers): https://www.spiedigitallibrary.org/conference-proceedings-of-spie/5010/0000/Header-and-footer-extraction-by-page-association/10.1117/12.472833.short
- KIE-HVQA: https://arxiv.org/abs/2506.20168; "When Low CER is Not Enough": https://arxiv.org/html/2607.24077v3
- Consensus Entropy: https://arxiv.org/abs/2504.11101; LRP: https://arxiv.org/abs/2511.19806; Arabic OCR prior: https://arxiv.org/abs/2608.22366

**Community and leaderboards** (read-only; threads cited inline in §6)
- Hacker News via the Algolia API: https://hn.algolia.com/api
- Reddit threads r/LocalLLaMA 1s0f5ar, 1vecxhw, 1vh7bxu, 1sk6kst, 1o866vl, 1r59th1; r/Rag 1vmi1xy, 1sk0reu, 1oiylhk, 1v94yfz; r/LangChain 1syu7vg (full URLs in §6)
- ParseBench leaderboard: https://raw.githubusercontent.com/run-llama/ParseBench/main/leaderboard.csv
- OCR Arena: https://www.ocrarena.ai/leaderboard
- IDP Leaderboard: https://idp-leaderboard.org/
- RD-TableBench: https://reducto.ai/blog/rd-tablebench
- olmOCR-bench dataset card: https://huggingface.co/datasets/allenai/olmOCR-bench
