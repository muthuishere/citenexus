"""The result of a revoke — the inverse of ``IngestResult`` (spec: document-revoke)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class DeleteResult(BaseModel):
    """What a ``CiteNexus.delete`` / ``revoke`` call produced.

    ``status`` distinguishes the two idempotent outcomes: ``"deleted"`` when the
    document existed and its artifacts were removed, ``"absent"`` when there was
    nothing to remove (an unknown or already-revoked id). ``removed_eu_ids`` are
    the Evidence-Unit rows that were purged.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    document_id: str
    status: Literal["deleted", "absent"]
    removed_eu_ids: tuple[str, ...] = ()

    @property
    def n_units(self) -> int:
        return len(self.removed_eu_ids)
