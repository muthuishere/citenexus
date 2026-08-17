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
import { resolveAnswerLanguage } from "../lang/lang.js";
import { unsupportedScripts } from "../tokenize/tokenize-v2.js";
import { splitClaims } from "./segment.js";
import {
  claim,
  Decision,
  evidenceSignals,
  result,
  sourceRef,
  TrustMode,
  type Result,
} from "../result/result.js";
// ADR-0007 conflict surfacing, native per port (ADR-0010 tier 1).
import {
  CONFLICT_TOP_K,
  collapseNearDuplicates,
  describeConflicts,
  findConflicts,
  type ConflictPair,
} from "./conflict.js";

/** One document in the corpus to index and search. */
export interface CorpusDoc {
  document_id: string;
  text: string;
  /** The document's declared language (a BCP-47-ish code such as `"te"`).
   *  OPTIONAL and additive: it mirrors the Python reference's
   *  `Candidate.language`, which is caller-supplied METADATA stamped at ingest —
   *  it is never derived from the text here. Absent means "not declared", and
   *  the cited `SourceRef` then reports the pinned `"und"` Python emits for
   *  `candidate.language or "und"`, NOT the answer language.
   *
   *  Before this field existed the ports stamped every passage `"en"`, so a
   *  Telugu passage reported English and any caller branching on
   *  `passage_language` was branching on a constant. */
  language?: string;
}

/** The pinned refusal string (§7); identical across every port. */
export const REFUSAL_ANSWER = "I can't answer that from the available evidence.";

/** The pinned ADR-0007 conflict abstention (`answer/flow.py:463`). A DIFFERENT
 *  string from `REFUSAL_ANSWER` on purpose: "the evidence isn't there" and
 *  "the evidence contradicts itself" are different findings, and collapsing
 *  them would hide the one the caller can actually act on. */
export const CONFLICT_REFUSAL_ANSWER = "The available evidence disagrees, so I can't answer that.";

interface Row {
  euId: string;
  documentId: string;
  text: string;
  /** Declared document language; `""` when undeclared. */
  language: string;
  vector: number[];
  order: number;
}

/** One candidate the tokenizer cannot read, with the unclaimed scripts that made
 *  it unreadable. */
interface BlockedRow {
  row: Row;
  scripts: string[];
}

/** One atomic claim and whether the cited passage supports it. */
interface ClaimVerdict {
  text: string;
  supported: boolean;
}

/** Rung 4 of the §11a chain: the dumb configured default. It is NOT the answer
 *  language — the answer language is whatever `resolveAnswerLanguage` returns,
 *  and this is only what it returns when nothing above it fired.
 *
 *  Until 2026-08-17 this port had a `const ANSWER_LANGUAGE = "en"` used for the
 *  answer language AND every `passage_language` AND `languages_in_evidence`. The
 *  chain shipped in `src/lang/lang.ts` with zero callers on the answer path, so
 *  all three fields were a constant wearing a signal's name. */
const DEFAULT_ANSWER_LANGUAGE = "en";

/** What a `SourceRef` reports when the cited document declared no language — the
 *  pinned Python value for `candidate.language or "und"`. Deliberately NOT the
 *  answer language: "I do not know what language this passage is in" and "I
 *  answered in English" are different facts, and the old code collapsed them. */
const UNDECLARED_LANGUAGE = "und";

/** The cited passage's DECLARED language, or the pinned `"und"` when the
 *  document declared none (`answer/flow.py:364`). Never the answer language. */
function passageLanguageOf(row: Row): string {
  return row.language === "" ? UNDECLARED_LANGUAGE : row.language;
}

/** The sorted set union of the given script lists. */
function sortedUnique(...lists: readonly (readonly string[])[]): string[] {
  return [...new Set(lists.flat())].sort();
}

/**
 * The localized refusal shell, mirroring `answer/flow.py:50`.
 *
 * `reason` is the ONE cause that actually produced the refusal; `unreachable` is
 * an additive note about material that was present but could not be read. The
 * two are separate on purpose — the second must never overwrite the first.
 */
function refuse(
  reason = "no sufficiently relevant evidence found",
  {
    answerLanguage = DEFAULT_ANSWER_LANGUAGE,
    unsupported = [] as string[],
    unreachable = [] as string[],
    conflictsDetected = 0,
  } = {},
): Result {
  return result({
    answer: REFUSAL_ANSWER,
    answerLanguage,
    mode: TrustMode.strict,
    evidence: evidenceSignals({
      decision: Decision.refused,
      conflictsDetected,
      unsupportedScripts: unsupported,
    }),
    missingEvidence: [reason, ...unreachable],
  });
}

/** The refusal reason when the tokenizer cannot read the QUESTION at all
 *  (ADR-0011, `flow.py:78`).
 *
 *  Reserved for the QUESTION on purpose. Applying it to the whole pool ran the
 *  conflation backwards: one unreadable row anywhere in the top-k rewrote the
 *  reason for an unrelated, purely-English refusal (measured: 11 of 14 refusals
 *  reported "unsupported script: unknown" over an English-only corpus). */
function capabilityReason(scripts: readonly string[]): string {
  return `unsupported script: ${scripts.join(", ")}`;
}

/** The refusal reason when the script gap genuinely explains the abstain: there
 *  WAS material, and we could not read it (`flow.py:99`). */
function unreadableReason(scripts: readonly string[]): string {
  return `no readable evidence found; unsupported script: ${scripts.join(", ")}`;
}

/**
 * The additive line naming material present but unreadable (`flow.py:108`).
 *
 * Measured: a Telugu annexure that capped leave at 5 days and stated it overrode
 * was silently skipped while the English handbook answered "a maximum of 10
 * days" — correctly cited, 100% grounded, and superseded. We cannot read that
 * annexure, so we assert nothing about it and we do not delete a correct,
 * grounded answer over it. What we can do is say it is there.
 */
function unreachableNote(blocked: readonly BlockedRow[]): string[] {
  if (blocked.length === 0) return [];
  const byDocument = new Map<string, string[]>();
  for (const b of blocked) {
    const document = b.row.documentId || b.row.euId;
    byDocument.set(document, sortedUnique(byDocument.get(document) ?? [], b.scripts));
  }
  const named = [...byDocument.entries()]
    .map(([document, scripts]) => `${document} (${scripts.join(", ")})`)
    .join(", ");
  return [
    `${byDocument.size} candidate document(s) could not be read and were excluded: ${named}`,
  ];
}

/** Everything `flow.py` derives from the post-retrieval pool before generation:
 *  the answer language, the observed evidence languages, the readable/blocked
 *  script partition, and the relevance-gated candidates. Either an early
 *  `refusal` (question unreadable, or nothing grounded) or a pool to answer from. */
interface Pool {
  refusal?: Result;
  answerLanguage: string;
  languages: string[];
  unsupported: string[];
  blocked: BlockedRow[];
  grounded: Row[];
}

/**
 * `ranked` is this port's analogue of the Python reference's `candidates`: the
 * post-retrieval, post-topK pool the flow is handed. This mirrors
 * `answer/flow.py` over that pool, in `flow.py`'s order.
 *
 * Shared by `ask` and `askWith` on purpose — this port carries the flow twice
 * (see the note above `askWith`), and every line kept in one place is a line
 * the two cannot drift on.
 */
function poolOf(ranked: readonly Row[], question: string, answerLanguageRequest?: string): Pool {
  // The evidence languages are OBSERVED and REPORTED, never an input to the
  // chain below (`flow.py:167`, and the `lang/fallback.py` docstring: the fourth
  // rung used to read them, which stamped 15 of 22 English questions Telugu or
  // Tamil). Distinct, in pool order, undeclared entries skipped.
  const languages = [...new Set(ranked.map((row) => row.language).filter((l) => l !== ""))];
  // The answer language follows the CALLER, then the question — never the
  // evidence. This port has no detector, so rung 2 is null; `languages` is
  // passed for signature parity and is ignored by construction.
  const answerLanguage = resolveAnswerLanguage({
    detection: null,
    answer_language: answerLanguageRequest ?? null,
    languages_in_evidence: languages,
    default_answer_language: DEFAULT_ANSWER_LANGUAGE,
  });

  // Which scripts in play the tokenizer does not CLAIM (ADR-0011). Note "claim",
  // not "process": the bigram path will mechanically produce tokens for Khmer,
  // Lao or Myanmar, and the gate will then accept a verbatim quote in them. That
  // is worse than refusing, because it looks exactly like a verified answer
  // while resting on a segmentation no fixture has ever checked. An unclaimed
  // script therefore ABSTAINS, and says why.
  //
  // The pool is PARTITIONED rather than unioned, because the two halves answer
  // different questions: `readable` decides what may be cited, and `blocked` is
  // the only thing a script-attributed refusal may be blamed on. Unioning them
  // is the measured mis-attribution defect (`flow.py:186-189`).
  const questionGap = unsupportedScripts(question);
  const readable: Row[] = [];
  const blocked: BlockedRow[] = [];
  for (const row of ranked) {
    const scripts = unsupportedScripts(row.text);
    if (scripts.length > 0) blocked.push({ row, scripts });
    else readable.push(row);
  }
  const blockedScripts = sortedUnique(...blocked.map((b) => b.scripts));
  // The SIGNAL still reports everything observed — narrowing it would lose the
  // very fact the unreachable-authority signal needs. Only the reason string is
  // attributed.
  const unsupported = sortedUnique(questionGap, blockedScripts);
  const base = { answerLanguage, languages, unsupported, blocked, grounded: [] as Row[] };

  // A question we cannot read is not answerable from anything.
  if (questionGap.length > 0) {
    return {
      ...base,
      refusal: refuse(capabilityReason(sortedUnique(questionGap)), {
        answerLanguage,
        unsupported,
      }),
    };
  }

  const grounded = readable.filter((row) => hasRelevanceOverlapV2(question, row.text));
  if (grounded.length === 0) {
    // Blame the script gap as the PRIMARY reason only when it is the only thing
    // between us and the pool — i.e. every candidate we got back was unreadable.
    // If we could read some of the pool and none of it was relevant, the corpus
    // is silent on this question, and saying otherwise sends the caller after a
    // phantom. The gap is still reported, additively, by the unreachable note.
    const onlyBlocked = blocked.length > 0 && readable.length === 0;
    return {
      ...base,
      refusal: onlyBlocked
        ? refuse(unreadableReason(blockedScripts), { answerLanguage, unsupported })
        : refuse("no sufficiently relevant evidence found", {
            answerLanguage,
            unsupported,
            unreachable: unreachableNote(blocked),
          }),
    };
  }
  return { ...base, grounded };
}

/**
 * Verification is PER ATOMIC CLAIM (ADR-0009). The answer is segmented and each
 * claim is checked independently against the cited passage; unsupported claims
 * are DROPPED rather than failing the answer whole, so a half-true generation
 * returns its true half instead of nothing. The candidate is accepted as soon as
 * at least one of its claims survives — `flow.py:307-315`.
 *
 * `splitClaims` shipped in this port, pinned by
 * `conformance/cases/segmentation.json`, with zero non-test callers: the port
 * gated the entire answer string as ONE claim, so a two-sentence answer with one
 * fabricated sentence refused BOTH sentences while Python kept the true one.
 */
function verifyClaims(answer: string, passage: string): ClaimVerdict[] {
  return splitClaims(answer).map((text) => ({ text, supported: isSupportedV2(text, passage) }));
}

/** The answered Result, once a candidate has at least one surviving claim.
 *  Shared by `ask` and `askWith` for the same anti-drift reason as `poolOf`. */
function answered(
  pool: Pool,
  ctx: ConflictContext,
  top: Row,
  verdicts: readonly ClaimVerdict[],
): Result {
  // Only SUPPORTED claims reach the answer; every atomic claim keeps its own
  // verdict, so a drop is auditable rather than silent (`flow.py:357-374`). The
  // decision stays `answered` even when a claim was dropped — Python's strict
  // flow never emits `partial` (that value is `agentic.py`'s, for deep-ask); the
  // drop is reported by `all_claims_verified: false` + `unsupported_claims_removed`.
  const supported = verdicts.filter((v) => v.supported);
  const removed = verdicts.length - supported.length;
  return result({
    answer: supported.map((v) => v.text).join(" "),
    answerLanguage: pool.answerLanguage,
    mode: TrustMode.strict,
    evidence: evidenceSignals({
      decision: Decision.answered,
      supportingSources: ctx.independent.length,
      distinctDocuments: new Set(ctx.independent.map((row) => row.documentId)).size,
      allClaimsVerified: removed === 0,
      unsupportedClaimsRemoved: removed,
      conflictsDetected: ctx.pairs.length,
      languagesInEvidence: pool.languages,
      unsupportedScripts: pool.unsupported,
    }),
    claims: verdicts.map((v) =>
      claim({ claim: v.text, supported: v.supported, sources: v.supported ? [top.euId] : [] }),
    ),
    sources: [
      sourceRef({ document: top.documentId, passage: top.text, passageLanguage: passageLanguageOf(top) }),
    ],
    // "I answered, but there is material here I cannot read." Empty on every
    // corpus without an unclaimed script, so those Results are unchanged.
    missingEvidence: unreachableNote(pool.blocked),
  });
}

/** What ADR-0007 asks of one post-fusion candidate set. Both questions come
 *  from the SAME pairwise comparison, and conflict is asked first: a one-word
 *  change is a duplicate only when that word is neither a value nor a polarity
 *  marker, and collapsing a contradiction into a corroboration is the worst
 *  outcome this can produce. */
interface ConflictContext {
  /** The first CONFLICT_TOP_K candidates — the pairwise comparison window, and
   *  the index space every `ConflictPair` refers to. */
  window: Row[];
  pairs: ConflictPair[];
  /** Candidates left after surface-clone collapse. Feeds the corroboration
   *  signals only: clones ingested under different document ids are one piece
   *  of evidence, not N. */
  independent: Row[];
}

function conflictContext(grounded: readonly Row[]): ConflictContext {
  const window = grounded.slice(0, CONFLICT_TOP_K);
  return {
    window,
    pairs: findConflicts(window.map((row) => row.text)),
    independent: collapseNearDuplicates(grounded.map((row) => row.text)).map(
      (i) => grounded[i] as Row,
    ),
  };
}

/**
 * Strict-mode abstention that cites BOTH sides of the disagreement.
 *
 * A refusal that hides the evidence is only marginally better than a confident
 * pick: the caller cannot check the library's reasoning or resolve the conflict
 * themselves. Both passages are returned as sources, verbatim, and neither is
 * named the winner.
 */
function conflictAbstention(
  ctx: ConflictContext,
  touching: readonly ConflictPair[],
  pool: Pool,
): Result {
  const cited = [];
  const seen = new Set<string>();
  for (const pair of touching) {
    for (const candidate of [ctx.window[pair.left] as Row, ctx.window[pair.right] as Row]) {
      if (seen.has(candidate.euId)) continue;
      seen.add(candidate.euId);
      cited.push(
        sourceRef({
          document: candidate.documentId,
          passage: candidate.text,
          passageLanguage: passageLanguageOf(candidate),
        }),
      );
    }
  }
  return result({
    answer: CONFLICT_REFUSAL_ANSWER,
    answerLanguage: pool.answerLanguage,
    mode: TrustMode.strict,
    evidence: evidenceSignals({
      decision: Decision.refused,
      supportingSources: ctx.independent.length,
      distinctDocuments: new Set(ctx.independent.map((row) => row.documentId)).size,
      conflictsDetected: ctx.pairs.length,
      languagesInEvidence: pool.languages,
      unsupportedScripts: pool.unsupported,
    }),
    sources: cited,
    conflicts: describeConflicts(
      touching,
      ctx.window.map((row) => row.documentId),
    ),
    missingEvidence: ["cited sources disagree and the conflict is unresolved"],
  });
}

/** Pairs whose two sides include the passage we are about to cite. An
 *  unresolved conflict touching the answer's own claim is not answerable in
 *  strict mode: the honest output is "these sources disagree, here are both",
 *  not a coin flip on rank order. This can only ever produce MORE abstention,
 *  so it cannot admit an ungrounded claim. */
function touchingPairs(pairs: readonly ConflictPair[], topIndex: number): ConflictPair[] {
  return pairs.filter((pair) => pair.left === topIndex || pair.right === topIndex);
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
    language: doc.language ?? "",
    vector: embedder.embed(doc.text),
    order: i,
  }));

  const qvec = embedder.embed(question);
  const ranked = rows
    .map((row) => ({ row, score: cosine(qvec, row.vector) }))
    .sort((a, b) => b.score - a.score || a.row.order - b.row.order)
    .slice(0, topK)
    .map((x) => x.row);

  const pool = poolOf(ranked, question);
  if (pool.refusal) return pool.refusal;

  // Conflict detection runs over the grounded candidates, before anything is
  // generated (ADR-0007). It reports and never resolves: picking a winner by
  // rank, recency or score is a policy decision belonging to the caller and to
  // authority (ADR-0004), and rank order deciding which of two contradictory
  // truths the caller sees is the defect this closes.
  const ctx = conflictContext(pool.grounded);

  const top = pool.grounded[0]!;
  const topIndex = 0;
  const answer = llm.answer(question, top.text);
  // cite-or-drop: never ungrounded, and now per atomic claim.
  const verdicts = verifyClaims(answer, top.text);
  if (!verdicts.some((v) => v.supported)) {
    // The gate owns this refusal. What was elsewhere in the pool did not cause
    // it, so it does not get blamed for it — an unreadable sibling is reported
    // AFTER the real reason, never instead of it (`flow.py:327-333`).
    return refuse("generated answer failed the faithfulness gate", {
      answerLanguage: pool.answerLanguage,
      unsupported: pool.unsupported,
      unreachable: unreachableNote(pool.blocked),
      conflictsDetected: ctx.pairs.length,
    });
  }

  const touching = touchingPairs(ctx.pairs, topIndex);
  if (touching.length > 0) return conflictAbstention(ctx, touching, pool);

  return answered(pool, ctx, top, verdicts);
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
  /** The CALLER's answer-language request — rung 1 of the §11a chain
   *  (`resolveAnswerLanguage`), the same slot Python's `ask(answer_language=...)`
   *  fills. Absent means "unspecified", which falls through to
   *  `DEFAULT_ANSWER_LANGUAGE`, and the `"auto"` sentinel is not a request (this
   *  port has no detector to resolve it with, so it also falls through). */
  answerLanguage?: string;
}

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
      language: doc.language ?? "",
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

  const pool = poolOf(ranked, question, providers.answerLanguage);
  if (pool.refusal) return pool.refusal;

  // ADR-0007, exactly as in `ask` above — the conflict check does not soften
  // because the caller supplied the model.
  const ctx = conflictContext(pool.grounded);

  const top = pool.grounded[0]!;
  const topIndex = 0;
  const answer = await generator.answer(question, top.text, pool.answerLanguage);

  // The faithfulness gate runs on injected output exactly as it runs on the
  // fake's — this gate is the product, and it does not soften because the caller
  // supplied the model. Per atomic claim (ADR-0009), with drop-not-fail.
  const verdicts = verifyClaims(answer, top.text);
  if (!verdicts.some((v) => v.supported)) {
    return refuse("generated answer failed the faithfulness gate", {
      answerLanguage: pool.answerLanguage,
      unsupported: pool.unsupported,
      unreachable: unreachableNote(pool.blocked),
      conflictsDetected: ctx.pairs.length,
    });
  }

  const touching = touchingPairs(ctx.pairs, topIndex);
  if (touching.length > 0) return conflictAbstention(ctx, touching, pool);

  return answered(pool, ctx, top, verdicts);
}
