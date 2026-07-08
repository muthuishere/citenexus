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
  freeString: Sym;
  detectorOpen: Sym;
  detect: Sym;
  detectorClose: Sym;
  storeOpen: Sym;
  storeUpsert: Sym;
  storeSearch: Sym;
  storeScan: Sym;
  storeDrop: Sym;
  storeClose: Sym;
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
    storeDrop: lib.func("citenexus_store_drop", "void*", [LanceStorePtr]),
    storeClose: lib.func("citenexus_store_close", "void", [LanceStorePtr]),
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
