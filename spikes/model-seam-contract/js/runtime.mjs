// Runtime half of the JS proof: what actually lands in the store when someone
// casts an async embedder through the synchronous seam (the only way to make
// TypeScript accept one). The loop below is copied from js/src/ingest/ingest.ts:60-72
// with the Rust-FFI store replaced by an array.
//
// Run: node spikes/model-seam-contract/js/runtime.mjs

const rows = [];
const chunks = [
  "the employee may disclose the defect",
  "the employee may not disclose the defect",
];

// A cast async embedder — the ONLY way an HTTP-backed model gets past
// `type Embedder = (text: string) => number[]`.
const embed = async (text) => [text.length, 0, 0, 0];

// VERBATIM shape of js/src/ingest/ingest.ts:60-72
for (let i = 0; i < chunks.length; i++) {
  const text = chunks[i];
  rows.push({
    eu_id: `doc-1::0::${i}`,
    document_id: "doc-1",
    order: 0,
    chunk_index: i,
    text,
    vector: embed(text), // <-- a Promise, not a number[]
  });
}

console.log("== CLAIM 4: js Embedder is synchronous ==");
console.log("row.vector is a", rows[0].vector.constructor.name);
console.log("Array.isArray(row.vector) =", Array.isArray(rows[0].vector));
console.log("JSON serialised for the FFI store:", JSON.stringify(rows[0]));
// -- BONUS: the defect goes one layer deeper than the ADR noticed --------
// js/src/models/openai.ts:11-15 declares `Transport = (...) => string`, but the
// ONLY concrete transport, js/src/http.ts:55, is `async send(): Promise<string>`.
// So js/src/models/embed.ts:42 does JSON.parse(<Promise>):
const realTransport = async () => JSON.stringify({ data: [{ embedding: [1, 2] }] });
try {
  JSON.parse(realTransport()); // exactly embed.ts:42 with the real HttpClient
} catch (e) {
  console.log(`\n  BONUS  OpenAIEmbedder.embed with the real HttpClient: ${e.constructor.name}: ${e.message}`);
  console.log("         (js/src/models/embed.ts:42 JSON.parse's a Promise) — the JS");
  console.log("         wire-embedder path is DEAD, not merely awkward. Every test that");
  console.log("         exercises it injects a *synchronous fake* transport, which is what");
  console.log("         hides it.");
}

console.log(
  "\n  => the vector field serialises to {} — the store receives an empty object\n" +
    "     where a float array belongs. Best case the native layer throws with a\n" +
    "     message about JSON shape; worst case it coerces to an empty/zero vector\n" +
    "     and we are back in the Go failure mode. Either way the model call itself\n" +
    "     is never awaited, so a rejected promise is an UNHANDLED REJECTION that\n" +
    "     ingest() never sees. VERDICT: claim 4 HOLDS.",
);
