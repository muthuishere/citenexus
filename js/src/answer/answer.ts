// The hermetic cite-or-abstain ask flow (SPEC-PORTS-v1 §0/§7).
//
// This is the guarantee: an answer is emitted only when retrieved evidence is
// relevant AND the generated claim is faithful to the cited passage. A port MUST
// NOT answer without the faithfulness gate — that gate is the product. Mirrors
// the Python reference SmokePipeline.ask exactly, over the deterministic fakes.

import {
  checkVector,
  embedOne,
  embedTexts,
  type EmbeddingProvider,
  type GeneratorProvider,
  type SingleTextEmbedder,
  type Vector,
} from "../contracts.js";
import { FakeEmbedding, FakeLLM, cosine } from "../fakes/fakes.js";
// ADR-0009 / ADR-0011: the answer path runs the V2 gates, the same pair the
// Python reference uses (`has_relevance_overlap_v2` / `is_supported_v2`).
// The v1 `hasRelevanceOverlap` / `isSupported` stay exported and frozen for the
// conformance vectors, but they are no longer what stands between a caller and
// a lie: v1 faithfulness is set containment, and a set is closed under
// reordering and deletion, so it accepted all nine adversarial false answers.
import { hasRelevanceOverlapV2 } from "../gate/gate.js";
import { isSupportedV2 } from "../gate/verify-v2.js";
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

  const grounded = ranked.filter((row) => hasRelevanceOverlapV2(question, row.text));
  if (grounded.length === 0) return refuse();

  const top = grounded[0]!;
  const passage = top.text;
  const answer = llm.answer(question, passage);
  if (!isSupportedV2(answer, passage)) return refuse(); // cite-or-drop: never ungrounded

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

// ---------------------------------------------------------------------------
// askWith — the injectable twin (ADR-0014 R4)
// ---------------------------------------------------------------------------
//
// `contracts.ts` publishes the model seam; this is what makes that publication
// mean something. Before it, `ask` constructed `new FakeEmbedding()` and
// `new FakeLLM()` INSIDE itself, so the port's only end-to-end path could not be
// reached by any provider a third party wrote — and a contract with no call site
// is decoration.
//
// `ask` above keeps its exact signature and SYNCHRONOUS behaviour: it is pinned
// byte-for-byte by conformance/cases/e2e_hermetic.json.
//
// Unlike Go — where `Ask` is literally `AskWith` with an empty provider set —
// `ask` here cannot delegate: a contract that may return a Promise makes the
// injectable path async, and `ask` must stay sync for the fixture and for the
// existing public API. So this port carries the flow TWICE, and the two are kept
// in lockstep by askwith.test.ts, which replays every fixture case through both
// and asserts the whole Result is deep-equal. That test is the seam that stops
// the duplication from drifting; do not weaken it.

/** The models the flow runs on. Every field is optional: an absent provider
 *  falls back to this port's deterministic fake, so a PARTIAL set is valid — a
 *  caller with a real generator and no embedding model, or the reverse, is a
 *  supported shape (the Python reference proves the same case).
 *
 *  Only the two seams the JS port CONSUMES appear here. There is no vision,
 *  completion or reranker field because there is nothing in this port that would
 *  call one; see `contracts.ts`. */
export interface AskProviders {
  /** Ranks the corpus against the question. Batch is the primitive, but the
   *  deprecated single-text shape is accepted too. */
  embedding?: EmbeddingProvider | SingleTextEmbedder;
  /** Turns the selected passage into an answer. It is NOT trusted: its output
   *  goes through the faithfulness gate below before it can be emitted, which is
   *  why an extractive generator is the best kind. */
  generator?: GeneratorProvider;
  /** Retrieval cutoff; defaults to 5, as `ask` does. */
  topK?: number;
}

/** Fixed at "en" in this port. Python resolves the answer language from config
 *  (including the "auto" sentinel — "answer in the query's language"); the JS
 *  port has no config layer and no `ask()` facade over one, so it does not
 *  pretend to. It is still passed through the contract so a provider sees the
 *  same signature it sees in Python. */
const ANSWER_LANGUAGE = "en";

/** The hermetic fake, wrapped in the published batch contract, so the fallback
 *  path and the injected path are ONE code path rather than two that can drift. */
const hermeticEmbedding: EmbeddingProvider = {
  embed(texts: readonly string[]): Vector[] {
    const fake = new FakeEmbedding();
    return texts.map((t) => fake.embed(t));
  },
};

/** The evidence-echoing fake, wrapped in the published contract. */
const hermeticGenerator: GeneratorProvider = {
  answer(question: string, passage: string): string {
    return new FakeLLM().answer(question, passage);
  },
};

/**
 * Answer `question` grounded in `corpus` using the injected providers, or refuse.
 *
 * Same flow as `ask` — embed, rank by cosine, keep topK, require a shared content
 * token, then require the generated answer to pass the faithfulness gate — with
 * the models supplied by the caller.
 *
 * FAILURE REJECTS; IT DOES NOT ABSTAIN. A refusal is a finding: "we searched the
 * evidence and it does not support an answer." A timed-out embedding model is not
 * a finding about the evidence, and reporting it as one would be the same class of
 * lie as the zero vector ADR-0014 R2 removed — a failure wearing the costume of a
 * successful negative result.
 */
export async function askWith(
  corpus: readonly CorpusDoc[],
  question: string,
  providers: AskProviders = {},
): Promise<Result> {
  const injected = providers.embedding !== undefined;
  const embedding = providers.embedding ?? hermeticEmbedding;
  const generator = providers.generator ?? hermeticGenerator;
  const topK = providers.topK ?? 5;

  // ONE batch call for the whole corpus — the contract's primitive.
  const docVectors = await embedTexts(
    embedding,
    corpus.map((doc) => doc.text),
  );

  let dim = 0;
  const rows: Row[] = corpus.map((doc, i) => {
    const vector = docVectors[i] ?? [];
    // The write-path guard, applied to the ask path. It runs only for an
    // INJECTED provider: the hermetic fake is this port's own reference
    // implementation, pinned by the conformance fixture, and a token-less
    // document legitimately embeds to zeros there and must still lead to a
    // refusal rather than an error.
    if (injected) {
      checkVector(doc.document_id, vector, dim);
      dim = vector.length;
    }
    return {
      euId: `${doc.document_id}::0`,
      documentId: doc.document_id,
      text: doc.text,
      vector,
      order: i,
    };
  });

  // A single text is a batch of one — the contract has no second method.
  const qvec = await embedOne(embedding, question);
  if (injected) checkVector("question", qvec, dim);

  const ranked = rows
    .map((row) => ({ row, score: cosine(qvec, row.vector) }))
    .sort((a, b) => b.score - a.score || a.row.order - b.row.order)
    .slice(0, topK)
    .map((x) => x.row);

  const grounded = ranked.filter((row) => hasRelevanceOverlapV2(question, row.text));
  if (grounded.length === 0) return refuse();

  const top = grounded[0]!;
  const passage = top.text;
  const answer = await generator.answer(question, passage, ANSWER_LANGUAGE);

  // The faithfulness gate runs on injected output exactly as it runs on the
  // fake's — this gate is the product, and it does not soften because the caller
  // supplied the model.
  if (!isSupportedV2(answer, passage)) return refuse();

  const distinctDocuments = new Set(grounded.map((row) => row.documentId)).size;
  return result({
    answer,
    answerLanguage: ANSWER_LANGUAGE,
    mode: TrustMode.strict,
    evidence: evidenceSignals({
      decision: Decision.answered,
      supportingSources: grounded.length,
      distinctDocuments,
      allClaimsVerified: true,
      languagesInEvidence: [ANSWER_LANGUAGE],
    }),
    claims: [claim({ claim: answer, supported: true, sources: [top.euId] })],
    sources: [sourceRef({ document: top.documentId, passage, passageLanguage: ANSWER_LANGUAGE })],
  });
}
