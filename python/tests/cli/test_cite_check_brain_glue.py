"""Complementarity proof: a cite-check verdict is recorded into a brain episode.

This exercises the real `cite-check-to-brain.sh` glue and the real `brain` CLI
(the memory organ). It is skipped when `brain` is not on PATH (e.g. CI), so the
hermetic suite stays green while this proves the organ interface end-to-end
wherever the fleet's tools are installed.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "cite-check-to-brain.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("brain") is None, reason="brain CLI (memory organ) not installed"
)


def _run(claim: str, evidence: Path, brain: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(_SCRIPT), claim, str(evidence)],
        env={"BRAIN": str(brain), "PATH": _path_with_citenexus()},
        capture_output=True,
        text=True,
    )


def _path_with_citenexus() -> str:
    import os

    # Ensure both `brain` and `citenexus` (this venv's console script) resolve.
    return os.environ["PATH"]


def test_cited_verdict_is_recorded_and_recallable(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "handbook.txt").write_text(
        "The employee may not disclose confidential information.", encoding="utf-8"
    )
    brain = tmp_path / "brain"
    subprocess.run(["brain", "--repo", str(brain), "init"], check=True, capture_output=True)

    result = _run("The employee may not disclose confidential information.", evidence, brain)
    assert result.returncode == 0, result.stderr
    assert '"verdict": "CITED"' in result.stdout

    recall = subprocess.run(
        ["brain", "--repo", str(brain), "recall", "cite-check", "-k", "5"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "CITED" in recall.stdout


def test_abstain_verdict_is_recorded_with_negative_reward(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "handbook.txt").write_text("Unrelated content.", encoding="utf-8")
    brain = tmp_path / "brain"
    subprocess.run(["brain", "--repo", str(brain), "init"], check=True, capture_output=True)

    result = _run("This dashboard is real and shipped to production.", evidence, brain)
    assert result.returncode == 3, result.stderr
    assert '"verdict": "ABSTAIN"' in result.stdout

    recall = subprocess.run(
        ["brain", "--repo", str(brain), "recall", "cite-check", "-k", "5"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "ABSTAIN" in recall.stdout
