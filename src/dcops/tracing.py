# (C)
"""OpenTelemetry setup: a JSONL span exporter, plus OTLP when it is configured and installed."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Sequence

from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)


class JsonlSpanExporter(SpanExporter):
    """Appends one JSON object per finished span to a file."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        if not spans:
            return SpanExportResult.SUCCESS
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                for span in spans:
                    f.write(json.dumps(_row(span)) + "\n")
        except OSError as e:
            print(f"trace export failed: {e}", file=sys.stderr)
            return SpanExportResult.FAILURE
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        pass


def _row(span: ReadableSpan) -> dict:
    ctx = span.get_span_context()
    return {
        "name": span.name,
        "trace_id": format(ctx.trace_id, "032x"),
        "span_id": format(ctx.span_id, "016x"),
        "parent_id": format(span.parent.span_id, "016x") if span.parent is not None else None,
        "start_ns": span.start_time,
        "end_ns": span.end_time,
        "attributes": dict(span.attributes or {}),
        "status": span.status.status_code.name,
    }


def setup_tracing(jsonl_path: Path | None) -> TracerProvider:
    """Build a provider. Spans go to jsonl_path when given, and to OTLP when
    OTEL_EXPORTER_OTLP_ENDPOINT is set and the otlp extra is installed."""
    provider = TracerProvider()
    if jsonl_path is not None:
        # Simple processor: each span lands on disk as it ends, so nothing is lost on exit.
        provider.add_span_processor(SimpleSpanProcessor(JsonlSpanExporter(jsonl_path)))
    if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        except ImportError:
            print(
                "OTEL_EXPORTER_OTLP_ENDPOINT is set but the otlp extra is not installed; "
                "skipping OTLP export (pip install 'dcops[otlp]')",
                file=sys.stderr,
            )
        else:
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    return provider
