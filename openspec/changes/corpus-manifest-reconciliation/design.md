## Context

ADR-0008 chose a declared manifest plus a reconciliation pass over the
alternative (make ingest the sole gate), because the failure modes worth
detecting are exactly the ones that bypassed ingest: restored snapshots, shared
bucket prefixes, crashed runs, wrong-config ingests.

`spikes/adr-0008-reconcile/` built it against real storage (`LocalFsBackend` +
a real on-disk LanceDB leaf, driven through the real `CiteNexus`) and verified
the three-set diff, disjointness, read-only-ness, idempotence,
supersession-as-drift, and remediation-through-`delete.py`. This design follows
what that spike measured; where the ADR and the spike disagree, the spike wins.

Constraints: no model and no network on the reconcile path (it is bookkeeping);
nothing deleted as a side effect of a diagnostic; a shared bucket is the normal
deployment, so the pass must never be able to talk anyone into deleting bytes it
cannot attribute.

## Goals / Non-Goals

**Goals:**

- Answer "is this index derived from exactly the corpus we agreed to?" with a
  report a non-engineer can read and an auditor can keep.
- Three disjoint sets, by construction rather than by assertion.
- Remediation that reuses the one existing deletion path.
- A report that is honest about what it does *not* cover.

**Non-Goals:**

- Byte-level orphan detection under `raw/` / `knowledge/`. Out of scope by
  construction — see the scope decision below.
- Whole-bucket / multi-partition reconcile. Deferred, with the reason stated.
- Auto-remediation. A data-loss footgun on a shared bucket; this library deletes
  only on explicit instruction.
- Retrieval-time filtering to the current version. ADR-0008 mentions it under
  supersession; it is a retrieval change with its own blast radius and belongs in
  its own change. Reconcile only *reports* supersession.
- Judging the manifest. A manifest rubber-stamped from a directory listing
  reproduces whatever is wrong in that directory. That is a process boundary the
  library cannot close.

## Decisions

### Enumeration unions the etag manifest with the vector scan

`EtagManifest.etags` is the **logical** presence record — it is what ingest
commits and what revoke forgets last. `VectorStore.scan()` rows carry
`document_id` and `checksum` and are the **physical** record. Either alone misses
one direction of half-state:

- etags only → a crashed revoke or an out-of-band write that left vector rows
  without a manifest entry is invisible, and on a shared bucket that is a
  *citable* document.
- scan only → with neither `embedding` nor `text` declared, ingest writes no
  vector rows at all, so the whole corpus reads as absent.

So a document counts as indexed if **either** source knows it, with the etag
manifest authoritative for its checksum. No new primitive is required; both calls
already exist.

*Cost note carried from the spike:* `scan()` has no projection and no pagination
(`lance_store.py` does `tbl.to_arrow().to_pylist()`), so it materializes every EU
row, vector column included. Reconcile is O(documents) through the manifest and
only pays the scan for the physical cross-check — which is why the scan is a
supplement here and not the primary source.

### Per-partition scope; `list_partitions` deliberately not added

`CiteNexus` is bound to one `PartitionPath` at construction, so `rag.reconcile()`
reconciles that partition. Whole-bucket reconcile needs
`list_partitions(base_uri)`, trivially derivable from
`list_prefix("manifests/")` — but it also needs an entry point that is *not* a
partition-bound client, which is a public-surface change of its own. Adding an
unused primitive now would be speculative; a caller with several partitions
iterates them today, which is what the spike did. Stated here so the omission is
a decision rather than an oversight.

### Supersession is drift, and the finding says which version

A `document_id` declared in the manifest is never an orphan, even if the indexed
bytes match no current entry — orphanhood means "nobody agreed this document
belongs here at all", which is a different remediation (delete) from "the wrong
version of an agreed document is indexed" (re-ingest). Classifying supersession
as orphanhood would route a version-lag straight into a deletion.

The drift finding therefore carries a `reason`: `content_mismatch` when the
indexed hash matches no declared version, `superseded_version` when it matches a
declared non-current one — plus that version's label, so the report names what is
indexed instead of only saying it is wrong.

### Disjointness is structural, not asserted

One pass over the indexed set classifies each `document_id` into exactly one
branch; `missing` is computed over declared ids that are, by construction, not in
the indexed set. The sets cannot overlap because no id can reach two branches.
Tests assert it anyway, on every fixture, because the property is the whole
contract.

### Read-only means "mutates no evidence"; the audit stream is append-only

There is a real tension in ADR-0008: reconcile "mutates nothing" *and* its report
is "stamped into the append-only audit stream". Resolved by scoping the guarantee
precisely rather than picking one:

- Reconcile writes to **no** existing object and to no evidence layer — not the
  index, not raw, not knowledge, not graph, not wiki, not the etag manifest.
- It appends one line to `eval/<P>/reconcile_log.jsonl`, an object that exists
  only to hold reconciliation records and is never rewritten in place.
- `audit=False` gives a strictly zero-write run, for a caller who wants the
  diagnostic without touching the bucket at all.

The tests assert the strong property directly: a full key/row snapshot of every
evidence layer, taken before and after, must be identical.

### Remediation removes orphans only, through `client.delete`

`remediate(report)` loops `client.delete(document_id)` over `report.orphans`.
Reusing revoke rather than deleting keys directly is what keeps the guarantee
that a removed document leaves nothing behind in any layer — including the
superseded raw blobs that the `revoke-superseded-blobs` change made reachable.
Two deletion mechanisms would mean two definitions of "removed", and the weaker
one would silently become the real one.

`missing` and `drifted` are never touched: the first needs an ingest and the
second a re-ingest, and both need the caller's source bytes, which the library
does not have.

A report can be stale by the time it is remediated. Rather than re-deriving the
diff (which would make remediation a second, hidden reconcile), remediation
inherits `delete`'s idempotence — a document already gone returns `absent` and
changes nothing — and the per-document outcome is recorded in the remediation
report so a stale entry is visible rather than silent.

### The report carries its own scope limitation as data

Reconcile is **document-keyed**. A crashed ingest leaves `raw/<P>/<hash>` and
`knowledge/<P>/structure/<id>.json` with no etag entry and no vector rows
(measured in the spike); those bytes are invisible to a document-keyed diff, and
so are blobs written by another tool into a shared prefix.

`ReconcileReport.scope` states this in the report object itself. A footnote in
the docs would be read once; a field is read every time the report is. An empty
report means "no document-level disagreement with the declared corpus", and the
report says so in its own words — it does not mean the bucket is clean.

## Risks / Trade-offs

- **The diagnostic is only as good as the manifest.** Unclosable in the library;
  stated in the spec and in the report's scope text.
- **Read-only by default leaves a drifted index wrong** until someone acts. That
  is the deliberate cost of never deleting as a side effect.
- **The physical cross-check is O(rows) in memory.** Documented above; the
  manifest path is the cheap one and remains authoritative.
- **Shared-prefix ghosts are only reachable on S3.** The union enumeration covers
  the shape (vector rows with no etag entry) but the spike could only produce it
  through the ingest API. A MinIO integration test is the honest follow-up.

## Open Questions

- Should retrieval filter to the manifest's current version by default? ADR-0008
  suggests it; it is a retrieval-behavior change and is out of scope here.
- Whole-bucket reconcile and the `list_partitions` primitive: deferred until
  there is a caller that needs it.
