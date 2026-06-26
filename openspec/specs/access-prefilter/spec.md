# access-prefilter Specification

## Purpose
TBD - created by archiving change access-prefilter. Update Purpose after archive.
## Requirements
### Requirement: Scope resolves to a partition-prefix path

The system SHALL resolve a query scope (a mapping of level→value) against the
deployment's ordered `partition_hierarchy` into a `PartitionPath`. The result
SHALL be a contiguous prefix of the hierarchy: a scope naming every level targets
one leaf partition; a scope naming a shorter prefix targets the entire sub-tree
beneath it. The system SHALL reject a scope that skips a hierarchy level (a gap)
and a scope containing any key not present in the hierarchy. An empty scope SHALL
resolve to the depth-0 root prefix.

#### Scenario: Full scope resolves to a leaf path
- **WHEN** `resolve_scope({"org":"acme","product_line":"contracts","product":"nda-review"}, ("org","product_line","product"))` is called
- **THEN** it returns the depth-3 `PartitionPath` `acme/contracts/nda-review`

#### Scenario: Partial scope resolves to a sub-tree prefix
- **WHEN** `resolve_scope({"org":"acme","product_line":"contracts"}, ("org","product_line","product"))` is called
- **THEN** it returns the depth-2 prefix `acme/contracts` that `is_prefix_of` every leaf below it

#### Scenario: Empty scope resolves to the root prefix
- **WHEN** `resolve_scope({}, ("org","product_line","product"))` is called
- **THEN** it returns a depth-0 `PartitionPath`

#### Scenario: Gap or unknown key is rejected
- **WHEN** a scope skips a level (e.g. `{"org":"acme","product":"nda"}`) or names a key outside the hierarchy (e.g. `{"region":"eu"}`)
- **THEN** the system raises `ValueError` naming the offending level or key

### Requirement: Allowed-partitions hard pre-filter

The system SHALL treat a caller-supplied set of allowed `PartitionPath`s as a hard
pre-filter consumed before retrieval. A candidate partition SHALL be allowed if and
only if some allowed path `is_prefix_of` it, so a principal authorized at a prefix
sees all descendant partitions. The system SHALL drop disallowed candidate
partitions, only ever shrinking the search space. An empty allowed set SHALL make
nothing visible. The system SHALL NOT itself enforce or evaluate RBAC beyond this
set membership — it consumes a decision resolved by an external store.

#### Scenario: Descendant of an allowed prefix is allowed
- **WHEN** `allowed_partition(acme/contracts/nda-review, {acme/contracts})` is evaluated
- **THEN** it returns true

#### Scenario: Disallowed sibling partition is rejected
- **WHEN** `allowed_partition(acme/hr, {acme/contracts})` is evaluated
- **THEN** it returns false

#### Scenario: Empty allowed set rejects everything
- **WHEN** `allowed_partition(candidate, set())` is evaluated for any candidate
- **THEN** it returns false

#### Scenario: Filtering drops disallowed partitions and preserves order
- **WHEN** `filter_partitions([acme/contracts, acme/hr, acme/contracts/nda, globex/contracts], {acme/contracts})` is called
- **THEN** it returns `[acme/contracts, acme/contracts/nda]` in input order

### Requirement: Optional opaque-acl predicate stage

The system SHALL offer an optional second-stage filter over already
partition-allowed objects, keyed on each object's opaque `acl`. The system SHALL
pass the `acl` verbatim to a caller-supplied predicate and SHALL NOT parse,
inspect, hash, or compare the `acl` itself — the predicate is the only code that
interprets it. When no predicate is supplied, the stage SHALL keep every object,
preserving order.

#### Scenario: Predicate filters remaining objects by acl
- **WHEN** `apply_acl_predicate(objects, acl_of, predicate)` runs with a predicate that accepts only partners
- **THEN** only objects whose acl the predicate accepts are kept, in input order

#### Scenario: No predicate keeps everything
- **WHEN** `apply_acl_predicate(objects, acl_of)` is called with no predicate
- **THEN** all objects are returned unchanged

#### Scenario: The acl is never parsed by the library
- **WHEN** an object carries an `acl` whose every comparison/hash/coercion would raise, and a predicate that merely records what it receives is supplied
- **THEN** the call succeeds and the predicate receives the exact same opaque `acl` object, proving the library never touched it

