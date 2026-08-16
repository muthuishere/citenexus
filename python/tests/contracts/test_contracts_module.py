"""The published model-seam contracts (ADR-0014 R1/R4).

A third party must be able to write a provider against a *published* interface
instead of reverse-engineering our call sites. These tests pin what "published"
means: importable from the package root, structural (no inheritance required),
and free of transport concerns.
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping, Sequence
from typing import Any, get_type_hints

import pytest

import citenexus
from citenexus import contracts
from citenexus.contracts import (
    CompletionProvider,
    EmbeddingProvider,
    GeneratorProvider,
    RerankerProvider,
    SequenceEmbedder,
    SingleTextEmbedder,
    Vector,
    VisionProvider,
)
from citenexus.retrieve.types import Candidate

MODEL_CONTRACTS = [
    EmbeddingProvider,
    GeneratorProvider,
    CompletionProvider,
    VisionProvider,
    RerankerProvider,
]

ALL_CONTRACTS = [*MODEL_CONTRACTS, SingleTextEmbedder, SequenceEmbedder]

CONTRACT_NAMES = [
    "CompletionProvider",
    "EmbeddingProvider",
    "GeneratorProvider",
    "RerankerProvider",
    "SequenceEmbedder",
    "SingleTextEmbedder",
    "VisionProvider",
]


# --- publication ------------------------------------------------------------


@pytest.mark.parametrize("name", CONTRACT_NAMES)
def test_contract_is_exported_from_the_package_root(name: str) -> None:
    """One import, from the obvious place — `from citenexus import X`."""
    assert hasattr(citenexus, name), f"{name} is not exported from citenexus"
    assert name in citenexus.__all__


@pytest.mark.parametrize("name", CONTRACT_NAMES)
def test_package_root_and_contracts_module_are_the_same_object(name: str) -> None:
    assert getattr(citenexus, name) is getattr(contracts, name)


@pytest.mark.parametrize("name", CONTRACT_NAMES)
def test_contract_is_listed_in_contracts_dunder_all(name: str) -> None:
    assert name in contracts.__all__


def test_vector_is_the_published_vector_alias() -> None:
    assert Vector == list[float]


def test_contracts_module_does_not_import_the_client() -> None:
    """A provider author imports the contract, not the whole library.

    `citenexus.contracts` must stay import-light: nothing in it may reach for
    `CiteNexus`, a storage backend, or a vector store.
    """
    source = inspect.getsource(contracts)
    for forbidden in ("from citenexus.client", "LanceVectorStore", "StorageBackend"):
        assert forbidden not in source


# --- structural, not nominal ------------------------------------------------


@pytest.mark.parametrize("contract", ALL_CONTRACTS)
def test_contract_is_a_runtime_checkable_protocol(contract: type) -> None:
    """`isinstance` must work — that is how the pipeline picks the batch path."""
    assert getattr(contract, "_is_protocol", False), f"{contract.__name__} is not a Protocol"
    assert getattr(contract, "_is_runtime_protocol", False), (
        f"{contract.__name__} is not @runtime_checkable"
    )


class OutsideEmbedding:
    """Written by someone who never imported a CiteNexus base class."""

    def embed_many(self, texts: Sequence[str]) -> list[list[float]]:
        return [[float(len(t))] for t in texts]


class OutsideGenerator:
    def answer(self, question: str, passage: str, answer_language: str = "en") -> str:
        return passage

    def complete(self, prompt: str) -> str:
        return prompt


class OutsideVision:
    def describe(self, image_region: Any) -> Mapping[str, Any]:
        return {"short_caption": "a square"}


class OutsideReranker:
    def rerank(self, query: str, candidates: Sequence[Candidate]) -> list[Candidate]:
        return list(candidates)


@pytest.mark.parametrize(
    ("obj", "contract"),
    [
        (OutsideEmbedding(), EmbeddingProvider),
        (OutsideGenerator(), GeneratorProvider),
        (OutsideGenerator(), CompletionProvider),
        (OutsideVision(), VisionProvider),
        (OutsideReranker(), RerankerProvider),
    ],
)
def test_matching_the_shape_is_enough(obj: object, contract: type) -> None:
    assert isinstance(obj, contract)


@pytest.mark.parametrize("contract", MODEL_CONTRACTS)
def test_an_unrelated_object_does_not_satisfy_a_contract(contract: type) -> None:
    assert not isinstance(object(), contract)


def test_a_provider_does_not_inherit_anything_from_citenexus() -> None:
    """The point of Protocols: no CiteNexus class in the provider's MRO."""
    for obj in (OutsideEmbedding(), OutsideGenerator(), OutsideVision(), OutsideReranker()):
        mro = type(obj).__mro__
        assert not any(cls.__module__.startswith("citenexus") for cls in mro)


# --- no transport in the contract (ADR-0014 R3 posture) ---------------------

_TRANSPORT_WORDS = {"base_url", "headers", "transport", "timeout", "api_key", "url"}


@pytest.mark.parametrize("contract", ALL_CONTRACTS)
def test_no_contract_method_takes_a_transport_parameter(contract: type) -> None:
    for name, member in vars(contract).items():
        if name.startswith("_") or not callable(member):
            continue
        params = set(inspect.signature(member).parameters) - {"self"}
        assert not (params & _TRANSPORT_WORDS), (
            f"{contract.__name__}.{name} leaks a transport concern: {params & _TRANSPORT_WORDS}"
        )


# --- the shapes themselves --------------------------------------------------


def test_embedding_contract_is_batch_first() -> None:
    """R1: batch is the primitive; a single text is a batch of one."""
    assert hasattr(EmbeddingProvider, "embed_many")
    assert not hasattr(EmbeddingProvider, "embed")
    hints = get_type_hints(EmbeddingProvider.embed_many)
    assert hints["return"] == list[Vector]


def test_generator_contract_matches_the_ask_seam() -> None:
    params = inspect.signature(GeneratorProvider.answer).parameters
    assert list(params) == ["self", "question", "passage", "answer_language"]
    assert params["answer_language"].default == "en"


def test_completion_contract_is_one_prompt_in_one_string_out() -> None:
    sig = inspect.signature(CompletionProvider.complete)
    assert list(sig.parameters) == ["self", "prompt"]
    assert get_type_hints(CompletionProvider.complete)["return"] is str


def test_legacy_single_text_shape_is_named_and_distinct_from_the_contract() -> None:
    """`embed` means two incompatible things; the contract uses neither name."""
    assert hasattr(SingleTextEmbedder, "embed")
    assert get_type_hints(SingleTextEmbedder.embed)["return"] == Vector
    assert get_type_hints(SequenceEmbedder.embed)["return"] == list[Vector]
    assert {SingleTextEmbedder.__name__, SequenceEmbedder.__name__} == {
        "SingleTextEmbedder",
        "SequenceEmbedder",
    }


def test_a_single_text_embedder_does_not_satisfy_the_batch_contract() -> None:
    class Legacy:
        def embed(self, text: str) -> list[float]:
            return [1.0]

    assert isinstance(Legacy(), SingleTextEmbedder)
    assert not isinstance(Legacy(), EmbeddingProvider)


# --- the dispatch helper ----------------------------------------------------


def test_embed_texts_prefers_the_contract() -> None:
    class Both:
        def __init__(self) -> None:
            self.batches: list[int] = []
            self.singles = 0

        def embed(self, text: str) -> list[float]:
            self.singles += 1
            return [0.0]

        def embed_many(self, texts: Sequence[str]) -> list[list[float]]:
            self.batches.append(len(texts))
            return [[float(len(t))] for t in texts]

    both = Both()
    out = contracts.embed_texts(both, ["a", "bb", "ccc"])
    assert out == [[1.0], [2.0], [3.0]]
    assert both.batches == [3]
    assert both.singles == 0


def test_embed_texts_falls_back_to_the_legacy_shape() -> None:
    class Legacy:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def embed(self, text: str) -> list[float]:
            self.calls.append(text)
            return [float(len(text))]

    legacy = Legacy()
    assert contracts.embed_texts(legacy, ["a", "bb"]) == [[1.0], [2.0]]
    assert legacy.calls == ["a", "bb"]


def test_embed_texts_on_no_texts_calls_nothing() -> None:
    class Exploding:
        def embed_many(self, texts: Sequence[str]) -> list[list[float]]:
            raise AssertionError("must not be called for an empty batch")

    assert contracts.embed_texts(Exploding(), []) == []


def test_embed_texts_preserves_order() -> None:
    provider = OutsideEmbedding()
    texts = [f"{'x' * i}" for i in range(1, 40)]
    assert contracts.embed_texts(provider, texts) == [[float(i)] for i in range(1, 40)]


def test_embed_one_is_a_batch_of_one() -> None:
    assert contracts.embed_one(OutsideEmbedding(), "abcd") == [4.0]
