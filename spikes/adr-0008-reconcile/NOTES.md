# Spike — ADR-0008 corpus↔index reconciliation, against real storage

Date: 2026-08-11 · Validates `docs/adr/0008-corpus-manifest-reconciliation.md`

`spikes/library-stress/NOTES.md` explicitly says ADR-0008 is UNVALIDATED by that
spike and needs one against real storage. This is that spike.

## Run

```
cd python && uv run python ../spikes/adr-0008-reconcile/spike.py
```

Real storage: `LocalFsBackend` over a tmp dir (the same `StorageBackend` ABC
`S3Backend` implements) plus a real on-disk LanceDB leaf store, driven through
the real `CiteNexus` client with signals `embedding,text,structure,graph,wiki`.
Only the embedder is a fake (deterministic hashing) — reconciliation is pure
bookkeeping, no model participates. **Exits 1** — because of a real bug found
(revoke residue), not a spike defect. Every other check passes.

## PART 1 — enumeration verdict: POSSIBLE TODAY, no new primitive needed

`document_id → content hash` for the live index is readable from existing API,
via two sources that are unioned (`spike.py:enumerate_index`):

- `python/src/citenexus/storage/manifest.py:31` — `EtagManifest.etags`
  (`document_id → checksum`), loaded with
  `python/src/citenexus/storage/manifest.py:78` `load_manifest(...)` under the
  key `python/src/citenexus/ingest/pipeline.py:79` `IngestPipeline.ETAG`.
- `python/src/citenexus/storage/protocols.py:40` — `VectorStore.scan()`; rows
  carry `document_id` and `checksum`, written at
  `python/src/citenexus/ingest/pipeline.py:182-200`.

The etag manifest is the *logical* presence record — it is the revoke commit
point (`python/src/citenexus/client.py:545`). The vector scan is the *physical*
one. Unioning them is what makes half-states (crashed ingest, interrupted
revoke) visible; either source alone would miss one direction. Verified equal
for a clean corpus.

Caveats that shape the cost, but do not block the ADR:

1. **`scan()` has no projection and no pagination** (`protocols.py:40`,
   `lance_store.py:67` does `tbl.to_arrow().to_pylist()`). Enumerating a large
   leaf materializes every EU row — vector column included — in memory. For
   reconciliation the etag manifest alone suffices and is O(docs), so the
   production path should read the manifest and use `scan()` only for the
   physical cross-check (or behind a size guard). Not a missing primitive, but
   a real "don't do the naive thing" note.
2. **Enumeration is per-partition.** `CiteNexus` is bound to one
   `PartitionPath` at construction (`client.py:159`), and there is no
   "list partitions under this base_uri" call. A corpus-wide reconcile over a
   multi-partition deployment must be driven by the caller iterating known
   partitions. If ADR-0008 wants whole-bucket reconciliation, **that** is the
   one primitive to add: `list_partitions(base_uri) -> [PartitionPath]`,
   derivable from `StorageBackend.list_prefix("manifests/")` — cheap, but it
   does not exist today.
3. **Signal-dependent.** With neither `embedding` nor `text` declared, ingest
   writes no vector rows at all (`pipeline.py:179`), so the etag manifest is
   the *only* record. Another reason the manifest, not the vector store, is the
   authoritative enumeration source.

## PART 2 — the diff

`reconcile(rag, manifest) -> ReconcileReport` returns three sets, read-only:

- **orphans** — indexed, `document_id` absent from the manifest entirely.
- **missing** — declared current in the manifest, not indexed.
- **drifted** — present in both but hash mismatch; *also* the supersession case
  (a `document_id` whose indexed hash matches a non-current manifest version).

Disjointness is structural, not merely observed: a `document_id` is classified
in exactly one branch of a single pass over the indexed set, and `missing` is
computed over ids that are by construction not in the indexed set. Asserted on
every fixture (`assert_disjoint`, 3 call sites, all pass). `reconcile` mutates
nothing — proved by comparing the full layer key/row snapshot before and after.

## PART 3 — drift scenarios (all caught)

| Scenario | How it was produced | Result |
|---|---|---|
| ghost document | ingested, never declared | `orphans=['ghost']` ✅ |
| crashed ingest | vector store wrapper raises on `upsert`, killing the run mid-pipeline | `missing=['crashed']` ✅ |
| changed source | ingest v1, then re-ingest new bytes; manifest still declares v1 | `drifted=('drifty', 73723d75, b2cacae5)` ✅ |
| superseded version | indexed v1; manifest declares v2 current, v1 not-current | `drifted`, **not** orphan ✅ |
| revoke residue | ingest, re-ingest, `delete()`, then probe every layer | **residue found — see below** ❌ |

Idempotence: two consecutive `reconcile` calls return byte-identical reports; a
manifest that matches the live index returns an empty report. Both pass.

### Incidental finding — an interrupted ingest leaves derived artifacts

The simulated crash (raised inside `VectorStore.upsert`) left behind, with **no**
etag entry and **no** vector rows:

```
raw/workspace=spike/e1227a21…      (the raw blob, written pipeline.py:169)
knowledge/workspace=spike/structure/crashed.json   (written pipeline.py:176)
```

This is by design — the etag write is the commit point (`pipeline.py:212`) and a
re-run overwrites both idempotently. But it means "orphan" is *document-level*;
byte-level orphans in the `raw`/`knowledge` layers are invisible to a
document-keyed reconcile. Worth stating in the ADR rather than implying the
report proves the storage is clean.

## Revoke residue — a real bug (BLOB LEAK)

`CiteNexus.delete` (`python/src/citenexus/client.py:493-548`) deletes the raw
blob for **only the checksum currently recorded in the etag manifest**:

```python
checksum = manifest.etags[document_id]          # client.py:513
...
if not manifest.owners_of(checksum, excluding=document_id):
    self._backend.delete_prefix(f"{raw_prefix}/{checksum}")   # client.py:536
```

But ingest **never removes the previous checksum's blob when a document is
re-ingested** (`pipeline.py:169` just writes the new one, and the manifest is a
single-valued `document_id → checksum` map, `manifest.py:31`). So every update
strands the prior blob, and the etag manifest has already forgotten it — the
revoke has no way to find it.

Measured: ingest `victim`, re-ingest `victim` with new bytes, `delete("victim")`.

```
RESIDUE in raw (superseded blob, by hash):
  raw/workspace=spike/3c58d7e6e138546e3cf43d156b69121fca9a3ae3801ec9ca1f0074f2adad3941
```

The revoked document's earlier full text is still sitting in object storage,
unreferenced and unreachable through any CiteNexus API, after a revoke that
reported `status="deleted"`. For a library whose selling point is
"retract a document from every layer", in regulated deployments (right-to-erasure,
privileged-document clawback), that is a serious correctness gap, not a tidiness
one. **Not patched here** — reported per the spike rules.

Layers that came back **clean** (probed by key *and* by file content):
vector rows, BM25/lexical index (derived from `scan()`, so it follows), the
structure index, the wiki page + `index.json`/`index.md`, the graph blob, and
the etag manifest. The wiki `log.md` retains a `delete | victim` line, which is
correct — it is an append-only audit trail, and the probe excludes it.

Adjacent smell (not exercised): `ProcessingManifest`
(`python/src/citenexus/storage/manifest.py:59-75`) is defined, exported, and
documents `clear_status` as "called on a revoke" — but **nothing in the codebase
ever constructs or writes it**, revoke included. Today it is dead code; the day
the durable worker starts writing it, revoke will leak slow-path status too.

## PART 4 — remediation through the existing revoke path

`remediate(report)` is a separate call that loops `rag.delete(doc_id)` over
`report.orphans` only. Verified: the ghost was removed, the follow-up reconcile
shows no orphans, and `missing`/`drifted` are unchanged (remediation does not
touch them — a drifted doc needs a re-ingest, a missing one an ingest, neither
is a deletion). Nothing is deleted inside `reconcile`.

One design point the prototype exposes: because the orphan removal path is
`delete.py`/`client.delete`, remediation **inherits the blob leak above**. An
auditor running reconcile → remediate → reconcile gets a clean report while
superseded bytes of the removed orphans remain in the bucket. The report would
be true and the storage would not be. Fix the leak before shipping remediation.

## Would anything differ on S3/MinIO?

The reconcile logic is backend-agnostic — it goes through `StorageBackend` and
`VectorStore` only. Differences that matter operationally:

- **Listing cost/consistency.** `S3Backend.list_prefix` (`backend.py:131`)
  paginates `list_objects_v2`; on a large bucket the residue-style byte-level
  probe used here is expensive. Document-keyed reconcile via the etag manifest
  is one `get_object` and is unaffected.
- **`delete_prefix` semantics.** On local FS, `delete_prefix("raw/<P>/<hash>")`
  unlinks exactly one file (`backend.py:83`). On S3 it deletes **every key with
  that prefix** (`backend.py:139`). A checksum is a full sha256 hex so a
  collision-by-prefix is not realistic, but the two backends are not the same
  operation, and the blob leak looks identical on both.
- **Shared-prefix / out-of-band writes** — the exact scenario ADR-0008 exists
  for — are only reachable on S3. This spike can produce the ghost only through
  the ingest API; on a shared bucket a ghost can also appear as vector rows with
  no etag entry. The union-based enumeration already covers that shape, but it
  is untested here and should be the first MinIO integration test.
- Nothing found suggests reconciliation would behave *differently* on S3; the
  risk profile changes, the logic does not.

## Verdict — is ADR-0008 buildable on the existing storage seam?

**Yes, as specified, with one caveat and one prerequisite.**

- The three-set diff, disjointness, read-only-ness, idempotence, supersession
  handling, and remediation-through-`delete.py` all work on the existing seam
  with **no changes under `python/src`**. The prototype is ~150 lines.
- **Caveat (scope honesty):** reconcile is document-keyed, so it detects
  document-level drift only. Byte-level orphans in `raw/` and `knowledge/`
  (from crashed ingests and from the re-ingest blob leak) are invisible to it.
  The ADR should say so; otherwise the report implies more than it proves.
- **Prerequisite (a real bug, not a new primitive):** fix the superseded-blob
  leak in the revoke path before remediation ships, or ADR-0008's remediation
  will certify a bucket clean while revoked content remains in it.
- **New primitive needed only for multi-partition scope:**
  `list_partitions(base_uri)` (trivially derivable from
  `StorageBackend.list_prefix("manifests/")`). Single-partition reconcile needs
  nothing new.
