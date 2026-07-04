// @muthuishere/citenexus-core — public entry (the pure, dependency-free surface).
//
// The optional native-engine bindings (Rust core via koffi: extract/detect/store,
// ingest) are separate subpath imports — "@muthuishere/citenexus-core/ffi" and
// "@muthuishere/citenexus-core/ingest" — because they load a platform-native library at
// runtime. Importing this root entry pulls in NO native dependency.
export * from "./tokenize/tokenize.js";
export * from "./bm25/bm25.js";
export * from "./rrf/rrf.js";
export * from "./gate/gate.js";
export * from "./chunker/chunker.js";
// euid re-exported explicitly: its internal chunkText helper collides with the
// chunker's public chunkText, so we expose only euid's public builders.
export { blockBuilderEuIds, chunkedBuilderEuIds, sha256Hex } from "./euid/euid.js";
export type { Block } from "./euid/euid.js";
export * from "./lang/lang.js";
export * from "./result/result.js";
export * from "./answer/answer.js";
export * from "./graph/graph.js";
export * from "./structure/structure.js";
export * from "./fakes/fakes.js";
