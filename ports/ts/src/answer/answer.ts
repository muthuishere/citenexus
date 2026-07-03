// The hermetic cite-or-abstain ask flow (SPEC-PORTS-v1 §0/§7).
//
// This is the guarantee: an answer is emitted only when retrieved evidence is
// relevant AND the generated claim is faithful to the cited passage. A port MUST
// NOT answer without the faithfulness gate — that gate is the product. Mirrors
// the Python reference SmokePipeline.ask exactly, over the deterministic fakes.

import { FakeEmbedding, FakeLLM, cosine } from "../fakes/fakes.js";
import { hasRelevanceOverlap, isSupported } from "../gate/gate.js";
import {
  claim,
  Decision,
  evidenceSignals,
  result,
  sourceRef,
  TrustMode,
  type Result,
} from "../result/result.js";

/** One document in the corpus to index and search. */
export interface CorpusDoc {
  document_id: string;
  text: string;
}

/** The pinned refusal string (§7); identical across every port. */
export const REFUSAL_ANSWER = "I can't answer that from the available evidence.";

interface Row {
  euId: string;
  documentId: string;
  text: string;
  vector: number[];
  order: number;
}

function refuse(): Result {
  return result({
    answer: REFUSAL_ANSWER,
    answerLanguage: "en",
    mode: TrustMode.strict,
    evidence: evidenceSignals({ decision: Decision.refused }),
    missingEvidence: ["no sufficiently relevant evidence found"],
  });
}

/**
 * Answer `question` grounded in `corpus`, or refuse if no faithful evidence
 * exists. Each document becomes one Evidence Unit ("{document_id}::0"); rows are
 * ranked by descending cosine to the question (stable tie-break by insertion
 * order), gated on content-token relevance, then on extractive faithfulness.
 */
export function ask(corpus: readonly CorpusDoc[], question: string, topK = 5): Result {
  const embedder = new FakeEmbedding();
  const llm = new FakeLLM();

  const rows: Row[] = corpus.map((doc, i) => ({
    euId: `${doc.document_id}::0`,
    documentId: doc.document_id,
    text: doc.text,
    vector: embedder.embed(doc.text),
    order: i,
  }));

  const qvec = embedder.embed(question);
  const ranked = rows
    .map((row) => ({ row, score: cosine(qvec, row.vector) }))
    .sort((a, b) => b.score - a.score || a.row.order - b.row.order)
    .slice(0, topK)
    .map((x) => x.row);

  const grounded = ranked.filter((row) => hasRelevanceOverlap(question, row.text));
  if (grounded.length === 0) return refuse();

  const top = grounded[0]!;
  const passage = top.text;
  const answer = llm.answer(question, passage);
  if (!isSupported(answer, passage)) return refuse(); // cite-or-drop: never ungrounded

  const distinctDocuments = new Set(grounded.map((row) => row.documentId)).size;
  return result({
    answer,
    answerLanguage: "en",
    mode: TrustMode.strict,
    evidence: evidenceSignals({
      decision: Decision.answered,
      supportingSources: grounded.length,
      distinctDocuments,
      allClaimsVerified: true,
      languagesInEvidence: ["en"],
    }),
    claims: [claim({ claim: answer, supported: true, sources: [top.euId] })],
    sources: [sourceRef({ document: top.documentId, passage, passageLanguage: "en" })],
  });
}
