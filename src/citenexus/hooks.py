"""Lifecycle hooks — observe every stage, mutate nothing (spec §6c).

``Hooks`` gives operators callbacks at the moments that matter, toolnexus-style:

- ``on_ingest(result)``        — a document finished ingesting
- ``on_retrieve(query, cands)``— fused candidates for a query
- ``on_answer(result)``        — a grounded answer was produced
- ``on_refuse(result)``        — the strict gate refused
- ``on_chunk(chunk)``          — a verified stream chunk was released

Two invariants keep the guarantees intact:

- **Observe-only.** Hooks receive results; nothing they return is read. A hook
  cannot alter the verified path — the same philosophy as retriever plugins
  never bypassing RRF + grounding (§4b).
- **Never fatal.** A hook that raises is swallowed: user code must never break
  ingest or the cite-or-abstain flow. (Use the telemetry sink for anything that
  must be durable.)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from citenexus.answer.result import Result
    from citenexus.ingest.result import IngestResult
    from citenexus.retrieve.types import Candidate


@dataclass(frozen=True)
class Hooks:
    """Optional lifecycle callbacks; any subset may be provided."""

    on_ingest: Callable[[IngestResult], Any] | None = None
    on_retrieve: Callable[[str, list[Candidate]], Any] | None = None
    on_answer: Callable[[Result], Any] | None = None
    on_refuse: Callable[[Result], Any] | None = None
    on_chunk: Callable[[str], Any] | None = None

    def fire(self, name: str, *args: Any) -> None:
        """Invoke the named hook with ``args``; a raising hook is swallowed."""
        hook = getattr(self, name, None)
        if hook is None:
            return
        try:
            hook(*args)
        except Exception:
            return
