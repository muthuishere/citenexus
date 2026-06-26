"""The fast-path ingest orchestrator."""

from trustrag.ingest.pipeline import Embedder, IngestPipeline
from trustrag.ingest.result import IngestResult

__all__ = ["Embedder", "IngestPipeline", "IngestResult"]
