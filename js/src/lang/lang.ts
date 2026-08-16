// The pinned §11a answer-language fallback chain (SPEC-PORTS-v1 §4/§10).
//
// Parity with the Python reference citenexus.lang.fallback.resolve_answer_language.
// Given a (possibly unreliable) detection of the QUESTION plus fallback signals,
// pick the answer language by this ordered chain:
//   1. explicit answer_language — the caller's word outranks the classifier;
//   2. a reliable detection of the QUESTION;
//   3. established conversation_language;
//   4. configured default_answer_language (the dumb default).
//
// BREAKING (2026-08-16): the chain no longer derives the answer language from
// the retrieved evidence, and an explicit answer_language now outranks a
// reliable detection. The old evidence rung was a corpus-shaped signal wearing
// §11's name: measured on examples/multilingual/, it stamped 15 of 22 English
// questions with a Telugu or Tamil answer language purely because the retrieved
// passages were in those languages.

export interface LanguageResult {
  language: string;
  confidence: number;
  is_reliable: boolean;
}

/**
 * The one value of `answer_language` that is not a language: "detect it from my
 * question". Resolution of the sentinel (running a detector over the question)
 * happens a layer above this pinned function; here it merely does not count as
 * an explicit request, and is never returned.
 */
export const AUTO_ANSWER_LANGUAGE = "auto";

export interface ResolveAnswerLanguageArgs {
  detection: LanguageResult | null;
  answer_language?: string | null;
  conversation_language?: string | null;
  /** Accepted for signature stability across ports, and ignored. */
  languages_in_evidence?: readonly string[] | null;
  default_answer_language?: string;
}

/** Pick the answer language by the §11a chain (question only). */
export function resolveAnswerLanguage({
  detection,
  answer_language = null,
  conversation_language = null,
  languages_in_evidence = null,
  default_answer_language = "en",
}: ResolveAnswerLanguageArgs): string {
  void languages_in_evidence; // accepted for signature stability; never read.
  if (answer_language && answer_language !== AUTO_ANSWER_LANGUAGE) {
    return answer_language;
  }
  if (detection !== null && detection.is_reliable) {
    return detection.language;
  }
  if (conversation_language) {
    return conversation_language;
  }
  return default_answer_language;
}
