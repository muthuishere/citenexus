"""End-to-end walking skeleton: ingest → retrieve → cite-or-abstain.

Hermetic (LocalFs + local LanceDB) by default; a MinIO variant is opt-in.
"""

from __future__ import annotations

import os
import urllib.request
import uuid
from pathlib import Path

import pytest

from trustrag.answer.result import Decision
from trustrag.domain.partition import PartitionPath
from trustrag.smoke import SmokePipeline
from trustrag.storage.backend import LocalFsBackend
from trustrag.testing import FakeEmbedding, FakeLLM

NDA = "The employee shall not disclose confidential information."


def _local_pipeline(tmp_path: Path) -> SmokePipeline:
    return SmokePipeline(
        backend=LocalFsBackend(tmp_path),
        base_uri=str(tmp_path),
        partition=PartitionPath.of(("workspace", "w1")),
        embedder=FakeEmbedding(),
        generator=FakeLLM(),
    )


def test_ingest_then_answer_cites_evidence(tmp_path: Path) -> None:
    p = _local_pipeline(tmp_path)
    p.ingest(NDA, "nda")
    r = p.ask("Can the employee disclose confidential information?")
    assert r.evidence.decision is Decision.answered
    assert r.sources[0].document == "nda"
    assert "confidential" in r.sources[0].passage
    assert r.claims[0].supported
    # Full provenance chain resolves down to a content-addressed object.
    assert r.provenance[0].evidence_unit == "nda::0"
    assert len(r.provenance[0].checksum) == 64


def test_abstains_on_empty_corpus(tmp_path: Path) -> None:
    p = _local_pipeline(tmp_path)
    r = p.ask("Anything at all?")
    assert r.evidence.decision is Decision.refused
    assert r.claims == ()
    assert r.answer  # a localized refusal, not a fabricated answer


def test_abstains_on_irrelevant_question_with_nonempty_corpus(tmp_path: Path) -> None:
    p = _local_pipeline(tmp_path)
    p.ingest(NDA, "nda")
    r = p.ask("What is the capital of France?")
    assert r.evidence.decision is Decision.refused
    assert r.claims == ()


def test_retrieves_the_relevant_document(tmp_path: Path) -> None:
    p = _local_pipeline(tmp_path)
    p.ingest("Cats are small domestic animals.", "cats")
    p.ingest("The contract termination clause requires thirty days notice.", "contract")
    r = p.ask("What does the termination clause require?")
    assert r.evidence.decision is Decision.answered
    assert r.sources[0].document == "contract"


# --- opt-in MinIO variant ---------------------------------------------------

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


@pytest.mark.integration
def test_smoke_on_minio() -> None:
    if not _minio_up():
        pytest.skip(f"MinIO not reachable on {ENDPOINT}")
    from trustrag.storage.backend import S3Backend

    part = PartitionPath.of(("workspace", f"it-{uuid.uuid4().hex}"))
    backend = S3Backend(
        BUCKET, endpoint_url=ENDPOINT, access_key_id=KEY, secret_access_key=SECRET
    )
    pipeline = SmokePipeline(
        backend=backend,
        base_uri=f"s3://{BUCKET}",
        partition=part,
        embedder=FakeEmbedding(),
        generator=FakeLLM(),
        storage_options={
            "endpoint": ENDPOINT,
            "allow_http": "true",
            "access_key_id": KEY,
            "secret_access_key": SECRET,
            "region": "us-east-1",
        },
    )
    try:
        pipeline.ingest(NDA, "nda")
        r = pipeline.ask("Can the employee disclose confidential information?")
        assert r.evidence.decision is Decision.answered
        assert r.sources[0].document == "nda"
    finally:
        from trustrag.storage.paths import Layer, layer_prefix

        for layer in (Layer.raw, Layer.manifests, Layer.vector):
            backend.delete_prefix(layer_prefix(layer, part))
