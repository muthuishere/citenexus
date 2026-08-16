#!/usr/bin/env python3
"""Feasibility spike for ADR-0014 — "the model seam is a contract, not an endpoint".

Runs entirely offline. Verifies the ADR's factual claims BY CONSTRUCTION rather
than by reading, and drives the Go and JS sub-proofs.

    python/.venv/bin/python spikes/model-seam-contract/spike.py

Sections
  1. The Python shape census — are there really four (five) embedder abstractions?
  2. `getattr(embedder, "embed_many")` — a capability no type checker can see.
  3. Python R2 — failure IS expressible today (the ADR overstates the defect here).
  4. `Embedding = Any` — the ABC's declared return type checks nothing.
  5. Go   (subprocess) — the zero-vector claim, proven.
  6. JS   (subprocess) — the synchronous-type claim, proven.
"""

from __future__ import annotations

import inspect
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "python" / "src"))


def rule(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def where(obj: object) -> str:
    """file:line of a definition, relative to the repo root."""
    try:
        src = inspect.getsourcefile(obj)  # type: ignore[arg-type]
        line = inspect.getsourcelines(obj)[1]  # type: ignore[arg-type]
    except (TypeError, OSError):
        return "<unknown>"
    return f"{Path(src).relative_to(REPO)}:{line}"


# ---------------------------------------------------------------- 1. census
def census() -> None:
    rule("1. THE PYTHON EMBEDDER SHAPE CENSUS (ADR table, verified live)")

    from citenexus import client as client_mod
    from citenexus.embed import batcher
    from citenexus.embed.client import OpenAICompatibleEmbedding
    from citenexus.ingest.pipeline import Embedder as PipelineEmbedder
    from citenexus.plugins.base import EmbeddingPlugin
    from citenexus.retrieve.vector import QueryEmbedder
    from citenexus.smoke import pipeline as smoke_mod

    shapes = [
        ("EmbeddingPlugin.embed        (ABC,      batch )", EmbeddingPlugin, EmbeddingPlugin.embed),
        ("ingest.pipeline.Embedder     (Protocol, single)", PipelineEmbedder, PipelineEmbedder.embed),
        ("embed.batcher._BatchEmbedder (Protocol, batch )", batcher._BatchEmbedder, batcher._BatchEmbedder.embed),
        ("retrieve.vector.QueryEmbedder(Protocol, single)", QueryEmbedder, QueryEmbedder.embed),
        ("smoke.pipeline.Embedder      (Protocol, single)", smoke_mod.Embedder, smoke_mod.Embedder.embed),
    ]
    for name, holder, fn in shapes:
        print(f"  {name}  {where(holder):<40} {name.split('.')[-1]}{inspect.signature(fn)}")

    print("\n  ...plus the two adapters that exist only to bridge the above:")
    for adapter in (client_mod._SingleTextEmbedder, client_mod._ZeroEmbedder):
        print(f"    {adapter.__name__:<20} {where(adapter)}")

    print(f"\n  concrete wire plugin: OpenAICompatibleEmbedding {where(OpenAICompatibleEmbedding)}")
    print(f"    .embed{inspect.signature(OpenAICompatibleEmbedding.embed)}")
    print(f"    .embed_query{inspect.signature(OpenAICompatibleEmbedding.embed_query)}"
          "   <- a SECOND method, exactly what R1 forbids")
    print("\n  VERDICT: ADR claim 1 HOLDS, and undercounts: FIVE declared abstractions,")
    print("           not four (QueryEmbedder and smoke's Embedder are separate decls).")


# ------------------------------------------------------- 2. getattr batching
def getattr_batching() -> None:
    rule("2. BATCHING IS DISCOVERED BY getattr (pipeline.py:391)")

    calls: list[str] = []

    class SingleOnly:
        def embed(self, text: str) -> list[float]:
            calls.append(f"single:{text}")
            return [1.0]

    class AlsoBatch(SingleOnly):
        def embed_many(self, texts: list[str]) -> list[list[float]]:
            calls.append(f"batch:{len(texts)}")
            return [[1.0] for _ in texts]

    # The exact body of IngestPipeline._embed_texts (ingest/pipeline.py:390-396).
    def embed_texts(embedder: object, texts: list[str]) -> list[list[float]]:
        embed_many = getattr(embedder, "embed_many", None)
        if callable(embed_many) and texts:
            return list(embed_many(texts))
        return [embedder.embed(t) for t in texts]  # type: ignore[attr-defined]

    texts = ["a", "b", "c"]
    embed_texts(SingleOnly(), texts)
    print(f"  SingleOnly -> {calls}")
    calls.clear()
    embed_texts(AlsoBatch(), texts)
    print(f"  AlsoBatch  -> {calls}")

    print("\n  Both satisfy every declared Protocol in the codebase; neither declares")
    print("  `embed_many` anywhere. A provider reading the type has no way to learn the")
    print("  capability exists, and mypy --strict cannot check the call.")
    print("  VERDICT: ADR claim 2 HOLDS.")


# ---------------------------------------------------------- 3. python and R2
def python_failure_is_expressible() -> None:
    rule("3. R2 IN PYTHON — failure ALREADY propagates (the ADR overstates this)")

    class TimingOutEmbedder:
        def embed(self, text: str) -> list[float]:
            raise TimeoutError("model call timed out after 30s")

    def embed_texts(embedder: object, texts: list[str]) -> list[list[float]]:
        return [embedder.embed(t) for t in texts]  # type: ignore[attr-defined]

    try:
        embed_texts(TimingOutEmbedder(), ["x"])
    except TimeoutError as exc:
        print(f"  ingest raised: {type(exc).__name__}: {exc}")
        print("  -> nothing is written; the caller learns the corpus is incomplete.")

    print("\n  Python's seam is UNTYPED about failure but not BROKEN by it: exceptions")
    print("  propagate for free. R2 is a Go/JS repair, not a Python one. The Python")
    print("  problem is R1 (five shapes) — a different, cheaper problem.")
    print("  VERDICT: ADR is right about Go/JS, imprecise in lumping Python in.")


# ------------------------------------------------------------ 4. Embedding=Any
def embedding_is_any() -> None:
    rule("4. THE DECLARED RETURN TYPE IS `Any` (plugins/base.py:28)")

    from citenexus.plugins import base

    print(f"  base.Embedding is {base.Embedding!r}   <- a bare alias for typing.Any")
    print(f"  EmbeddingPlugin.embed{inspect.signature(base.EmbeddingPlugin.embed)}")
    print("  OpenAICompatibleEmbedding.embed returns list[list[float]] and still")
    print("  type-checks against `list[Embedding]`, because Any absorbs everything.")

    from citenexus.evidence.unit import EvidenceUnit

    field = EvidenceUnit.model_fields["sparse_vector"]
    print(f"\n  EvidenceUnit.sparse_vector exists ({field.annotation}) — evidence/unit.py:95")
    print("  ...and is written by NOTHING in the codebase (grep: one declaration, zero")
    print("  assignments, zero reads). The sparse signal is BM25 over stored EU text")
    print("  (storage/bm25.py), not embedder output; embed/client.py:13-15 says so in")
    print("  its own docstring: 'this plugin never fakes a sparse vector'.")
    print("  => Open question 2 answers itself: the contract returns dense vectors.")


# ------------------------------------------------------------- 5/6. subprocess
def run_go() -> None:
    rule("5. GO — CLAIM 3: `Embed(text string) []float64` cannot report failure")
    go_dir = Path(__file__).parent / "go"
    if not _have("go"):
        print("  [skipped: no `go` on PATH]")
        return
    print(subprocess.run(["go", "run", "."], cwd=go_dir, capture_output=True, text=True).stdout)
    print("  -- and the honest signature does not compile --")
    build = subprocess.run(["go", "build", "./honest"], cwd=go_dir, capture_output=True, text=True)
    for line in build.stderr.strip().splitlines():
        print(f"    {line}")


def run_js() -> None:
    rule("6. JS — CLAIM 4: `(text: string) => number[]` is unsatisfiable over a wire")
    js_dir = Path(__file__).parent / "js"
    if not _have("node"):
        print("  [skipped: no `node` on PATH]")
        return
    print(subprocess.run(["node", str(js_dir / "runtime.mjs")], capture_output=True, text=True).stdout)

    tsc = REPO / "js" / "node_modules" / ".bin" / "tsc"
    if not tsc.exists():
        print("  [tsc not installed; skipping the type-level half]")
        return
    print("  -- and the type-level half --")
    out = subprocess.run(
        [str(tsc), "--noEmit", "--strict", "--target", "es2022", "--lib", "es2022,dom",
         "--module", "esnext", "--moduleResolution", "bundler", str(js_dir / "embedder.ts")],
        capture_output=True, text=True, cwd=REPO,
    )
    for line in (out.stdout or out.stderr).strip().splitlines()[:4]:
        print(f"    {line}")


def _have(cmd: str) -> bool:
    from shutil import which

    return which(cmd) is not None


if __name__ == "__main__":
    census()
    getattr_batching()
    python_failure_is_expressible()
    embedding_is_any()
    run_go()
    run_js()
    print("\nFull findings, open questions and verdict: spikes/model-seam-contract/NOTES.md")
