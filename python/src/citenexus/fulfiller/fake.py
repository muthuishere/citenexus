"""The deterministic fake fulfiller — emit → fulfill → parse, offline.

``FakeModelFulfiller`` returns canned, provider-canonical JSON per seam with no
network and no credential, so the whole two-phase protocol is exercisable in a
hermetic unit test. Optional ``responses`` script an exact body per ``request_id``.
"""

from __future__ import annotations

from collections.abc import Mapping

from citenexus.domain.model import JsonObject, ModelRequest, ModelResponse


def _canned(request: ModelRequest) -> JsonObject:
    """A minimal, deterministic provider body shaped to the request's inputs."""
    if request.kind == "embed":
        count = len(request.body.get("input", []))
        return {"data": [{"embedding": [0.0, float(i)]} for i in range(count)]}
    if request.kind == "rerank":
        docs = request.body.get("documents", [])
        return {
            "results": [{"index": i, "relevance_score": 1.0 - i} for i in range(len(docs))]
        }
    # generate + vision share the chat-completion shape.
    return {"choices": [{"message": {"content": f"fake {request.kind} answer"}}]}


class FakeModelFulfiller:
    """A ``Fulfiller`` that never touches the network or a credential."""

    def __init__(self, responses: Mapping[str, JsonObject] | None = None) -> None:
        self._responses = dict(responses or {})

    def fulfill(self, request: ModelRequest) -> ModelResponse:
        body = self._responses.get(request.request_id)
        if body is None:
            body = _canned(request)
        return ModelResponse(request_id=request.request_id, status=200, body=body)
