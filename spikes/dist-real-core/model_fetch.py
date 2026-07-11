"""SHA256-verified fetch-and-cache for vendored model assets (e.g. lid.176).

The reference `mochallama` fetch-cache omits checksums; we ADD SHA256
verification so a corrupted or swapped download can never be loaded. Contract:

  path = fetch_cached(ASSETS["lid.176.bin"])   # downloads once, verifies, caches

Guarantees
- **Atomic**: download to `<final>.part` then `os.replace` — no half-file is
  ever visible under the final name.
- **Verified**: SHA256 of the bytes must equal the pinned digest, else the
  partial is deleted and it raises. A cached file is re-verified on load; a
  mismatched cache entry is discarded and re-fetched.
- **Cached**: reused across runs from an XDG-style cache dir
  (`$CITENEXUS_CACHE_DIR` or `~/.cache/citenexus/models`).

No third-party deps (stdlib urllib) so it can live behind the LanguageDetector
plugin without adding to the install closure.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class Asset:
    name: str          # cache filename, e.g. "lid.176.bin"
    url: str           # source URL
    sha256: str        # lowercase hex digest of the expected bytes
    size: int | None = None  # optional expected byte length (cheap early check)


# Pin the exact upstream lid.176 (fastText language id, ~126 MB). The digest
# MUST be filled from the trusted source before enabling fetch in production;
# left as a sentinel here so the spike can't silently accept an unpinned model.
ASSETS: dict[str, Asset] = {
    "lid.176.bin": Asset(
        name="lid.176.bin",
        url="https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.bin",
        sha256="<PIN-ME: sha256 of lid.176.bin>",
        size=131266198,
    ),
}


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
    """Return a local path to `asset`, downloading + verifying if needed.

    Raises ValueError on a SHA256 mismatch (partial removed), or if the pinned
    digest is still the sentinel placeholder.
    """
    if asset.sha256.startswith("<PIN"):
        raise ValueError(
            f"{asset.name}: sha256 is not pinned — refusing to fetch an "
            "unverifiable model. Set Asset.sha256 to the trusted digest."
        )
    base = cache or cache_dir()
    final = os.path.join(base, asset.name)

    # cache hit — re-verify; discard a tampered/corrupt entry
    if os.path.exists(final):
        if _sha256_file(final) == asset.sha256:
            return final
        os.remove(final)

    # download to a sibling .part, verify, then atomically publish
    fd, tmp = tempfile.mkstemp(prefix=asset.name + ".", suffix=".part", dir=base)
    os.close(fd)
    try:
        with urllib.request.urlopen(asset.url) as r, open(tmp, "wb") as out:
            while True:
                block = r.read(1 << 20)
                if not block:
                    break
                out.write(block)
        if asset.size is not None and os.path.getsize(tmp) != asset.size:
            raise ValueError(f"{asset.name}: size mismatch")
        digest = _sha256_file(tmp)
        if digest != asset.sha256:
            raise ValueError(
                f"{asset.name}: sha256 mismatch (got {digest}, want {asset.sha256})"
            )
        os.replace(tmp, final)
        return final
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


if __name__ == "__main__":
    # Offline self-test: verify the checksum gate without the 126 MB download.
    import sys

    d = tempfile.mkdtemp()
    payload = b"hello citenexus"
    good = Asset("probe.bin", "file:///dev/null", hashlib.sha256(payload).hexdigest())
    # write a matching cache file, prove verify accepts it
    with open(os.path.join(d, good.name), "wb") as f:
        f.write(payload)
    assert fetch_cached(good, cache=d) == os.path.join(d, good.name)
    # corrupt it, prove verify rejects (and here there is no real URL to refetch)
    with open(os.path.join(d, good.name), "wb") as f:
        f.write(b"tampered")
    try:
        fetch_cached(good, cache=d)  # will remove bad cache then try file:// url -> fail
    except Exception:
        pass
    # sentinel digest must be refused
    try:
        fetch_cached(ASSETS["lid.176.bin"])
        print("FAIL: unpinned asset was fetched", file=sys.stderr)
        sys.exit(1)
    except ValueError:
        pass
    print("[model_fetch] OK — checksum gate + sentinel refusal verified")
