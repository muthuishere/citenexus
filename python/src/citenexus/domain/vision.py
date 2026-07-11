"""Two-phase vision-orchestration domain types (ADR-0005, §9).

Figures are described by an injected vision LLM, but the polyglot core must not
make that call: doing so would force it to re-implement the host's transport and,
worse, hold the API key. So vision runs in three phases across a plain-data seam:

1. **emit** — the core parses an artifact and returns a tuple of
   `PendingVisionRequest`s: each a stable `request_id`, a model-ready `payload`
   (the base64 ``image_url`` data URI + the prompt, fully assembled by the core),
   and the `source_ref` (document + page + bbox) the figure is cited to.
2. **fulfill** — the host POSTs each payload with its **own** transport (its auth,
   concurrency, mocking) and returns one description per `request_id`.
3. **assemble** — the core joins descriptions to requests by `request_id` and
   builds the citable figure Evidence Units.

These types are the wire between the phases. They are frozen, forbid unknown
fields, and — the load-bearing invariant — carry **no credential**: the API key
lives only in the host's fulfiller and never crosses into the core.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

# A bounding box as [x0, y0, x1, y1] in page coordinates — exactly four numbers.
# Defined here (not imported from evidence.unit) to keep the domain layer at the
# bottom of the import graph; structurally identical to ``evidence.unit.BBox``.
BBox = tuple[float, float, float, float]


class VisionSourceRef(BaseModel):
    """Where an emitted request's figure lives — the citation target the
    assembled figure Evidence Unit points back at (document + page + bbox)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    document: str
    page: int | None = None
    bbox: BBox | None = None
    source_uri: str | None = None


class VisionPayload(BaseModel):
    """The model-ready content the host POSTs: the prompt plus the base64
    ``image_url`` data URI, both assembled by the core. Provider-shaped
    (OpenAI ``image_url``); credential-free by construction — the host wraps it
    in its own request with its own model/temperature and auth."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt: str
    image_url: str


class PendingVisionRequest(BaseModel):
    """One figure awaiting host fulfillment (the two-phase seam's unit of work).

    ``request_id`` is the figure's future ``eu_id`` (``{document}::img::{image_id}``)
    and the sole key the fulfilled description is addressed back by; ``payload`` is
    opaque to the host beyond "send it and return the text"; ``source_ref`` carries
    the citation geometry so assemble needs nothing but the description to build
    the figure EU."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: str
    payload: VisionPayload
    source_ref: VisionSourceRef
