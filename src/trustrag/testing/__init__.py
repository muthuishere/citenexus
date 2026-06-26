"""Deterministic test doubles + tiny utilities used by tests and the example.

These are reference fakes (no network, fully deterministic) so the evidence-first
guarantees can be proven offline and the example runs without any model server.
"""

from trustrag.testing.fakes import FakeEmbedding, FakeLLM, FakeReranker, tokenize

__all__ = ["FakeEmbedding", "FakeLLM", "FakeReranker", "tokenize"]
