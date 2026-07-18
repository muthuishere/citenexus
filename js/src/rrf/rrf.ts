// Reciprocal Rank Fusion — the pinned in-core merge of ranked signal lists
// (SPEC-PORTS-v1 §4/§10). Parity with the Python reference
// citenexus.retrieve.fusion.rrf_fuse.
//
// Each input list is a ranked list of eu_id strings. A candidate at zero-based
// `rank` in a list contributes 1 / (k + rank + 1) to its eu_id's fused score.
// Contributions sum across all lists. The result is ordered by descending fused
// score, tie-broken ascending by eu_id.

/**
 * Fuse ranked eu_id lists with Reciprocal Rank Fusion (k defaults to 60).
 *
 * @deprecated rrf now lives once in the shared Rust core (ADR-0006). Prefer the
 * core-backed `rrf` from `citenexus/core`, which shares one implementation
 * across all SDKs. This pure helper is retained for the native-lib-free path and
 * stays pinned to the Python reference by the conformance/cases/rrf.json vectors;
 * it is byte-identical to `core.rrf`.
 */
export function rrfFuse(lists: string[][], k = 60): string[] {
  const fusedScore = new Map<string, number>();

  for (const candidates of lists) {
    for (const [rank, euId] of candidates.entries()) {
      fusedScore.set(euId, (fusedScore.get(euId) ?? 0) + 1 / (k + rank + 1));
    }
  }

  return [...fusedScore.entries()]
    .sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0))
    .map(([euId]) => euId);
}
