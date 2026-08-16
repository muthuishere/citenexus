"""End-to-end walking skeleton: ingest → retrieve → cite-or-abstain.

Hermetic (LocalFs + local LanceDB) by default; a MinIO variant is opt-in.
"""

from __future__ import annotations

import os
import urllib.request
import uuid
from pathlib import Path

import pytest

from citenexus.answer.result import Decision
from citenexus.domain.partition import PartitionPath
from citenexus.smoke import SmokePipeline
from citenexus.storage.backend import LocalFsBackend
from citenexus.testing import FakeEmbedding, FakeLLM

NDA = "The employee shall not disclose confidential information."


def _local_pipeline(tmp_path: Path, generator: object | None = None) -> SmokePipeline:
    return SmokePipeline(
        backend=LocalFsBackend(tmp_path),
        base_uri=str(tmp_path),
        partition=PartitionPath.of(("workspace", "w1")),
        embedder=FakeEmbedding(),
        generator=generator or FakeLLM(),  # type: ignore[arg-type]
    )


class _HalfTrueLLM:
    """Quotes the passage verbatim, then appends an invented sentence."""

    def answer(self, question: str, passage: str) -> str:
        return f"{passage} The penalty is a fine of one million euros."


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


def test_unsupported_claim_is_dropped_not_fatal(tmp_path: Path) -> None:
    """Per-claim drop-not-fail: the true half survives, the invented half does not."""
    p = _local_pipeline(tmp_path, generator=_HalfTrueLLM())
    p.ingest(NDA, "nda")
    r = p.ask("Can the employee disclose confidential information?")
    assert r.evidence.decision is Decision.answered
    assert r.answer == NDA
    assert "million euros" not in r.answer
    assert r.evidence.unsupported_claims_removed == 1
    assert r.evidence.all_claims_verified is False
    # Both verdicts are recorded, so the drop is auditable rather than silent.
    assert [c.supported for c in r.claims] == [True, False]
    assert len(r.provenance) == 1


def test_reordered_claim_fails_the_gate(tmp_path: Path) -> None:
    """The smoke pipeline uses the shared ordered predicate, not set containment."""

    class _ReorderingLLM:
        def answer(self, question: str, passage: str) -> str:
            return "Confidential information shall disclose the employee."

    p = _local_pipeline(tmp_path, generator=_ReorderingLLM())
    p.ingest(NDA, "nda")
    r = p.ask("Can the employee disclose confidential information?")
    assert r.evidence.decision is Decision.refused


def test_retrieves_the_relevant_document(tmp_path: Path) -> None:
    p = _local_pipeline(tmp_path)
    p.ingest("Cats are small domestic animals.", "cats")
    p.ingest("The contract termination clause requires thirty days notice.", "contract")
    r = p.ask("What does the termination clause require?")
    assert r.evidence.decision is Decision.answered
    assert r.sources[0].document == "contract"


# --- opt-in MinIO variant ---------------------------------------------------

ENDPOINT = os.environ.get("CITENEXUS_S3_ENDPOINT_URL", "http://localhost:19000")
BUCKET = os.environ.get("CITENEXUS_BUCKET", "citenexus-local")
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
    from citenexus.storage.backend import S3Backend

    part = PartitionPath.of(("workspace", f"it-{uuid.uuid4().hex}"))
    backend = S3Backend(BUCKET, endpoint_url=ENDPOINT, access_key_id=KEY, secret_access_key=SECRET)
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
        from citenexus.storage.paths import Layer, layer_prefix

        for layer in (Layer.raw, Layer.manifests, Layer.vector):
            backend.delete_prefix(layer_prefix(layer, part))
