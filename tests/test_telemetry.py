"""Tests for telemetry module — structured logging, event tracking, metrics."""

from __future__ import annotations

import json
import logging
import time

import pytest

from swarm_agent.telemetry import (
    EventTracker,
    JSONFormatter,
    configure_logging,
)


class TestJSONFormatter:
    def test_formats_as_json(self):
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello %s", args=("world",), exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert data["msg"] == "hello world"
        assert data["level"] == "INFO"
        assert data["logger"] == "test"

    def test_includes_event_data(self):
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="event", args=(), exc_info=None,
        )
        record.event_data = {"name": "discover", "stage": "discovery"}  # type: ignore
        output = formatter.format(record)
        data = json.loads(output)
        assert data["event"]["name"] == "discover"

    def test_includes_exception(self):
        formatter = JSONFormatter()
        try:
            raise ValueError("boom")
        except ValueError:
            import sys
            record = logging.LogRecord(
                name="test", level=logging.ERROR, pathname="", lineno=0,
                msg="failed", args=(), exc_info=sys.exc_info(),
            )
        output = formatter.format(record)
        data = json.loads(output)
        assert "ValueError" in data["exception"]


class TestConfigureLogging:
    def test_text_format(self):
        configure_logging("text")
        root = logging.getLogger()
        assert len(root.handlers) == 1
        assert not isinstance(root.handlers[0].formatter, JSONFormatter)

    def test_json_format(self):
        configure_logging("json")
        root = logging.getLogger()
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0].formatter, JSONFormatter)

    def teardown_method(self):
        # Reset logging
        configure_logging("text")


class TestEventTracker:
    def test_span_records_event(self):
        tracker = EventTracker(persona="tester", repo="org/repo")
        with tracker.span("test_step", stage="testing"):
            pass
        assert len(tracker.events) == 1
        ev = tracker.events[0]
        assert ev.name == "test_step"
        assert ev.stage == "testing"
        assert ev.success is True
        assert ev.duration_ms is not None
        assert ev.duration_ms >= 0

    def test_span_records_failure(self):
        tracker = EventTracker(persona="tester", repo="org/repo")
        with pytest.raises(ValueError, match="oops"):
            with tracker.span("failing_step", stage="testing"):
                raise ValueError("oops")
        assert len(tracker.events) == 1
        ev = tracker.events[0]
        assert ev.success is False
        assert ev.error == "oops"

    def test_record_instant_event(self):
        tracker = EventTracker(persona="tester", repo="org/repo")
        tracker.record("claimed_issue", stage="discovery", issue=42)
        assert len(tracker.events) == 1
        ev = tracker.events[0]
        assert ev.name == "claimed_issue"
        assert ev.metadata["issue"] == 42
        assert ev.duration_ms is not None  # near-zero

    def test_span_with_metadata(self):
        tracker = EventTracker(persona="dev", repo="org/repo")
        with tracker.span("llm_call", stage="reasoning", model="gpt-4o"):
            pass
        ev = tracker.events[0]
        assert ev.metadata["model"] == "gpt-4o"

    def test_summary(self):
        tracker = EventTracker(
            persona="dev", repo="org/repo",
            target_type="issue", target_ref="42",
        )
        with tracker.span("step1", stage="a"):
            time.sleep(0.01)
        with tracker.span("step2", stage="b"):
            time.sleep(0.01)
        tracker.record("note", stage="c")

        summary = tracker.summary()
        assert summary["persona"] == "dev"
        assert summary["repo"] == "org/repo"
        assert summary["target"] == "issue#42"
        assert summary["event_count"] == 3
        assert summary["total_duration_ms"] > 0
        assert "step1" in summary["stages"]
        assert "step2" in summary["stages"]
        assert summary["errors"] == []

    def test_summary_with_errors(self):
        tracker = EventTracker(persona="dev", repo="org/repo")
        try:
            with tracker.span("bad", stage="x"):
                raise RuntimeError("fail")
        except RuntimeError:
            pass
        summary = tracker.summary()
        assert len(summary["errors"]) == 1
        assert summary["errors"][0]["error"] == "fail"

    def test_format_markdown_report(self):
        tracker = EventTracker(
            persona="dev", repo="org/repo",
            target_type="issue", target_ref="7",
        )
        with tracker.span("clone", stage="setup"):
            pass
        with tracker.span("reasoning", stage="llm"):
            pass
        report = tracker.format_markdown_report()
        assert "📊 Agent metrics" in report
        assert "clone" in report
        assert "reasoning" in report
        assert "dev" in report
        assert "<details>" in report

    def test_multiple_spans_accumulate(self):
        tracker = EventTracker(persona="dev", repo="org/repo")
        for i in range(5):
            with tracker.span(f"step_{i}", stage="work"):
                pass
        assert len(tracker.events) == 5
        summary = tracker.summary()
        assert summary["event_count"] == 5


class TestDashboard:
    """Tests for the SwarmDashboard — uses mocked subprocess."""

    def test_extract_statuses_active(self):
        from swarm_agent.dashboard.app import SwarmDashboard
        dash = SwarmDashboard("org/repo")
        item = {
            "number": 42,
            "title": "Fix bug",
            "labels": [{"name": "review:started:backend-engineer"}],
        }
        statuses = dash._extract_statuses(item, "issue")
        assert len(statuses) == 1
        assert statuses[0].persona == "backend-engineer"
        assert statuses[0].state == "active"
        assert statuses[0].target_number == 42

    def test_extract_statuses_complete(self):
        from swarm_agent.dashboard.app import SwarmDashboard
        dash = SwarmDashboard("org/repo")
        item = {
            "number": 10,
            "title": "Add feature",
            "labels": [
                {"name": "review:started:qa-lead"},
                {"name": "review:complete:qa-lead"},
            ],
        }
        statuses = dash._extract_statuses(item, "pr")
        assert len(statuses) == 1
        assert statuses[0].state == "complete"
        assert statuses[0].persona == "qa-lead"

    def test_extract_statuses_mixed(self):
        from swarm_agent.dashboard.app import SwarmDashboard
        dash = SwarmDashboard("org/repo")
        item = {
            "number": 5,
            "title": "Refactor",
            "labels": [
                {"name": "review:started:dev"},
                {"name": "review:complete:dev"},
                {"name": "review:started:qa"},
            ],
        }
        statuses = dash._extract_statuses(item, "issue")
        assert len(statuses) == 2
        states = {s.persona: s.state for s in statuses}
        assert states["dev"] == "complete"
        assert states["qa"] == "active"

    def test_extract_statuses_no_labels(self):
        from swarm_agent.dashboard.app import SwarmDashboard
        dash = SwarmDashboard("org/repo")
        item = {"number": 1, "title": "New", "labels": []}
        statuses = dash._extract_statuses(item, "issue")
        assert len(statuses) == 0

    def test_extract_statuses_non_swarm_labels(self):
        from swarm_agent.dashboard.app import SwarmDashboard
        dash = SwarmDashboard("org/repo")
        item = {
            "number": 1,
            "title": "Bug",
            "labels": [{"name": "bug"}, {"name": "priority:high"}],
        }
        statuses = dash._extract_statuses(item, "issue")
        assert len(statuses) == 0
