"""The S3 location object — one place for bucket + endpoint + credentials.

`CiteNexus("s3://bucket")` as a bare string can't carry an endpoint or
credentials; `S3(...)` can, and derives BOTH storage halves (the boto3 backend
and the Lance store's options) from one declaration. Credentials follow the
house rule: referenced by env-var NAME, read at connect time, never stored as
values on the object (safe to repr/log).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from citenexus import S3, CiteNexus
from citenexus.testing import FakeEmbedding


def test_base_uri_and_prefix() -> None:
    assert S3(bucket="b").base_uri() == "s3://b"
    assert S3(bucket="b", prefix="tenants/acme").base_uri() == "s3://b/tenants/acme"


def test_lance_options_derive_from_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "k")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "s")
    loc = S3(bucket="b", endpoint_url="http://localhost:19000", region="eu-1")
    opts = loc.lance_storage_options()
    assert opts["endpoint"] == "http://localhost:19000"
    assert opts["allow_http"] == "true"  # http endpoint => allow_http
    assert opts["region"] == "eu-1"
    assert opts["access_key_id"] == "k"

    https = S3(bucket="b", endpoint_url="https://minio.example.com")
    assert "allow_http" not in https.lance_storage_options()


def test_credentials_by_env_name_never_stored(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "not-a-real-secret"
    monkeypatch.setenv("MY_S3_KEY", "key-id")
    monkeypatch.setenv("MY_S3_SECRET", secret)
    loc = S3(
        bucket="b",
        endpoint_url="http://localhost:19000",
        access_key_env="MY_S3_KEY",
        secret_key_env="MY_S3_SECRET",
    )
    # the VALUE must not live on the object (safe to repr/log)
    assert secret not in repr(loc)
    # but it is read (by name) when options are built for the store
    assert loc.lance_storage_options()["secret_access_key"] == secret


def test_client_accepts_s3_location(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "k")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "s")
    loc = S3(bucket="my-bucket", endpoint_url="http://localhost:19000")
    rag = CiteNexus(loc, embedder=FakeEmbedding())  # construction only, no IO
    assert rag.base_uri == "s3://my-bucket"
    # the backend is the endpoint-wired S3Backend, not the bare-string default
    from citenexus.storage.backend import S3Backend

    assert isinstance(rag._backend, S3Backend)


def test_plain_paths_still_work(tmp_path: Path) -> None:
    rag = CiteNexus(tmp_path, embedder=FakeEmbedding())
    assert rag.base_uri == str(tmp_path)
