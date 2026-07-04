"""Retrieval: the six signals, RRF fusion, rerank, and the retrieve() engine."""

from citenexus.retrieve.engine import Reranker, RetrievalEngine
from citenexus.retrieve.fusion import rrf_fuse
from citenexus.retrieve.lexical import LexicalRetriever
from citenexus.retrieve.rerank import OpenAICompatibleReranker
from citenexus.retrieve.structure import StructureRetriever
from citenexus.retrieve.types import Candidate, RetrievalSignal
from citenexus.retrieve.vector import QueryEmbedder, VectorRetriever

__all__ = [
    "Candidate",
    "LexicalRetriever",
    "OpenAICompatibleReranker",
    "QueryEmbedder",
    "Reranker",
    "RetrievalEngine",
    "RetrievalSignal",
    "StructureRetriever",
    "VectorRetriever",
    "rrf_fuse",
]
