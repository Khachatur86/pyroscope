# Pyroscope Event Model Contract — v1.0

`SESSION_SCHEMA_VERSION = "1.0"` (defined in `session.py`)

This document is the stable serialization contract for captures produced by
`SessionStore.capture_dict()` / `store.save_json()` and consumed by
`SessionStore.from_capture()`, the CLI `replay` command, and the UI.

Downstream consumers (replay, export, UI, fixture minimization, NDJSON sink)
**must** rely only on the fields listed here as **required**. Optional fields
may be absent in older captures; `from_capture()` is required to tolerate
their absence without raising.

---

## Top-level capture envelope

```json
{
  "schema_version": "1.0",
  "snapshot": { ... },
  "events":   [ ... ],
  "stacks":   [ ... ],
  "resources": [ ... ]
}
```

| Field            | Type   | Required | Description |
|------------------|--------|----------|-------------|
| `schema_version` | string | yes      | Always `"1.0"` for this contract version |
| `snapshot`       | object | yes      | Point-in-time derived state (tasks, segments, insights) |
| `events`         | array  | yes      | Ordered raw events as recorded by the tracer |
| `stacks`         | array  | yes      | Stack snapshots indexed by `stack_id` |
| `resources`      | array  | yes      | Resource ownership graph rows |

---

## snapshot

```json
{
  "session": { ... },
  "tasks":    [ ... ],
  "segments": [ ... ],
  "insights": [ ... ]
}
```

### snapshot.session

| Field              | Type           | Required | Description |
|--------------------|----------------|----------|-------------|
| `schema_version`   | string         | yes      | Same as top-level |
| `session_id`       | string         | yes      | Unique session identifier (`sess_<hex>`) |
| `session_name`     | string         | yes      | Human-readable name (script basename or arg) |
| `started_ts_ns`    | int            | yes      | Unix epoch nanoseconds when session was created |
| `completed_ts_ns`  | int \| null    | yes      | Nanosecond timestamp when `mark_completed()` was called; null if still live |
| `event_count`      | int            | yes      | Total events recorded |
| `task_count`       | int            | yes      | Total tasks recorded |
| `script_path`      | string \| null | yes      | Absolute path of the traced script |
| `python_version`   | string \| null | yes      | Python version string (e.g. `"3.12.0"`) |
| `command_line`     | list \| null   | yes      | `sys.argv` at time of run |
| `tags`             | object \| null | yes      | User-supplied key-value tags |
| `run_notes`        | string \| null | yes      | Free-form annotation set by caller |

---

## Event

Each element of `events[]` is the serialized form of `model.Event`.

| Field                  | Type           | Required | Description |
|------------------------|----------------|----------|-------------|
| `session_id`           | string         | yes      | Parent session identifier |
| `seq`                  | int            | yes      | Monotonically increasing event sequence number |
| `ts_ns`                | int            | yes      | Event timestamp in nanoseconds |
| `kind`                 | string         | yes      | Event kind (see [Event kinds](#event-kinds)) |
| `task_id`              | int \| null    | no       | ID of the task this event pertains to |
| `task_name`            | string \| null | no       | Name of the task at event time |
| `state`                | string \| null | no       | Task state after this event |
| `reason`               | string \| null | no       | Block/unblock reason (e.g. `lock_acquire`, `sleep`) |
| `resource_id`          | string \| null | no       | Resource identifier (e.g. `lock:0x7f...`, `queue:jobs`) |
| `parent_task_id`       | int \| null    | no       | Parent task ID for `task.create` events |
| `cancelled_by_task_id` | int \| null    | no       | ID of task that triggered cancellation |
| `cancellation_origin`  | string \| null | no       | `"parent_task"`, `"timeout"`, or `"external"` |
| `stack_id`             | string \| null | no       | References a `StackSnapshot.stack_id` |
| `metadata`             | object         | no       | Arbitrary key-value payload; defaults to `{}` |

### Event kinds

| Kind | Description |
|------|-------------|
| `task.create` | Task object created |
| `task.start` | Task entered RUNNING state |
| `task.block` | Task entered BLOCKED state |
| `task.unblock` | Task left BLOCKED state |
| `task.end` | Task reached DONE state |
| `task.cancel` | Task reached CANCELLED state |
| `task.fail` | Task reached FAILED state |
| `task.shield` | Task wrapped with `asyncio.shield()` |
| `taskgroup.enter` | `TaskGroup.__aenter__` called |
| `taskgroup.exit` | `TaskGroup.__aexit__` called |

---

## TaskRecord

Each element of `snapshot.tasks[]` is the serialized form of `model.TaskRecord`.

| Field                  | Type           | Required | Description |
|------------------------|----------------|----------|-------------|
| `task_id`              | int            | yes      | Unique task identifier |
| `name`                 | string         | yes      | Task name |
| `parent_task_id`       | int \| null    | yes      | ID of parent task; null for root tasks |
| `children`             | list[int]      | yes      | IDs of child tasks |
| `state`                | string         | yes      | Terminal or current state |
| `created_ts_ns`        | int            | yes      | Nanosecond creation timestamp |
| `updated_ts_ns`        | int            | yes      | Nanosecond timestamp of last state change |
| `metadata`             | object         | yes      | Arbitrary key-value payload |
| `cancelled_by_task_id` | int \| null    | no       | ID of cancelling task |
| `cancellation_origin`  | string \| null | no       | Origin of cancellation |
| `reason`               | string \| null | no       | Block reason at last block event |
| `resource_id`          | string \| null | no       | Resource ID at last block event |
| `stack_id`             | string \| null | no       | Most recent stack snapshot ID |
| `end_ts_ns`            | int \| null    | no       | Nanosecond completion timestamp |

### Task states

`READY` → `RUNNING` → `BLOCKED` ↔ `RUNNING` → `DONE` | `FAILED` | `CANCELLED`

---

## TimelineSegment

Each element of `snapshot.segments[]` is the serialized form of `model.TimelineSegment`.

| Field          | Type           | Required | Description |
|----------------|----------------|----------|-------------|
| `task_id`      | int            | yes      | Task this segment belongs to |
| `task_name`    | string         | yes      | Task name at segment creation |
| `start_ts_ns`  | int            | yes      | Segment start in nanoseconds |
| `end_ts_ns`    | int            | yes      | Segment end in nanoseconds |
| `state`        | string         | yes      | State during this segment |
| `reason`       | string \| null | no       | Block reason (only for BLOCKED segments) |
| `resource_id`  | string \| null | no       | Resource ID (only for BLOCKED segments) |

---

## StackSnapshot

Each element of `stacks[]` is the serialized form of `model.StackSnapshot`.

| Field      | Type      | Required | Description |
|------------|-----------|----------|-------------|
| `stack_id` | string    | yes      | Unique snapshot identifier |
| `task_id`  | int       | yes      | Task that produced this snapshot |
| `ts_ns`    | int       | yes      | Nanosecond timestamp of capture |
| `frames`   | list[str] | yes      | Ordered stack frames (innermost last) |

---

## Invariants

- `from_capture()` **must not raise** on any capture with `schema_version = "1.0"`.
- `from_capture()` **must not raise** on captures with unknown top-level keys (forward-compat).
- Unknown fields inside `Event` or `StackSnapshot` objects are silently stripped via `_EVENT_FIELDS` / `_STACK_FIELDS` guards.
- `insights()` always includes an `explanation` field (`what` + `how`) on every insight object.
- `cancellation_cascade` payloads always include `parent_task_name` and `affected_task_names`.
- `deadlock` payloads always include `cycle_task_ids` (list of int) and `cycle_task_names` (list of str).
- `timeout_taskgroup_cascade` payloads always include `group_task_id` (int), `group_task_name` (str), `cancelled_task_ids` (list of int), and `timeout_seconds` (float | null).
- When a `timeout_taskgroup_cascade` insight is present for a given parent task, any `cancellation_cascade` insight for the same parent task is suppressed (deduplication).
- All timestamps are nanoseconds since Unix epoch (Python `time.time_ns()`).

---

## Versioning

Bump `SESSION_SCHEMA_VERSION` when **adding a required field** to Event or TaskRecord. Optional
fields can be added without a version bump as long as `from_capture()` tolerates their absence.

Compatibility fixtures live in `tests/fixtures/` as `replay_schema_*.json`.
