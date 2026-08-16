# 0008 — Corpus–index reconciliation: the agreed corpus is the authority

Status: proposed · 2026-08-11

## Context

CiteNexus already has most of the freshness machinery: ingest is idempotent by
content hash, `storage/manifest.py` records what is stored, `provenance/stamp.py`
+ `provenance/rebuild_planner.py` compute surgical partial rebuilds (the SPEC-v6
§4c matrix), and `delete.py` revokes a document from every layer.

What it cannot do is answer the one question an auditor asks: **is this index
derived from exactly the corpus we agreed to, and nothing else?**

Every existing mechanism is *change-driven* — it reacts to an ingest, an update,
or a revoke. None is *state-driven*. Nothing ever compares the live index against
an independent statement of what should be in it. So an artifact that entered by
a path the change log didn't cover — a partial or crashed ingest, a restored
snapshot, a shared bucket prefix, a superseded document version, an ingest run
against the wrong config — stays indexed, stays retrievable, and gets **cited**.
A citation to a document nobody agreed was in the corpus is indistinguishable, at
the point of use, from a correct one: it has a real document ID, a real page, a
real bbox, and a verbatim passage. The cite-or-abstain guarantee holds and the
answer is still indefensible, because the guarantee is scoped to the index and
the auditor's question is scoped to the corpus.

This is the one gap in the freshness story that cannot be closed by being more
careful during ingest, because its whole premise is that something got in
*without* going through ingest.

Two shapes were considered:

1. **Make ingest the sole gate** — refuse any write that isn't manifest-approved.
   Rejected: it does not detect what is *already* there, it does not survive a
   restored snapshot or an out-of-band write to shared object storage, and it
   turns a diagnostic into a hard coupling on the write path.
2. **A declared corpus manifest plus a reconciliation pass that diffs it against
   live index state.** Chosen — it is verifiable after the fact, it works
   regardless of how a stray artifact arrived, and it produces a report a
   non-engineer can read.

## Decision

Introduce the **corpus manifest** as a first-class, caller-declared input, and a
reconciliation pass that diffs it against live index state.

- A versioned manifest declares the agreed corpus: `document_id`, source URI,
  file SHA-256, version, effective date. It is *authored by the caller*, not
  derived from the index — a manifest generated from the index could never
  disagree with it, which is the entire point.
- `reconcile(manifest)` returns a structured report with three disjoint sets:
  **orphans** (indexed, not in the manifest), **missing** (in the manifest, not
  indexed), and **drifted** (present in both, content hash mismatch). It is a
  read-only diagnostic and mutates nothing.
- Remediation is a **separate, explicit call** that consumes a report. Orphans
  are removed through the existing `delete.py` revoke path — one deletion
  mechanism, not two. Nothing is ever deleted as a side effect of a diagnostic.
- Version supersession folds in here: when a manifest designates one version as
  current, prior versions of the same `document_id` are drifted, not orphans, and
  retrieval filters to the current version by default.
- A reconciliation report is stamped into the append-only audit stream, so
  "the index matched the agreed corpus at time T" is an evidence artifact rather
  than a claim.

## Validation (spike, 2026-08-11 — `spikes/adr-0008-reconcile/`)

Prototyped against real storage. Buildable on the existing seam in ~150 lines
with zero core changes; the three-set diff, disjointness, read-only-ness,
idempotence, supersession-as-drift and remediation-via-`delete.py` all verified.

Three findings amend this ADR:

- **Enumeration needs no new primitive** for the per-partition case. Union
  `EtagManifest.etags` (`storage/manifest.py:31`, the logical record and the
  revoke commit point) with `VectorStore.scan()` (`storage/protocols.py:40`, the
  physical record) — the union is what makes half-states visible. Whole-bucket
  reconcile is the exception and needs one new `list_partitions(base_uri)`,
  derivable from `list_prefix("manifests/")`.
- **Reconcile is document-keyed**, so byte-level orphans under `raw/` and
  `knowledge/` are invisible to it. The report must state its own scope rather
  than imply it proves storage is clean.
- **Blocking precondition — a blob leak in the existing revoke path.** Re-ingest
  overwrites the single-valued `document_id → checksum` map (`ingest/pipeline.py:169`)
  without deleting the prior blob, and `client.delete` removes only the currently
  recorded checksum (`client.py:513,536`). Measured: ingest → re-ingest →
  `delete()` reports `status="deleted"` while the revoked document's earlier full
  text survives at `raw/<partition>/<old-hash>`, unreferenced and unreachable
  through any API. Remediation must not ship before this is fixed, or
  reconcile → remediate → reconcile will certify a bucket clean while revoked
  bytes remain — an actively false assurance, which is worse than no report.
  Tracked separately as a bug against revoke, not as part of this change.

## Consequences

- CiteNexus gains an auditable answer to "where did this citation come from" that
  reaches past the index to the agreed corpus. In regulated deployments this is
  the difference between a demonstrable control and a verbal assurance.
- The manifest is a new caller obligation. Callers who don't supply one lose
  nothing: reconciliation is opt-in and every existing flow is untouched.
- Read-only-by-default is a deliberate cost. A drifted index stays wrong until
  someone acts on the report. Auto-remediation would be a data-loss footgun on a
  shared bucket, and this library deletes only on explicit instruction.
- The diagnostic is only as good as the manifest's honesty. A manifest
  rubber-stamped from a directory listing reproduces whatever is wrong in that
  directory. This is a process boundary the library cannot close, and the docs
  must say so rather than imply the report proves more than it does.
- Passes both scope gates (CLAUDE.md): it improves grounded retrieval by bounding
  what may be cited, and its output is fully citable — every line of the report
  names a document and a hash.
