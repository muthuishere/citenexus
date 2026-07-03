"""The storage backend seam (spec §2, §5).

S3 is the source of truth, but the *logic* (manifests, content-addressing, layer
prefixes) is identical over any object store. So everything goes through a small
``StorageBackend`` ABC with two interchangeable implementations: ``LocalFsBackend``
for hermetic tests and ``S3Backend`` (boto3, MinIO-compatible) for the real thing.
"""

from __future__ import annotations

import abc
import hashlib
import json
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable


class StorageBackend(abc.ABC):
    """Bytes + JSON + content-addressed blobs over an object store."""

    @abc.abstractmethod
    def put_bytes(self, key: str, data: bytes) -> None: ...

    @abc.abstractmethod
    def get_bytes(self, key: str) -> bytes: ...

    @abc.abstractmethod
    def exists(self, key: str) -> bool: ...

    @abc.abstractmethod
    def list_prefix(self, prefix: str) -> list[str]: ...

    @abc.abstractmethod
    def delete_prefix(self, prefix: str) -> None: ...

    def put_json(self, key: str, obj: Any) -> None:
        self.put_bytes(key, json.dumps(obj, sort_keys=True).encode("utf-8"))

    def get_json(self, key: str) -> Any:
        return json.loads(self.get_bytes(key).decode("utf-8"))

    def put_blob(self, prefix: str, data: bytes) -> str:
        """Store ``data`` content-addressed under ``prefix`` and return its sha256."""
        digest = hashlib.sha256(data).hexdigest()
        key = f"{prefix.rstrip('/')}/{digest}"
        if not self.exists(key):
            self.put_bytes(key, data)
        return digest


class LocalFsBackend(StorageBackend):
    """A filesystem-backed object store rooted at a directory (hermetic tests)."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        return self.root / key

    def put_bytes(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get_bytes(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def list_prefix(self, prefix: str) -> list[str]:
        base = self._path(prefix)
        if not base.exists():
            return []
        if base.is_file():
            return [prefix]
        return sorted(str(p.relative_to(self.root)) for p in base.rglob("*") if p.is_file())

    def delete_prefix(self, prefix: str) -> None:
        path = self._path(prefix)
        if path.is_dir():
            shutil.rmtree(path)
        elif path.is_file():
            path.unlink()


class S3Backend(StorageBackend):
    """An S3 / MinIO object store (boto3)."""

    def __init__(
        self,
        bucket: str,
        *,
        endpoint_url: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        region: str = "us-east-1",
    ) -> None:
        import boto3

        self.bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region,
        )

    def put_bytes(self, key: str, data: bytes) -> None:
        self._client.put_object(Bucket=self.bucket, Key=key, Body=data)

    def get_bytes(self, key: str) -> bytes:
        resp = self._client.get_object(Bucket=self.bucket, Key=key)
        body: bytes = resp["Body"].read()
        return body

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
        except ClientError:
            return False
        return True

    def list_prefix(self, prefix: str) -> list[str]:
        paginator = self._client.get_paginator("list_objects_v2")
        keys: list[str] = []
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                keys.append(obj["Key"])
        return sorted(keys)

    def delete_prefix(self, prefix: str) -> None:
        keys = self.list_prefix(prefix)
        if not keys:
            return
        batch: Iterable[dict[str, str]] = [{"Key": k} for k in keys]
        self._client.delete_objects(Bucket=self.bucket, Delete={"Objects": list(batch)})
