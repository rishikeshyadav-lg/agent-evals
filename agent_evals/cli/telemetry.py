"""OpenTelemetry spans for everything the tool does, written under the run's log directory.

Every mine, draft, agent call, scorer and warehouse query becomes a span, so a slow or expensive run
can be read back afterwards rather than guessed at.

OpenTelemetry is a hard requirement of the CLI and is imported here, never from the library. That
split is deliberate: `import agent_evals` must stay free of dependencies, which is what
`python -m agent_evals.selfcheck` proves and why the package is safe to install beside an agent. The
check lists this module's imports as forbidden, so the separation is enforced rather than remembered.

Spans go to a file under the log directory by default. Set `otlp_endpoint` in the config and they are
also exported to that collector.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

# OpenTelemetry is a hard requirement of the CLI, so this module imports it plainly rather than
# guarding every use. A caller that must tolerate its absence catches ImportError on importing this
# module; `agent_evals` itself never imports it, which the selfcheck enforces.
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter, SpanExportResult

SERVICE_NAME = "agent-evals"


def start(logs: Path, *, otlp_endpoint: str = "", run_id: str = "") -> TracerProvider:
    """Begin recording, writing spans as JSON lines under `logs`.

    A file exporter rather than a collector by default, because the point is that a run leaves a
    readable record on the machine that ran it, with no service to stand up first.
    """

    resource = Resource.create({"service.name": SERVICE_NAME, "agent_evals.run_id": run_id})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(SimpleSpanProcessor(_JsonLinesExporter(logs / "spans.jsonl")))
    if otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint)))
    trace.set_tracer_provider(provider)
    return provider


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[Any]:
    """One span. Without `start`, OpenTelemetry's own no-op tracer records nothing and costs nothing,
    so an evaluation runs unchanged whether or not telemetry was switched on."""

    tracer = trace.get_tracer(SERVICE_NAME)
    with tracer.start_as_current_span(name) as current:
        for key, value in attributes.items():
            if value is not None:
                current.set_attribute(key, value)
        yield current


class _JsonLinesExporter(SpanExporter):
    """Writes each finished span as one JSON line, so the log is greppable without a collector."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def export(self, spans: Any) -> SpanExportResult:
        with self._path.open("a") as handle:
            for item in spans:
                handle.write(json.dumps(_as_record(item), default=str) + "\n")
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return True


def _as_record(span_to_record: Any) -> dict[str, Any]:
    context = span_to_record.get_span_context()
    started, ended = span_to_record.start_time, span_to_record.end_time
    return {
        "name": span_to_record.name,
        "trace_id": format(context.trace_id, "032x"),
        "span_id": format(context.span_id, "016x"),
        "start_unix_nano": started,
        "duration_ms": None if not (started and ended) else (ended - started) / 1_000_000,
        "status": str(span_to_record.status.status_code.name),
        "attributes": dict(span_to_record.attributes or {}),
    }


__all__ = ["SERVICE_NAME", "span", "start"]
