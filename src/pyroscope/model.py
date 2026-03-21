from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class Event:
    session_id: str
    seq: int
    ts_ns: int
    kind: str
    task_id: int | None = None
    task_name: str | None = None
    state: str | None = None
    reason: str | None = None
    resource_id: str | None = None
    parent_task_id: int | None = None
    cancelled_by_task_id: int | None = None
    cancellation_origin: str | None = None
    stack_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TaskRecord:
    task_id: int
    name: str
    parent_task_id: int | None
    children: list[int]
    state: str
    created_ts_ns: int
    updated_ts_ns: int
    cancelled_by_task_id: int | None = None
    cancellation_origin: str | None = None
    reason: str | None = None
    resource_id: str | None = None
    stack_id: str | None = None
    end_ts_ns: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TimelineSegment:
    task_id: int
    task_name: str
    start_ts_ns: int
    end_ts_ns: int
    state: str
    reason: str | None = None
    resource_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class StackSnapshot:
    stack_id: str
    task_id: int
    ts_ns: int
    frames: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
