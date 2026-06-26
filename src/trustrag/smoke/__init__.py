"""The walking-skeleton pipeline that proves the evidence-first guarantee composes.

Foundation-first (ADR-0002) defers the full ingest/retrieval/answer layers, so
`smoke-e2e` wires the thinnest real path — ingest → embed → per-leaf vector store →
retrieve → cite-or-abstain — over the L2 storage layer. The public shape
(`ingest`/`ask`) and the "no ungrounded claim" guarantee are what L3-L5 grow into.
"""

from trustrag.smoke.pipeline import Embedder, Generator, SmokePipeline

__all__ = ["Embedder", "Generator", "SmokePipeline"]
