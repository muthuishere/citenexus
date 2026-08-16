"""rag.code.ingest_from — typed code intake, fail-loud on a missing graph signal."""

from __future__ import annotations

from pathlib import Path

import pytest

from citenexus import CiteNexus
from citenexus.testing import FakeEmbedding


def _rag(tmp_path: Path, *, signals: list[str]) -> CiteNexus:
    return CiteNexus(tmp_path / "store", embedder=FakeEmbedding(), signals=signals)


def _write_repo(root: Path) -> None:
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "tokenize.go").write_text(
        "package pkg\n\nimport \"strings\"\n\n"
        "func Tokenize(s string) []string {\n\treturn strings.Fields(s)\n}\n"
    )
    (root / "lexer.py").write_text(
        "import re\n\n\ndef lex(text):\n    return re.findall(r'\\w+', text)\n"
    )
    # Vendored/build dirs that MUST be skipped.
    (root / "node_modules").mkdir()
    (root / "node_modules" / "dep.py").write_text("def vendored():\n    return 1\n")
    (root / "vendor").mkdir()
    (root / "vendor" / "lib.go").write_text("package vendor\n\nfunc V() {}\n")
    # A non-code file is ignored.
    (root / "README.md").write_text("# repo\n")


def test_folder_ingest_produces_symbol_eus_skipping_vendored(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_repo(repo)
    rag = _rag(tmp_path, signals=["embedding", "graph"])

    report = rag.code.ingest_from(repo)

    assert set(report.document_ids) == {"lexer.py", "pkg/tokenize.go"}
    # Vendored/build dirs never entered the corpus.
    assert not any("node_modules" in d or "vendor" in d for d in report.document_ids)

    # The symbols are real, verbatim, citable Evidence Units.
    rows = {str(r["eu_id"]): r for r in rag._store.scan()}
    texts = [str(r["text"]) for r in rows.values()]
    assert any(t.startswith("func Tokenize") for t in texts)
    assert any(t.startswith("def lex") for t in texts)


def test_missing_graph_signal_fails_loud(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_repo(repo)
    rag = _rag(tmp_path, signals=["embedding", "text"])  # no graph/community

    with pytest.raises(ValueError, match="graph"):
        rag.code.ingest_from(repo)

    # Nothing was ingested.
    assert list(rag._store.scan()) == []


def test_community_signal_also_satisfies_precondition(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_repo(repo)
    rag = _rag(tmp_path, signals=["embedding", "community"])

    report = rag.code.ingest_from(repo)
    assert report.ingested == 2


def test_git_url_is_cloned_and_ingested(tmp_path: Path) -> None:
    """A git URL is acquired (shallow clone) and its code files ingested."""
    # A real local git repo doubles as the "remote" — clone works over file://.
    import subprocess

    origin = tmp_path / "origin"
    origin.mkdir()
    _write_repo(origin)
    subprocess.run(["git", "init", "-q"], cwd=origin, check=True)
    subprocess.run(["git", "add", "-A"], cwd=origin, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
        cwd=origin,
        check=True,
    )

    rag = _rag(tmp_path, signals=["embedding", "graph"])
    report = rag.code.ingest_from(f"file://{origin.as_posix()}")

    assert set(report.document_ids) == {"lexer.py", "pkg/tokenize.go"}
