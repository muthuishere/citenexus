"""TrustRAG — evidence-first, multilingual, S3-native RAG.

Public surface is intentionally tiny (see docs/SPEC-v6.md §15): construct a
client, ``ingest``, ``ask``, and ``evaluate``. The heavy machinery lives behind
typed plugin protocols so nothing in the pipeline is hardwired.
"""

from trustrag.client import TrustRAG
from trustrag.hooks import Hooks

__version__ = "0.2.0"

__all__ = ["Hooks", "TrustRAG", "__version__"]
