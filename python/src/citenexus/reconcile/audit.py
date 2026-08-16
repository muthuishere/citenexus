"""The append-only reconciliation audit stream (ADR-0008).

One JSON object per line under ``eval/<P>/reconcile_log.jsonl``. Append-only is
the point: "the index matched the agreed corpus at time T" is only evidence if
the record of it cannot be quietly revised. Nothing here ever rewrites a line —
the object is read, the new line is concatenated, and the whole is written back,
the same S3-native append the wiki journal uses.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from citenexus.storage.paths import Layer, layer_prefix

if TYPE_CHECKING:
    from citenexus.domain.partition import PartitionPath
    from citenexus.storage.backend import StorageBackend

LOG_NAME = "reconcile_log.jsonl"


def audit_key(partition: PartitionPath) -> str:
    return f"{layer_prefix(Layer.eval, partition)}/{LOG_NAME}"


def append_audit(backend: StorageBackend, partition: PartitionPath, record: Any) -> None:
    """Append one record. Never modifies an existing line."""
    key = audit_key(partition)
    existing = backend.get_bytes(key) if backend.exists(key) else b""
    line = json.dumps(record, sort_keys=True).encode("utf-8") + b"\n"
    backend.put_bytes(key, existing + line)


def read_audit(backend: StorageBackend, partition: PartitionPath) -> list[dict[str, Any]]:
    """Every audit record, oldest first (the read side, for callers and tests)."""
    key = audit_key(partition)
    if not backend.exists(key):
        return []
    text = backend.get_bytes(key).decode("utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]
