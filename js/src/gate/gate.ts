// Faithfulness and relevance gates for grounded answers (SPEC-PORTS-v1 §4/§10).
//
// The v0.1 verifier is deliberately extractive: a generated claim is accepted
// only when every answer token appears in the cited passage. Parity with the
// Python reference citenexus.answer.verify. Uses the pinned §4 tokenizer and the
// pinned 44-word stopword list loaded from conformance/stopwords.json.

import { tokenize } from "../tokenize/tokenize.js";
import { tokenizeV2 } from "../tokenize/tokenize-v2.js";
import { STOPWORDS_TABLE } from "../gen/tables.js";

const STOPWORDS: ReadonlySet<string> = new Set(STOPWORDS_TABLE);

/** Meaning-bearing tokens used by the relevance gate: tokens minus stopwords. */
export function contentTokens(text: string): Set<string> {
  const out = new Set<string>();
  for (const tok of tokenize(text)) {
    if (!STOPWORDS.has(tok)) out.add(tok);
  }
  return out;
}

/**
 * `contentTokens` over the Unicode tokenizer (ADR-0011).
 *
 * The stopword table stays English-only and stays applied unconditionally: it is
 * a fixed list of ASCII words, so it is a no-op on tokens from any other script
 * and cannot silently strip meaning there.
 */
export function contentTokensV2(text: string): Set<string> {
  const out = new Set<string>();
  for (const tok of tokenizeV2(text)) {
    if (!STOPWORDS.has(tok)) out.add(tok);
  }
  return out;
}

/** True when question and passage share at least one content token.
 *
 * FROZEN alongside `isSupported` — pinned by the shipped conformance vectors.
 * The answer path uses `hasRelevanceOverlapV2`. */
export function hasRelevanceOverlap(question: string, passage: string): boolean {
  const q = contentTokens(question);
  for (const tok of contentTokens(passage)) {
    if (q.has(tok)) return true;
  }
  return false;
}

/**
 * True when question and passage share at least one Unicode content token.
 *
 * Under v1 this returned false for every non-Latin script — both sides tokenized
 * to the empty set — so the relevance gate abstained before the faithfulness
 * gate ever ran. The abstention was over-determined; this is one of the two
 * places it came from (ADR-0011).
 */
export function hasRelevanceOverlapV2(question: string, passage: string): boolean {
  const q = contentTokensV2(question);
  for (const tok of contentTokensV2(passage)) {
    if (q.has(tok)) return true;
  }
  return false;
}

/** Every answer token (stopwords included) must appear in the cited passage. */
export function isSupported(answer: string, passage: string): boolean {
  const answerTokens = new Set(tokenize(answer));
  if (answerTokens.size === 0) return false;
  const passageTokens = new Set(tokenize(passage));
  for (const tok of answerTokens) {
    if (!passageTokens.has(tok)) return false;
  }
  return true;
}
