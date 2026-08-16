"""The two-phase model-fulfiller protocol (spec: model-fulfiller).

Generalizes the vision emit/fulfill seam to every remote-model call: the core
emits a typed :class:`~citenexus.domain.model.ModelRequest`, the host fulfills it,
the core parses the :class:`~citenexus.domain.model.ModelResponse`. Two phases, no
FFI callback — and the credential never crosses into the core, in either direction.

This package holds the host side: the emit builders (:mod:`.requests`), the
reference :class:`~citenexus.fulfiller.host.ModelFulfiller` (expand ``${ENV}`` →
HTTP → scrub), and a deterministic :class:`~citenexus.fulfiller.fake.FakeModelFulfiller`
so the whole protocol runs offline.
"""

from citenexus.fulfiller.fake import FakeModelFulfiller
from citenexus.fulfiller.host import Fulfiller, ModelFulfiller, SignedRequest, Signer
from citenexus.fulfiller.requests import (
    build_embed_request,
    build_generate_request,
    build_rerank_request,
    build_vision_request,
)

__all__ = [
    "FakeModelFulfiller",
    "Fulfiller",
    "ModelFulfiller",
    "SignedRequest",
    "Signer",
    "build_embed_request",
    "build_generate_request",
    "build_rerank_request",
    "build_vision_request",
]
