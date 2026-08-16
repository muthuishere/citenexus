"""``rag.code.ingest_from(folder | git)`` — the typed code-intake verb.

Code is ingested through its own namespaced verb, never the generic ``ingest()``
firehose ("we don't want to ingest everything everywhere"). This sub-facade owns
source acquisition (git clone / folder walk) and code-file filtering (skip
vendored/build dirs), then drives the core code extractor per file and rebuilds
the structural graph once.

It enforces its own prerequisite: a code corpus is meaningless without its
structural graph, so it raises immediately if the instance was created without
the ``graph`` (or ``community``) signal — no silent partial ingest.

The ``rag.code`` namespace is a lazy sub-facade bound to the same instance (it
reads the existing ``signals`` contract and the shared stores); it adds nothing
to ``CiteNexus.__init__``. Any private-git auth uses a ``${ENV}`` token *name*
expanded only at the git call — never a token value in the signature.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from collections.abc import Collection, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

from citenexus.config.signals import Signal
from citenexus.extract.types import SourceType
from citenexus.ingest.result import IngestResult

# The code file extensions the extractor understands today (Python + Go). Unknown
# extensions are simply not walked into the corpus.
_CODE_EXTENSIONS = frozenset({".py", ".go"})

# Vendored / build / cache directories never carry first-party source.
_SKIP_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "vendor",
        "target",
        "dist",
        "build",
        "out",
        "__pycache__",
        ".venv",
        "venv",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".idea",
        ".vscode",
        "site-packages",
    }
)


class _CodeClient(Protocol):
    """The slice of ``CiteNexus`` the code facade drives."""

    @property
    def signals(self) -> Collection[Signal]: ...

    def ingest(
        self,
        source: object = ...,
        *,
        text: str | None = ...,
        document_id: str | None = ...,
        source_type: object = ...,
        acl: object = ...,
    ) -> IngestResult: ...

    def refresh_slow_path(self) -> None: ...


@dataclass
class CodeIngestReport:
    """What one ``ingest_from`` call ingested."""

    document_ids: tuple[str, ...] = ()
    skipped: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ingested(self) -> int:
        return len(self.document_ids)


class CodeFacade:
    """Lazy ``rag.code`` sub-facade — bound to one ``CiteNexus`` instance."""

    def __init__(self, client: _CodeClient) -> None:
        self._client = client

    def ingest_from(
        self,
        source: str | Path,
        *,
        token_env: str | None = None,
    ) -> CodeIngestReport:
        """Ingest a code corpus from a local folder path OR a git URL.

        ``token_env`` names an environment variable holding a git access token
        (e.g. ``"GITHUB_TOKEN"``) for a private https clone — the *name*, never
        the value; it is read from the environment and expanded only at the git
        command, never logged.
        """
        self._require_graph_signal()
        document_ids: list[str] = []
        with _acquire(source, token_env=token_env) as root:
            for path in _walk_code_files(root):
                relative = path.relative_to(root).as_posix()
                result = self._client.ingest(
                    source=path,
                    document_id=relative,
                    source_type=SourceType.code,
                )
                document_ids.append(result.document_id)
        # One graph rebuild after the batch — runs the injected structural
        # distiller (deferred/dirty per-ingest keeps this from rebuilding N times).
        self._client.refresh_slow_path()
        return CodeIngestReport(document_ids=tuple(document_ids))

    def _require_graph_signal(self) -> None:
        signals = set(self._client.signals)
        if Signal.graph not in signals and Signal.community not in signals:
            raise ValueError(
                "rag.code.ingest_from requires the 'graph' (or 'community') signal — "
                "a code corpus is meaningless without its structural graph. Construct "
                "CiteNexus(..., signals=[..., 'graph']). No code was ingested."
            )


def _walk_code_files(root: Path) -> list[Path]:
    """Every code file under ``root``, skipping vendored/build dirs. Sorted so the
    ingest order (and thus any downstream artifact) is deterministic."""
    out: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix not in _CODE_EXTENSIONS:
            continue
        if any(part in _SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        out.append(path)
    return out


def _is_git_url(source: str) -> bool:
    return source.startswith(
        ("git@", "ssh://", "git://", "file://", "http://", "https://")
    ) or source.endswith(".git")


@contextmanager
def _acquire(source: str | Path, *, token_env: str | None) -> Iterator[Path]:
    """Yield a local root for ``source`` — a folder as-is, a git URL shallow-cloned
    into a temp dir that is removed afterwards."""
    if isinstance(source, Path) or (isinstance(source, str) and Path(source).is_dir()):
        root = Path(source)
        if not root.is_dir():
            raise NotADirectoryError(f"code source is not a folder: {root}")
        yield root
        return
    if isinstance(source, str) and _is_git_url(source):
        with tempfile.TemporaryDirectory(prefix="citenexus-code-") as tmp:
            _git_clone(source, Path(tmp), token_env=token_env)
            yield Path(tmp)
        return
    raise ValueError(f"code source is neither an existing folder nor a git URL: {source!r}")


def _git_clone(url: str, dest: Path, *, token_env: str | None) -> None:
    clone_url = url
    if token_env is not None and url.startswith(("http://", "https://")):
        token = os.environ.get(token_env)
        if not token:
            raise ValueError(f"token_env {token_env!r} is not set in the environment")
        parts = urlsplit(url)
        # Expand the token value only here, at the git boundary; never logged.
        netloc = f"{token}@{parts.hostname}" + (f":{parts.port}" if parts.port else "")
        clone_url = urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    subprocess.run(
        ["git", "clone", "--depth", "1", clone_url, str(dest)],
        check=True,
        capture_output=True,
    )
