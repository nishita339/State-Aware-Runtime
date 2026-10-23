"""
Append-Only Lineage Logger with Causal Provenance
===================================================

Provides a forensic-grade audit trail for all runtime operations.
Every action proposal, contract evaluation, memory write, checkpoint,
rollback, and completion verification is recorded as an immutable
event in a JSONL append-only log.

Causal relationships between events are tracked via parent_event_id
links, enabling reconstruction of the full causal DAG for any
execution trajectory.

Design Principles (from Springdrift, Brady 2026):
    - Append-only: events are never modified or deleted
    - Causal: every event links to its causal parent(s)
    - Replayable: the log supports deterministic replay
    - Exportable: the causal graph can be exported for visualization

References:
    - Springdrift (Brady, 2026): Auditable Persistent Runtime
    - Trace-Based Assurance (Paduraru et al., 2026): Message-Action Traces
    - Reasoning Provenance (Vispute, 2026): Behavioral Analytics
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from state_aware_runtime.config import generate_id

logger = logging.getLogger(__name__)

__all__ = [
    "LineageEvent",
    "LineageLogger",
    "CausalTracer",
]

# Valid event types
EVENT_TYPES = frozenset({
    "action_proposed",
    "action_approved",
    "action_blocked",
    "action_rewritten",
    "action_executed",
    "action_failed",
    "state_committed",
    "state_grown",
    "state_compressed",
    "state_revised",
    "checkpoint_created",
    "checkpoint_restored",
    "rollback_executed",
    "contract_violated",
    "contract_checked",
    "drift_detected",
    "memory_written",
    "memory_decayed",
    "memory_quarantined",
    "memory_rejected",
    "completion_claimed",
    "completion_verified",
    "completion_rejected",
    "subtask_started",
    "subtask_completed",
    "subtask_failed",
    "session_started",
    "session_ended",
    "recovery_initiated",
    "recovery_completed",
    "span_started",
    "span_ended",
})

ACTORS = frozenset({
    "manager",
    "executor",
    "auditor",
    "governor",
    "firewall",
    "recovery",
    "system",
    "agent",
})

SEVERITIES = frozenset({"info", "warning", "error", "critical"})


# ============================================================================
# Lineage Event
# ============================================================================


@dataclass
class LineageEvent:
    """
    A single immutable audit event in the lineage log.

    Events form a causal DAG through parent_event_id links,
    enabling forensic reconstruction of any execution sequence.
    """

    event_id: str = field(default_factory=lambda: generate_id("evt"))
    session_id: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    event_type: str = "action_proposed"
    node_id: str = ""
    parent_event_id: Optional[str] = None
    payload: dict[str, Any] = field(default_factory=dict)
    actor: str = "system"
    severity: str = "info"

    def __post_init__(self) -> None:
        if self.event_type not in EVENT_TYPES:
            logger.warning("Unknown event type: %s", self.event_type)
        if self.actor not in ACTORS:
            logger.warning("Unknown actor: %s", self.actor)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "session_id": self.session_id,
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type,
            "node_id": self.node_id,
            "parent_event_id": self.parent_event_id,
            "payload": self.payload,
            "actor": self.actor,
            "severity": self.severity,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LineageEvent:
        ts = data.get("timestamp", "")
        if isinstance(ts, str) and ts:
            timestamp = datetime.fromisoformat(ts)
        else:
            timestamp = datetime.now(timezone.utc)

        return cls(
            event_id=data.get("event_id", generate_id("evt")),
            session_id=data.get("session_id", ""),
            timestamp=timestamp,
            event_type=data.get("event_type", "action_proposed"),
            node_id=data.get("node_id", ""),
            parent_event_id=data.get("parent_event_id"),
            payload=data.get("payload", {}),
            actor=data.get("actor", "system"),
            severity=data.get("severity", "info"),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


# ============================================================================
# Lineage Logger
# ============================================================================


class LineageLogger:
    """
    Append-only JSONL logger for runtime lineage events.

    Each event is atomically appended to a JSONL file. Events are never
    modified or deleted, ensuring a complete forensic record.

    The logger supports querying, causal chain tracing, and aggregate
    statistics for runtime analysis.
    """

    def __init__(self, log_dir: Path, session_id: str) -> None:
        self._log_dir = log_dir
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._session_id = session_id
        self._log_file = self._log_dir / f"lineage_{session_id}.jsonl"
        self._event_count = 0
        self._events_cache: list[LineageEvent] = []

        # Emit session start event
        self.emit(LineageEvent(
            session_id=session_id,
            event_type="session_started",
            actor="system",
            payload={"log_file": str(self._log_file)},
        ))

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def event_count(self) -> int:
        return self._event_count

    def emit(self, event: LineageEvent) -> None:
        """
        Append an event to the JSONL log.

        This is an atomic append operation — partial writes will not
        corrupt the log file.
        """
        if not event.session_id:
            event.session_id = self._session_id

        # Atomic append
        line = event.to_json() + "\n"
        with open(self._log_file, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())

        self._events_cache.append(event)
        self._event_count += 1

        if event.severity in ("error", "critical"):
            logger.warning("Lineage [%s]: %s — %s", event.severity, event.event_type, event.payload)

    def query(
        self,
        event_type: Optional[str] = None,
        node_id: Optional[str] = None,
        actor: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        severity: Optional[str] = None,
    ) -> list[LineageEvent]:
        """
        Query events with optional filters.

        Reads from the cache for the current session. Falls back to
        reading from disk if the cache is empty.
        """
        events = self._load_events()

        filtered = []
        for event in events:
            if event_type and event.event_type != event_type:
                continue
            if node_id and event.node_id != node_id:
                continue
            if actor and event.actor != actor:
                continue
            if since and event.timestamp < since:
                continue
            if until and event.timestamp > until:
                continue
            if severity and event.severity != severity:
                continue
            filtered.append(event)

        return filtered

    def get_causal_chain(self, event_id: str) -> list[LineageEvent]:
        """
        Trace the causal chain backwards from an event.

        Follows parent_event_id links to reconstruct the full
        causal ancestry of any event.
        """
        events = self._load_events()
        event_map = {e.event_id: e for e in events}

        chain: list[LineageEvent] = []
        current_id: Optional[str] = event_id

        visited: set[str] = set()
        while current_id and current_id not in visited:
            visited.add(current_id)
            event = event_map.get(current_id)
            if event is None:
                break
            chain.append(event)
            current_id = event.parent_event_id

        chain.reverse()  # Root cause first
        return chain

    def get_session_summary(self) -> dict[str, Any]:
        """
        Compute aggregate statistics for the session.

        Returns counts of events by type, actor, and severity,
        plus timing information.
        """
        events = self._load_events()

        type_counts: dict[str, int] = {}
        actor_counts: dict[str, int] = {}
        severity_counts: dict[str, int] = {}

        for event in events:
            type_counts[event.event_type] = type_counts.get(event.event_type, 0) + 1
            actor_counts[event.actor] = actor_counts.get(event.actor, 0) + 1
            severity_counts[event.severity] = severity_counts.get(event.severity, 0) + 1

        first_ts = events[0].timestamp if events else None
        last_ts = events[-1].timestamp if events else None

        return {
            "session_id": self._session_id,
            "total_events": len(events),
            "event_types": type_counts,
            "actors": actor_counts,
            "severities": severity_counts,
            "first_event": first_ts.isoformat() if first_ts else None,
            "last_event": last_ts.isoformat() if last_ts else None,
            "duration_seconds": (
                (last_ts - first_ts).total_seconds()
                if first_ts and last_ts
                else 0
            ),
        }

    def export_graph(self) -> dict[str, Any]:
        """
        Export the causal DAG for visualization.

        Returns nodes (events) and edges (causal links) suitable
        for rendering with graph visualization tools.
        """
        events = self._load_events()

        nodes = []
        edges = []

        for event in events:
            nodes.append({
                "id": event.event_id,
                "type": event.event_type,
                "actor": event.actor,
                "severity": event.severity,
                "timestamp": event.timestamp.isoformat(),
                "node_id": event.node_id,
            })
            if event.parent_event_id:
                edges.append({
                    "source": event.parent_event_id,
                    "target": event.event_id,
                    "relationship": "caused",
                })

        return {"nodes": nodes, "edges": edges}

    def _load_events(self) -> list[LineageEvent]:
        """Load events from cache or disk."""
        if self._events_cache:
            return self._events_cache

        if not self._log_file.exists():
            return []

        events = []
        with open(self._log_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        data = json.loads(line)
                        events.append(LineageEvent.from_dict(data))
                    except json.JSONDecodeError:
                        logger.warning("Skipping malformed lineage line")

        self._events_cache = events
        return events


# ============================================================================
# Causal Tracer
# ============================================================================


class CausalTracer:
    """
    Tracks causal relationships between events using span-based tracing.

    Provides a higher-level API for creating causal spans (start/end pairs)
    and linking events into causal chains for structured forensic analysis.
    """

    def __init__(self, lineage_logger: LineageLogger) -> None:
        self._logger = lineage_logger
        self._open_spans: dict[str, LineageEvent] = {}

    def start_span(
        self,
        event_type: str,
        actor: str,
        node_id: str = "",
        payload: Optional[dict[str, Any]] = None,
        parent_event_id: Optional[str] = None,
    ) -> LineageEvent:
        """
        Begin a causal span.

        Creates a 'span_started' event that can later be closed
        with end_span(). Useful for tracking the duration and
        outcome of multi-step operations.

        Args:
            event_type: The type of operation being spanned.
            actor: Who initiated this span.
            node_id: Related state tree node.
            payload: Initial span data.
            parent_event_id: Causal parent event.

        Returns:
            The span start event (keep reference for end_span).
        """
        span_event = LineageEvent(
            session_id=self._logger.session_id,
            event_type="span_started",
            actor=actor,
            node_id=node_id,
            parent_event_id=parent_event_id,
            payload={
                "span_type": event_type,
                **(payload or {}),
            },
        )
        self._logger.emit(span_event)
        self._open_spans[span_event.event_id] = span_event
        return span_event

    def end_span(
        self,
        span_event: LineageEvent,
        result_payload: Optional[dict[str, Any]] = None,
        success: bool = True,
    ) -> LineageEvent:
        """
        Complete a causal span.

        Creates a 'span_ended' event linked to the span start event,
        recording the outcome and duration.

        Args:
            span_event: The start event returned by start_span().
            result_payload: Result data for the span.
            success: Whether the spanned operation succeeded.

        Returns:
            The span end event.
        """
        duration_ms = (
            datetime.now(timezone.utc) - span_event.timestamp
        ).total_seconds() * 1000

        end_event = LineageEvent(
            session_id=self._logger.session_id,
            event_type="span_ended",
            actor=span_event.actor,
            node_id=span_event.node_id,
            parent_event_id=span_event.event_id,
            severity="info" if success else "warning",
            payload={
                "span_type": span_event.payload.get("span_type", ""),
                "duration_ms": duration_ms,
                "success": success,
                **(result_payload or {}),
            },
        )
        self._logger.emit(end_event)
        self._open_spans.pop(span_event.event_id, None)
        return end_event

    def link(
        self,
        parent_event: LineageEvent,
        child_event_type: str,
        actor: str,
        node_id: str = "",
        payload: Optional[dict[str, Any]] = None,
        severity: str = "info",
    ) -> LineageEvent:
        """
        Create a causal link from a parent event to a new child event.

        Args:
            parent_event: The causing event.
            child_event_type: Type of the caused event.
            actor: Who is responsible for the child event.
            node_id: Related state tree node.
            payload: Child event data.
            severity: Event severity.

        Returns:
            The newly created child event.
        """
        child_event = LineageEvent(
            session_id=self._logger.session_id,
            event_type=child_event_type,
            actor=actor,
            node_id=node_id,
            parent_event_id=parent_event.event_id,
            payload=payload or {},
            severity=severity,
        )
        self._logger.emit(child_event)
        return child_event

    @property
    def open_span_count(self) -> int:
        return len(self._open_spans)
