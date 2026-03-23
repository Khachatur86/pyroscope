# Tasks

## In Progress

- Move the internal event model toward a more stable contract for replay, exports, and UI consumers.
- Improve cancellation analysis beyond the current TaskGroup and grouped-cascade heuristics.

## Recently Completed

- Fixed task ordering to sort by `created_ts_ns` instead of `task_id` (was non-deterministic).
- Moved `_INTERNAL_TASK_NAMES` to a module-level `frozenset` constant in `runtime.py`.
- Added `cancellation_origin` filter to `session.tasks()` and `/api/v1/tasks`.
- Added `asyncio.Condition.wait` tracing with `condition_wait` reason and `condition:<id>` resource.
- Added `asyncio.timeout()` (Python 3.11+) tracing: `task.block`/`task.unblock` with `reason=timeout_cm` and `timeout_seconds` metadata.
- Added `/api/v1/tasks/count` endpoint returning `total` and `by_state` buckets.
- Added `/api/v1/stacks` endpoint with `task_id` filter and pagination.
- Added `script_path`, `python_version`, `command_line` to session metadata (snapshot, save/load, headless summary, text output).
- Added `q` search parametrized fixture coverage (name, reason, resource_id, request_label, job_label).
- Added schema forward-compatibility test (unknown fields in envelope do not raise).
- Added `Script`, `Python`, `Command` lines to headless `summary` text output.
- Added `state_changes` and `hot_task_drift` to `compare_summary` and CLI compare output.
- Traced `asyncio.Barrier.wait` with `reason=barrier_wait`, `barrier:<id>` resource, and parties/n_waiting metadata.
- Traced `asyncio.shield()` — emit `task.shield` event and mark inner task with `shielded=True` metadata.
- Included `cancellation_cascade` in headless `_cancellation_insights` with chain/cascade prioritised over individual `task_cancelled`.
- Added task names (`owner_task_names`, `waiter_task_names`, `cancelled_waiter_task_names`) to detailed resource graph.
- Traced `asyncio.TaskGroup.__aenter__`/`__aexit__` as `taskgroup.enter`/`taskgroup.exit` events with `group_id` and `exit_status` metadata.
- Added `mixed_cause_cascade` insight for chains that start with timeout and fan out through sibling-failure.
- Added `label_resource(resource, name)` API on AsyncioTracer for user-supplied resource labels.
- Added `demo` scenarios for `timeout-contention` and `resource-contention`.
- Added flat JSONL export (`export_jsonl()`, `--format jsonl`) for downstream analysis tools.
- Added `--baseline` flag to `run` for automatic post-run drift comparison.
- Added `blocked_reason`/`blocked_resource_id` columns to CSV export.
- Added `tags` and `run_notes` to `SessionStore` for local incident comparison workflows.
- Added `pyroscope assert` command with `--no-error`, `--no-deadlock`, `--no-timeout-cancellation`, `--max-blocked N` predicates.
- Distinguished `timeout_cm` from `wait_for` timeout in cancellation_chain messages (says "asyncio.timeout()" instead of "wait_for").
- Added OTLP JSON span export (`export_otlp_json()`, `--format otlp-json`) for cross-tool inspection in Jaeger/Tempo.
- Fixed `parent_task_id` being cleared on task.end/cancel/fail events that don't carry a parent_task_id.
- Added `pyroscope watch` command with `--interval`, `--max-runs`, `--save-dir` for automated regression detection.
- Surfaced inline insight explanations (`explanation.what` / `explanation.how`) on all 12 insight kinds.

---

## Next Up

### Schema & Replay Contract

- Stabilize the event/session contract from the current MVP shape into a clearer replay-safe schema with explicit compatibility rules.
- Add replay contract tests for cross-session schema drift, including missing optional fields and future additive metadata, so `schema_version` bumps are regression-covered before they ship.
- Add forward/backward compatibility fixtures that cover: loading a capture written by an older schema version, loading a capture with unknown optional fields, and round-tripping through export+reload without data loss.

### Cancellation Analysis

- Deepen cancellation analysis so timeout, sibling-failure, parent-task, external, and mixed-cause cascades produce more precise summaries instead of relying on mostly heuristic grouping.
- Distinguish `asyncio.wait_for` timeout cancellation from `asyncio.timeout()` context-manager cancellation in `cancellation_origin` so the two paths produce separate insight kinds.

### Cancellation Analysis

- Deepen cancellation analysis so parent-task, external, and mixed-cause cascades produce even more precise summaries (timeout_cm/wait_for distinction now done; parent/external messaging could be improved further).

---

## Soon

### Testing

- Add an end-to-end test that exercises packaged static assets through the local server, so a missing `web_dist` build does not silently produce a broken UI at the packaged entry point.
- Introduce Vitest coverage for timeline hover, filter preset activation, and resource/cancellation panel coordination in the React UI so interaction paths beyond the initial render smoke test are covered.

### Resource Graph

- Add resource name aliasing so queue/lock/semaphore IDs derived from `id()` can be annotated with a user-supplied label (e.g. via a context var or naming convention) for readability in larger captures. *(label_resource() implemented in tracer; graph propagation done)*

---

## Later

### UI

- Add timeline zoom and windowing for longer captures so the canvas remains usable when sessions have thousands of segments.
- Add keyboard shortcuts for common debug actions (next task, previous insight, jump to selected task's timeline segment) so the UI is navigable without a mouse during live debugging sessions.
- Add an export button in the UI that triggers a JSON/CSV download of the current session so captures can be saved directly from the browser without using the CLI `export` command.
- Add a "why is this task blocked?" explainer panel that walks parent links, blocking reason, resource ownership, and cancellation history in one pane for the selected task.
- Add a timeline scrubber so the selected time range can be narrowed interactively and all panels (task list, insights, resource graph) filter to that window.

### Teaching Mode

- Add a lightweight "teaching mode" that overlays common asyncio patterns and explains why a queue, lock, semaphore, or gather shape looks suspicious, with links to the relevant asyncio documentation sections.
- Surface pattern explanations inline on insights so each insight kind includes a short "what this means" and "how to fix" hint instead of only the raw message string.

### Session & Capture

- Add capture diff fixtures for service-style workloads with multiple request labels and overlapping jobs.
- Add a `watch` mode for replay comparison so a saved baseline can be contrasted automatically against a newly captured run.

### Request/Job Views

- Add request-centric and job-centric dashboard views that collapse task noise into higher-level local service flows grouped by `request_label` and `job_label`.
- Add per-request and per-job timeline strips so the timeline panel can be switched from task-level to request-level granularity.

---

## Bugs / Technical Debt

- Runtime instrumentation is useful but still partial relative to full `asyncio` behavior, especially around `Condition`, `Barrier`, `shield`, and `TaskGroup` entry/exit semantics.
- The UI currently fetches the full snapshot eagerly on connect; larger captures will eventually need incremental loading and stronger server-side pagination usage.
- Built frontend assets are committed into `src/pyroscope/web_dist`, which is practical today but creates review noise and risks the committed assets diverging from `web/src`.
- There is still no end-to-end check that exercises packaged static assets through the local server.
- Headless summaries and UI drilldowns share concepts (hot tasks, cancellation insights, error tasks) but not a single presentation contract, which raises the risk of subtle output drift as either side evolves.
- The `q` search parameter is wired end-to-end but has no fixture coverage, no documented semantics, and no UI entry point.
- SSE subscriber queue capacity (512) is a hard-coded constant with no back-pressure signal to the UI; a slow client silently drops events rather than receiving an error.

---

## Future Ideas

- Add fixture minimization tooling that trims large captures into the smallest reproducible regression artifact.
- Add a `pyroscope attach` mode for already-running processes via monkey-patching over a pipe or Unix socket, keeping the local model as the source of truth.
- Add a structured log sink so `pyroscope run` can optionally emit NDJSON event logs alongside the in-memory session for post-mortem analysis of long-running services.
- Add a web-based capture browser for comparing multiple saved `.json` captures in one UI session without restarting the server.
