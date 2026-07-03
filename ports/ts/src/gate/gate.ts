// Faithfulness and relevance gates for grounded answers (SPEC-PORTS-v1 §4/§10).
//
// The v0.1 verifier is deliberately extractive: a generated claim is accepted
// only when every answer token appears in the cited passage. Parity with the
// Python reference citenexus.answer.verify. Uses the pinned §4 tokenizer and the
// pinned 44-word stopword list loaded from conformance/stopwords.json.

import { tokenize } from "../tokenize/tokenize.js";
import { loadData } from "../conform/fixtures.js";

const STOPWORDS: ReadonlySet<string> = new Set(loadData<string[]>("stopwords.json"));

/** Meaning-bearing tokens used by the relevance gate: tokens minus stopwords. */
export function contentTokens(text: string): Set<string> {
  const out = new Set<string>();
  for (const tok of tokenize(text)) {
    if (!STOPWORDS.has(tok)) out.add(tok);
  }
  return out;
}

/** True when question and passage share at least one content token. */
export function hasRelevanceOverlap(question: string, passage: string): boolean {
  const q = contentTokens(question);
  for (const tok of contentTokens(passage)) {
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
