"""``S3`` — a first-class storage location (spec §6b).

A bare ``"s3://bucket"`` string cannot carry an endpoint, region, or
credentials, which real S3-compatibles (MinIO, Cloudflare R2, custom gateways)
need. ``S3`` declares the connection ONCE and derives both storage halves:

- ``make_backend()`` — the boto3 :class:`S3Backend` for raw blobs / manifests /
  graph / wiki artifacts;
- ``lance_storage_options()`` — the object-store options the Lance vector
  store needs for the same bucket.

Credentials follow the house rule: referenced by **environment-variable name**
(defaults: ``AWS_ACCESS_KEY_ID`` / ``AWS_SECRET_ACCESS_KEY``), read at connect
time, never stored as values on the object — an ``S3`` instance is safe to
repr and log.

    from citenexus import CiteNexus, S3

    rag = CiteNexus(S3(bucket="docs", endpoint_url="http://localhost:19000"))
"""

from __future__ import annotations

import os

from pydantic import BaseModel, ConfigDict

from citenexus.storage.backend import S3Backend
from citenexus.storage.lance_store import StorageOptions


class S3(BaseModel):
    """An S3-compatible storage location: bucket + endpoint + credential names."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    bucket: str
    prefix: str = ""
    endpoint_url: str | None = None
    region: str = "us-east-1"
    # Env-var NAMES, not values (§ secrets rule). boto3 also falls back to its
    # own default credential chain when the variables are unset.
    access_key_env: str = "AWS_ACCESS_KEY_ID"
    secret_key_env: str = "AWS_SECRET_ACCESS_KEY"

    def base_uri(self) -> str:
        uri = f"s3://{self.bucket}"
        if self.prefix:
            uri += f"/{self.prefix.strip('/')}"
        return uri

    def make_backend(self) -> S3Backend:
        """The object backend, credentials read from the env by name (now)."""
        return S3Backend(
            self.bucket,
            endpoint_url=self.endpoint_url,
            access_key_id=os.environ.get(self.access_key_env),
            secret_access_key=os.environ.get(self.secret_key_env),
            region=self.region,
        )

    def lance_storage_options(self) -> StorageOptions:
        """Object-store options for the Lance store on the same bucket."""
        options: StorageOptions = {"region": self.region}
        if self.endpoint_url:
            options["endpoint"] = self.endpoint_url
            if self.endpoint_url.startswith("http://"):
                options["allow_http"] = "true"
        access_key = os.environ.get(self.access_key_env)
        secret_key = os.environ.get(self.secret_key_env)
        if access_key:
            options["access_key_id"] = access_key
        if secret_key:
            options["secret_access_key"] = secret_key
        return options
