from __future__ import annotations

import csv
import json
import queue
import threading
import time
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

from .model import Event, StackSnapshot, TaskRecord, TimelineSegment

TERMINAL_STATES = {"DONE", "FAILED", "CANCELLED"}


class SessionStore:
    def __init__(self, session_name: str) -> None:
        self.session_id = f"sess_{uuid.uuid4().hex[:12]}"
        self.session_name = session_name
        self.started_ts_ns = time.time_ns()
        self.completed_ts_ns: int | None = None
        self._seq = 0
        self._events: list[Event] = []
        self._tasks: dict[int, TaskRecord] = {}
        self._segments: list[TimelineSegment] = []
        self._open_segments: dict[int, TimelineSegment] = {}
        self._stacks: dict[str, StackSnapshot] = {}
        self._resource_edges: dict[str, set[int]] = defaultdict(set)
        self._subscribers: list[queue.Queue[dict[str, Any]]] = []
        self._lock = threading.RLock()

    def next_seq(self) -> int:
        with self._lock:
            self._seq += 1
            return self._seq

    def append_event(self, event: Event) -> None:
        with self._lock:
            self._events.append(event)
            self._apply_event(event)
            payload = {"type": "event", "event": event.to_dict()}
            dead: list[queue.Queue[dict[str, Any]]] = []
            for sub in self._subscribers:
                try:
                    sub.put_nowait(payload)
                except queue.Full:
                    dead.append(sub)
            for sub in dead:
                self._subscribers.remove(sub)

    def add_stack(self, snapshot: StackSnapshot) -> None:
        with self._lock:
            self._stacks[snapshot.stack_id] = snapshot
            payload = {"type": "stack", "stack": snapshot.to_dict()}
            for sub in list(self._subscribers):
                try:
                    sub.put_nowait(payload)
                except queue.Full:
                    self._subscribers.remove(sub)

    def mark_completed(self) -> None:
        with self._lock:
            if self.completed_ts_ns is not None:
                return
            self.completed_ts_ns = time.time_ns()
            self._close_open_segments(self.completed_ts_ns)

    def subscribe(self) -> queue.Queue[dict[str, Any]]:
        subscriber: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=512)
        with self._lock:
            self._subscribers.append(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: queue.Queue[dict[str, Any]]) -> None:
        with self._lock:
            if subscriber in self._subscribers:
                self._subscribers.remove(subscriber)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "session": {
                    "session_id": self.session_id,
                    "session_name": self.session_name,
                    "started_ts_ns": self.started_ts_ns,
                    "completed_ts_ns": self.completed_ts_ns,
                    "event_count": len(self._events),
                    "task_count": len(self._tasks),
                },
                "tasks": [task.to_dict() for task in self._tasks.values()],
                "segments": [segment.to_dict() for segment in self.timeline()],
                "insights": self.insights(),
            }

    def session_payload(self) -> dict[str, Any]:
        snapshot = self.snapshot()
        return {
            "session": snapshot["session"],
            "tasks": snapshot["tasks"],
            "segments": snapshot["segments"],
            "insights": snapshot["insights"],
        }

    def events(self) -> list[dict[str, Any]]:
        with self._lock:
            return [event.to_dict() for event in self._events]

    def tasks(self) -> list[dict[str, Any]]:
        with self._lock:
            return [task.to_dict() for task in self._tasks.values()]

    def task(self, task_id: int) -> dict[str, Any] | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            children = [
                child.task_id
                for child in self._tasks.values()
                if child.parent_task_id == task_id
            ]
            payload = task.to_dict()
            payload["children"] = children
            if task.stack_id and task.stack_id in self._stacks:
                payload["stack"] = self._stacks[task.stack_id].to_dict()
            return payload

    def timeline(self) -> list[TimelineSegment]:
        with self._lock:
            result = list(self._segments)
            result.extend(self._open_segments.values())
            return sorted(result, key=lambda item: (item.start_ts_ns, item.task_id))

    def resource_graph(self) -> list[dict[str, Any]]:
        with self._lock:
            graph = []
            for resource_id, task_ids in sorted(self._resource_edges.items()):
                graph.append(
                    {
                        "resource_id": resource_id,
                        "task_ids": sorted(task_ids),
                    }
                )
            return graph

    def insights(self) -> list[dict[str, Any]]:
        now = self.completed_ts_ns or time.time_ns()
        findings: list[dict[str, Any]] = []
        with self._lock:
            for task in self._tasks.values():
                age_ms = max(0, (now - task.created_ts_ns) / 1_000_000)
                if task.state == "BLOCKED" and age_ms > 250:
                    findings.append(
                        {
                            "kind": "long_block",
                            "task_id": task.task_id,
                            "severity": "warning",
                            "message": f"Task {task.name} is blocked for {age_ms:.1f} ms",
                            "reason": task.reason,
                        }
                    )
                if (
                    task.state not in TERMINAL_STATES
                    and self.completed_ts_ns is not None
                ):
                    findings.append(
                        {
                            "kind": "task_leak",
                            "task_id": task.task_id,
                            "severity": "warning",
                            "message": f"Task {task.name} did not finish before session end",
                            "reason": task.reason,
                        }
                    )
                if task.state == "FAILED":
                    findings.append(
                        {
                            "kind": "task_error",
                            "task_id": task.task_id,
                            "severity": "error",
                            "message": f"Task {task.name} raised an exception",
                            "reason": task.reason,
                        }
                    )
                if task.state == "CANCELLED":
                    findings.append(
                        {
                            "kind": "task_cancelled",
                            "task_id": task.task_id,
                            "severity": "info",
                            "message": f"Task {task.name} was cancelled",
                            "reason": task.reason,
                        }
                    )
        return findings

    def save_json(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "snapshot": self.snapshot(),
            "events": self.events(),
            "stacks": [stack.to_dict() for stack in self._stacks.values()],
            "resources": self.resource_graph(),
        }
        target.write_text(json.dumps(payload, indent=2))
        return target

    def export_csv(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "task_id",
                    "task_name",
                    "start_ts_ns",
                    "end_ts_ns",
                    "state",
                    "reason",
                    "resource_id",
                ],
            )
            writer.writeheader()
            for segment in self.timeline():
                writer.writerow(segment.to_dict())
        return target

    @classmethod
    def from_capture(cls, data: dict[str, Any]) -> "SessionStore":
        session_name = (
            data.get("snapshot", {}).get("session", {}).get("session_name", "replay")
        )
        store = cls(session_name=session_name)
        snapshot_session = data.get("snapshot", {}).get("session", {})
        store.session_id = snapshot_session.get("session_id", store.session_id)
        store.started_ts_ns = snapshot_session.get("started_ts_ns", store.started_ts_ns)
        for raw_event in data.get("events", []):
            event = Event(**raw_event)
            store._seq = max(store._seq, event.seq)
            store._events.append(event)
            store._apply_event(event)
        for raw_stack in data.get("stacks", []):
            stack = StackSnapshot(**raw_stack)
            store._stacks[stack.stack_id] = stack
        store.completed_ts_ns = snapshot_session.get("completed_ts_ns")
        if store.completed_ts_ns is not None:
            store._close_open_segments(store.completed_ts_ns)
        return store

    def replace_with(self, other: "SessionStore") -> None:
        with self._lock:
            self.session_id = other.session_id
            self.session_name = other.session_name
            self.started_ts_ns = other.started_ts_ns
            self.completed_ts_ns = other.completed_ts_ns
            self._seq = other._seq
            self._events = list(other._events)
            self._tasks = dict(other._tasks)
            self._segments = list(other._segments)
            self._open_segments = dict(other._open_segments)
            self._stacks = dict(other._stacks)
            self._resource_edges = defaultdict(
                set,
                {
                    resource_id: set(task_ids)
                    for resource_id, task_ids in other._resource_edges.items()
                },
            )

    def _apply_event(self, event: Event) -> None:
        if event.kind == "stack.snapshot" and event.stack_id:
            return
        if event.task_id is None:
            return
        if event.kind == "task.create":
            self._tasks[event.task_id] = TaskRecord(
                task_id=event.task_id,
                name=event.task_name or f"task-{event.task_id}",
                parent_task_id=event.parent_task_id,
                state=event.state or "READY",
                created_ts_ns=event.ts_ns,
                updated_ts_ns=event.ts_ns,
                reason=event.reason,
                resource_id=event.resource_id,
                stack_id=event.stack_id,
                metadata=dict(event.metadata),
            )
            self._open_segment(event)
            return

        task = self._tasks.setdefault(
            event.task_id,
            TaskRecord(
                task_id=event.task_id,
                name=event.task_name or f"task-{event.task_id}",
                parent_task_id=event.parent_task_id,
                state=event.state or "READY",
                created_ts_ns=event.ts_ns,
                updated_ts_ns=event.ts_ns,
            ),
        )
        task.updated_ts_ns = event.ts_ns
        if event.task_name:
            task.name = event.task_name
        if event.state:
            task.state = event.state
        task.reason = event.reason
        task.resource_id = event.resource_id
        if event.stack_id:
            task.stack_id = event.stack_id
        if event.metadata:
            task.metadata.update(event.metadata)
        if event.kind in {"task.end", "task.error", "task.cancel"}:
            task.end_ts_ns = event.ts_ns
        if event.resource_id:
            self._resource_edges[event.resource_id].add(event.task_id)
        self._transition_segment(event)

    def _open_segment(self, event: Event) -> None:
        if event.task_id is None:
            return
        task_name = event.task_name or f"task-{event.task_id}"
        self._open_segments[event.task_id] = TimelineSegment(
            task_id=event.task_id,
            task_name=task_name,
            start_ts_ns=event.ts_ns,
            end_ts_ns=event.ts_ns,
            state=event.state or "READY",
            reason=event.reason,
            resource_id=event.resource_id,
        )

    def _transition_segment(self, event: Event) -> None:
        if event.task_id is None:
            return
        current = self._open_segments.get(event.task_id)
        if current is None:
            self._open_segment(event)
            return
        current.end_ts_ns = event.ts_ns
        next_state = event.state or current.state
        if (
            current.state == next_state
            and current.reason == event.reason
            and current.resource_id == event.resource_id
        ):
            return
        self._segments.append(current)
        self._open_segments[event.task_id] = TimelineSegment(
            task_id=event.task_id,
            task_name=event.task_name or current.task_name,
            start_ts_ns=event.ts_ns,
            end_ts_ns=event.ts_ns,
            state=next_state,
            reason=event.reason,
            resource_id=event.resource_id,
        )

    def _close_open_segments(self, end_ts_ns: int) -> None:
        for task_id, segment in list(self._open_segments.items()):
            segment.end_ts_ns = end_ts_ns
            self._segments.append(segment)
            del self._open_segments[task_id]
