from __future__ import annotations

import csv
import json
import queue
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import fields as _dataclass_fields
from pathlib import Path
from typing import IO, Any

from .model import Event, StackSnapshot, TaskRecord, TimelineSegment

# Known field names for each dataclass — used to strip unknown fields from
# future captures so forward-compatible loading never crashes on new fields.
_EVENT_FIELDS: frozenset[str] = frozenset(f.name for f in _dataclass_fields(Event))
_STACK_FIELDS: frozenset[str] = frozenset(
    f.name for f in _dataclass_fields(StackSnapshot)
)

TERMINAL_STATES = {"DONE", "FAILED", "CANCELLED"}
FAN_OUT_CHILDREN_THRESHOLD = 5
GATHER_STALL_MS_THRESHOLD = 100.0
RESOURCE_CONTENTION_THRESHOLD = 2
SESSION_SCHEMA_VERSION = "1.0"
LONG_BLOCK_MS_THRESHOLD = 250
HOT_TASKS_LIMIT = 3
ERROR_TASKS_LIMIT = 3


class SessionStore:
    def __init__(
        self,
        session_name: str,
        *,
        script_path: str | None = None,
        python_version: str | None = None,
        command_line: list[str] | None = None,
        tags: dict[str, str] | None = None,
        run_notes: str | None = None,
    ) -> None:
        self._schema_version = SESSION_SCHEMA_VERSION
        self.session_id = f"sess_{uuid.uuid4().hex[:12]}"
        self.session_name = session_name
        self.script_path = script_path
        self.python_version = python_version
        self.command_line = command_line
        self.tags = tags
        self.run_notes = run_notes
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
        self._log_sink_fh: IO[str] | None = None

    def next_seq(self) -> int:
        with self._lock:
            self._seq += 1
            return self._seq

    def open_log_sink(self, path: str | Path) -> None:
        """Open an NDJSON log sink; each appended event is written as one JSON line."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._log_sink_fh = target.open("w", encoding="utf-8")

    def close_log_sink(self) -> None:
        """Flush and close the NDJSON log sink if one is open."""
        if self._log_sink_fh is not None:
            self._log_sink_fh.flush()
            self._log_sink_fh.close()
            self._log_sink_fh = None

    def append_event(self, event: Event) -> None:
        with self._lock:
            self._events.append(event)
            self._apply_event(event)
            if self._log_sink_fh is not None:
                self._log_sink_fh.write(json.dumps(event.to_dict()) + "\n")
            payload = {"type": "event", "event": event.to_dict()}
            dead: list[queue.Queue[dict[str, Any]]] = []
            for sub in self._subscribers:
                try:
                    sub.put_nowait(payload)
                except queue.Full:
                    dead.append(sub)
            _error_frame: dict[str, Any] = {"type": "error", "code": "slow_client"}
            for sub in dead:
                try:
                    sub.get_nowait()
                except queue.Empty:
                    pass
                try:
                    sub.put_nowait(_error_frame)
                except queue.Full:
                    pass
                self._subscribers.remove(sub)

    def add_stack(self, snapshot: StackSnapshot) -> None:
        with self._lock:
            self._stacks[snapshot.stack_id] = snapshot
            payload = {"type": "stack", "stack": snapshot.to_dict()}
            dead: list[queue.Queue[dict[str, Any]]] = []
            for sub in self._subscribers:
                try:
                    sub.put_nowait(payload)
                except queue.Full:
                    dead.append(sub)
            _error_frame: dict[str, Any] = {"type": "error", "code": "slow_client"}
            for sub in dead:
                try:
                    sub.get_nowait()
                except queue.Empty:
                    pass
                try:
                    sub.put_nowait(_error_frame)
                except queue.Full:
                    pass
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
                    "script_path": self.script_path,
                    "python_version": self.python_version,
                    "command_line": self.command_line,
                    "tags": self.tags,
                    "run_notes": self.run_notes,
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
            "tasks": self.tasks(),
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
        cancellation_origin: str | None = None,
        request_label: str | None = None,
        job_label: str | None = None,
        q: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        with self._lock:
            tasks = []
            for task in self._tasks.values():
                payload = task.to_dict()
                payload["resource_roles"] = self._resource_roles_for(task.task_id)
                tasks.append(payload)
            filtered = [
                task
                for task in tasks
                if self._matches_task_filters(
                    task,
                    state=state,
                    role=role,
                    reason=reason,
                    resource_id=resource_id,
                    cancellation_origin=cancellation_origin,
                    request_label=request_label,
                    job_label=job_label,
                    q=q,
                )
            ]
            filtered.sort(key=lambda item: item["created_ts_ns"])
            return self._paginate(filtered, offset=offset, limit=limit)

    def task_counts(self) -> dict[str, Any]:
        with self._lock:
            by_state: dict[str, int] = {}
            for task in self._tasks.values():
                by_state[task.state] = by_state.get(task.state, 0) + 1
            return {"total": len(self._tasks), "by_state": by_state}

    def stacks(
        self,
        *,
        task_id: int | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        with self._lock:
            result = [
                snap.to_dict()
                for snap in self._stacks.values()
                if task_id is None or snap.task_id == task_id
            ]
            result.sort(key=lambda s: (s["ts_ns"], s["stack_id"]))
            return self._paginate(result, offset=offset, limit=limit)

    def task(self, task_id: int) -> dict[str, Any] | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            payload = task.to_dict()
            payload["resource_roles"] = self._resource_roles_for(task.task_id)
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
        detailed: bool = False,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        with self._lock:
            cancelled_waiters_by_resource: dict[str, set[int]] = defaultdict(set)
            if detailed:
                for task in self._tasks.values():
                    blocked_resource_id = task.metadata.get("blocked_resource_id")
                    if task.state == "CANCELLED" and blocked_resource_id:
                        cancelled_waiters_by_resource[str(blocked_resource_id)].add(
                            task.task_id
                        )
            graph = []
            resource_ids = set(self._resource_edges)
            if detailed:
                resource_ids.update(cancelled_waiters_by_resource)
            for current_resource_id in sorted(resource_ids):
                task_ids = self._resource_edges.get(current_resource_id, set())
                cancelled_waiter_ids = cancelled_waiters_by_resource.get(
                    current_resource_id, set()
                )
                owner_task_ids = {
                    task_id
                    for task_id in task_ids
                    if self._resource_owner_for(task_id, current_resource_id)
                }
                owner_task_ids.update(
                    self._resource_owner_ids_from_metadata(current_resource_id)
                )
                waiter_task_ids = {
                    task_id
                    for task_id in task_ids
                    if self._resource_waiter_for(task_id, current_resource_id)
                }
                all_task_ids = set(task_ids) | set(cancelled_waiter_ids)
                if resource_id is not None and current_resource_id != resource_id:
                    continue
                if task_id is not None and task_id not in all_task_ids:
                    continue
                row: dict[str, Any] = {
                    "resource_id": current_resource_id,
                    "task_ids": sorted(task_ids),
                }
                # Attach user-supplied label if any task recorded one
                for tid in sorted(all_task_ids):
                    t = self._tasks.get(tid)
                    if t is not None:
                        label = t.metadata.get("resource_label")
                        if label is not None:
                            row["resource_label"] = label
                            break
                if detailed:
                    sorted_owners = sorted(owner_task_ids)
                    sorted_waiters = sorted(waiter_task_ids)
                    sorted_cancelled = sorted(cancelled_waiter_ids)
                    row["owner_task_ids"] = sorted_owners
                    row["waiter_task_ids"] = sorted_waiters
                    row["cancelled_waiter_task_ids"] = sorted_cancelled
                    row["owner_task_names"] = [
                        self._tasks[tid].name
                        for tid in sorted_owners
                        if tid in self._tasks
                    ]
                    row["waiter_task_names"] = [
                        self._tasks[tid].name
                        for tid in sorted_waiters
                        if tid in self._tasks
                    ]
                    row["cancelled_waiter_task_names"] = [
                        self._tasks[tid].name
                        for tid in sorted_cancelled
                        if tid in self._tasks
                    ]
                graph.append(row)
            return self._paginate(graph, offset=offset, limit=limit)

    def _resource_owner_for(self, task_id: int, resource_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task is None:
            return False
        return task.resource_id == resource_id and not self._resource_waiter_for(
            task_id, resource_id
        )

    def _resource_waiter_for(self, task_id: int, resource_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task is None:
            return False
        blocked_resource_id = task.metadata.get("blocked_resource_id")
        if blocked_resource_id is not None:
            return str(blocked_resource_id) == resource_id
        return task.state == "BLOCKED" and task.resource_id == resource_id

    def _resource_owner_ids_from_metadata(self, resource_id: str) -> set[int]:
        owner_task_ids: set[int] = set()
        for task in self._tasks.values():
            blocked_resource_id = task.metadata.get("blocked_resource_id")
            task_blocks_resource = (
                blocked_resource_id is not None
                and str(blocked_resource_id) == resource_id
            ) or (task.state == "BLOCKED" and task.resource_id == resource_id)
            if not task_blocks_resource:
                continue
            raw_owner_ids = task.metadata.get("owner_task_ids", [])
            if isinstance(raw_owner_ids, list):
                owner_task_ids.update(
                    owner_id for owner_id in raw_owner_ids if isinstance(owner_id, int)
                )
        return owner_task_ids

    def _resource_roles_for(self, task_id: int) -> list[str]:
        roles: list[str] = []
        for resource_id, task_ids in self._resource_edges.items():
            if task_id not in task_ids:
                continue
            if self._resource_owner_for(task_id, resource_id):
                roles.append("owner")
            if self._resource_waiter_for(task_id, resource_id):
                roles.append("waiter")
        task = self._tasks.get(task_id)
        if (
            task is not None
            and task.state == "CANCELLED"
            and task.metadata.get("blocked_resource_id") is not None
        ):
            roles.append("cancelled waiter")
        return [r for r in ("owner", "waiter", "cancelled waiter") if r in roles]

    def _cancelled_waiter_ids_for_resource(self, resource_id: str) -> list[int]:
        return sorted(
            task.task_id
            for task in self._tasks.values()
            if task.state == "CANCELLED"
            and str(task.metadata.get("blocked_resource_id", "")) == resource_id
        )

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
                if task.state == "BLOCKED" and age_ms > LONG_BLOCK_MS_THRESHOLD:
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
                            **self._wait_state_metadata(task),
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
                            source_task_state=(
                                source_task.state if source_task is not None else None
                            ),
                        ),
                        "reason": cancellation_origin,
                        "source_task_id": source_task_id,
                        "source_task_name": source_task_name,
                        "source_task_state": (
                            source_task.state if source_task is not None else None
                        ),
                        "source_task_reason": (
                            source_task.reason if source_task is not None else None
                        ),
                        "source_task_error": (
                            source_task.metadata.get("error")
                            if source_task is not None
                            else None
                        ),
                        "affected_task_ids": sorted(task.task_id for task in tasks),
                        "affected_task_names": [
                            task.name
                            for task in sorted(tasks, key=lambda item: item.task_id)
                        ],
                        "parent_task_id": parent_task_id,
                        "timeout_seconds": self._cancellation_timeout_seconds(tasks),
                        **self._shared_blocked_metadata(tasks),
                        **self._shared_wait_state_metadata(tasks),
                    }
                )
            for parent_task_id, tasks in cancelled_by_parent.items():
                if len(tasks) < 2:
                    continue
                parent_rec = self._tasks.get(parent_task_id)
                parent_name = (
                    parent_rec.name
                    if parent_rec is not None
                    else f"task-{parent_task_id}"
                )
                parent_state = parent_rec.state if parent_rec is not None else None
                parent_reason = parent_rec.reason if parent_rec is not None else None
                affected_sorted = sorted(tasks, key=lambda t: t.task_id)
                findings.append(
                    {
                        "kind": "cancellation_cascade",
                        "task_id": parent_task_id,
                        "severity": "warning",
                        "message": self._cancellation_cascade_message(
                            parent_name, parent_state, len(tasks)
                        ),
                        "reason": "taskgroup_or_parent_shutdown",
                        "parent_task_name": parent_name,
                        "parent_task_state": parent_state,
                        "parent_task_reason": parent_reason,
                        "affected_task_ids": [t.task_id for t in affected_sorted],
                        "affected_task_names": [t.name for t in affected_sorted],
                    }
                )
            # Mixed-cause cascade: same source task appears in both a timeout chain
            # and a sibling_failure chain — a timeout triggered sibling cancellations.
            source_by_origin: dict[int, dict[str, set[int]]] = defaultdict(
                lambda: defaultdict(set)
            )
            for (
                source_task_id,
                cancellation_origin,
                _parent_task_id,
            ), tasks in cancelled_by_source.items():
                source_by_origin[source_task_id][cancellation_origin].update(
                    task.task_id for task in tasks
                )
            for source_task_id, origin_map in sorted(source_by_origin.items()):
                timeout_origin = (
                    "timeout"
                    if "timeout" in origin_map
                    else ("timeout_cm" if "timeout_cm" in origin_map else None)
                )
                if timeout_origin is not None and "sibling_failure" in origin_map:
                    source_task = self._tasks.get(source_task_id)
                    source_name = (
                        source_task.name
                        if source_task is not None
                        else f"task-{source_task_id}"
                    )
                    timeout_ids = sorted(origin_map[timeout_origin])
                    sibling_ids = sorted(origin_map["sibling_failure"])
                    timeout_seconds = None
                    for tid in timeout_ids:
                        t = self._tasks.get(tid)
                        if t is not None:
                            timeout_seconds = t.metadata.get("timeout_seconds")
                            if timeout_seconds is not None:
                                break
                    ts_suffix = (
                        f" after {timeout_seconds:.2f}s timeout"
                        if timeout_seconds is not None
                        else ""
                    )
                    findings.append(
                        {
                            "kind": "mixed_cause_cascade",
                            "task_id": source_task_id,
                            "severity": "warning",
                            "message": (
                                f"Task {source_name} timed out{ts_suffix} and triggered "
                                f"sibling cancellation of {len(sibling_ids)} task"
                                f"{'s' if len(sibling_ids) != 1 else ''}"
                            ),
                            "reason": "timeout_then_sibling_failure",
                            "source_task_id": source_task_id,
                            "source_task_name": source_name,
                            "timeout_task_ids": timeout_ids,
                            "sibling_task_ids": sibling_ids,
                            "timeout_seconds": timeout_seconds,
                        }
                    )
            findings.extend(self._timeout_taskgroup_cascade_insights())
            findings.extend(self._deadlock_insights())
            findings.extend(self._resource_contention_insights())
            findings.extend(self._fan_out_insights())
            findings.extend(self._stalled_gather_insights())
        # Dedup: suppress cancellation_cascade when timeout_taskgroup_cascade already
        # covers the same parent task (the latter is more specific).
        tg_cascade_parents: frozenset[int] = frozenset(
            f["task_id"]
            for f in findings
            if f.get("kind") == "timeout_taskgroup_cascade"
            and f.get("task_id") is not None
        )
        if tg_cascade_parents:
            findings = [
                f
                for f in findings
                if not (
                    f.get("kind") == "cancellation_cascade"
                    and f.get("task_id") in tg_cascade_parents
                )
            ]
        for finding in findings:
            finding["explanation"] = self._insight_explanation(
                str(finding.get("kind", ""))
            )
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

    def capture_dict(self) -> dict[str, Any]:
        """Return the full capture payload as a dict (same structure as save_json)."""
        return {
            "schema_version": self._schema_version,
            "snapshot": self.snapshot(),
            "events": self.events(),
            "stacks": [stack.to_dict() for stack in self._stacks.values()],
            "resources": self.resource_graph(),
        }

    def capture_csv_bytes(self) -> bytes:
        """Return the timeline CSV as UTF-8 bytes (same columns as export_csv)."""
        import io

        task_block_context: dict[int, dict[str, Any]] = {}
        for task in self.tasks():
            meta = task.get("metadata", {})
            blocked_reason = meta.get("blocked_reason")
            blocked_resource_id = meta.get("blocked_resource_id")
            if blocked_reason is not None or blocked_resource_id is not None:
                task_block_context[int(task["task_id"])] = {
                    "blocked_reason": blocked_reason,
                    "blocked_resource_id": blocked_resource_id,
                }
        buf = io.StringIO()
        writer = csv.DictWriter(
            buf,
            fieldnames=[
                "task_id",
                "task_name",
                "start_ts_ns",
                "end_ts_ns",
                "state",
                "reason",
                "resource_id",
                "blocked_reason",
                "blocked_resource_id",
            ],
        )
        writer.writeheader()
        for segment in self.timeline():
            row = segment.to_dict()
            ctx = task_block_context.get(int(row["task_id"]), {})
            row["blocked_reason"] = ctx.get("blocked_reason", "")
            row["blocked_resource_id"] = ctx.get("blocked_resource_id", "")
            writer.writerow(row)
        return buf.getvalue().encode("utf-8")

    def save_json(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.capture_dict(), indent=2))
        return target

    def minimize_dict(self) -> dict[str, Any]:
        """Return the minimized capture as a dict (in-memory, no file I/O)."""
        relevant_ids = self._insight_task_ids()
        return {
            "schema_version": self._schema_version,
            "snapshot": self.snapshot(),
            "events": [e.to_dict() for e in self._events if e.task_id in relevant_ids],
            "stacks": [
                s.to_dict() for s in self._stacks.values() if s.task_id in relevant_ids
            ],
            "resources": self.resource_graph(),
        }

    def minimize(self, path: str | Path) -> Path:
        """Write a minimized capture retaining only events for insight-referenced tasks."""
        relevant_ids = self._insight_task_ids()
        filtered_events = [
            e.to_dict() for e in self._events if e.task_id in relevant_ids
        ]
        filtered_stacks = [
            s.to_dict() for s in self._stacks.values() if s.task_id in relevant_ids
        ]
        payload = {
            "schema_version": self._schema_version,
            "snapshot": self.snapshot(),
            "events": filtered_events,
            "stacks": filtered_stacks,
            "resources": self.resource_graph(),
        }
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=2))
        return target

    def _insight_task_ids(self) -> set[int]:
        """Collect all task IDs referenced by any insight."""
        ids: set[int] = set()
        for insight in self.insights():
            for key in (
                "task_id",
                "source_task_id",
                "group_task_id",
                "parent_task_id",
                "resource_task_id",
            ):
                val = insight.get(key)
                if isinstance(val, int):
                    ids.add(val)
            for key in (
                "affected_task_ids",
                "cancelled_task_ids",
                "cycle_task_ids",
                "timeout_task_ids",
                "sibling_task_ids",
                "owner_task_ids",
                "waiter_task_ids",
            ):
                lst = insight.get(key)
                if isinstance(lst, list):
                    ids.update(x for x in lst if isinstance(x, int))
        return ids

    def export_csv(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        task_block_context: dict[int, dict[str, Any]] = {}
        for task in self.tasks():
            meta = task.get("metadata", {})
            blocked_reason = meta.get("blocked_reason")
            blocked_resource_id = meta.get("blocked_resource_id")
            if blocked_reason is not None or blocked_resource_id is not None:
                task_block_context[int(task["task_id"])] = {
                    "blocked_reason": blocked_reason,
                    "blocked_resource_id": blocked_resource_id,
                }
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
                    "blocked_reason",
                    "blocked_resource_id",
                ],
            )
            writer.writeheader()
            for segment in self.timeline():
                row = segment.to_dict()
                ctx = task_block_context.get(int(row["task_id"]), {})
                row["blocked_reason"] = ctx.get("blocked_reason", "")
                row["blocked_resource_id"] = ctx.get("blocked_resource_id", "")
                writer.writerow(row)
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

    def export_jsonl(self, path: str | Path) -> Path:
        """Export all task records as newline-delimited JSON (one object per line).

        Each line contains a flat task record with all fields from the task dict
        plus flattened resource-wait context from metadata so the output is
        consumable by pandas, jq, or DuckDB without parsing the full envelope.
        """
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        lines: list[str] = []
        for task in self.tasks():
            meta = task.get("metadata", {})
            record: dict[str, Any] = {
                "task_id": task["task_id"],
                "name": task["name"],
                "state": task["state"],
                "parent_task_id": task.get("parent_task_id"),
                "created_ts_ns": task.get("created_ts_ns"),
                "end_ts_ns": task.get("end_ts_ns"),
                "duration_ms": (
                    round((task["end_ts_ns"] - task["created_ts_ns"]) / 1_000_000, 3)
                    if task.get("end_ts_ns") and task.get("created_ts_ns")
                    else None
                ),
                "reason": task.get("reason"),
                "resource_id": task.get("resource_id"),
                "cancellation_origin": task.get("cancellation_origin"),
                "cancelled_by_task_id": task.get("cancelled_by_task_id"),
                "error": meta.get("error"),
                "request_label": meta.get("request_label"),
                "job_label": meta.get("job_label"),
                "blocked_reason": meta.get("blocked_reason"),
                "blocked_resource_id": meta.get("blocked_resource_id"),
                "timeout_seconds": meta.get("timeout_seconds"),
                "shielded": meta.get("shielded"),
            }
            lines.append(json.dumps(record, default=str))
        target.write_text("\n".join(lines) + "\n" if lines else "")
        return target

    def export_otlp_json(self, path: str | Path) -> Path:
        """Export tasks as OTLP-compatible JSON spans for cross-tool inspection."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Build a stable 16-hex trace_id from the session_id
        trace_id = self.session_id.replace("sess_", "").ljust(32, "0")[:32]
        spans: list[dict[str, Any]] = []
        for task in self.tasks():
            task_id = int(task["task_id"])
            parent_task_id = task.get("parent_task_id")
            meta = task.get("metadata", {})
            state = str(task["state"])
            span_id = format(task_id & 0xFFFFFFFFFFFFFFFF, "016x")
            parent_span_id = (
                format(int(parent_task_id) & 0xFFFFFFFFFFFFFFFF, "016x")
                if parent_task_id is not None
                else None
            )
            start_ns = task.get("created_ts_ns") or 0
            end_ns = task.get("end_ts_ns") or self.completed_ts_ns or start_ns
            if state == "FAILED":
                status = {
                    "code": "STATUS_CODE_ERROR",
                    "message": str(meta.get("error", "")),
                }
            elif state in TERMINAL_STATES:
                status = {"code": "STATUS_CODE_OK"}
            else:
                status = {"code": "STATUS_CODE_UNSET"}
            attributes: list[dict[str, Any]] = [
                {"key": "pyroscope.task.state", "value": {"stringValue": state}},
            ]
            if task.get("reason"):
                attributes.append(
                    {
                        "key": "pyroscope.task.reason",
                        "value": {"stringValue": str(task["reason"])},
                    }
                )
            if meta.get("error"):
                attributes.append(
                    {
                        "key": "error.message",
                        "value": {"stringValue": str(meta["error"])},
                    }
                )
            if meta.get("request_label"):
                attributes.append(
                    {
                        "key": "pyroscope.request_label",
                        "value": {"stringValue": str(meta["request_label"])},
                    }
                )
            if meta.get("job_label"):
                attributes.append(
                    {
                        "key": "pyroscope.job_label",
                        "value": {"stringValue": str(meta["job_label"])},
                    }
                )
            span: dict[str, Any] = {
                "traceId": trace_id,
                "spanId": span_id,
                "name": str(task["name"]),
                "startTimeUnixNano": start_ns,
                "endTimeUnixNano": end_ns,
                "status": status,
                "attributes": attributes,
            }
            if parent_span_id is not None:
                span["parentSpanId"] = parent_span_id
            spans.append(span)
        payload: dict[str, Any] = {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            {
                                "key": "service.name",
                                "value": {"stringValue": self.session_name},
                            },
                        ]
                    },
                    "scopeSpans": [
                        {
                            "scope": {"name": "pyroscope"},
                            "spans": spans,
                        }
                    ],
                }
            ]
        }
        target.write_text(json.dumps(payload, indent=2))
        return target

    def compare_summary(self, other: SessionStore) -> dict[str, Any]:
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
            "hot_tasks": {
                "baseline": self._hot_tasks(baseline_tasks),
                "candidate": self._hot_tasks(candidate_tasks),
            },
            "request_labels": self._compare_label_counts(
                baseline_tasks, candidate_tasks, "request_label"
            ),
            "job_labels": self._compare_label_counts(
                baseline_tasks, candidate_tasks, "job_label"
            ),
            "error_tasks": {
                "baseline": self._error_tasks(baseline_tasks),
                "candidate": other._error_tasks(candidate_tasks),
            },
            "error_drift": self._compare_error_tasks(
                self._error_tasks(baseline_tasks),
                other._error_tasks(candidate_tasks),
            ),
            "cancellation_insights": {
                "baseline": self._cancellation_insights(baseline_insights),
                "candidate": other._cancellation_insights(candidate_insights),
            },
            "cancellation_drift": self._compare_cancellation_insights(
                self._cancellation_insights(baseline_insights),
                other._cancellation_insights(candidate_insights),
            ),
            "state_changes": self._state_changes(baseline_tasks, candidate_tasks),
            "hot_task_drift": self._compare_hot_tasks(
                self._hot_tasks(baseline_tasks),
                self._hot_tasks(candidate_tasks),
            ),
        }

    def headless_summary(self) -> dict[str, Any]:
        tasks = self.tasks()
        resources = self.resource_graph()
        insights = self.insights()
        resource_rows = sorted(
            (
                {
                    "resource_id": resource["resource_id"],
                    "task_count": len(resource["task_ids"]),
                }
                for resource in resources
            ),
            key=lambda item: (-item["task_count"], item["resource_id"]),
        )
        return {
            "session": self._compare_identity_payload(),
            "counts": {
                "tasks": len(tasks),
                "resources": len(resources),
                "insights": len(insights),
                "segments": len(self.timeline()),
            },
            "states": dict(sorted(self._task_state_counts(tasks).items())),
            "insights": dict(sorted(self._insight_kind_counts(insights).items())),
            "top_resources": resource_rows[:5],
            "hot_tasks": self._hot_tasks(tasks),
            "request_labels": self._label_counts(tasks, "request_label"),
            "job_labels": self._label_counts(tasks, "job_label"),
            "error_tasks": self._error_tasks(tasks),
            "cancellation_insights": self._cancellation_insights(insights),
        }

    @classmethod
    def from_capture(cls, data: dict[str, Any]) -> SessionStore:
        session_name = (
            data.get("snapshot", {}).get("session", {}).get("session_name", "replay")
        )
        store = cls(session_name=session_name)
        snapshot = data.get("snapshot", {})
        snapshot_session = snapshot.get("session", {})
        schema_version = snapshot_session.get(
            "schema_version", data.get("schema_version", SESSION_SCHEMA_VERSION)
        )
        store.session_id = snapshot_session.get("session_id", store.session_id)
        store.session_name = snapshot_session.get("session_name", store.session_name)
        store.script_path = snapshot_session.get("script_path")
        store.python_version = snapshot_session.get("python_version")
        store.command_line = snapshot_session.get("command_line")
        store.tags = snapshot_session.get("tags") or None
        store.run_notes = snapshot_session.get("run_notes") or None
        store.started_ts_ns = snapshot_session.get("started_ts_ns", store.started_ts_ns)
        store._schema_version = schema_version
        raw_events = data.get("events", [])
        for raw_event in raw_events:
            event = Event(**{k: v for k, v in raw_event.items() if k in _EVENT_FIELDS})
            store._seq = max(store._seq, event.seq)
            store._events.append(event)
            store._apply_event(event)
        for raw_stack in data.get("stacks", []):
            stack = StackSnapshot(
                **{k: v for k, v in raw_stack.items() if k in _STACK_FIELDS}
            )
            store._stacks[stack.stack_id] = stack
        if not raw_events and snapshot.get("tasks"):
            store._hydrate_from_snapshot(snapshot)
        store.completed_ts_ns = snapshot_session.get("completed_ts_ns")
        if store.completed_ts_ns is not None:
            store._close_open_segments(store.completed_ts_ns)
        return store

    def replace_with(self, other: SessionStore) -> None:
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

    def _hydrate_from_snapshot(self, snapshot: dict[str, Any]) -> None:
        for raw_task in snapshot.get("tasks", []):
            task = TaskRecord(
                task_id=raw_task["task_id"],
                name=raw_task.get("name") or f"task-{raw_task['task_id']}",
                parent_task_id=raw_task.get("parent_task_id"),
                children=list(raw_task.get("children", [])),
                state=raw_task.get("state", "READY"),
                created_ts_ns=raw_task.get("created_ts_ns", self.started_ts_ns),
                updated_ts_ns=raw_task.get(
                    "updated_ts_ns", raw_task.get("created_ts_ns", self.started_ts_ns)
                ),
                cancelled_by_task_id=raw_task.get("cancelled_by_task_id"),
                cancellation_origin=raw_task.get("cancellation_origin"),
                reason=raw_task.get("reason"),
                resource_id=raw_task.get("resource_id"),
                stack_id=raw_task.get("stack_id"),
                end_ts_ns=raw_task.get("end_ts_ns"),
                metadata=dict(raw_task.get("metadata", {})),
            )
            self._tasks[task.task_id] = task

        for task in list(self._tasks.values()):
            if task.parent_task_id is not None:
                self._sync_parent_child_link(task.task_id, task.parent_task_id)
            if task.resource_id:
                self._resource_edges[task.resource_id].add(task.task_id)
            blocked_resource_id = task.metadata.get("blocked_resource_id")
            if blocked_resource_id:
                self._resource_edges[blocked_resource_id].add(task.task_id)

        self._segments = [
            TimelineSegment(
                task_id=raw_segment["task_id"],
                task_name=self._snapshot_segment_task_name(raw_segment),
                start_ts_ns=raw_segment["start_ts_ns"],
                end_ts_ns=raw_segment["end_ts_ns"],
                state=raw_segment.get("state", "READY"),
                reason=raw_segment.get("reason"),
                resource_id=raw_segment.get("resource_id"),
            )
            for raw_segment in snapshot.get("segments", [])
        ]

    def _snapshot_segment_task_name(self, raw_segment: dict[str, Any]) -> str:
        if raw_segment.get("task_name"):
            return str(raw_segment["task_name"])
        task_id = raw_segment["task_id"]
        task = self._tasks.get(task_id)
        if task is not None:
            return task.name
        return f"task-{task_id}"

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

        if event.kind == "task.shield":
            shielded_id = event.metadata.get("shielded_task_id")
            if shielded_id is not None:
                shielded = self._tasks.get(shielded_id)
                if shielded is not None:
                    shielded.metadata["shielded"] = True
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
        if (
            event.parent_task_id is not None
            and event.parent_task_id != task.parent_task_id
        ):
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
        wait_state_suffix = self._wait_state_suffix(task)
        context_suffix = f"{blocked_suffix}{wait_state_suffix}"
        if task.cancellation_origin == "timeout":
            timeout_seconds = task.metadata.get("timeout_seconds")
            if source_payload is not None and timeout_seconds is not None:
                return (
                    f"Task {task.name} was cancelled after "
                    f"{source_payload.get('task_name', source_payload['task_id'])} "
                    f"hit wait_for timeout {timeout_seconds:.2f}s{context_suffix}"
                )
            if timeout_seconds is not None:
                return (
                    f"Task {task.name} was cancelled after wait_for timeout "
                    f"{timeout_seconds:.2f}s{context_suffix}"
                )
        if task.cancellation_origin == "timeout_cm":
            timeout_seconds = task.metadata.get("timeout_seconds")
            if timeout_seconds is not None:
                return (
                    f"Task {task.name} was cancelled by asyncio.timeout() "
                    f"after {timeout_seconds:.2f}s{context_suffix}"
                )
            return (
                f"Task {task.name} was cancelled by asyncio.timeout(){context_suffix}"
            )
        if task.cancellation_origin == "sibling_failure" and source_payload is not None:
            return (
                f"Task {task.name} was cancelled after sibling "
                f"{source_payload.get('task_name', source_payload['task_id'])} failed"
                f"{context_suffix}"
            )
        if task.cancellation_origin == "parent_task" and source_payload is not None:
            parent_name = source_payload.get("task_name", source_payload["task_id"])
            parent_state = source_payload.get("state")
            if parent_state == "CANCELLED":
                return (
                    f"Task {task.name} was cancelled because parent task "
                    f"{parent_name} was also cancelled{context_suffix}"
                )
            if parent_state == "FAILED":
                return (
                    f"Task {task.name} was cancelled after parent task "
                    f"{parent_name} failed{context_suffix}"
                )
            return (
                f"Task {task.name} was cancelled by parent "
                f"{parent_name}{context_suffix}"
            )
        if task.cancellation_origin == "external":
            return f"Task {task.name} was cancelled externally{context_suffix}"
        return f"Task {task.name} was cancelled{context_suffix}"

    def _matches_task_filters(
        self,
        task: dict[str, Any],
        *,
        state: str | None,
        role: str | None,
        reason: str | None,
        resource_id: str | None,
        cancellation_origin: str | None,
        request_label: str | None,
        job_label: str | None,
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
        if (
            cancellation_origin
            and task.get("cancellation_origin") != cancellation_origin
        ):
            return False
        if (
            request_label
            and task.get("metadata", {}).get("request_label") != request_label
        ):
            return False
        if job_label and task.get("metadata", {}).get("job_label") != job_label:
            return False
        if q:
            needle = q.lower()
            searchable = " ".join(
                str(value or "")
                for value in (
                    task.get("name"),
                    task.get("reason"),
                    task.get("resource_id"),
                    task.get("metadata", {}).get("request_label"),
                    task.get("metadata", {}).get("job_label"),
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
        return task_id is None or segment.task_id == task_id

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
        return task_id is None or insight.get("task_id") == task_id

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
            "script_path": snapshot.get("script_path"),
            "python_version": snapshot.get("python_version"),
            "command_line": snapshot.get("command_line"),
            "tags": snapshot.get("tags"),
            "run_notes": snapshot.get("run_notes"),
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

    def _insight_kind_counts(self, insights: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for insight in insights:
            kind = str(insight["kind"])
            counts[kind] = counts.get(kind, 0) + 1
        return counts

    def _hot_tasks(self, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        interesting_states = {"BLOCKED", "FAILED", "CANCELLED"}
        seen_resources: set[str] = set()
        hot_tasks: list[dict[str, Any]] = []
        for task in sorted(tasks, key=lambda item: item["task_id"]):
            if task["state"] not in interesting_states:
                continue
            resource_id = task.get("resource_id")
            if resource_id and resource_id in seen_resources:
                continue
            if resource_id:
                seen_resources.add(str(resource_id))
            hot_tasks.append(
                {
                    "task_id": task["task_id"],
                    "name": task["name"],
                    "state": task["state"],
                    "reason": task.get("reason"),
                    "resource_id": resource_id,
                }
            )
            if len(hot_tasks) == HOT_TASKS_LIMIT:
                break
        return hot_tasks

    def _label_counts(
        self, tasks: list[dict[str, Any]], key: str
    ) -> list[dict[str, Any]]:
        counts: dict[str, int] = {}
        for task in tasks:
            label = task.get("metadata", {}).get(key)
            if not label:
                continue
            label_key = str(label)
            counts[label_key] = counts.get(label_key, 0) + 1
        return [
            {"label": label, "task_count": task_count}
            for label, task_count in sorted(
                counts.items(), key=lambda item: (-item[1], item[0])
            )
        ]

    def _compare_label_counts(
        self,
        baseline_tasks: list[dict[str, Any]],
        candidate_tasks: list[dict[str, Any]],
        key: str,
    ) -> dict[str, dict[str, int]]:
        baseline = {
            item["label"]: item["task_count"]
            for item in self._label_counts(baseline_tasks, key)
        }
        candidate = {
            item["label"]: item["task_count"]
            for item in self._label_counts(candidate_tasks, key)
        }
        return self._compare_counts(baseline, candidate)

    def _error_tasks(self, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        error_tasks: list[dict[str, Any]] = []
        for task in sorted(tasks, key=lambda item: item["task_id"]):
            if task["state"] != "FAILED":
                continue
            record = self._tasks.get(task["task_id"])
            stack_preview = None
            stack_frames: list[str] = []
            if record is not None and record.stack_id:
                stack = self._stacks.get(record.stack_id)
                if stack is not None and stack.frames:
                    stack_frames = stack.frames[-3:]
                    stack_preview = stack.frames[-1]
            error_tasks.append(
                {
                    "task_id": task["task_id"],
                    "name": task["name"],
                    "reason": task.get("reason"),
                    "error": task.get("metadata", {}).get("error"),
                    "stack_preview": stack_preview,
                    "stack_frames": stack_frames,
                }
            )
            if len(error_tasks) == ERROR_TASKS_LIMIT:
                break
        return error_tasks

    def _cancellation_insights(
        self, insights: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        allowed = {
            "task_cancelled",
            "cancellation_chain",
            "cancellation_cascade",
            "mixed_cause_cascade",
            "timeout_taskgroup_cascade",
        }
        summary_kinds = {
            "cancellation_chain",
            "cancellation_cascade",
            "mixed_cause_cascade",
            "timeout_taskgroup_cascade",
        }
        # summary-level insights (chain/cascade) rank before individual task_cancelled
        ordered = sorted(
            (i for i in insights if i["kind"] in allowed),
            key=lambda i: (0 if i["kind"] in summary_kinds else 1),
        )
        return [
            {
                "kind": insight["kind"],
                "reason": insight.get("reason") or insight.get("cancellation_origin"),
                "message": insight["message"],
            }
            for insight in ordered[:3]
        ]

    def _compare_error_tasks(
        self,
        baseline_items: list[dict[str, Any]],
        candidate_items: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        def key(item: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
            return (
                item.get("name"),
                item.get("reason"),
                item.get("error"),
            )

        baseline_by_key = {key(item): item for item in baseline_items}
        candidate_by_key = {key(item): item for item in candidate_items}
        return {
            "added": [
                candidate_by_key[item_key]
                for item_key in sorted(set(candidate_by_key) - set(baseline_by_key))
            ],
            "removed": [
                baseline_by_key[item_key]
                for item_key in sorted(set(baseline_by_key) - set(candidate_by_key))
            ],
        }

    def _compare_cancellation_insights(
        self,
        baseline_items: list[dict[str, Any]],
        candidate_items: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        def key(item: dict[str, Any]) -> tuple[str | None, str | None, str]:
            return (
                item.get("kind"),
                item.get("reason"),
                str(item.get("message", "")),
            )

        baseline_by_key = {key(item): item for item in baseline_items}
        candidate_by_key = {key(item): item for item in candidate_items}
        return {
            "added": [
                candidate_by_key[item_key]
                for item_key in sorted(set(candidate_by_key) - set(baseline_by_key))
            ],
            "removed": [
                baseline_by_key[item_key]
                for item_key in sorted(set(baseline_by_key) - set(candidate_by_key))
            ],
        }

    def _state_changes(
        self,
        baseline_tasks: list[dict[str, Any]],
        candidate_tasks: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        baseline_by_name = {task["name"]: task["state"] for task in baseline_tasks}
        candidate_by_name = {task["name"]: task["state"] for task in candidate_tasks}
        changes: list[dict[str, Any]] = []
        for name in sorted(set(baseline_by_name) & set(candidate_by_name)):
            b_state = baseline_by_name[name]
            c_state = candidate_by_name[name]
            if b_state != c_state:
                changes.append(
                    {
                        "name": name,
                        "baseline_state": b_state,
                        "candidate_state": c_state,
                    }
                )
        return changes

    def _compare_hot_tasks(
        self,
        baseline_hot: list[dict[str, Any]],
        candidate_hot: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        baseline_names = {item["name"] for item in baseline_hot}
        candidate_names = {item["name"] for item in candidate_hot}
        return {
            "added": [
                item for item in candidate_hot if item["name"] not in baseline_names
            ],
            "removed": [
                item for item in baseline_hot if item["name"] not in candidate_names
            ],
        }

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
        source_task_state: str | None = None,
    ) -> str:
        affected_names = ", ".join(
            task.name for task in sorted(affected_tasks, key=lambda item: item.task_id)
        )
        count = len(affected_tasks)
        blocked_suffix = self._shared_blocked_suffix(affected_tasks)
        wait_state_suffix = self._shared_wait_state_suffix(affected_tasks)
        context_suffix = f"{blocked_suffix}{wait_state_suffix}"
        if cancellation_origin == "sibling_failure":
            return (
                f"Task {source_task_name} triggered cancellation of {count} sibling "
                f"task{'s' if count != 1 else ''}{context_suffix}: {affected_names}"
            )
        if cancellation_origin == "parent_task":
            if source_task_state == "CANCELLED":
                intro = f"Task {source_task_name} was cancelled and propagated cancellation to"
            elif source_task_state == "FAILED":
                intro = f"Task {source_task_name} failed and cancelled"
            else:
                intro = f"Task {source_task_name} cancelled"
            return (
                f"{intro} {count} child "
                f"task{'s' if count != 1 else ''}{context_suffix}: {affected_names}"
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
                f"task{'s' if count != 1 else ''}{timeout_suffix}{context_suffix}: "
                f"{affected_names}"
            )
        if cancellation_origin == "timeout_cm":
            timeout_seconds = self._cancellation_timeout_seconds(affected_tasks)
            timeout_suffix = (
                f" after asyncio.timeout() {timeout_seconds:.2f}s"
                if timeout_seconds is not None
                else " via asyncio.timeout()"
            )
            return (
                f"Task {source_task_name} cancelled {count} child "
                f"task{'s' if count != 1 else ''}{timeout_suffix}{context_suffix}: "
                f"{affected_names}"
            )
        return (
            f"Cancellation source {source_task_name} affected {count} task"
            f"{'s' if count != 1 else ''}{context_suffix}: {affected_names}"
        )

    def _cancellation_cascade_message(
        self, parent_name: str, parent_state: str | None, count: int
    ) -> str:
        plural = f"task{'s' if count != 1 else ''}"
        if parent_state == "CANCELLED":
            return (
                f"Task {parent_name} was cancelled and propagated cancellation "
                f"to {count} child {plural}"
            )
        if parent_state == "FAILED":
            return f"Task {parent_name} failed and cancelled {count} child {plural}"
        return f"Task {parent_name} cancelled {count} child {plural}"

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

    def _wait_state_metadata(self, task: TaskRecord) -> dict[str, Any]:
        metadata: dict[str, Any] = {}
        for key in ("queue_size", "queue_maxsize", "event_is_set"):
            if key in task.metadata:
                metadata[key] = task.metadata[key]
        return metadata

    def _wait_state_suffix(self, task: TaskRecord) -> str:
        parts: list[str] = []
        queue_size = task.metadata.get("queue_size")
        queue_maxsize = task.metadata.get("queue_maxsize")
        event_is_set = task.metadata.get("event_is_set")
        if queue_size is not None and queue_maxsize is not None:
            parts.append(f"queue {queue_size}/{queue_maxsize}")
        elif queue_size is not None:
            parts.append(f"queue {queue_size}")
        elif queue_maxsize is not None:
            parts.append(f"queue max {queue_maxsize}")
        if event_is_set is not None:
            parts.append(f"event set={'yes' if event_is_set else 'no'}")
        if not parts:
            return ""
        return f" with {' · '.join(parts)}"

    def _shared_wait_state_metadata(self, tasks: list[TaskRecord]) -> dict[str, Any]:
        shared: dict[str, Any] = {}
        for key in ("queue_size", "queue_maxsize", "event_is_set"):
            values = {task.metadata.get(key) for task in tasks if key in task.metadata}
            if len(values) == 1:
                shared[key] = next(iter(values))
        return shared

    def _shared_blocked_metadata(self, tasks: list[TaskRecord]) -> dict[str, Any]:
        shared: dict[str, Any] = {}
        blocked_reasons = {
            task.metadata.get("blocked_reason")
            for task in tasks
            if task.metadata.get("blocked_reason") is not None
        }
        if len(blocked_reasons) == 1:
            shared["blocked_reason"] = next(iter(blocked_reasons))

        blocked_resources = {
            task.metadata.get("blocked_resource_id")
            for task in tasks
            if task.metadata.get("blocked_resource_id") is not None
        }
        if len(blocked_resources) == 1:
            shared["blocked_resource_id"] = next(iter(blocked_resources))
        return shared

    def _shared_blocked_suffix(self, tasks: list[TaskRecord]) -> str:
        shared = self._shared_blocked_metadata(tasks)
        blocked_reason = shared.get("blocked_reason")
        blocked_resource_id = shared.get("blocked_resource_id")
        if blocked_reason is None:
            return ""
        if blocked_resource_id is not None:
            return f" while waiting on {blocked_reason} ({blocked_resource_id})"
        return f" while waiting on {blocked_reason}"

    def _shared_wait_state_suffix(self, tasks: list[TaskRecord]) -> str:
        shared = self._shared_wait_state_metadata(tasks)
        parts: list[str] = []
        queue_size = shared.get("queue_size")
        queue_maxsize = shared.get("queue_maxsize")
        event_is_set = shared.get("event_is_set")
        if queue_size is not None and queue_maxsize is not None:
            parts.append(f"queue {queue_size}/{queue_maxsize}")
        elif queue_size is not None:
            parts.append(f"queue {queue_size}")
        elif queue_maxsize is not None:
            parts.append(f"queue max {queue_maxsize}")
        if event_is_set is not None:
            parts.append(f"event set={'yes' if event_is_set else 'no'}")
        if not parts:
            return ""
        return f" with {' · '.join(parts)}"

    def _timeout_taskgroup_cascade_insights(self) -> list[dict[str, Any]]:
        """Emit timeout_taskgroup_cascade when a TaskGroup exits cancelled due to a timeout."""
        _TIMEOUT_ORIGINS: frozenset[str] = frozenset({"timeout", "timeout_cm"})
        findings: list[dict[str, Any]] = []
        for event in self._events:
            if event.kind != "taskgroup.exit":
                continue
            if event.metadata.get("exit_status") != "cancelled":
                continue
            if event.task_id is None:
                continue
            task = self._tasks.get(event.task_id)
            if task is None:
                continue
            origin = task.cancellation_origin or ""
            if origin not in _TIMEOUT_ORIGINS:
                continue
            # Collect children cancelled as a result
            cancelled_children = [
                t
                for t in self._tasks.values()
                if t.cancelled_by_task_id == event.task_id and t.state == "CANCELLED"
            ]
            if not cancelled_children:
                continue
            sorted_children = sorted(cancelled_children, key=lambda t: t.task_id)
            timeout_seconds: float | None = task.metadata.get("timeout_seconds")
            ts_suffix = (
                f" after {timeout_seconds:.2f}s timeout"
                if timeout_seconds is not None
                else ""
            )
            findings.append(
                {
                    "kind": "timeout_taskgroup_cascade",
                    "severity": "error",
                    "task_id": event.task_id,
                    "group_task_id": event.task_id,
                    "group_task_name": task.name,
                    "message": (
                        f"TaskGroup on '{task.name}' cancelled {len(sorted_children)} "
                        f"task{'s' if len(sorted_children) != 1 else ''}{ts_suffix}"
                    ),
                    "timeout_seconds": timeout_seconds,
                    "cancellation_origin": origin,
                    "cancelled_task_ids": [t.task_id for t in sorted_children],
                    "cancelled_task_names": [t.name for t in sorted_children],
                }
            )
        return findings

    def _deadlock_insights(self) -> list[dict[str, Any]]:
        """Detect cycles in the waits-for graph among BLOCKED tasks."""
        # Build waits_for: task_id -> frozenset of owner task IDs it is waiting for
        waits_for: dict[int, frozenset[int]] = {}
        for task in self._tasks.values():
            if task.state != "BLOCKED" or task.resource_id is None:
                continue
            owner_ids: set[int] = set()
            raw = task.metadata.get("owner_task_ids", [])
            if isinstance(raw, list):
                owner_ids.update(x for x in raw if isinstance(x, int))
            owner_ids.update(self._resource_owner_ids_from_metadata(task.resource_id))
            for other in self._tasks.values():
                if self._resource_owner_for(other.task_id, task.resource_id):
                    owner_ids.add(other.task_id)
            owner_ids.discard(task.task_id)
            if owner_ids:
                waits_for[task.task_id] = frozenset(owner_ids)

        if not waits_for:
            return []

        findings: list[dict[str, Any]] = []
        seen_cycle_sets: set[frozenset[int]] = set()

        def _dfs(start: int, current: int, path: list[int], on_path: set[int]) -> None:
            for neighbor in waits_for.get(current, frozenset()):
                if neighbor == start and len(path) >= 2:
                    cycle_set = frozenset(path)
                    if cycle_set not in seen_cycle_sets:
                        seen_cycle_sets.add(cycle_set)
                        names = [self._tasks[t].name for t in path if t in self._tasks]
                        cycle_str = " → ".join(names + names[:1])
                        findings.append(
                            {
                                "kind": "deadlock",
                                "severity": "error",
                                "task_id": path[0],
                                "cycle_task_ids": list(path),
                                "cycle_task_names": names,
                                "message": f"Deadlock: {cycle_str}",
                            }
                        )
                elif neighbor not in on_path:
                    on_path.add(neighbor)
                    _dfs(start, neighbor, path + [neighbor], on_path)
                    on_path.discard(neighbor)

        for task_id in waits_for:
            _dfs(task_id, task_id, [task_id], {task_id})

        return findings

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
            owner_task_ids = self._resource_owner_ids_for_insight(
                resource_id, blocked_tasks
            )
            owner_task_names = self._task_names(owner_task_ids)
            cancelled_waiter_task_ids = self._cancelled_waiter_ids_for_resource(
                resource_id
            )
            resource_label: str | None = None
            for bt in blocked_tasks:
                lbl = bt.metadata.get("resource_label")
                if lbl is not None:
                    resource_label = str(lbl)
                    break
            entry: dict[str, Any] = {
                "kind": kind,
                "task_id": blocked_tasks[0].task_id,
                "severity": "warning",
                "message": self._resource_contention_message(
                    kind=kind,
                    resource_id=resource_id,
                    tasks=blocked_tasks,
                    owner_task_names=owner_task_names,
                ),
                "reason": blocked_tasks[0].reason,
                "resource_id": resource_id,
                "blocked_count": len(blocked_tasks),
                "owner_count": len(owner_task_ids),
                "waiter_count": len(blocked_tasks),
                "cancelled_waiter_count": len(cancelled_waiter_task_ids),
                "blocked_task_ids": [task.task_id for task in blocked_tasks],
                "blocked_task_names": [task.name for task in blocked_tasks],
                "owner_task_ids": owner_task_ids,
                "owner_task_names": owner_task_names,
                "cancelled_waiter_task_ids": cancelled_waiter_task_ids,
            }
            if resource_label is not None:
                entry["resource_label"] = resource_label
            findings.append(entry)
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
        self,
        *,
        kind: str,
        resource_id: str,
        tasks: list[TaskRecord],
        owner_task_names: list[str],
    ) -> str:
        task_names = ", ".join(task.name for task in tasks)
        count = len(tasks)
        if kind == "queue_backpressure":
            return (
                f"Queue {resource_id} is backing up with {count} waiting task"
                f"{'s' if count != 1 else ''}: {task_names}"
            )
        if kind == "lock_contention":
            owner_suffix = self._resource_owner_suffix(owner_task_names)
            return (
                f"Lock {resource_id} has {count} waiting task"
                f"{'s' if count != 1 else ''}{owner_suffix}: {task_names}"
            )
        owner_suffix = self._resource_owner_suffix(owner_task_names)
        return (
            f"Semaphore {resource_id} is saturated with {count} waiting task"
            f"{'s' if count != 1 else ''}{owner_suffix}: {task_names}"
        )

    def _insight_explanation(self, kind: str) -> dict[str, str]:
        _EXPLANATIONS: dict[str, dict[str, str]] = {
            "task_error": {
                "what": "A task raised an unhandled exception and terminated in the FAILED state.",
                "how": "Inspect the error message and stack_frames. Wrap the task body in try/except or use a TaskGroup so the exception propagates cleanly to the parent.",
            },
            "task_cancelled": {
                "what": "A task was cancelled before it could complete, either by a timeout, parent task, sibling failure, or external request.",
                "how": "Check cancellation_origin to identify the source. If unexpected, verify that timeouts are appropriate and that parent tasks handle child cancellation.",
            },
            "cancellation_chain": {
                "what": "One task triggered the cancellation of one or more other tasks — a linear cancellation path from a single source.",
                "how": "Trace back to the source task. If this is a timeout, increase the deadline or reduce work. If sibling failure, add error isolation so one failing task does not cancel unrelated siblings.",
            },
            "cancellation_cascade": {
                "what": "A parent task cancelled multiple child tasks simultaneously, producing a fan-out of cancellations.",
                "how": "Check whether the parent task had a valid reason to cancel. If the children should be independent, restructure with asyncio.gather(return_exceptions=True) or TaskGroup with error isolation.",
            },
            "mixed_cause_cascade": {
                "what": "The same source task both timed out and triggered sibling-failure cancellations — a compound cascade with two distinct causes.",
                "how": "Separate the two failure paths. Handle the timeout first (raise or propagate), then isolate siblings from each other to prevent cascading cancellation.",
            },
            "timeout_taskgroup_cascade": {
                "what": "An asyncio.TaskGroup was cancelled because the enclosing timeout fired, which propagated cancellation to all child tasks in the group.",
                "how": "Increase the timeout deadline, reduce the work each child task performs, or restructure so only the slow subtasks are guarded by a timeout while others can complete independently.",
            },
            "deadlock": {
                "what": "Two or more tasks are waiting on each other in a circular chain, so none of them can ever make progress.",
                "how": "Break the cycle by releasing one resource before acquiring another, use asyncio.wait_for to add a timeout, or redesign the dependency order to be acyclic.",
            },
            "long_block": {
                "what": "A task has been in the BLOCKED state for an unusually long time, suggesting a slow dependency, deadlock, or resource starvation.",
                "how": "Identify the resource being waited on. Check for deadlocks (circular waits), slow producers, or under-provisioned workers. Consider adding a timeout with asyncio.wait_for.",
            },
            "task_leak": {
                "what": "A task is still running after the session completed, indicating it was not properly awaited or cancelled.",
                "how": "Ensure all created tasks are either awaited or cancelled before the event loop exits. Use asyncio.TaskGroup or track tasks manually and cancel them in cleanup.",
            },
            "fan_out_explosion": {
                "what": "A single task spawned an unusually large number of children, which may overwhelm the event loop or exhaust resources.",
                "how": "Use a semaphore or worker pool to limit concurrency. Replace unbounded fan-out with asyncio.Semaphore or asyncio.Queue-based worker patterns.",
            },
            "stalled_gather_group": {
                "what": "An asyncio.gather group appears to be stalled — one or more tasks are blocking the group from completing.",
                "how": "Identify the slowest task in the group. Add per-task timeouts with asyncio.wait_for, or break the gather into smaller groups to isolate stalls.",
            },
            "queue_backpressure": {
                "what": "Multiple tasks are waiting on the same queue, indicating the queue is full or producers are faster than consumers.",
                "how": "Add more consumer workers, increase queue capacity, or apply backpressure on the producer side. Consider asyncio.Queue.put_nowait with overflow handling.",
            },
            "lock_contention": {
                "what": "Multiple tasks are competing for the same asyncio.Lock, serializing work that could otherwise be parallel.",
                "how": "Reduce the critical section held under the lock, use asyncio.Semaphore for bounded concurrency instead of exclusive access, or redesign to avoid shared mutable state.",
            },
            "semaphore_saturation": {
                "what": "An asyncio.Semaphore is at capacity with tasks queued waiting to acquire it.",
                "how": "Increase the semaphore count if resources allow, or reduce the amount of work each holder performs to release the semaphore sooner.",
            },
        }
        return _EXPLANATIONS.get(
            kind,
            {
                "what": f"An insight of kind '{kind}' was detected.",
                "how": "Review the insight message and affected tasks for more context.",
            },
        )

    def _resource_owner_ids_for_insight(
        self, resource_id: str, blocked_tasks: list[TaskRecord]
    ) -> list[int]:
        owner_task_ids = self._resource_owner_ids_from_metadata(resource_id)
        for task in blocked_tasks:
            raw_owner_ids = task.metadata.get("owner_task_ids", [])
            if isinstance(raw_owner_ids, list):
                owner_task_ids.update(
                    owner_id for owner_id in raw_owner_ids if isinstance(owner_id, int)
                )
        owner_task_ids.update(
            task_id
            for task_id in self._resource_edges.get(resource_id, set())
            if self._resource_owner_for(task_id, resource_id)
        )
        return sorted(owner_task_ids)

    def _task_names(self, task_ids: list[int]) -> list[str]:
        task_names: list[str] = []
        for task_id in task_ids:
            task = self._tasks.get(task_id)
            task_names.append(task.name if task is not None else f"task-{task_id}")
        return task_names

    def _resource_owner_suffix(self, owner_task_names: list[str]) -> str:
        if not owner_task_names:
            return ""
        return f" held by {', '.join(owner_task_names)}"

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
