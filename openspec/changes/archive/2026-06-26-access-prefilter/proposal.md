## Why

CiteNexus's tenancy model is physical and hierarchical (§6b): every Evidence Unit
lives in a variable-depth partition (org → product line → product) and carries an
opaque `acl`. Final RBAC enforcement is delegated to an external operator-managed
store (Postgres or other), keeping the library S3-pure. The library still needs a
defined, honest seam to *consume* that store's decision — turning a query scope
into a partition prefix and using a caller-resolved set of allowed partitions as a
hard pre-filter that shrinks the search space before retrieval (§7c).

## What Changes

- Add `resolve_scope(scope, hierarchy)`: a scope dict + the deployment's ordered
  `partition_hierarchy` resolve into a `PartitionPath` *prefix* (full scope → one
  leaf; shorter prefix → its sub-tree). Gaps and unknown keys are rejected.
- Add the partition pre-filter: `allowed_partition(candidate, allowed_set)` is true
  iff some allowed path `is_prefix_of` the candidate (authorization at a prefix
  grants its descendants); `filter_partitions(...)` drops disallowed partitions
  *before* retrieval; an empty allowed set ⇒ nothing visible.
- Add an OPTIONAL `apply_acl_predicate(objects, acl_of, predicate)` second stage to
  filter remaining objects by their opaque `acl`. The library NEVER parses `acl`;
  it is passed verbatim to the caller's predicate.
- The library remains RBAC-*ready*, not an RBAC engine: it carries tags + `acl` at
  zero query cost until a caller supplies an allowed set; it never enforces.

## Capabilities

### New Capabilities
- `access-prefilter`: scope→partition-prefix resolution and the hard
  allowed-partitions pre-filter (plus the optional opaque-acl predicate stage)
  that gate retrieval by tenancy without the library acting as an RBAC engine.

### Modified Capabilities
<!-- None: this is purely additive; PartitionPath (§6b) already ships and is reused unchanged. -->

## Impact

- New module `src/citenexus/access/` (`scope.py`, `prefilter.py`, `__init__.py`),
  building only on the existing `citenexus.domain.partition.PartitionPath`.
- New tests under `tests/access/`. No new dependencies; no public-API verb change
  (this is a seam consumed by L3+ retrieval, not a fourth verb).
