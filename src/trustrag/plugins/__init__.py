"""Typed plugin protocols + the registry — the swappable-stage seam (§4b)."""

from trustrag.plugins.base import (
    ChunkerPlugin,
    EmbeddingPlugin,
    EvaluatorPlugin,
    ExtractorPlugin,
    GraphExtractorPlugin,
    JudgePlugin,
    LanguageDetectorPlugin,
    MemoryPlugin,
    Plugin,
    RerankerPlugin,
    RetrieverPlugin,
    VisionPlugin,
)
from trustrag.plugins.registry import PluginRegistry

__all__ = [
    "ChunkerPlugin",
    "EmbeddingPlugin",
    "EvaluatorPlugin",
    "ExtractorPlugin",
    "GraphExtractorPlugin",
    "JudgePlugin",
    "LanguageDetectorPlugin",
    "MemoryPlugin",
    "Plugin",
    "PluginRegistry",
    "RerankerPlugin",
    "RetrieverPlugin",
    "VisionPlugin",
]
