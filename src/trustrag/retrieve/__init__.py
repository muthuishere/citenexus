"""Retrieval: the six signals, RRF fusion, rerank, and the retrieve() engine."""

from trustrag.retrieve.engine import Reranker, RetrievalEngine
from trustrag.retrieve.fusion import rrf_fuse
from trustrag.retrieve.lexical import LexicalRetriever
from trustrag.retrieve.rerank import OpenAICompatibleReranker
from trustrag.retrieve.structure import StructureRetriever
from trustrag.retrieve.types import Candidate, RetrievalSignal
from trustrag.retrieve.vector import QueryEmbedder, VectorRetriever

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
