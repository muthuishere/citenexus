// Spike: prove ADR-0014's claim 4 — the JS embedder seam is synchronous, so no
// network- or model-backed embedder can satisfy it.
//
// The type is copied VERBATIM from js/src/ingest/ingest.ts:16.
// Type-check: npx tsc --noEmit --strict spikes/model-seam-contract/js/embedder.ts

/** VERBATIM from js/src/ingest/ingest.ts:16 */
export type Embedder = (text: string) => number[];

/** What a resident, in-process model can do — fine. */
export const residentEmbedder: Embedder = (text) => [text.length, 0, 0, 0];

/** What EVERY network-backed embedder must look like. */
async function httpEmbed(text: string): Promise<number[]> {
  const res = await fetch("http://localhost:11434/v1/embeddings", {
    method: "POST",
    body: JSON.stringify({ model: "bge-m3", input: [text] }),
  });
  const json = (await res.json()) as { data: { embedding: number[] }[] };
  return json.data[0]!.embedding;
}

// The assignment TypeScript refuses. There is no adapter: JS has no way to
// synchronously await a promise, so this is not a style issue but a hard wall.
export const wireEmbedder: Embedder = httpEmbed;

// And the "just cast it" escape hatch is worse than the error, because it is
// silent at runtime — see runtime.mjs.
export const castEmbedder = httpEmbed as unknown as Embedder;
