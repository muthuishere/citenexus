## Context

§6b makes tenancy physical: every EU lives in a variable-depth `PartitionPath`
(org → product line → product) and carries an opaque `acl`. §7c keeps the library
**RBAC-ready, not an RBAC engine** — final enforcement lives in an external
operator-managed store (Postgres or other). This change adds the seam that
consumes that store's decision: scope→prefix resolution plus a hard
allowed-partitions pre-filter, building only on the already-shipped
`trustrag.domain.partition.PartitionPath` (`is_prefix_of`, variable depth).

## Goals / Non-Goals

**Goals:**
- Resolve a query scope + hierarchy order into a single `PartitionPath` prefix.
- Gate candidate partitions against a caller-resolved allowed set, as a pre-filter
  that runs *before* retrieval and only shrinks the search space.
- Offer an optional, opaque-`acl` predicate stage the library never parses.

**Non-Goals:**
- No RBAC engine, role/policy model, or `acl` schema. The library never decides
  *who* is allowed — it consumes an allowed set someone else resolved.
- No external-store integration, caching, or query path here (that is L6
  `external-store authorization enforcement`).
- No change to `PartitionPath` or the three-verb public surface.

## Decisions

- **Prefix = contiguous run of the hierarchy.** `resolve_scope` walks the
  hierarchy in order and consumes levels present in the scope; the first missing
  level closes the prefix. A value *after* a gap, or a key outside the hierarchy,
  raises `ValueError`. Rationale: a partition key is positional, so a scope that
  skips `product_line` but names `product` is meaningless — fail loudly rather than
  silently dropping the deeper level. Alternative (best-effort: take whatever
  contiguous prefix exists, ignore the rest) was rejected as a silent-authz
  footgun.
- **Allow-by-prefix, not allow-by-exact.** `allowed_partition` is `any(a.is_prefix_of(c))`.
  Authorization at a prefix intentionally grants the whole sub-tree, matching the
  tenancy hierarchy; an exact-match rule would force callers to enumerate every
  leaf. The asymmetry is deliberate: being allowed at `acme/contracts/nda` does
  **not** grant the broader `acme/contracts` (an ancestor is not a descendant).
- **Empty allowed set ⇒ deny-all.** `any(...)` over an empty set is `False`, which
  is the correct fail-closed default — absence of an allowance is denial, never a
  wildcard.
- **`acl` stays opaque.** `apply_acl_predicate(objects, acl_of, predicate)` extracts
  the acl via `acl_of` and hands it untouched to `predicate`. The library performs
  no parse/compare/hash/coerce on the acl. This keeps the library agnostic to the
  operator's acl format and is enforced by a test using an acl whose every dunder
  raises. With no predicate the stage is an order-preserving no-op.

## Risks / Trade-offs

- **Honest scope — coarse is solid, fine is weak.** Partition-prefix enforcement is
  strong: a dropped partition is never retrieved, so its EUs cannot reach the
  answer. The optional `acl` stage is materially weaker — it filters whole
  candidate objects the caller chooses to expose, and the library cannot reason
  about acl semantics at all. → Document it as defense-in-depth, not a guarantee;
  the partition pre-filter is the real boundary.
- **Answer-leakage is out of scope.** Neither stage addresses *answer*-level
  leakage (a grounded answer paraphrasing content the principal may see from a
  partition they can see, but which a finer acl would hide within that partition).
  Finer-than-partition data must live in a separate partition to be truly isolated.
  → Do not oversell `acl` as row-level security.
- **Zero query cost until used.** Carrying tags + acl costs nothing until a caller
  supplies an allowed set / predicate; when supplied, the pre-filter strictly
  reduces candidates, so enforcement improves latency and never costs it. → The
  only risk is mis-resolved scope/allowed sets *by the caller*, which is theirs to
  own (the external-store responsibility).

## Open Questions

- Whether L6's external-store enforcement should also cache resolved allowed sets
  per principal — deferred to that change; this seam stays pure and stateless.
