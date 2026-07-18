//! Reciprocal Rank Fusion — pure rank arithmetic over candidate IDs (ADR-0006).
//!
//! This is the ONE deterministic algorithm ADR-0006 moves into the core: it has
//! no tokenization, no Unicode, and no credentials — only rank/score arithmetic
//! over `eu_id` strings, so there is zero multilingual risk in relocating it.
//! The gate, tokenizer, `bm25`, and `chunker` stay per host language and are
//! pinned by conformance vectors instead.
//!
//! Contract (parity with the Python reference `citenexus.retrieve.fusion`):
//! given several ranked lists of `eu_id` strings and a constant `k` (default
//! 60), a candidate at zero-based `rank` in a list contributes `1 / (k + rank +
//! 1)` to its `eu_id`'s fused score. Contributions sum across all lists. The
//! result is ordered by descending fused score, tie-broken ascending by `eu_id`.

use std::collections::HashMap;

/// Fuse ranked `eu_id` lists with Reciprocal Rank Fusion and return the fused
/// `eu_id` order (descending fused score, ascending `eu_id` tie-break). The
/// policy constant `k` is passed in so the core stays policy-free (ADR-0006).
pub fn rrf(lists: &[Vec<String>], k: i64) -> Vec<String> {
    // Accumulate in list-then-rank traversal order so the per-eu_id float sum is
    // bit-identical to the Python/Go/JS reference (identical IEEE-754 ops, same
    // order). Final ordering is fully deterministic via the (score, eu_id) sort.
    let mut scores: HashMap<&str, f64> = HashMap::new();
    for list in lists {
        for (rank, eu_id) in list.iter().enumerate() {
            let contribution = 1.0 / (k + rank as i64 + 1) as f64;
            *scores.entry(eu_id.as_str()).or_insert(0.0) += contribution;
        }
    }

    let mut fused: Vec<(&str, f64)> = scores.into_iter().collect();
    fused.sort_by(|a, b| {
        // Descending score, then ascending eu_id — matches the reference exactly.
        b.1.partial_cmp(&a.1)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| a.0.cmp(b.0))
    });
    fused.into_iter().map(|(eu_id, _)| eu_id.to_string()).collect()
}
