"""Structured logging, event tracking, and optional OpenTelemetry tracing."""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

# ── JSON Log Formatter ──


class JSONFormatter(logging.Formatter):
    """Formats log records as single-line JSON for machine consumption."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            entry["exception"] = self.formatException(record.exc_info)
        # Merge any extra fields attached by EventTracker
        if hasattr(record, "event_data"):
            entry["event"] = record.event_data
        return json.dumps(entry, default=str)


def configure_logging(log_format: str = "text") -> None:
    """Set up root logging. Use log_format='json' for structured output."""
    import sys

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    handler = logging.StreamHandler(sys.stderr)
    if log_format == "json":
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )

    root.handlers.clear()
    root.addHandler(handler)


# ── Event Tracking ──


@dataclass
class Event:
    """A single lifecycle event with timing."""

    name: str
    stage: str
    started_at: float = field(default_factory=time.monotonic)
    ended_at: float | None = None
    duration_ms: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    success: bool = True
    error: str | None = None

    def finish(self, success: bool = True, error: str | None = None) -> None:
        self.ended_at = time.monotonic()
        self.duration_ms = round((self.ended_at - self.started_at) * 1000, 2)
        self.success = success
        self.error = error


class EventTracker:
    """Records lifecycle events for an agent run.

    Usage:
        tracker = EventTracker(persona="backend-engineer", repo="org/repo")
        with tracker.span("discover", stage="discovery"):
            ...  # do work
        tracker.record("claimed_issue", stage="discovery", issue=42)
        report = tracker.summary()
    """

    def __init__(
        self,
        persona: str = "",
        repo: str = "",
        target_type: str = "",
        target_ref: str = "",
    ) -> None:
        self.persona = persona
        self.repo = repo
        self.target_type = target_type
        self.target_ref = target_ref
        self.events: list[Event] = []
        self.run_started_at = time.monotonic()
        self._logger = logging.getLogger("swarm_agent.telemetry")
        self._otel_tracer = _get_otel_tracer()

    @contextmanager
    def span(
        self, name: str, stage: str, **metadata: Any
    ) -> Generator[Event, None, None]:
        """Context manager that records a timed event (span)."""
        event = Event(name=name, stage=stage, metadata=metadata)
        otel_span = None

        if self._otel_tracer:
            otel_span = self._otel_tracer.start_span(
                name,
                attributes={
                    "swarm.persona": self.persona,
                    "swarm.repo": self.repo,
                    "swarm.stage": stage,
                    "swarm.target_type": self.target_type,
                    "swarm.target_ref": self.target_ref,
                    **{f"swarm.{k}": str(v) for k, v in metadata.items()},
                },
            )

        try:
            yield event
            event.finish(success=True)
        except Exception as exc:
            event.finish(success=False, error=str(exc))
            if otel_span:
                otel_span.set_status(_otel_status_error(str(exc)))
                otel_span.record_exception(exc)
            raise
        finally:
            self.events.append(event)
            self._emit_event_log(event)
            if otel_span:
                if event.success:
                    otel_span.set_status(_otel_status_ok())
                otel_span.end()

    def record(self, name: str, stage: str, **metadata: Any) -> None:
        """Record an instantaneous event (no duration)."""
        event = Event(name=name, stage=stage, metadata=metadata)
        event.finish()
        self.events.append(event)
        self._emit_event_log(event)

    def _emit_event_log(self, event: Event) -> None:
        """Emit an event as a structured log entry."""
        event_data = {
            "name": event.name,
            "stage": event.stage,
            "duration_ms": event.duration_ms,
            "success": event.success,
            "persona": self.persona,
            "repo": self.repo,
            "target": f"{self.target_type}#{self.target_ref}",
        }
        if event.metadata:
            event_data["meta"] = event.metadata
        if event.error:
            event_data["error"] = event.error

        record = self._logger.makeRecord(
            "swarm_agent.telemetry",
            logging.INFO,
            "",
            0,
            "event: %s [%s] %.0fms",
            (event.name, event.stage, event.duration_ms or 0),
            None,
        )
        record.event_data = event_data  # type: ignore[attr-defined]
        self._logger.handle(record)

    def summary(self) -> dict[str, Any]:
        """Return a summary of all recorded events."""
        total_ms = round((time.monotonic() - self.run_started_at) * 1000, 2)
        stages: dict[str, float] = {}
        for ev in self.events:
            if ev.duration_ms is not None:
                stages[ev.name] = stages.get(ev.name, 0) + ev.duration_ms

        return {
            "persona": self.persona,
            "repo": self.repo,
            "target": f"{self.target_type}#{self.target_ref}",
            "total_duration_ms": total_ms,
            "event_count": len(self.events),
            "stages": stages,
            "errors": [
                {"name": ev.name, "error": ev.error}
                for ev in self.events
                if not ev.success
            ],
        }

    def format_markdown_report(self) -> str:
        """Format a markdown summary suitable for posting as a GitHub comment."""
        s = self.summary()
        total_secs = s["total_duration_ms"] / 1000

        lines = [
            "<details>",
            f"<summary>📊 Agent metrics — {total_secs:.1f}s total</summary>",
            "",
            "| Stage | Duration |",
            "|-------|----------|",
        ]

        for name, ms in s["stages"].items():
            lines.append(f"| {name} | {ms / 1000:.2f}s |")

        lines.append(f"| **Total** | **{total_secs:.2f}s** |")
        lines.append("")

        if s["errors"]:
            lines.append("**Errors:**")
            for err in s["errors"]:
                lines.append(f"- `{err['name']}`: {err['error']}")
            lines.append("")

        lines.append(f"Persona: `{s['persona']}` · Target: `{s['target']}`")
        lines.append("</details>")

        return "\n".join(lines)


# ── Optional OpenTelemetry Support ──


def _get_otel_tracer():
    """Return an OpenTelemetry tracer if OTEL is configured, else None."""
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return None

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logging.getLogger(__name__).debug(
            "OpenTelemetry packages not installed — tracing disabled"
        )
        return None

    resource = Resource.create({
        "service.name": "swarm-agent",
        "service.namespace": "swarmymcswarmface",
    })
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
    )
    trace.set_tracer_provider(provider)
    return trace.get_tracer("swarm-agent")


def _otel_status_ok():
    """Return an OTel OK status."""
    try:
        from opentelemetry.trace import StatusCode

        return StatusCode.OK
    except ImportError:
        return None


def _otel_status_error(description: str = ""):
    """Return an OTel ERROR status."""
    try:
        from opentelemetry.trace import Status, StatusCode

        return Status(StatusCode.ERROR, description)
    except ImportError:
        return None
