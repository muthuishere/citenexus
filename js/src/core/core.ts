// OPT-IN koffi FFI binding to the shared Rust engine (citenexus-core):
// binary-document extraction, lid.176 language detection, and the Lance store —
// the heavy ingest stages the pure TS port cannot reimplement byte-identically.
//
// This module is ISOLATED from the default build path: it is not imported by any
// pure-port entrypoint, and loading it dlopen's the native cdylib at call time.
// So `tsc` and consumers who never touch `citenexus/core` stay clean and need no
// native library. Build the Rust cdylib first (`cd rust && cargo build --release`)
// before importing it. One C ABI, shared with the Go cgo binding (SPEC-PORTS-v1 §3.4).
//
// Every string the C ABI returns is malloc'd on the Rust side and MUST be freed
// with citenexus_free_string — every wrapper below does exactly that. The
// version string is the one exception (a static, no-free pointer).

import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

// koffi is a CommonJS addon; load it through createRequire so this ESM module
// can pull it in without a bundler.
const require = createRequire(import.meta.url);
// eslint-disable-next-line @typescript-eslint/no-var-requires
const koffi = require("koffi") as typeof import("koffi");

/** Resolve the built cdylib for the current platform. */
function libraryPath(): string {
  const here = dirname(fileURLToPath(import.meta.url));
  // src/core -> ../../../rust/target/release
  const releaseDir = resolve(here, "..", "..", "..", "rust", "target", "release");
  const name =
    process.platform === "win32"
      ? "citenexus_core.dll"
      : process.platform === "darwin"
        ? "libcitenexus_core.dylib"
        : "libcitenexus_core.so";
  const override = process.env.CITENEXUS_CORE_LIB;
  return override && override.length > 0 ? override : resolve(releaseDir, name);
}

// koffi opaque handle types for the three C ABI resource pointers.
const Detector = koffi.opaque("Detector");
const LanceStore = koffi.opaque("LanceStore");

// Lazily loaded native symbols. Loading is deferred so merely importing this
// module (e.g. for type checking) never dlopen's a missing library.
type Sym = ReturnType<ReturnType<typeof koffi.load>["func"]>;
interface Symbols {
  version: Sym;
  extract: Sym;
  toMarkdown: Sym;
  rrf: Sym;
  freeString: Sym;
  detectorOpen: Sym;
  detect: Sym;
  detectorClose: Sym;
  storeOpen: Sym;
  storeUpsert: Sym;
  storeSearch: Sym;
  storeScan: Sym;
  storeDeleteDocument: Sym;
  storeDrop: Sym;
  storeClose: Sym;
  pdfUnits: Sym;
  pdfPrepare: Sym;
  pdfAssemble: Sym;
  ooxmlUnits: Sym;
}

let cached: Symbols | undefined;

function symbols(): Symbols {
  if (cached) return cached;
  const lib = koffi.load(libraryPath());
  // Pointers to opaque handles.
  const DetectorPtr = koffi.pointer(Detector);
  const LanceStorePtr = koffi.pointer(LanceStore);
  // String-returning symbols use a `void*` return so koffi hands back the raw
  // malloc'd pointer instead of auto-decoding a `char*` into a JS string (which
  // would leak — we could never free it). takeString() decodes then frees.
  cached = {
    version: lib.func("citenexus_core_version", "const char*", []),
    extract: lib.func("citenexus_extract", "void*", [
      "const uint8_t*",
      "size_t",
      "const char*",
      "const char*",
    ]),
    toMarkdown: lib.func("citenexus_to_markdown", "void*", [
      "const uint8_t*",
      "size_t",
      "const char*",
    ]),
    rrf: lib.func("citenexus_rrf", "void*", ["const char*", "int64_t"]),
    freeString: lib.func("citenexus_free_string", "void", ["void*"]),
    detectorOpen: lib.func("citenexus_detector_open", DetectorPtr, ["const char*"]),
    detect: lib.func("citenexus_detect", "void*", [DetectorPtr, "const char*"]),
    detectorClose: lib.func("citenexus_detector_close", "void", [DetectorPtr]),
    storeOpen: lib.func("citenexus_store_open", LanceStorePtr, [
      "const char*",
      "const char*",
    ]),
    storeUpsert: lib.func("citenexus_store_upsert", "void*", [LanceStorePtr, "const char*"]),
    storeSearch: lib.func("citenexus_store_search", "void*", [
      LanceStorePtr,
      "const char*",
      "size_t",
    ]),
    storeScan: lib.func("citenexus_store_scan", "void*", [LanceStorePtr, "int64_t"]),
    storeDeleteDocument: lib.func("citenexus_store_delete_document", "void*", [
      LanceStorePtr,
      "const char*",
    ]),
    storeDrop: lib.func("citenexus_store_drop", "void*", [LanceStorePtr]),
    storeClose: lib.func("citenexus_store_close", "void", [LanceStorePtr]),
    pdfUnits: lib.func("citenexus_pdf_units", "void*", ["const uint8_t*", "size_t", "const char*"]),
    pdfPrepare: lib.func("citenexus_pdf_prepare", "void*", [
      "const uint8_t*",
      "size_t",
      "const char*",
    ]),
    pdfAssemble: lib.func("citenexus_pdf_assemble", "void*", [
      "const uint8_t*",
      "size_t",
      "const char*",
      "const char*",
    ]),
    ooxmlUnits: lib.func("citenexus_ooxml_units", "void*", [
      "const uint8_t*",
      "size_t",
      "const char*",
    ]),
  };
  return cached;
}

/**
 * Call a symbol that returns a malloc'd C string, decode it, then free it with
 * citenexus_free_string. This is the single place strings are released — no
 * caller ever holds the raw pointer.
 */
function takeString(ptr: unknown, sym: Symbols): string {
  if (ptr === null) {
    throw new Error("citenexus-core returned a null string");
  }
  try {
    return koffi.decode(ptr, "char", -1) as unknown as string;
  } finally {
    sym.freeString(ptr);
  }
}

/** The shared Rust core's version (static string, no free needed). */
export function version(): string {
  const sym = symbols();
  return sym.version() as string;
}

// ---- extract ---------------------------------------------------------------

export interface ExtractedBlock {
  order: number;
  kind: string;
  text: string;
  page?: number | null;
  bbox?: unknown;
  level?: number | null;
  structure_path: string[];
  /** Raw cell values for `table` blocks (aligned to the header on `structure_path`); empty otherwise. */
  cells: string[];
}

export interface ExtractedDoc {
  document_id: string;
  source_type: string;
  structure_type: string;
  source_uri?: string | null;
  blocks: ExtractedBlock[];
  images: unknown[];
}

export interface CoreError {
  error: string;
}

function parseJson<T>(raw: string): T {
  const value = JSON.parse(raw) as T | CoreError;
  if (value && typeof value === "object" && "error" in value) {
    throw new Error(`citenexus-core: ${(value as CoreError).error}`);
  }
  return value as T;
}

/**
 * Extract raw bytes as `sourceType` (e.g. "plain", "md", "html", "csv", "pdf",
 * "docx", "pptx") into an ExtractedDoc. Throws on a core-reported error.
 */
export function extract(
  bytes: Uint8Array,
  sourceType: string,
  documentID: string,
): ExtractedDoc {
  const sym = symbols();
  // koffi accepts a Uint8Array directly for `const uint8_t*`. Guard the empty
  // case with a 0-length buffer so the pointer is non-null but len 0.
  const buf = bytes.length > 0 ? bytes : new Uint8Array(0);
  const raw = takeString(sym.extract(buf, buf.length, sourceType, documentID), sym);
  return parseJson<ExtractedDoc>(raw);
}

/**
 * Convert raw bytes of `sourceType` ("docx", "xlsx", "html", …) straight to
 * markdown via the shared Rust extract+emit path. Throws on a core-reported
 * error.
 */
export function toMarkdown(bytes: Uint8Array, sourceType: string): string {
  const sym = symbols();
  const buf = bytes.length > 0 ? bytes : new Uint8Array(0);
  const raw = takeString(sym.toMarkdown(buf, buf.length, sourceType), sym);
  return parseJson<{ markdown: string }>(raw).markdown;
}

// ---- rrf --------------------------------------------------------------------

/**
 * Reciprocal-rank-fuse ranked `eu_id` lists through the shared Rust core
 * (ADR-0006: rrf is pure rank arithmetic and lives once in the core). `k` is the
 * RRF constant (60 is standard). Returns the fused `eu_id` order — byte-identical
 * to the Python reference and to every other SDK's core-backed fusion. This is
 * the canonical fusion path; the pure `rrfFuse` helper is deprecated in its
 * favor. Throws on a core-reported error.
 */
export function rrf(lists: string[][], k = 60): string[] {
  const sym = symbols();
  const raw = takeString(sym.rrf(JSON.stringify(lists), k), sym);
  return parseJson<string[]>(raw);
}

// ---- detect ----------------------------------------------------------------

export interface Detection {
  language: string;
  confidence: number;
}

/**
 * Detect the language of `text` using the lid.176 model at `modelPath`. The
 * model is caller-supplied — the core never downloads it. Throws if the model
 * is missing/unloadable or on a core-reported error. The detector handle is
 * opened and closed per call (simple; detection is not hot-path here).
 */
export function detect(modelPath: string, text: string): Detection {
  const sym = symbols();
  const handle = sym.detectorOpen(modelPath);
  if (handle === null) {
    throw new Error(`citenexus-core: could not open detector model at ${modelPath}`);
  }
  try {
    const raw = takeString(sym.detect(handle, text), sym);
    return parseJson<Detection>(raw);
  } finally {
    sym.detectorClose(handle);
  }
}

// ---- store -----------------------------------------------------------------

/** One evidence-unit row; `vector` is a dense float array, keyed by `eu_id`. */
export interface StoreRow {
  eu_id: string;
  [column: string]: string | number | boolean | number[];
}

/**
 * A single leaf Lance partition (Rust twin of Python's LanceVectorStore).
 * Open with `Store.open`, and ALWAYS `close()` when done — the handle owns a
 * tokio runtime and a DB connection on the Rust side.
 */
export class Store {
  private handle: unknown;
  private readonly sym: Symbols;

  private constructor(handle: unknown, sym: Symbols) {
    this.handle = handle;
    this.sym = sym;
  }

  /**
   * Open (or create) the Lance database at `uri` (a local path or `s3://…`).
   * `storageOptions` is passed through to lancedb (endpoint, keys, region) or
   * omitted for a local path.
   */
  static open(uri: string, storageOptions?: Record<string, string>): Store {
    const sym = symbols();
    const optionsJson =
      storageOptions && Object.keys(storageOptions).length > 0
        ? JSON.stringify(storageOptions)
        : null;
    const handle = sym.storeOpen(uri, optionsJson);
    if (handle === null) {
      throw new Error(`citenexus-core: could not open store at ${uri}`);
    }
    return new Store(handle, sym);
  }

  private assertOpen(): unknown {
    if (this.handle === null) {
      throw new Error("citenexus-core: store is closed");
    }
    return this.handle;
  }

  /** Upsert rows keyed by `eu_id` (idempotent, merge-insert). No-op on empty. */
  upsert(rows: StoreRow[]): void {
    const handle = this.assertOpen();
    const raw = takeString(this.sym.storeUpsert(handle, JSON.stringify(rows)), this.sym);
    parseJson<{ ok: true }>(raw);
  }

  /** Nearest `limit` rows to `vector`, each carrying `_distance`. */
  search(vector: number[], limit: number): Record<string, unknown>[] {
    const handle = this.assertOpen();
    const raw = takeString(
      this.sym.storeSearch(handle, JSON.stringify(vector), limit),
      this.sym,
    );
    return parseJson<Record<string, unknown>[]>(raw);
  }

  /** Every row, optionally truncated (`limit < 0` means no limit). */
  scan(limit = -1): Record<string, unknown>[] {
    const handle = this.assertOpen();
    const raw = takeString(this.sym.storeScan(handle, limit), this.sym);
    return parseJson<Record<string, unknown>[]>(raw);
  }

  /** Remove every row for `documentId` (no-op when absent) — the row-level
   *  inverse of `upsert` used by document-revoke. */
  deleteDocument(documentId: string): void {
    const handle = this.assertOpen();
    const raw = takeString(this.sym.storeDeleteDocument(handle, documentId), this.sym);
    parseJson<{ ok: true }>(raw);
  }

  /** Drop the evidence_units table (the leaf becomes empty). */
  drop(): void {
    const handle = this.assertOpen();
    const raw = takeString(this.sym.storeDrop(handle), this.sym);
    parseJson<{ ok: true }>(raw);
  }

  /** Release the store handle. Idempotent; safe to call more than once. */
  close(): void {
    if (this.handle !== null) {
      this.sym.storeClose(this.handle);
      this.handle = null;
    }
  }
}

// ---- structured units + the PDF model contract (ADR-0017) -------------------
//
// docs/pdf-model-contract.md is the host contract. pdfPrepare returns requests;
// the HOST fulfils them with its own models (this module never calls a model);
// pdfAssemble applies every response that passes the core's checks. PDF calls
// need the core built with `--features pdf` and libpdfium loadable
// (PDFIUM_DYNAMIC_LIB_PATH). Same C ABI as Go and Python: same bytes out.

export interface PdfOptions {
  language?: string;
  layout_text?: boolean;
  /** Also ask the model about tables the deterministic path accepted. */
  model_tables?: boolean;
}

export interface Provenance {
  route: string;
  table_source: string | null;
  vision_transcribed: boolean;
  table_uncertain: boolean;
  failed_check: string | null;
  heading_source: string | null;
  joined_hyphen: boolean;
  vision_disputed: boolean;
  header_flattened: boolean;
  model_verdict: string | null;
}

/** kind: heading|paragraph|list|table|furniture|image|image_description;
 *  bbox: [x0, y0, x1, y1] in points, top-left origin. */
export interface DocUnit {
  page: number | null;
  bbox: [number, number, number, number] | null;
  kind: string;
  level: number | null;
  markdown: string;
  provenance: Provenance;
}

export interface PdfPageInfo {
  page: number;
  width: number;
  height: number;
  route: string;
  signals: Record<string, unknown>;
  layout_text?: string | null;
}

export interface PdfDocumentSignals {
  pages: number;
  responses_applied: number;
  responses_rejected: number;
  [signal: string]: unknown;
}

export interface PdfUnitsOutput {
  units: DocUnit[];
  pages: PdfPageInfo[];
  document: PdfDocumentSignals;
}

export interface PdfWord {
  id: string;
  text: string;
  bbox: [number, number, number, number];
  /** A list-marker glyph; a grid may leave it out. */
  marker: boolean;
}

export interface PdfRequest {
  id: string;
  page: number;
  kind: "table_structure" | "vision_page" | "vision_region";
  prompt: string;
  bbox: [number, number, number, number];
  words: PdfWord[];
  /** 1 or 2 for vision (every region is asked twice); null for tables. */
  variant: number | null;
  hint: string | null;
}

export interface PdfPrepared extends PdfUnitsOutput {
  requests: PdfRequest[];
}

export type PdfCell = string[] | { words: string[]; colspan?: number; rowspan?: number };

export interface PdfGrid {
  rows: PdfCell[][];
}

export interface PdfResponse {
  request_id: string;
  finish_reason?: string | null;
  /** table_structure: grids of word IDs; `[]` means "no table here". */
  tables?: PdfGrid[] | null;
  /** vision_page / vision_region. */
  markdown?: string | null;
  /** vision_region: "description" when the region has no text and is described. */
  mode?: "transcription" | "description" | null;
}

function pdfBuffer(pdf: Uint8Array): Uint8Array {
  return pdf.length > 0 ? pdf : new Uint8Array(0);
}

/** The base output (no model) as the core's JSON, untouched. */
export function pdfUnitsJson(pdf: Uint8Array, options: PdfOptions = {}): string {
  const sym = symbols();
  const buf = pdfBuffer(pdf);
  const raw = takeString(sym.pdfUnits(buf, buf.length, JSON.stringify(options)), sym);
  parseJson<unknown>(raw);
  return raw;
}

export function pdfPrepareJson(pdf: Uint8Array, options: PdfOptions = {}): string {
  const sym = symbols();
  const buf = pdfBuffer(pdf);
  const raw = takeString(sym.pdfPrepare(buf, buf.length, JSON.stringify(options)), sym);
  parseJson<unknown>(raw);
  return raw;
}

/** Apply responses (typed, or a JSON array string) and return the core's JSON
 *  untouched: byte-identical across JS, Go and Python. */
export function pdfAssembleJson(
  pdf: Uint8Array,
  responses: PdfResponse[] | string,
  options: PdfOptions = {},
): string {
  const sym = symbols();
  const buf = pdfBuffer(pdf);
  const body = typeof responses === "string" ? responses : JSON.stringify(responses);
  const raw = takeString(sym.pdfAssemble(buf, buf.length, JSON.stringify(options), body), sym);
  parseJson<unknown>(raw);
  return raw;
}

/** The base output: pdfAssemble with no responses. */
export function pdfUnits(pdf: Uint8Array, options: PdfOptions = {}): PdfUnitsOutput {
  return JSON.parse(pdfUnitsJson(pdf, options)) as PdfUnitsOutput;
}

/** Phase one: the base output plus the requests the host may fulfil. */
export function pdfPrepare(pdf: Uint8Array, options: PdfOptions = {}): PdfPrepared {
  return JSON.parse(pdfPrepareJson(pdf, options)) as PdfPrepared;
}

/** Phase two: re-parse and apply every response that passes the checks. A
 *  missing or failed response is base output (the latter with failed_check). */
export function pdfAssemble(
  pdf: Uint8Array,
  responses: PdfResponse[] | string,
  options: PdfOptions = {},
): PdfUnitsOutput {
  return JSON.parse(pdfAssembleJson(pdf, responses, options)) as PdfUnitsOutput;
}

/** DOCX/PPTX units from their own OOXML structure (no model). */
export function ooxmlUnits(bytes: Uint8Array, sourceType: "docx" | "pptx"): DocUnit[] {
  const sym = symbols();
  const buf = pdfBuffer(bytes);
  const raw = takeString(sym.ooxmlUnits(buf, buf.length, sourceType), sym);
  return parseJson<DocUnit[]>(raw);
}

const NON_CITABLE = ["<!-- vision_disputed", "<!-- image_description"];

/** `markdown` with every <!-- vision_disputed … --> and <!-- image_description
 *  … --> block removed: the only text a host may cite or quote-match. Mirrors
 *  the core's vision::citable_text. */
export function citableText(markdown: string): string {
  let out = "";
  let rest = markdown;
  for (;;) {
    const starts = NON_CITABLE.map((b) => rest.indexOf(b)).filter((i) => i >= 0);
    if (starts.length === 0) {
      out += rest;
      break;
    }
    const start = Math.min(...starts);
    out += rest.slice(0, start);
    const end = rest.indexOf("-->", start);
    if (end < 0) break;
    rest = rest.slice(end + 3);
  }
  return out
    .split("\n")
    .map((l) => l.replace(/\s+$/, ""))
    .filter((l) => l.trim().length > 0)
    .join("\n");
}
