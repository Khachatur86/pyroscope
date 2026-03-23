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

---

## Next Up

### Runtime

- Trace `asyncio.TaskGroup` entry/exit so sibling-failure cancellation inside a TaskGroup produces a first-class group event rather than relying on individual task.cancel heuristics.
- Trace `asyncio.timeout()` context manager (Python 3.11+) as an alternative to `wait_for` so timeout-driven cancellations are attributed correctly when code uses the newer API.
- Trace `asyncio.shield()` so shielded sub-tasks that survive outer cancellation are marked distinctly instead of appearing as unrelated orphan tasks.
- Trace `asyncio.Barrier` (Python 3.11+) to capture coordinated group wait patterns that currently produce no resource-graph signal.

### Schema & Replay Contract

- Stabilize the event/session contract from the current MVP shape into a clearer replay-safe schema with explicit compatibility rules.
- Add replay contract tests for cross-session schema drift, including missing optional fields and future additive metadata, so `schema_version` bumps are regression-covered before they ship.
- Add forward/backward compatibility fixtures that cover: loading a capture written by an older schema version, loading a capture with unknown optional fields, and round-tripping through export+reload without data loss.

### Cancellation Analysis

- Deepen cancellation analysis so timeout, sibling-failure, parent-task, external, and mixed-cause cascades produce more precise summaries instead of relying on mostly heuristic grouping.
- Distinguish `asyncio.wait_for` timeout cancellation from `asyncio.timeout()` context-manager cancellation in `cancellation_origin` so the two paths produce separate insight kinds.
- Add mixed-cause cascade analysis so a chain that starts with a timeout and fans out through sibling-failure is summarised as one compound event rather than two disconnected insights.

### API

- Add a search-first query flow (`q=`) to the task API for task name, exception text, request label, and job label so large captures can be narrowed by keyword without manual filter combinations. (Currently `q` is accepted but not documented and has no fixture coverage.)
- Expose stack snapshots through a `/api/v1/stacks` endpoint so the UI can page through all captured frames independently of the task detail view.

### Headless Output

- Add richer headless compare output for changed task states, hot task drift, request/job label changes, and new insight kinds so regression review is useful without opening the UI.
- Add stack-aware error summaries to headless `summary` and `compare` output so failed captures expose the top exception frame immediately in terminal output.

---

## Soon

### Session Metadata

- Expose `script_path`, `python_version`, and `command_line` in headless `summary` textual output (currently in JSON only).

### Testing

- Add explicit fixture coverage for `q` search behavior on mixed captures (task name, exception text, request label, job label) so the search path is regression-covered.
- Add task-detail API coverage for request/job label filtering plus `q` search on mixed captures.
- Add an end-to-end test that exercises packaged static assets through the local server, so a missing `web_dist` build does not silently produce a broken UI at the packaged entry point.
- Add replay contract tests for the `schema_version` field: assert that loading a future-versioned capture with unknown fields does not raise, and that all required fields are always present.
- Introduce Vitest coverage for timeline hover, filter preset activation, and resource/cancellation panel coordination in the React UI so interaction paths beyond the initial render smoke test are covered.

### Resource Graph

- Improve resource graph drilldown to distinguish owners, waiters, and cancelled waiters per resource, including the task names and current states, instead of only listing task IDs.
- Add resource name aliasing so queue/lock/semaphore IDs derived from `id()` can be annotated with a user-supplied label (e.g. via a context var or naming convention) for readability in larger captures.

### CLI

- Add `demo` scenario for `timeout-contention` (tasks racing a `wait_for` timeout against a shared queue) so the built-in demos cover the timeout cancellation path that has fixture coverage but no runnable demo.
- Add `demo` scenario for `resource-contention` (multiple tasks sharing a semaphore and lock) so the resource graph demo path is exercisable without constructing a custom script.

---

## Later

### UI

- Add timeline zoom and windowing for longer captures so the canvas remains usable when sessions have thousands of segments.
- Add keyboard shortcuts for common debug actions (next task, previous insight, jump to selected task's timeline segment) so the UI is navigable without a mouse during live debugging sessions.
- Add an export button in the UI that triggers a JSON/CSV download of the current session so captures can be saved directly from the browser without using the CLI `export` command.
- Add a "why is this task blocked?" explainer panel that walks parent links, blocking reason, resource ownership, and cancellation history in one pane for the selected task.
- Add a timeline scrubber so the selected time range can be narrowed interactively and all panels (task list, insights, resource graph) filter to that window.

### CLI

- Add a `watch` command that re-runs a target on a given interval, compares each run against the previous capture, and prints drift summaries so regressions are detected automatically without a full CI setup.
- Add `--baseline` flag to `run` so a capture taken during a known-good run is automatically compared at the end and a brief drift summary is printed to stdout.

### Export

- Add a flattened task JSONL export format so downstream analysis tools (pandas, jq, DuckDB) can consume task records without parsing the full session envelope.
- Add resource-wait summary to the CSV export so the flat format includes blocked-resource context alongside task lifecycle data.
- Add optional OpenTelemetry-compatible span export (OTLP JSON) for cross-tool inspection while keeping the local session model as the source of truth.

### Teaching Mode

- Add a lightweight "teaching mode" that overlays common asyncio patterns and explains why a queue, lock, semaphore, or gather shape looks suspicious, with links to the relevant asyncio documentation sections.
- Surface pattern explanations inline on insights so each insight kind includes a short "what this means" and "how to fix" hint instead of only the raw message string.

### Session & Capture

- Support optional session tags or run notes on saved captures for local incident comparison workflows.
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
- Add a CI-friendly `pyroscope assert` command that runs a script, evaluates a set of insight predicates (e.g. "no deadlock", "no timeout cancellation"), and exits non-zero on violations.
- Add a web-based capture browser for comparing multiple saved `.json` captures in one UI session without restarting the server.
