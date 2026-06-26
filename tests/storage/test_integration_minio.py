"""Same storage contract over real S3/MinIO. Opt-in: `pytest -m integration`.

Needs the compose MinIO up (`task local:minio:up`). Skips if unreachable.
"""

from __future__ import annotations

import os
import urllib.request
import uuid

import pytest

from trustrag.domain.partition import PartitionPath
from trustrag.storage.backend import S3Backend
from trustrag.storage.lance_store import LeafVectorStore
from trustrag.storage.paths import leaf_vector_uri

pytestmark = pytest.mark.integration

ENDPOINT = os.environ.get("TRUSTRAG_S3_ENDPOINT_URL", "http://localhost:19000")
BUCKET = os.environ.get("TRUSTRAG_BUCKET", "trustrag-local")
KEY = os.environ.get("AWS_ACCESS_KEY_ID", "minioadmin")
SECRET = os.environ.get("AWS_SECRET_ACCESS_KEY", "minioadmin")


def _minio_up() -> bool:
    try:
        with urllib.request.urlopen(f"{ENDPOINT}/minio/health/live", timeout=2) as r:
            return bool(r.status == 200)
    except OSError:
        return False


@pytest.fixture(autouse=True)
def _require_minio() -> None:
    if not _minio_up():
        pytest.skip(f"MinIO not reachable on {ENDPOINT}")


def test_s3_backend_round_trip_and_delete() -> None:
    backend = S3Backend(
        BUCKET, endpoint_url=ENDPOINT, access_key_id=KEY, secret_access_key=SECRET
    )
    prefix = f"raw/it-{uuid.uuid4().hex}"
    digest = backend.put_blob(prefix, b"evidence-bytes")
    assert backend.exists(f"{prefix}/{digest}")
    assert backend.get_bytes(f"{prefix}/{digest}") == b"evidence-bytes"
    backend.delete_prefix(prefix)
    assert backend.list_prefix(prefix) == []


def test_lance_leaf_on_s3() -> None:
    part = PartitionPath.of(("workspace", f"it-{uuid.uuid4().hex}"))
    uri = leaf_vector_uri(f"s3://{BUCKET}", part)
    so = {
        "endpoint": ENDPOINT,
        "allow_http": "true",
        "access_key_id": KEY,
        "secret_access_key": SECRET,
        "region": "us-east-1",
    }
    store = LeafVectorStore(uri, storage_options=so)
    try:
        store.upsert(
            [
                {"eu_id": "eu_1", "vector": [0.1, 0.2, 0.3], "text": "near"},
                {"eu_id": "eu_2", "vector": [0.9, 0.8, 0.7], "text": "far"},
            ]
        )
        hits = store.search([0.1, 0.2, 0.3], limit=1)
        assert hits[0]["eu_id"] == "eu_1"
    finally:
        store.drop()
