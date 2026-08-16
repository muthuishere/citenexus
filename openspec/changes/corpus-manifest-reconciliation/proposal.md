## Why

CiteNexus can prove a citation is faithful to the index. It cannot prove the
index is derived from the corpus that was agreed to.

Every freshness mechanism in the library is **change-driven**: ingest is
idempotent by content hash, `provenance/rebuild_planner.py` computes surgical
rebuilds, `delete.py` revokes. Each reacts to an operation. Nothing is
**state-driven** — nothing ever compares the live index against an independent
statement of what belongs in it. So an artifact that entered by a path the change
log did not cover (a crashed ingest, a restored snapshot, a shared bucket prefix,
an ingest run against the wrong config, a superseded document version) stays
indexed, stays retrievable, and gets **cited**.

That citation is indistinguishable, at the point of use, from a correct one: real
document id, real page, real bbox, verbatim passage. The cite-or-abstain
guarantee holds and the answer is still indefensible, because the guarantee is
scoped to the index and the auditor's question is scoped to the corpus.

Being more careful during ingest cannot close this, because the premise is that
something got in *without* going through ingest. ADR-0008 records the decision;
`spikes/adr-0008-reconcile/` validated it against real storage (~150 lines, zero
core changes, every property verified).

Its blocking precondition — the revoke blob leak — is fixed by the
`revoke-superseded-blobs` change. Without it, reconcile → remediate → reconcile
would have certified a bucket clean while revoked bytes remained.

## What Changes

- Add `CorpusManifest` — a caller-**authored**, versioned declaration of the
  agreed corpus: `document_id`, source URI, file SHA-256, version, effective
  date. Authored, never derived: a manifest generated from the index could not
  disagree with the index, which is the entire point of the mechanism.
- Add `rag.reconcile(manifest) -> ReconcileReport` — three DISJOINT sets:
  **orphans** (indexed, not declared), **missing** (declared current, not
  indexed), **drifted** (declared and indexed, hashes disagree). It changes
  nothing in the index or in any evidence layer.
- Version supersession is **drift, not orphanhood**: a `document_id` whose
  indexed bytes match a declared non-current version is drifted, with the
  superseded version named in the finding.
- Add `rag.remediate(report) -> RemediationReport` — a **separate, explicit**
  call that consumes a report and removes **orphans only**, through the existing
  `client.delete` path. One deletion mechanism, not two. `missing` needs an
  ingest and `drifted` needs a re-ingest; neither is a deletion, so neither is
  touched. Nothing is ever deleted as a side effect of a diagnostic.
- Both calls append a stamped record to an **append-only** reconciliation audit
  stream under `eval/<P>/`, so "the index matched the agreed corpus at time T" is
  an evidence artifact rather than a claim. Appending can be switched off for a
  strictly zero-write run.
- The report **states its own scope**: it is document-keyed, so byte-level
  residue under `raw/` and `knowledge/` is invisible to it. The report carries
  that limitation as data, not as a docs footnote, so nothing downstream can read
  it as proof that storage is clean.

## Capabilities

### New Capabilities
- `corpus-manifest-reconciliation`: the declared corpus manifest, the read-only
  three-set diff, supersession-as-drift, explicit orphan remediation through the
  existing revoke path, and the audit stamp.

## Impact

- **Code:** new `python/src/citenexus/reconcile/` (`manifest.py`, `report.py`,
  `engine.py`, `audit.py`); `client.py` gains `reconcile()` / `remediate()`;
  `citenexus/__init__.py` exports the new types.
- **Storage:** a new append-only object `eval/<P>/reconcile_log.jsonl`. No
  existing layer is read differently or written at all.
- **New primitives:** none. Enumeration unions `EtagManifest.etags` (the logical
  presence record, and the revoke commit point) with `VectorStore.scan()` (the
  physical one) — the union is what makes half-states visible. Both already
  exist.
- **Scope:** per-partition, because `CiteNexus` is bound to one `PartitionPath`
  at construction. Whole-bucket reconcile would need `list_partitions(base_uri)`;
  deliberately **not** added here (see `design.md`).
- **Tests:** new `tests/reconcile/` — the ADR's drift matrix (ghost, crashed
  ingest, changed source, superseded version), disjointness, read-only-ness,
  idempotence, remediation-through-revoke, audit append.
- **Ports:** none. Reconciliation is orchestration over the storage seam, not a
  deterministic algorithm the ports share.
- **Not touched:** `answer/`, retrieval, conformance vectors, ingest.
