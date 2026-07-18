// The Result object and its parts (SPEC-PORTS-v1 §7; spec §16/§12/§11).
//
// A Result is a grounded answer with a reproducible provenance chain. Confidence
// is expressed as structured signals (§12), never a scalar. The serialized shape
// is the port contract, proven byte-for-byte against
// conformance/cases/result_roundtrip.json: absent optional fields are emitted as
// null (never omitted), empty lists as [] (never null). Builders take camelCase
// options and produce the canonical snake_case JSON object directly, so
// JSON.stringify(result) yields the contract shape.

/** Trust mode governing the answer (§8). Only strict ships in v0.1. */
export enum TrustMode {
  strict = "strict",
}

/** The outcome recorded on the evidence signals. */
export enum Decision {
  answered = "answered",
  refused = "refused",
  partial = "partial",
}

/** Deep-ask loop accounting (signals.loop); Python-only today. JS carries the type
 * for wire parity and always emits null on the strict flow. */
export interface LoopSignals {
  stop_reason: string;
  hops: number;
  tool_calls: number;
  evidence_units: number;
}

export interface EvidenceSignals {
  decision: Decision;
  supporting_sources: number;
  distinct_documents: number;
  retrieval_score_spread: number;
  all_claims_verified: boolean;
  unsupported_claims_removed: number;
  conflicts_detected: number;
  languages_in_evidence: string[];
  /** null on the strict flow (deep-ask is Python-only) — present for wire parity. */
  loop: LoopSignals | null;
}

export interface SourceRef {
  document: string;
  passage: string;
  passage_language: string;
  page: number | null;
  bbox: unknown | null;
  source_uri: string | null;
  translation: string | null;
}

export interface Claim {
  claim: string;
  supported: boolean;
  sources: string[];
}

export interface ProvenanceEntry {
  claim: string;
  evidence_unit: string;
  document_id: string;
  s3_object: string;
  checksum: string;
  page: number | null;
  bbox: unknown | null;
  produced_by: Record<string, unknown> | null;
}

export interface Result {
  answer: string;
  answer_language: string;
  mode: TrustMode;
  evidence: EvidenceSignals;
  claims: Claim[];
  sources: SourceRef[];
  missing_evidence: string[];
  conflicts: string[];
  provenance: ProvenanceEntry[];
}

export function evidenceSignals(opts: {
  decision: Decision;
  supportingSources?: number;
  distinctDocuments?: number;
  retrievalScoreSpread?: number;
  allClaimsVerified?: boolean;
  unsupportedClaimsRemoved?: number;
  conflictsDetected?: number;
  languagesInEvidence?: string[];
}): EvidenceSignals {
  return {
    decision: opts.decision,
    supporting_sources: opts.supportingSources ?? 0,
    distinct_documents: opts.distinctDocuments ?? 0,
    retrieval_score_spread: opts.retrievalScoreSpread ?? 0.0,
    all_claims_verified: opts.allClaimsVerified ?? false,
    unsupported_claims_removed: opts.unsupportedClaimsRemoved ?? 0,
    conflicts_detected: opts.conflictsDetected ?? 0,
    languages_in_evidence: opts.languagesInEvidence ?? [],
    loop: null,
  };
}

export function sourceRef(opts: {
  document: string;
  passage: string;
  passageLanguage: string;
  page?: number | null;
  bbox?: unknown | null;
  sourceUri?: string | null;
  translation?: string | null;
}): SourceRef {
  return {
    document: opts.document,
    passage: opts.passage,
    passage_language: opts.passageLanguage,
    page: opts.page ?? null,
    bbox: opts.bbox ?? null,
    source_uri: opts.sourceUri ?? null,
    translation: opts.translation ?? null,
  };
}

export function claim(opts: {
  claim: string;
  supported: boolean;
  sources?: string[];
}): Claim {
  return {
    claim: opts.claim,
    supported: opts.supported,
    sources: opts.sources ?? [],
  };
}

export function provenanceEntry(opts: {
  claim: string;
  evidenceUnit: string;
  documentId: string;
  s3Object: string;
  checksum: string;
  page?: number | null;
  bbox?: unknown | null;
  producedBy?: Record<string, unknown> | null;
}): ProvenanceEntry {
  return {
    claim: opts.claim,
    evidence_unit: opts.evidenceUnit,
    document_id: opts.documentId,
    s3_object: opts.s3Object,
    checksum: opts.checksum,
    page: opts.page ?? null,
    bbox: opts.bbox ?? null,
    produced_by: opts.producedBy ?? null,
  };
}

export function result(opts: {
  answer: string;
  answerLanguage: string;
  mode: TrustMode;
  evidence: EvidenceSignals;
  claims?: Claim[];
  sources?: SourceRef[];
  missingEvidence?: string[];
  conflicts?: string[];
  provenance?: ProvenanceEntry[];
}): Result {
  return {
    answer: opts.answer,
    answer_language: opts.answerLanguage,
    mode: opts.mode,
    evidence: opts.evidence,
    claims: opts.claims ?? [],
    sources: opts.sources ?? [],
    missing_evidence: opts.missingEvidence ?? [],
    conflicts: opts.conflicts ?? [],
    provenance: opts.provenance ?? [],
  };
}
