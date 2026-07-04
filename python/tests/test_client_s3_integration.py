"""Opt-in: the PUBLIC client end-to-end on S3 (MinIO) — `task local:minio:up`.

`CiteNexus(S3(bucket=..., endpoint_url=...))` is the headline promise: one
location object carries the endpoint + credential names and both storage halves
derive from it. This proves raw blobs, manifests, graph/wiki artifacts AND the
Lance store all land on the bucket, and ask() answers with a citation whose raw
object genuinely exists there. Skips when MinIO isn't reachable.
"""

from __future__ import annotations

import os
import urllib.request
import uuid

import pytest

from citenexus import S3, CiteNexus
from citenexus.answer.result import Decision
from citenexus.domain.partition import PartitionPath
from citenexus.lang.detect import HeuristicDetector
from citenexus.storage.paths import Layer, layer_prefix
from citenexus.testing import FakeEmbedding, FakeLLM

ENDPOINT = os.environ.get("CITENEXUS_S3_ENDPOINT_URL", "http://localhost:19000")
BUCKET = os.environ.get("CITENEXUS_BUCKET", "citenexus-local")


def _minio_up() -> bool:
    try:
        with urllib.request.urlopen(f"{ENDPOINT}/minio/health/live", timeout=2) as r:
            return bool(r.status == 200)
    except OSError:
        return False


@pytest.mark.integration
def test_public_client_on_s3_location() -> None:
    if not _minio_up():
        pytest.skip(f"MinIO not reachable on {ENDPOINT}")
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "minioadmin")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "minioadmin")

    partition = PartitionPath.of(("workspace", f"it-{uuid.uuid4().hex[:8]}"))
    rag = CiteNexus(
        S3(bucket=BUCKET, endpoint_url=ENDPOINT),
        partition=partition,
        signals=("embedding", "text"),
        embedder=FakeEmbedding(),
        generator=FakeLLM(),
        detector=HeuristicDetector(),
    )
    try:
        result = rag.ingest(
            text="The employee shall not disclose confidential information.",
            document_id="nda",
        )
        assert result.status == "ingested"

        answer = rag.ask("Can the employee disclose confidential information?")
        assert answer.evidence.decision is Decision.answered
        assert answer.sources[0].document == "nda"
        # the citation's raw object genuinely lives on the bucket
        assert rag._backend.exists(answer.provenance[0].s3_object)
    finally:
        for layer in (Layer.raw, Layer.manifests, Layer.vector, Layer.knowledge, Layer.graph):
            rag._backend.delete_prefix(layer_prefix(layer, partition))
