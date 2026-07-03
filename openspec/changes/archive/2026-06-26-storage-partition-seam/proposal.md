## Why

S3 is CiteNexus's source of truth and every index is a rebuildable cache (§2). The
storage layer is what makes that real: it maps a variable-depth `PartitionPath`
(§6b) to physical S3 prefixes, stores raw blobs content-addressed, persists the
manifests that drive change-detection and rebuilds, and opens **one LanceDB per
leaf partition** so indexes stay small and a leaf can be deleted by deleting a
prefix. Everything sits behind a backend seam so the same logic runs over a local
filesystem (hermetic tests) and S3/MinIO (integration, the example, prod).

## What Changes

- Add deterministic partition→prefix path resolution (raw/extracted/knowledge/
  graph/vector/manifests/eval) for any declared hierarchy depth.
- Add a `StorageBackend` seam with two implementations: `LocalFsBackend` and
  `S3Backend` (boto3, MinIO-compatible) — bytes + JSON + content-addressed blobs,
  `exists`, `list_prefix`, `delete_prefix`.
- Add a per-leaf `LeafVectorStore` over LanceDB (local path or `s3://…`) — create/
  open, upsert Evidence-Unit rows, vector search, drop-leaf.
- Add typed manifests (etag / model / processing) loaded & saved as JSON via the
  backend, with ETag/checksum change-detection for the fast path.

## Capabilities

### New Capabilities
- `storage-partition-seam`: partition→prefix resolution, the backend seam (local +
  S3/MinIO), per-leaf LanceDB stores, and manifest persistence.

## Impact

- New modules under `src/citenexus/storage/`. New deps already added: `boto3`,
  `lancedb`. Hermetic tests use `LocalFsBackend` + a local LanceDB path; an opt-in
  `@pytest.mark.integration` suite runs the same contract against the compose MinIO.
