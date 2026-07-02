"""Telemetry sinks — pluggable emit, in-memory capture, stdout JSON lines (§6c)."""

import io

from citenexus.domain import PartitionPath
from citenexus.telemetry import (
    InMemorySink,
    Stage,
    StageEvent,
    StdoutSink,
    TelemetrySink,
)


def _event(stage: Stage) -> StageEvent:
    return StageEvent(stage=stage, partition=PartitionPath.of(("org", "acme")))


def test_in_memory_sink_captures_in_order() -> None:
    sink = InMemorySink()
    sink.emit(_event(Stage.extract))
    sink.emit(_event(Stage.generate))
    assert [e.stage for e in sink.events] == [Stage.extract, Stage.generate]


def test_in_memory_sink_satisfies_protocol() -> None:
    sink = InMemorySink()
    assert isinstance(sink, TelemetrySink)


def test_stdout_sink_writes_one_json_line_per_event() -> None:
    buf = io.StringIO()
    sink = StdoutSink(stream=buf)
    sink.emit(_event(Stage.embedding))
    sink.emit(_event(Stage.rerank))
    lines = buf.getvalue().splitlines()
    assert len(lines) == 2
    assert StageEvent.model_validate_json(lines[0]).stage is Stage.embedding


def test_sink_is_pluggable_via_protocol() -> None:
    def run(sink: TelemetrySink) -> None:
        sink.emit(_event(Stage.verify))

    sink = InMemorySink()
    run(sink)
    assert len(sink.events) == 1
