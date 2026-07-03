"""Telemetry sinks — a pluggable seam for where events go (spec §6c).

`TelemetrySink` is a structural protocol: anything with an `emit(event)` is a
sink, so the operator can wire in their own (OTLP, a queue, a DB) without
CiteNexus depending on it. Two built-ins ship: `StdoutSink` (one JSON line per
event) and `InMemorySink` (collects events, for tests and the cost view).
"""

from __future__ import annotations

import sys
from typing import Protocol, TextIO, runtime_checkable

from citenexus.telemetry.events import StageEvent


@runtime_checkable
class TelemetrySink(Protocol):
    """Anything that can accept a `StageEvent`."""

    def emit(self, event: StageEvent) -> None: ...


class StdoutSink:
    """Writes each event as a single JSON line to a stream (stdout by default)."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream: TextIO = stream if stream is not None else sys.stdout

    def emit(self, event: StageEvent) -> None:
        self._stream.write(event.model_dump_json() + "\n")


class InMemorySink:
    """Collects emitted events in order — the default sink for tests."""

    def __init__(self) -> None:
        self.events: list[StageEvent] = []

    def emit(self, event: StageEvent) -> None:
        self.events.append(event)
