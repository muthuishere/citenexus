"""One definition per seam, several names.

ADR-0014 counts four Python abstractions for embedding alone (five, counting
`retrieve/vector.QueryEmbedder`), plus an undeclared `Generator` Protocol and an
undeclared `Completion` Protocol. After this change each of those names resolves
to *the same object* as the published contract — so they cannot drift apart.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import citenexus.client as client_module
import citenexus.ingest.pipeline as pipeline_module
from citenexus import CiteNexus
from citenexus.answer.decision import Completion
from citenexus.answer.flow import Generator
from citenexus.contracts import (
    CompletionProvider,
    GeneratorProvider,
    SequenceEmbedder,
    SingleTextEmbedder,
    VisionProvider,
)
from citenexus.embed import batcher
from citenexus.ingest.pipeline import Embedder, VisionDescriber
from citenexus.retrieve.vector import QueryEmbedder
from citenexus.testing import FakeLLM


def test_answer_flow_generator_is_the_published_contract() -> None:
    assert Generator is GeneratorProvider


def test_answer_decision_completion_is_the_published_contract() -> None:
    assert Completion is CompletionProvider


def test_ingest_vision_describer_is_the_published_contract() -> None:
    assert VisionDescriber is VisionProvider


def test_the_two_single_text_embedder_seams_are_one_object() -> None:
    assert Embedder is SingleTextEmbedder
    assert QueryEmbedder is SingleTextEmbedder


def test_the_private_batch_embedder_protocol_is_gone() -> None:
    assert not hasattr(batcher, "_BatchEmbedder")
    assert inspect.signature(batcher.embed_in_batches).parameters["plugin"].annotation in (
        SequenceEmbedder,
        "SequenceEmbedder",
    )


# --- the private adapters ADR-0014 said should disappear --------------------


def test_single_text_embedder_adapter_is_gone() -> None:
    assert not hasattr(client_module, "_SingleTextEmbedder")


def test_zero_embedder_is_gone() -> None:
    assert not hasattr(client_module, "_ZeroEmbedder")


def test_client_source_has_no_adapter_left() -> None:
    source = inspect.getsource(client_module)
    assert "_SingleTextEmbedder" not in source
    assert "_ZeroEmbedder" not in source


def test_the_getattr_embed_many_probe_is_gone() -> None:
    """Batching is a contract, not a discovered capability."""
    source = inspect.getsource(pipeline_module)
    assert 'getattr(self._embedder, "embed_many"' not in source
    assert '"embed_many"' not in source


# --- absent is absent, not a fake provider ----------------------------------


def test_pipeline_embedder_is_optional() -> None:
    assert (
        inspect.signature(pipeline_module.IngestPipeline.__init__).parameters["embedder"].default
        is None
    )


def test_a_model_less_client_still_ingests_and_answers_lexically(tmp_path: Path) -> None:
    rag = CiteNexus(tmp_path, generator=FakeLLM())
    rag.ingest(text="The employee shall not disclose confidential information.", document_id="nda")
    result = rag.ask("Can the employee disclose confidential information?")
    assert result.sources
    assert result.sources[0].document == "nda"
