"""Shared SHA256-verified model fetch-cache (reference utility).

The one runtime download every language port expects: lid.176. mochallama's
fetch-cache omits checksums; this pins the digest so a corrupt or swapped model
can never be loaded. Python's shipping copy lives in
``citenexus.lang.detect._ensure_model`` (verified there); Go/JS reuse the same
fetch+verify+cache shape as their ``corefetch`` core loader with this asset.

Cache convention (shared across languages):
    $CITENEXUS_CACHE_DIR  or  ~/.cache/citenexus/models/<name>
"""
from __future__ import annotations

import hashlib
import os
import tempfile
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class Asset:
    name: str
    url: str
    sha256: str  # lowercase hex; verified against the fetched bytes


# lid.176 compressed fastText language-id model (~917 KB). Digest verified
# 2026-07-11 against the upstream file.
LID176 = Asset(
    name="lid.176.ftz",
    url="https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.ftz",
    sha256="8f3472cfe8738a7b6099e8e999c3cbfae0dcd15696aac7d7738a8039db603e83",
)


def cache_dir() -> str:
    d = os.environ.get("CITENEXUS_CACHE_DIR") or os.path.join(
        os.path.expanduser("~"), ".cache", "citenexus", "models"
    )
    os.makedirs(d, exist_ok=True)
    return d


def _sha256_file(path: str, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def fetch_cached(asset: Asset, *, cache: str | None = None) -> str:
    """Return a verified local path to ``asset``, fetching + caching if needed."""
    base = cache or cache_dir()
    os.makedirs(base, exist_ok=True)
    final = os.path.join(base, asset.name)

    if os.path.exists(final):
        if _sha256_file(final) == asset.sha256:
            return final
        os.remove(final)  # corrupt/stale — re-fetch

    fd, tmp = tempfile.mkstemp(prefix=asset.name + ".", suffix=".part", dir=base)
    os.close(fd)
    try:
        urllib.request.urlretrieve(asset.url, tmp)
        got = _sha256_file(tmp)
        if got != asset.sha256:
            raise ValueError(
                f"{asset.name}: sha256 mismatch (got {got}, want {asset.sha256})"
            )
        os.replace(tmp, final)
        return final
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


if __name__ == "__main__":
    # Hermetic self-test of the checksum gate (no network): serve a local file://.
    import sys

    d = tempfile.mkdtemp()
    payload = b"hello citenexus model"
    good = Asset("m.bin", "", hashlib.sha256(payload).hexdigest())
    src = os.path.join(d, "src.bin")
    open(src, "wb").write(payload)
    good = Asset("m.bin", "file://" + src, good.sha256)
    assert fetch_cached(good, cache=d).endswith("m.bin")
    bad = Asset("b.bin", "file://" + src, "0" * 64)
    try:
        fetch_cached(bad, cache=d)
        print("FAIL: mismatch accepted", file=sys.stderr)
        sys.exit(1)
    except ValueError:
        pass
    print("[model_fetch] OK — SHA256 gate accepts good, rejects mismatch")
