// The pinned §11a answer-language fallback chain (SPEC-PORTS-v1 §4/§10).
//
// Parity with the Python reference citenexus.lang.fallback.resolve_answer_language.
// Given a (possibly unreliable) query-language detection plus fallback signals,
// pick the answer language by this ordered chain:
//   1. reliable detection of the query language;
//   2. explicit answer_language override;
//   3. established conversation_language;
//   4. dominant language among languages_in_evidence (ties -> first-seen);
//   5. configured default_answer_language.

export interface LanguageResult {
  language: string;
  confidence: number;
  is_reliable: boolean;
}

export interface ResolveAnswerLanguageArgs {
  detection: LanguageResult | null;
  answer_language?: string | null;
  conversation_language?: string | null;
  languages_in_evidence?: readonly string[] | null;
  default_answer_language?: string;
}

/** Pick the answer language by the §11a chain (short query only). */
export function resolveAnswerLanguage({
  detection,
  answer_language = null,
  conversation_language = null,
  languages_in_evidence = null,
  default_answer_language = "en",
}: ResolveAnswerLanguageArgs): string {
  if (detection !== null && detection.is_reliable) {
    return detection.language;
  }
  if (answer_language) {
    return answer_language;
  }
  if (conversation_language) {
    return conversation_language;
  }
  if (languages_in_evidence && languages_in_evidence.length > 0) {
    // Counter.most_common(1) — highest count, ties resolved to first-seen
    // (stable insertion order). Deterministic.
    const counts = new Map<string, number>();
    for (const lang of languages_in_evidence) {
      counts.set(lang, (counts.get(lang) ?? 0) + 1);
    }
    let best = "";
    let bestCount = -1;
    for (const [lang, count] of counts) {
      if (count > bestCount) {
        best = lang;
        bestCount = count;
      }
    }
    return best;
  }
  return default_answer_language;
}
