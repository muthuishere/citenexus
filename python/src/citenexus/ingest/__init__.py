"""The fast-path ingest orchestrator."""

from citenexus.ingest.pipeline import Embedder, IngestPipeline
from citenexus.ingest.result import IngestResult

__all__ = ["Embedder", "IngestPipeline", "IngestResult"]
