// The pinned CiteNexus tokenizer (SPEC-PORTS-v1 §4).
//
// Frozen contract: lowercase the input, then return every match of [a-z0-9]+
// (ASCII only, no stemming). The single tokenizer behind BM25, the relevance
// gate, and the faithfulness gate — parity with the Python reference
// citenexus.testing.fakes.tokenize (str.lower() + [a-z0-9]+ findall).

const TOKEN_RE = /[a-z0-9]+/g;

/** Lowercase `text` and return all ASCII [a-z0-9]+ runs, in order. */
export function tokenize(text: string): string[] {
  return text.toLowerCase().match(TOKEN_RE) ?? [];
}
