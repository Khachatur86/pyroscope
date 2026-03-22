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
FAN_OUT_CHILDREN_THRESHOLD = 5
GATHER_STALL_MS_THRESHOLD = 100.0
RESOURCE_CONTENTION_THRESHOLD = 2
SESSION_SCHEMA_VERSION = "1.0"


class SessionStore:
    def __init__(self, session_name: str) -> None:
        self._schema_version = SESSION_SCHEMA_VERSION
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
                    "schema_version": self._schema_version,
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

    def tasks(
        self,
        *,
        state: str | None = None,
        role: str | None = None,
        reason: str | None = None,
        resource_id: str | None = None,
        q: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        with self._lock:
            tasks = [task.to_dict() for task in self._tasks.values()]
            filtered = [
                task
                for task in tasks
                if self._matches_task_filters(
                    task,
                    state=state,
                    role=role,
                    reason=reason,
                    resource_id=resource_id,
                    q=q,
                )
            ]
            filtered.sort(key=lambda item: item["task_id"])
            return self._paginate(filtered, offset=offset, limit=limit)

    def task(self, task_id: int) -> dict[str, Any] | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            payload = task.to_dict()
            payload["cancellation_source"] = self._cancellation_source_payload(task)
            if task.stack_id and task.stack_id in self._stacks:
                payload["stack"] = self._stacks[task.stack_id].to_dict()
            return payload

    def timeline(
        self,
        *,
        state: str | None = None,
        reason: str | None = None,
        resource_id: str | None = None,
        task_id: int | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[TimelineSegment]:
        with self._lock:
            result = list(self._segments)
            result.extend(self._open_segments.values())
            filtered = [
                segment
                for segment in result
                if self._matches_timeline_filters(
                    segment,
                    state=state,
                    reason=reason,
                    resource_id=resource_id,
                    task_id=task_id,
                )
            ]
            filtered.sort(key=lambda item: (item.start_ts_ns, item.task_id))
            return self._paginate(filtered, offset=offset, limit=limit)

    def resource_graph(
        self,
        *,
        resource_id: str | None = None,
        task_id: int | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        with self._lock:
            graph = []
            for current_resource_id, task_ids in sorted(self._resource_edges.items()):
                if resource_id is not None and current_resource_id != resource_id:
                    continue
                if task_id is not None and task_id not in task_ids:
                    continue
                graph.append(
                    {
                        "resource_id": current_resource_id,
                        "task_ids": sorted(task_ids),
                    }
                )
            return self._paginate(graph, offset=offset, limit=limit)

    def insights(
        self,
        *,
        kind: str | None = None,
        severity: str | None = None,
        task_id: int | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        now = self.completed_ts_ns or time.time_ns()
        findings: list[dict[str, Any]] = []
        with self._lock:
            cancelled_by_parent: dict[int, list[TaskRecord]] = defaultdict(list)
            cancelled_by_source: dict[tuple[int, str, int | None], list[TaskRecord]] = (
                defaultdict(list)
            )
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
                    if task.parent_task_id is not None:
                        cancelled_by_parent[task.parent_task_id].append(task)
                    if (
                        task.cancelled_by_task_id is not None
                        and task.cancellation_origin is not None
                    ):
                        cancelled_by_source[
                            (
                                task.cancelled_by_task_id,
                                task.cancellation_origin,
                                task.parent_task_id,
                            )
                        ].append(task)
                    source_payload = self._cancellation_source_payload(task)
                    findings.append(
                        {
                            "kind": "task_cancelled",
                            "task_id": task.task_id,
                            "severity": "info",
                            "message": self._cancellation_message(task, source_payload),
                            "reason": task.reason,
                            "cancelled_by_task_id": task.cancelled_by_task_id,
                            "cancellation_origin": task.cancellation_origin,
                            "cancellation_source": source_payload,
                            "timeout_seconds": task.metadata.get("timeout_seconds"),
                            "blocked_reason": task.metadata.get("blocked_reason"),
                            "blocked_resource_id": task.metadata.get(
                                "blocked_resource_id"
                            ),
                        }
                    )
            for (
                source_task_id,
                cancellation_origin,
                parent_task_id,
            ), tasks in sorted(cancelled_by_source.items()):
                source_task = self._tasks.get(source_task_id)
                source_task_name = (
                    source_task.name
                    if source_task is not None
                    else f"task-{source_task_id}"
                )
                findings.append(
                    {
                        "kind": "cancellation_chain",
                        "task_id": source_task_id,
                        "severity": (
                            "warning"
                            if cancellation_origin == "sibling_failure"
                            else "info"
                        ),
                        "message": self._cancellation_chain_message(
                            source_task_name=source_task_name,
                            cancellation_origin=cancellation_origin,
                            affected_tasks=tasks,
                        ),
                        "reason": cancellation_origin,
                        "source_task_id": source_task_id,
                        "source_task_name": source_task_name,
                        "affected_task_ids": sorted(task.task_id for task in tasks),
                        "affected_task_names": [
                            task.name
                            for task in sorted(tasks, key=lambda item: item.task_id)
                        ],
                        "parent_task_id": parent_task_id,
                        "timeout_seconds": self._cancellation_timeout_seconds(tasks),
                    }
                )
            for parent_task_id, tasks in cancelled_by_parent.items():
                if len(tasks) < 2:
                    continue
                findings.append(
                    {
                        "kind": "cancellation_cascade",
                        "task_id": parent_task_id,
                        "severity": "warning",
                        "message": f"Parent task {parent_task_id} cancelled {len(tasks)} child tasks",
                        "reason": "taskgroup_or_parent_shutdown",
                    }
                )
            findings.extend(self._resource_contention_insights())
            findings.extend(self._fan_out_insights())
            findings.extend(self._stalled_gather_insights())
        filtered = [
            finding
            for finding in findings
            if self._matches_insight_filters(
                finding,
                kind=kind,
                severity=severity,
                task_id=task_id,
            )
        ]
        return self._paginate(filtered, offset=offset, limit=limit)

    def save_json(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": self._schema_version,
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

    def export_summary_json(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tasks = self.tasks()
        resources = self.resource_graph()
        insights = self.insights()

        state_counts: dict[str, int] = {}
        for task in tasks:
            state = str(task["state"])
            state_counts[state] = state_counts.get(state, 0) + 1

        insight_counts: dict[str, int] = {}
        for insight in insights:
            kind = str(insight["kind"])
            insight_counts[kind] = insight_counts.get(kind, 0) + 1

        payload = {
            "schema_version": self._schema_version,
            "session": self.snapshot()["session"],
            "counts": {
                "tasks": len(tasks),
                "segments": len(self.timeline()),
                "resources": len(resources),
                "insights": len(insights),
            },
            "state_counts": dict(sorted(state_counts.items())),
            "insight_counts": dict(sorted(insight_counts.items())),
        }
        target.write_text(json.dumps(payload, indent=2))
        return target

    def export_insights_csv(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "kind",
                    "severity",
                    "task_id",
                    "reason",
                    "resource_id",
                    "blocked_resource_id",
                    "message",
                ],
            )
            writer.writeheader()
            for insight in self.insights():
                writer.writerow(
                    {
                        "kind": insight.get("kind"),
                        "severity": insight.get("severity"),
                        "task_id": insight.get("task_id"),
                        "reason": insight.get("reason"),
                        "resource_id": insight.get("resource_id"),
                        "blocked_resource_id": insight.get("blocked_resource_id"),
                        "message": insight.get("message"),
                    }
                )
        return target

    def compare_summary(self, other: "SessionStore") -> dict[str, Any]:
        baseline_tasks = self.tasks()
        candidate_tasks = other.tasks()
        baseline_insights = self.insights()
        candidate_insights = other.insights()
        baseline_resources = self.resource_graph()
        candidate_resources = other.resource_graph()

        return {
            "baseline": self._compare_identity_payload(),
            "candidate": other._compare_identity_payload(),
            "counts": {
                "baseline_tasks": len(baseline_tasks),
                "candidate_tasks": len(candidate_tasks),
                "baseline_resources": len(baseline_resources),
                "candidate_resources": len(candidate_resources),
                "baseline_insights": len(baseline_insights),
                "candidate_insights": len(candidate_insights),
            },
            "states": self._compare_counts(
                self._task_state_counts(baseline_tasks),
                self._task_state_counts(candidate_tasks),
            ),
            "reasons": self._compare_counts(
                self._task_reason_counts(baseline_tasks),
                self._task_reason_counts(candidate_tasks),
            ),
            "resources": {
                "added": self._added_sorted(
                    [resource["resource_id"] for resource in baseline_resources],
                    [resource["resource_id"] for resource in candidate_resources],
                ),
                "removed": self._removed_sorted(
                    [resource["resource_id"] for resource in baseline_resources],
                    [resource["resource_id"] for resource in candidate_resources],
                ),
            },
            "task_names": {
                "added": self._added_sorted(
                    [task["name"] for task in baseline_tasks],
                    [task["name"] for task in candidate_tasks],
                ),
                "removed": self._removed_sorted(
                    [task["name"] for task in baseline_tasks],
                    [task["name"] for task in candidate_tasks],
                ),
            },
        }

    @classmethod
    def from_capture(cls, data: dict[str, Any]) -> "SessionStore":
        session_name = (
            data.get("snapshot", {}).get("session", {}).get("session_name", "replay")
        )
        store = cls(session_name=session_name)
        snapshot_session = data.get("snapshot", {}).get("session", {})
        schema_version = snapshot_session.get(
            "schema_version", data.get("schema_version", SESSION_SCHEMA_VERSION)
        )
        store.session_id = snapshot_session.get("session_id", store.session_id)
        store.session_name = snapshot_session.get("session_name", store.session_name)
        store.started_ts_ns = snapshot_session.get("started_ts_ns", store.started_ts_ns)
        store._schema_version = schema_version
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
            self._schema_version = other._schema_version
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
                children=[],
                state=event.state or "READY",
                created_ts_ns=event.ts_ns,
                updated_ts_ns=event.ts_ns,
                cancelled_by_task_id=event.cancelled_by_task_id,
                cancellation_origin=event.cancellation_origin,
                reason=event.reason,
                resource_id=event.resource_id,
                stack_id=event.stack_id,
                metadata=dict(event.metadata),
            )
            self._hydrate_existing_children(event.task_id)
            self._sync_parent_child_link(
                task_id=event.task_id, parent_task_id=event.parent_task_id
            )
            self._open_segment(event)
            return

        task = self._tasks.setdefault(
            event.task_id,
            TaskRecord(
                task_id=event.task_id,
                name=event.task_name or f"task-{event.task_id}",
                parent_task_id=event.parent_task_id,
                children=[],
                state=event.state or "READY",
                created_ts_ns=event.ts_ns,
                updated_ts_ns=event.ts_ns,
                cancelled_by_task_id=event.cancelled_by_task_id,
                cancellation_origin=event.cancellation_origin,
            ),
        )
        self._hydrate_existing_children(event.task_id)
        task.updated_ts_ns = event.ts_ns
        if event.task_name:
            task.name = event.task_name
        if event.parent_task_id != task.parent_task_id:
            self._sync_parent_child_link(
                task_id=event.task_id,
                parent_task_id=event.parent_task_id,
                previous_parent_task_id=task.parent_task_id,
            )
            task.parent_task_id = event.parent_task_id
        if event.state:
            task.state = event.state
        if event.cancelled_by_task_id is not None:
            task.cancelled_by_task_id = event.cancelled_by_task_id
        if event.cancellation_origin is not None:
            task.cancellation_origin = event.cancellation_origin
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

    def _sync_parent_child_link(
        self,
        task_id: int,
        parent_task_id: int | None,
        previous_parent_task_id: int | None = None,
    ) -> None:
        if previous_parent_task_id is not None:
            previous_parent = self._tasks.get(previous_parent_task_id)
            if previous_parent is not None:
                previous_parent.children = [
                    child_id
                    for child_id in previous_parent.children
                    if child_id != task_id
                ]
        if parent_task_id is None:
            return
        parent = self._tasks.get(parent_task_id)
        if parent is None:
            return
        if task_id not in parent.children:
            parent.children.append(task_id)
            parent.children.sort()

    def _hydrate_existing_children(self, task_id: int) -> None:
        task = self._tasks.get(task_id)
        if task is None:
            return
        task.children = sorted(
            child.task_id
            for child in self._tasks.values()
            if child.parent_task_id == task_id and child.task_id != task_id
        )

    def _cancellation_source_payload(self, task: TaskRecord) -> dict[str, Any] | None:
        if task.cancelled_by_task_id is None:
            return None
        source = self._tasks.get(task.cancelled_by_task_id)
        if source is None:
            return {"task_id": task.cancelled_by_task_id}
        return {
            "task_id": source.task_id,
            "task_name": source.name,
            "state": source.state,
        }

    def _cancellation_message(
        self, task: TaskRecord, source_payload: dict[str, Any] | None
    ) -> str:
        blocked_suffix = self._blocked_suffix(task)
        if task.cancellation_origin == "timeout":
            timeout_seconds = task.metadata.get("timeout_seconds")
            if source_payload is not None and timeout_seconds is not None:
                return (
                    f"Task {task.name} was cancelled after "
                    f"{source_payload.get('task_name', source_payload['task_id'])} "
                    f"hit wait_for timeout {timeout_seconds:.2f}s{blocked_suffix}"
                )
            if timeout_seconds is not None:
                return (
                    f"Task {task.name} was cancelled after wait_for timeout "
                    f"{timeout_seconds:.2f}s{blocked_suffix}"
                )
        if task.cancellation_origin == "sibling_failure" and source_payload is not None:
            return (
                f"Task {task.name} was cancelled after sibling "
                f"{source_payload.get('task_name', source_payload['task_id'])} failed"
                f"{blocked_suffix}"
            )
        if task.cancellation_origin == "parent_task" and source_payload is not None:
            return (
                f"Task {task.name} was cancelled by parent "
                f"{source_payload.get('task_name', source_payload['task_id'])}"
                f"{blocked_suffix}"
            )
        if task.cancellation_origin == "external":
            return f"Task {task.name} was cancelled externally{blocked_suffix}"
        return f"Task {task.name} was cancelled{blocked_suffix}"

    def _matches_task_filters(
        self,
        task: dict[str, Any],
        *,
        state: str | None,
        role: str | None,
        reason: str | None,
        resource_id: str | None,
        q: str | None,
    ) -> bool:
        if state and task.get("state") != state:
            return False
        if role and task.get("metadata", {}).get("task_role") != role:
            return False
        if reason and task.get("reason") != reason:
            return False
        if resource_id and task.get("resource_id") != resource_id:
            return False
        if q:
            needle = q.lower()
            searchable = " ".join(
                str(value or "")
                for value in (
                    task.get("name"),
                    task.get("reason"),
                    task.get("resource_id"),
                )
            ).lower()
            if needle not in searchable:
                return False
        return True

    def _matches_timeline_filters(
        self,
        segment: TimelineSegment,
        *,
        state: str | None,
        reason: str | None,
        resource_id: str | None,
        task_id: int | None,
    ) -> bool:
        if state and segment.state != state:
            return False
        if reason and segment.reason != reason:
            return False
        if resource_id and segment.resource_id != resource_id:
            return False
        if task_id is not None and segment.task_id != task_id:
            return False
        return True

    def _matches_insight_filters(
        self,
        insight: dict[str, Any],
        *,
        kind: str | None,
        severity: str | None,
        task_id: int | None,
    ) -> bool:
        if kind and insight.get("kind") != kind:
            return False
        if severity and insight.get("severity") != severity:
            return False
        if task_id is not None and insight.get("task_id") != task_id:
            return False
        return True

    def _paginate(
        self,
        items: list[dict[str, Any]] | list[TimelineSegment],
        *,
        offset: int = 0,
        limit: int | None,
    ) -> Any:
        start = max(offset, 0)
        if limit is None:
            return items[start:]
        end = start + max(limit, 0)
        return items[start:end]

    def _compare_identity_payload(self) -> dict[str, Any]:
        snapshot = self.snapshot()["session"]
        return {
            "session_id": snapshot["session_id"],
            "session_name": snapshot["session_name"],
            "schema_version": snapshot["schema_version"],
        }

    def _task_state_counts(self, tasks: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for task in tasks:
            state = str(task["state"])
            counts[state] = counts.get(state, 0) + 1
        return counts

    def _task_reason_counts(self, tasks: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for task in tasks:
            reason = task.get("reason")
            if not reason:
                continue
            key = str(reason)
            counts[key] = counts.get(key, 0) + 1
        return counts

    def _compare_counts(
        self, baseline: dict[str, int], candidate: dict[str, int]
    ) -> dict[str, dict[str, int]]:
        added: dict[str, int] = {}
        removed: dict[str, int] = {}
        for key in sorted(set(baseline) | set(candidate)):
            diff = candidate.get(key, 0) - baseline.get(key, 0)
            if diff > 0:
                added[key] = diff
            elif diff < 0:
                removed[key] = abs(diff)
        return {"added": added, "removed": removed}

    def _added_sorted(
        self, baseline_items: list[str], candidate_items: list[str]
    ) -> list[str]:
        return sorted(set(candidate_items) - set(baseline_items))

    def _removed_sorted(
        self, baseline_items: list[str], candidate_items: list[str]
    ) -> list[str]:
        return sorted(set(baseline_items) - set(candidate_items))

    def _cancellation_chain_message(
        self,
        *,
        source_task_name: str,
        cancellation_origin: str,
        affected_tasks: list[TaskRecord],
    ) -> str:
        affected_names = ", ".join(
            task.name for task in sorted(affected_tasks, key=lambda item: item.task_id)
        )
        count = len(affected_tasks)
        if cancellation_origin == "sibling_failure":
            return (
                f"Task {source_task_name} triggered cancellation of {count} sibling "
                f"task{'s' if count != 1 else ''}: {affected_names}"
            )
        if cancellation_origin == "parent_task":
            return (
                f"Task {source_task_name} cancelled {count} child "
                f"task{'s' if count != 1 else ''}: {affected_names}"
            )
        if cancellation_origin == "timeout":
            timeout_seconds = self._cancellation_timeout_seconds(affected_tasks)
            timeout_suffix = (
                f" after wait_for timeout {timeout_seconds:.2f}s"
                if timeout_seconds is not None
                else ""
            )
            return (
                f"Task {source_task_name} cancelled {count} child "
                f"task{'s' if count != 1 else ''}{timeout_suffix}: {affected_names}"
            )
        return (
            f"Cancellation source {source_task_name} affected {count} task"
            f"{'s' if count != 1 else ''}: {affected_names}"
        )

    def _cancellation_timeout_seconds(
        self, tasks: list[TaskRecord]
    ) -> float | int | None:
        for task in tasks:
            timeout_seconds = task.metadata.get("timeout_seconds")
            if timeout_seconds is not None:
                return timeout_seconds
        return None

    def _blocked_suffix(self, task: TaskRecord) -> str:
        blocked_reason = task.metadata.get("blocked_reason")
        blocked_resource_id = task.metadata.get("blocked_resource_id")
        if blocked_reason is None:
            return ""
        if blocked_resource_id is not None:
            return f" while waiting on {blocked_reason} ({blocked_resource_id})"
        return f" while waiting on {blocked_reason}"

    def _fan_out_insights(self) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        for task in self._tasks.values():
            child_ids = sorted(task.children)
            if len(child_ids) < FAN_OUT_CHILDREN_THRESHOLD:
                continue
            findings.append(
                {
                    "kind": "fan_out_explosion",
                    "task_id": task.task_id,
                    "severity": "warning",
                    "message": (
                        f"Task {task.name} spawned {len(child_ids)} child tasks in one"
                        " scope"
                    ),
                    "reason": "high_child_fan_out",
                    "child_count": len(child_ids),
                    "child_task_ids": child_ids,
                }
            )
        return findings

    def _resource_contention_insights(self) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        blocked_by_resource: dict[str, list[TaskRecord]] = defaultdict(list)
        for task in self._tasks.values():
            if task.state != "BLOCKED" or task.resource_id is None:
                continue
            blocked_by_resource[task.resource_id].append(task)

        for resource_id, tasks in sorted(blocked_by_resource.items()):
            blocked_tasks = sorted(tasks, key=lambda item: item.task_id)
            if len(blocked_tasks) < RESOURCE_CONTENTION_THRESHOLD:
                continue
            kind = self._resource_insight_kind(blocked_tasks[0].reason, resource_id)
            if kind is None:
                continue
            findings.append(
                {
                    "kind": kind,
                    "task_id": blocked_tasks[0].task_id,
                    "severity": "warning",
                    "message": self._resource_contention_message(
                        kind=kind,
                        resource_id=resource_id,
                        tasks=blocked_tasks,
                    ),
                    "reason": blocked_tasks[0].reason,
                    "resource_id": resource_id,
                    "blocked_count": len(blocked_tasks),
                    "blocked_task_ids": [task.task_id for task in blocked_tasks],
                    "blocked_task_names": [task.name for task in blocked_tasks],
                }
            )
        return findings

    def _stalled_gather_insights(self) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        for segment in self.timeline():
            if segment.state != "BLOCKED" or segment.reason != "gather":
                continue
            duration_ms = max(
                0.0, (segment.end_ts_ns - segment.start_ts_ns) / 1_000_000
            )
            if duration_ms < GATHER_STALL_MS_THRESHOLD:
                continue
            parent = self._tasks.get(segment.task_id)
            if parent is None:
                continue
            children = [
                self._tasks[child_id]
                for child_id in sorted(parent.children)
                if child_id in self._tasks
            ]
            if not children:
                continue
            slow_child = max(
                children,
                key=lambda item: (
                    item.end_ts_ns if item.end_ts_ns is not None else item.updated_ts_ns
                ),
            )
            findings.append(
                {
                    "kind": "stalled_gather_group",
                    "task_id": parent.task_id,
                    "severity": "warning",
                    "message": (
                        f"Task {parent.name} stayed blocked on gather for "
                        f"{duration_ms:.1f} ms while waiting on {slow_child.name}"
                    ),
                    "reason": "gather_stall",
                    "duration_ms": duration_ms,
                    "slow_task_id": slow_child.task_id,
                    "slow_task_name": slow_child.name,
                    "child_task_ids": [child.task_id for child in children],
                }
            )
        return findings

    def _resource_insight_kind(
        self, reason: str | None, resource_id: str
    ) -> str | None:
        if reason == "queue_get" or resource_id.startswith("queue:"):
            return "queue_backpressure"
        if reason == "lock_acquire" or resource_id.startswith("lock:"):
            return "lock_contention"
        if reason == "semaphore_acquire" or resource_id.startswith("semaphore:"):
            return "semaphore_saturation"
        return None

    def _resource_contention_message(
        self, *, kind: str, resource_id: str, tasks: list[TaskRecord]
    ) -> str:
        task_names = ", ".join(task.name for task in tasks)
        count = len(tasks)
        if kind == "queue_backpressure":
            return (
                f"Queue {resource_id} is backing up with {count} waiting task"
                f"{'s' if count != 1 else ''}: {task_names}"
            )
        if kind == "lock_contention":
            return (
                f"Lock {resource_id} has {count} waiting task"
                f"{'s' if count != 1 else ''}: {task_names}"
            )
        return (
            f"Semaphore {resource_id} is saturated with {count} waiting task"
            f"{'s' if count != 1 else ''}: {task_names}"
        )

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
