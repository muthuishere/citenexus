## 0. Precondition

- [x] 0.1 The revoke blob leak is fixed (`revoke-superseded-blobs`). Without it,
      reconcile → remediate → reconcile would certify a bucket clean while the
      revoked documents' superseded bytes remained — an actively false assurance

## 1. The declared corpus manifest

- [x] 1.1 `reconcile/manifest.py`: `CorpusEntry` (`document_id`, `sha256`,
      `version`, `current`, `source_uri`, `effective_date`) and `CorpusManifest`
      (`manifest_version`, `entries`), both frozen
- [x] 1.2 Reject a manifest declaring two current versions of one document — the
      ambiguity is unanswerable at the point it is consumed, so it fails where it
      is authored
- [x] 1.3 `current()` / `declares()` / `version_with_hash()` — the three
      questions the diff asks
- [x] 1.4 Provide NO index-derived constructor. A manifest generated from the
      index could not disagree with the index, which would void the diagnostic
- [x] 1.5 Tests: rejection of two current versions; one current plus superseded
      versions accepted

## 2. Enumeration (no new primitive)

- [x] 2.1 `enumerate_index()` — union `EtagManifest.etags` (logical, and the
      revoke commit point) with `VectorStore.scan()` (physical); the manifest is
      authoritative on the checksum, the scan only adds ids it never knew
- [x] 2.2 Confirm no new storage primitive is required for the per-partition
      case (the only scope a partition-bound `CiteNexus` has)
- [x] 2.3 Test the union in BOTH blind directions: rows with no manifest entry
      are still seen; a partition with no `embedding`/`text` signal (hence no
      rows at all) still enumerates
- [x] 2.4 Do NOT add `list_partitions(base_uri)`. Whole-bucket reconcile also
      needs a non-partition-bound entry point; deferring is recorded as a
      decision in design.md, not left as an omission

## 3. The three-set diff

- [x] 3.1 `reconcile()` — one pass over the indexed set, each id in exactly one
      branch; `missing` computed over declared ids not in the indexed set
- [x] 3.2 Orphan = declared in NO version. Drift = declared, hash disagrees
- [x] 3.3 Supersession → `reason="superseded_version"` plus the indexed version's
      label; unknown hash → `reason="content_mismatch"`
- [x] 3.4 `ReconcileReport` stamped with partition, manifest version, timestamp
- [x] 3.5 Tests: clean corpus, ghost → orphan, undelivered ingest → missing,
      changed source → drift, superseded → drift NOT orphan, unknown hash →
      content_mismatch, all three shapes at once
- [x] 3.6 Assert disjointness on every fixture

## 4. Read-only

- [x] 4.1 Reconcile deletes nothing and writes to no evidence layer
- [x] 4.2 `audit=False` → a strictly zero-write run
- [x] 4.3 Test with a full key/bytes/rows snapshot of raw, knowledge, manifests,
      graph and the vector store taken before and after — equality, not a spot
      check
- [x] 4.4 Test idempotence: two consecutive runs, same three sets
- [x] 4.5 Test that reconcile leaves an orphan in place (a diagnostic never
      deletes)

## 5. Remediation — separate, explicit, orphans only

- [x] 5.1 `remediate(report)` loops `client.delete` over `report.orphans`
- [x] 5.2 Never touches `missing` or `drifted` (both need source bytes the
      library does not hold)
- [x] 5.3 Records per-document outcome so a stale report shows `absent` rather
      than failing silently
- [x] 5.4 Tests: orphan removed and the follow-up report clean; missing/drifted
      unchanged; stale report safe; the removed orphan's raw blob is gone (the
      revoke-path guarantee, inherited not reimplemented)

## 6. Audit stream

- [x] 6.1 `reconcile/audit.py` — append-only JSONL at `eval/<P>/reconcile_log.jsonl`,
      read-concat-write, same S3-native append as the wiki journal
- [x] 6.2 Both `reconcile` and `remediate` append one record
- [x] 6.3 Tests: two runs → two records with the first unmodified; remediation
      records what it removed; the log lives outside every evidence layer

## 7. Scope honesty

- [x] 7.1 `ReconcileReport.scope` carries the document-keyed limitation as data,
      not as a docs footnote
- [x] 7.2 Test that a CLEAN report still states it
- [x] 7.3 Test that byte-level residue under `raw/` is invisible — pinned so the
      limitation is a known property, not a surprise for the first auditor who
      leans on an empty report

## 8. Facade + exports

- [x] 8.1 `CiteNexus.reconcile(manifest, *, audit=True)`
- [x] 8.2 `CiteNexus.remediate(report, *, audit=True)`
- [x] 8.3 Export `CorpusManifest`, `CorpusEntry`, `ReconcileReport`,
      `RemediationReport`, `DriftedDocument` from `citenexus`

## 9. Gates

- [x] 9.1 `uv run pytest -q` green (24 new reconcile tests, none removed)
- [x] 9.2 `uv run mypy src` — no issues
- [x] 9.3 `uv run ruff check` clean on every touched file

## 10. Follow-ups (recorded, not done)

- [ ] 10.1 MinIO integration test for the shared-prefix ghost — the shape only
      reachable on S3, and the ADR's motivating case
- [ ] 10.2 Whole-bucket reconcile + `list_partitions(base_uri)`, when a caller
      needs it
- [ ] 10.3 Retrieval filtering to the manifest's current version (ADR-0008
      mentions it; it is a retrieval-behavior change with its own blast radius)
