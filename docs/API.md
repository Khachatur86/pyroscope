# Pyroscope HTTP API

Base URL: `http://127.0.0.1:7070`

All responses are JSON unless stated otherwise.

---

## GET /api/v1/session

Returns the full session snapshot: session metadata, all tasks, timeline segments, and insights.

**Response fields:**
- `session` — session metadata (name, id, schema_version, python_version, script_path, etc.)
- `tasks` — array of task objects
- `segments` — array of timeline segments
- `insights` — array of insight objects

---

## GET /api/v1/tasks

Returns a filtered, paginated list of tasks.

**Query parameters:**

| Parameter            | Type   | Description |
|----------------------|--------|-------------|
| `state`              | string | Filter by task state: `READY`, `RUNNING`, `BLOCKED`, `DONE`, `FAILED`, `CANCELLED` |
| `role`               | string | Filter by `metadata.task_role` |
| `reason`             | string | Filter by block reason (e.g. `sleep`, `lock_acquire`, `queue_get`) |
| `resource_id`        | string | Filter by the resource the task is currently waiting on |
| `cancellation_origin`| string | Filter by cancellation origin |
| `request_label`      | string | Filter by `metadata.request_label` |
| `job_label`          | string | Filter by `metadata.job_label` |
| `q`                  | string | Full-text search across multiple fields (see below) |
| `limit`              | int    | Maximum number of results to return |
| `offset`             | int    | Number of results to skip (default: 0) |

### The `q` parameter

`q` is a case-insensitive substring search applied across the following task fields simultaneously:

| Field | Location |
|-------|----------|
| `name` | task name |
| `reason` | block reason |
| `resource_id` | resource the task is waiting on |
| `request_label` | `metadata.request_label` |
| `job_label` | `metadata.job_label` |

All five values are concatenated into a single searchable string and the `q` value is checked for containment. A task matches if `q` is a substring of any of those fields.

**Examples:**

```
GET /api/v1/tasks?q=worker
# Returns tasks whose name, reason, or labels contain "worker"

GET /api/v1/tasks?q=lock
# Returns tasks blocked on a lock resource or whose reason contains "lock"

GET /api/v1/tasks?q=GET+/users
# Returns tasks carrying request_label "GET /users"

GET /api/v1/tasks?q=auth-service
# Matches tasks with that substring in name, resource_id, or any label
```

`q` can be combined with other filters. All filters are ANDed together:

```
GET /api/v1/tasks?state=BLOCKED&q=lock
# Tasks that are currently BLOCKED and match "lock" in any searchable field
```

---

## GET /api/v1/tasks/count

Returns total task count and breakdown by state.

**Response:**
```json
{
  "total": 12,
  "by_state": {
    "RUNNING": 3,
    "BLOCKED": 5,
    "DONE": 4
  }
}
```

---

## GET /api/v1/tasks/{task_id}

Returns a single task by numeric ID. Includes `cancellation_source`, `resource_roles`, and `stack` (if available).

Returns `404` if the task does not exist.

---

## GET /api/v1/tasks/{task_id}/children

Returns all tasks whose `parent_task_id` matches `task_id`.

---

## GET /api/v1/timeline

Returns timeline segments, optionally filtered.

**Query parameters:** `state`, `reason`, `resource_id`, `task_id`, `limit`, `offset`

---

## GET /api/v1/insights

Returns insights (analysis results), optionally filtered.

**Query parameters:**

| Parameter | Type   | Description |
|-----------|--------|-------------|
| `kind`    | string | Filter by insight kind (see table below) |
| `severity`| string | Filter by severity: `error`, `warning`, `info` |
| `task_id` | int    | Filter to insights involving a specific task |
| `limit`   | int    | Maximum results |
| `offset`  | int    | Skip N results |

**Insight kinds:**

| Kind | Severity | Description |
|------|----------|-------------|
| `task_error` | error | A task raised an unhandled exception |
| `task_cancelled` | info | A task was cancelled |
| `cancellation_chain` | info/warning | One task triggered cancellation of one or more others |
| `cancellation_cascade` | warning | A parent task cancelled multiple children simultaneously |
| `mixed_cause_cascade` | warning | A source task both timed out and triggered sibling cancellations |
| `timeout_taskgroup_cascade` | error | A `TaskGroup` was cancelled because the enclosing timeout fired |
| `deadlock` | error | Two or more tasks form a circular wait cycle |
| `long_block` | warning | A task has been BLOCKED for an unusually long time |
| `task_leak` | warning | A task is still running after the session completed |
| `fan_out_explosion` | warning | A single task spawned an unusually large number of children |
| `stalled_gather_group` | warning | An `asyncio.gather` group appears stalled |
| `queue_backpressure` | warning | Multiple tasks are waiting on the same queue |
| `lock_contention` | warning | Multiple tasks are competing for the same `asyncio.Lock` |
| `semaphore_saturation` | warning | An `asyncio.Semaphore` is at capacity |

---

## GET /api/v1/resources/graph

Returns the resource ownership/wait graph.

**Query parameters:** `resource_id`, `task_id`, `detail` (`detailed` for full owner/waiter names), `limit`, `offset`

---

## GET /api/v1/stacks

Returns stack snapshots.

**Query parameters:** `task_id`, `limit`, `offset`

---

## GET /api/v1/summary

Returns a headless summary: hot tasks, error tasks, cancellation insights, and session metadata. Used by CLI `summary` command and the UI `/api/v1/summary` widget.

---

## GET /api/v1/export

Downloads the session as a file.

**Query parameters:**

| Parameter | Values | Description |
|-----------|--------|-------------|
| `format`  | `json` (default), `csv`, `minimized` | Download format. `minimized` returns a smaller JSON capture retaining only events for tasks referenced by at least one insight. |

---

## GET /api/v1/stream

Server-Sent Events stream. Emits `data:` frames on every new event or stack snapshot.

**Frame types:**
- `{"type": "snapshot"}` — initial frame sent on connect, signals client to fetch `/api/v1/session`
- `{"type": "event", "event": {...}}` — new runtime event recorded
- `{"type": "stack", "stack": {...}}` — new stack snapshot recorded
- `{"type": "error", "code": "slow_client"}` — subscriber queue was full; server closes the stream. The client should reload or reconnect.

The stream emits `: keep-alive` comments every second when idle.

---

## POST /api/v1/replay/load

Replaces the live session with a capture loaded from a JSON body. Used by `pyroscope replay`.

**Request body:** a capture JSON object (as produced by `pyroscope export --format json`).

**Response:** `{"ok": true, "session_id": "sess_..."}`
