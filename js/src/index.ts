// @muthuishere/citenexus — public entry (the pure, dependency-free surface).
//
// The optional native-engine bindings (Rust core via koffi: extract/detect/store,
// ingest) are separate subpath imports — "@muthuishere/citenexus/ffi" and
// "@muthuishere/citenexus/ingest" — because they load a platform-native library at
// runtime. Importing this root entry pulls in NO native dependency.
// ADR-0014 R4: the published model seam. A provider author's ONE import — it
// pulls in no other module, and satisfying a contract needs no CiteNexus class.
export * from "./contracts.js";
export * from "./tokenize/tokenize.js";
// ADR-0011: the Unicode tokenizer that supersedes v1 on BM25 and the answer
// path. v1 stays exported and frozen.
export * from "./tokenize/tokenize-v2.js";
export * from "./bm25/bm25.js";
export * from "./rrf/rrf.js";
export * from "./gate/gate.js";
// ADR-0009: the ordered-containment + polarity predicate that supersedes
// isSupported on the answer path. isSupported stays exported and frozen.
export * from "./gate/verify-v2.js";
export * from "./chunker/chunker.js";
// euid re-exported explicitly: its internal chunkText helper collides with the
// chunker's public chunkText, so we expose only euid's public builders.
export { blockBuilderEuIds, chunkedBuilderEuIds, sha256Hex } from "./euid/euid.js";
export type { Block } from "./euid/euid.js";
export * from "./lang/lang.js";
// The named code sets (Language / Script). A const object + union type, never a
// TS enum — a plain string stays assignable at every call site (see codes.ts).
export * from "./lang/codes.js";
export * from "./result/result.js";
export * from "./answer/answer.js";
// ADR-0009 guarded claim segmentation (tier-1 scanner over a tier-2 table).
export * from "./answer/segment.js";
// ADR-0007 conflict surfacing + near-duplicate collapse (tier-1 set arithmetic
// over the tier-2 tables in gen/conflict_tables.ts). Pure ESM, no native
// dependency: it runs unchanged in a browser or a Cloudflare Worker.
export * from "./answer/conflict.js";
export * from "./graph/graph.js";
export * from "./structure/structure.js";
export * from "./fakes/fakes.js";
// Storage seam: VectorStore/TextSearch protocols + the pgvector backend. The
// Postgres store imports `pg` lazily at first connection, so this root entry
// stays dependency-free (parity with Python's citenexus.storage).
export * from "./storage/index.js";
// The shared HTTP layer: ${ENV}-header auth expanded at the request boundary.
export * from "./http.js";
// The shipped OpenAI-compatible model clients. They are the other half of the
// HTTP layer above — `HttpClient` was reachable from the package root while the
// clients it exists to authenticate were not, so the documented one-liner
// (`import { OpenAIEmbedder, HttpClient } from "@muthuishere/citenexus"`) threw.
// Parity with Python, which exports its model clients top-level.
export * from "./models/embed.js";
export * from "./models/openai.js";
export * from "./models/anthropic.js";
export * from "./models/vision.js";
// §9 conditional-vision ORCHESTRATION (ADR-0005 two-phase emit/fulfil/assemble).
// Vision is an INJECTED model like the generator and the embedder; everything
// around the call is deterministic, so it ports natively — pure ESM, no native
// dependency. The pinned prompt is generated into gen/prompts.ts from
// conformance/prompts.json (ADR-0010 tier 2).
export * from "./vision/prefilter.js";
export * from "./vision/requests.js";
export * from "./vision/describe.js";
export * from "./vision/fulfill.js";
export * from "./vision/units.js";
export * from "./gen/prompts.js";
