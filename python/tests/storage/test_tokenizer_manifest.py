"""ADR-0011 item 5: the tokenizer version is recorded per index.

A corpus tokenized under v1 keeps working, but it does not benefit from the
Unicode tokenizer until it is re-indexed — and a non-Latin corpus indexed under
v1 has no lexical terms at all. The stamp is what makes that mismatch
detectable rather than silent.
"""

from __future__ import annotations

from pathlib import Path

from citenexus.domain.partition import PartitionPath
from citenexus.storage.backend import LocalFsBackend
from citenexus.storage.manifest import (
    TOKENIZER,
    TokenizerManifest,
    manifest_key,
    record_tokenizer_version,
    save_manifest,
    tokenizer_manifest,
)
from citenexus.tokenize import TOKENIZER_VERSION

_PARTITION = PartitionPath.of(("workspace", "w1"))


def test_an_unstamped_partition_reads_as_v1_and_therefore_stale(tmp_path: Path) -> None:
    """Absent manifest means 'written before versioning', i.e. written by v1.

    Defaulting to the CURRENT version would report every legacy index as fresh —
    the silent-success failure this manifest exists to prevent.
    """
    manifest = tokenizer_manifest(LocalFsBackend(tmp_path), _PARTITION)
    assert manifest.version == 1
    assert manifest.is_stale is True


def test_recording_stamps_the_running_tokenizer(tmp_path: Path) -> None:
    backend = LocalFsBackend(tmp_path)
    record_tokenizer_version(backend, _PARTITION)
    manifest = tokenizer_manifest(backend, _PARTITION)
    assert manifest.version == TOKENIZER_VERSION
    assert manifest.is_stale is False


def test_a_future_version_is_also_a_mismatch(tmp_path: Path) -> None:
    backend = LocalFsBackend(tmp_path)
    save_manifest(backend, _PARTITION, TOKENIZER, TokenizerManifest(version=TOKENIZER_VERSION + 1))
    assert tokenizer_manifest(backend, _PARTITION).is_stale is True


def test_the_stamp_lands_beside_the_other_manifests(tmp_path: Path) -> None:
    backend = LocalFsBackend(tmp_path)
    record_tokenizer_version(backend, _PARTITION)
    assert backend.exists(manifest_key(_PARTITION, TOKENIZER))


def test_ingesting_stamps_the_partition(tmp_path: Path) -> None:
    from citenexus.smoke import SmokePipeline
    from citenexus.storage.paths import leaf_vector_uri
    from citenexus.testing import FakeEmbedding, FakeLLM

    assert leaf_vector_uri(str(tmp_path), _PARTITION)
    backend = LocalFsBackend(tmp_path)
    pipeline = SmokePipeline(
        backend=backend,
        base_uri=str(tmp_path),
        partition=_PARTITION,
        embedder=FakeEmbedding(),
        generator=FakeLLM(),
    )
    pipeline.ingest("The employee shall not disclose confidential information.", "nda")
    assert tokenizer_manifest(backend, _PARTITION).is_stale is False
