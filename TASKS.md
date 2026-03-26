# Tasks

## In Progress

## Recently Completed

- Updated `docs/EVENT_CONTRACT.md` invariants: added `deadlock` payload guarantee (`cycle_task_ids`, `cycle_task_names`), `timeout_taskgroup_cascade` payload guarantee (`group_task_id`, `group_task_name`, `cancelled_task_ids`, `timeout_seconds`), and deduplication rule. 185 pytest + 56 Vitest pass.
- Added `DeadlockFocus` panel + "Deadlock" tab in FocusWorkspace; `isDeadlockInsight()` routing in utils.js/useAppState/App. Clicking a deadlock insight opens the tab and lists cycle tasks. Covered by 1 Vitest. 185 pytest + 56 Vitest pass.
- Added `CancellationFocus` reads `cancelled_task_ids` for `timeout_taskgroup_cascade`; `isCancellationInsight` covers `timeout_taskgroup_cascade`; `insightMeta` renders deadlock cycle / TaskGroup name. Covered by 2 Vitest. 185 pytest + 56 Vitest pass.
- Added `/api/v1/export?format=minimized` endpoint + `store.minimize_dict()` + "Export Minimized" link in UI hero. Covered by 1 pytest + 1 Vitest. 185 pytest + 54 Vitest pass.
- Added insight deduplication: `cancellation_cascade` is suppressed when `timeout_taskgroup_cascade` covers the same parent task. Covered by 1 pytest. 185 pytest pass.
- Added `isCancellationInsight` covers `timeout_taskgroup_cascade`; `insightMeta` renders deadlock cycle string and TaskGroup name; `_cancellation_insights` includes `timeout_taskgroup_cascade` in headless summary. 3 new Vitest.
- Added `pyroscope assert --no-timeout-cascade` predicate; `watch --log-sink` and `replay --log-sink`; `minimize` prints stripped event/stack stats. Covered by 4 pytest. 185 pytest pass.
- Added `pyroscope run --log-sink <path>`: streams each event as an NDJSON line to the given file via `SessionStore.open_log_sink()`/`close_log_sink()`; file is flushed and closed in the `finally` block after the run. Covered by 2 pytest. 178 pytest pass.
- Added `pyroscope minimize` CLI command: strips events for tasks not referenced by any insight; `store.minimize(path)` + `store._insight_task_ids()`; also filters stacks. Covered by 2 pytest. 176 pytest pass.
- Added `timeout_taskgroup_cascade` insight: emitted when a `taskgroup.exit` with `exit_status=cancelled` is caused by a parent timeout (`timeout_cm`/`timeout`); includes `group_task_id`, `cancelled_task_ids`, `timeout_seconds`, and `explanation`. Covered by 2 pytest. 174 pytest pass.
- Added deadlock detection insight: `_deadlock_insights()` uses DFS cycle detection on the waits-for graph; emits `kind=deadlock` with `cycle_task_ids`, `cycle_task_names`, and `explanation`. Covered by 2 pytest. 172 pytest pass.
- Added `docs/EVENT_CONTRACT.md` — v1.0 stable contract for Event, TaskRecord, TimelineSegment, StackSnapshot, capture envelope, and invariants; 8 new pytest verify `capture_dict()` shape and `from_capture()` round-trip. 170 pytest pass.
- Added per-request/per-job timeline strips: Task / Request / Job toggle buttons in Timeline; Request/Job modes draw one bar per label group (span = min→max segment time, color = dominant state). `groupTasksByLabel(tasks, segments, labelKey)` utility in utils.js. Covered by 4 Vitest (3 unit + 1 integration). 162 pytest + 49 Vitest pass.
- Added `watch --save-dir` auto-baseline: run 1 saved as baseline with "(baseline saved)" note; runs 2+ print "vs baseline: tasks N->M, insights N->M" drift via `compare_summary`. Covered by 1 new pytest. 162 pytest pass.
- Decoupled `web_dist` from git: added `src/pyroscope/web_dist/` and `web/dist/` to `.gitignore`, removed committed assets with `git rm --cached`, created `.github/workflows/ci.yml` (Node build → Vitest → pytest). E2E test uses `web/dist/` in dev/CI; `web_dist/` reserved for package mode.
- Added SSE back-pressure signal: when subscriber queue is full, server drains one slot, pushes `{"type":"error","code":"slow_client"}`, and closes the stream; UI shows "Connection too slow" warning banner. Covered by 1 pytest + 1 Vitest. 161 pytest + 45 Vitest pass.
- Added `docs/API.md` documenting all HTTP endpoints, the `q` full-text search parameter (fields: name, reason, resource_id, request_label, job_label), and the SSE frame protocol including the new `error` frame type.
- Added `RequestJobPanel`: groups tasks by `request_label`/`job_label` with per-label state breakdown badges; clicking a row narrows task list via existing `filters.requestLabel`/`filters.jobLabel`. 44 Vitest + 160 pytest pass.
- Added service-workload capture diff fixtures (`replay_service_workload_baseline.json` / `_shifted.json`): overlapping GET /users, GET /orders, POST /orders requests with job labels; `compare_summary` detects label, resource, and state drift. Covered by 3 new pytest. 160 pytest + 43 Vitest pass.
- Added teaching mode toggle: hero button enables/disables `teachingMode` state; `InsightCard` shows `explanation.what` and `explanation.how` from insight payload when active. Covered by 1 Vitest test. 157 pytest + 43 Vitest pass.
- Split App.jsx (1147 lines) into `utils.js` (pure helpers), `Timeline.jsx` (canvas component), `useAppState.js` (custom hook), and a slim `App.jsx` render (~200 lines). All 42 Vitest tests pass unchanged.
- Added pagination to the task list: `TASK_PAGE_SIZE=25`, page state with reset on filter change, page indicator always visible, prev/next buttons only when multiple pages. Covered by 1 Vitest test. 157 pytest + 42 Vitest pass.
- Added `/api/v1/summary` endpoint exposing `headless_summary()` as the single presentation contract for hot_tasks, error_tasks, and cancellation_insights — both CLI and UI are now driven by the same server-computed derived views. Fixed `isCancellationInsight()` in App.jsx to match the server's definition (added `cancellation_cascade` and `mixed_cause_cascade`). Covered by `test_summary_endpoint_matches_headless_summary`.
- Added Vitest coverage for: timeline mouseLeave clears hover, canvas click selects hovered task, `cancellation_cascade` preset activation via "Cancelled" button, and task navigation from cancellation drilldown to inspector. 26 Vitest tests now pass.
- Completed resource name aliasing: `_resource_contention_insights()` now includes `resource_label` when tasks carry it; `insightMeta()` in App.jsx prefers `resource_label` over `resource_id`; `ResourceFocus` panel shows `resource_label ?? resource_id`. Covered by `test_resource_contention_insight_includes_resource_label` and a new Vitest test. 155 pytest + 27 vitest pass.
- Added task name search input to the Task filters panel; closes both the "Later / UI" item and the "Bugs / Technical Debt" `q` UI entry point. Filter clears on "Clear" button. 28 Vitest tests pass.
- Added per-severity filtering (All / Error / Warning / Info toggle buttons) to the Insights panel. 29 Vitest + 155 pytest pass.
- Added "Copy as JSON" button to the Inspector panel; copies full task payload to clipboard. 30 Vitest pass.
- Added collapsible insight cards with ▼/▶ toggle; insight message body hides on collapse. 31 Vitest pass.
- Added Python version and script path metric cards to the hero header. 32 Vitest pass.

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
- Added `pre-commit` pipeline with ruff, black, ty, pytest; fixed all pre-existing lint/type issues surfaced by hooks.
- Stabilized event/stack forward-compat loading: unknown fields stripped via `dataclasses.fields()` before `Event(**...)` / `StackSnapshot(**...)`.
- Added schema replay contract: round-trip tests, backward-compat fixture (v0.9 missing newer fields), forward-compat fixture (v2.0 with unknown fields in session/events/stacks).
- Deepened cancellation analysis: `cancellation_cascade` carries parent name/state/affected names; `task_cancelled` and `cancellation_chain` messages reflect whether parent was cancelled or failed.
- Added E2E test `test_packaged_web_dist_serves_index_and_assets` covering: index.html present, assets serve with correct Content-Type, missing asset returns 404, SPA fallback works.
- Added dark/light mode toggle: `getInitialTheme()` reads `localStorage` → falls back to `prefers-color-scheme`; `useEffect` writes `document.documentElement.dataset.theme` and persists to localStorage; toggle button in hero with aria-label "Switch to dark/light mode". Covered by 1 Vitest test. 157 pytest + 41 Vitest pass.
- Added `TaskTree` panel (`TaskTree` + `TreeNode` in dashboard-panels.jsx): renders full parent-child hierarchy from `task.children`; each node is collapsible (▼/▶); clicking a node selects the task. Placed between Inspector and FocusWorkspace. Covered by 1 Vitest test. 157 pytest + 40 Vitest pass.
- Added timeline scrubber: two range inputs (0–100%) in the Timeline component drive a `timeWindow` state in App; `filteredTasks` drops tasks with no segment overlapping the window; `filteredSegments` clips to the window. "Clear time filter" button resets. Covered by 1 Vitest test with non-overlapping task fixtures. 157 pytest + 39 Vitest pass.
- Added `BlockExplainer` component inside Inspector: renders "Why blocked?" / "Why cancelled?" / "Why failed?" narrative section with resource holder count and waiter context for the selected task. Covered by 1 Vitest test. 157 pytest + 38 Vitest pass.
- Added keyboard shortcuts: `ArrowDown`/`ArrowUp` navigate tasks, `n`/`p` navigate insights (skipped when a text input is focused). Insight keys call the same `handleInsightSelect` logic — switch focus tab + select resource/task. Covered by 1 Vitest test. 157 pytest + 37 Vitest pass.
- Added timeline zoom and windowing: `viewRange` state in `Timeline`, `timelineGeometry` accepts `viewStart`/`viewEnd` fractions, zoom-in/out/reset buttons + mouse-wheel zoom around pointer. Covered by 1 Vitest test. 157 pytest + 36 Vitest pass.
- Added permalink-to-task: `history.replaceState` writes `#task=<id>` on selection; initial hash pre-selects the matching task on load. Covered by 2 Vitest tests. 157 pytest + 35 Vitest pass.
- Added `/api/v1/export?format=json` and `/api/v1/export?format=csv` endpoints; added `capture_dict()` and `capture_csv_bytes()` to `SessionStore`; added Export JSON / Export CSV download links to the hero header. Covered by `test_export_json_endpoint_returns_capture_payload`, `test_export_csv_endpoint_returns_timeline_csv`, and a Vitest test. 157 pytest + 33 Vitest pass.

---

## Next Up

---

## Soon

---

## Later

### UI

~~- Add timeline zoom and windowing for longer captures so the canvas remains usable when sessions have thousands of segments.~~
~~- Add keyboard shortcuts for common debug actions (next task, previous insight, jump to selected task's timeline segment) so the UI is navigable without a mouse during live debugging sessions.~~
~~- Add an export button in the UI that triggers a JSON/CSV download of the current session so captures can be saved directly from the browser without using the CLI `export` command.~~
~~- Add a "why is this task blocked?" explainer panel that walks parent links, blocking reason, resource ownership, and cancellation history in one pane for the selected task.~~
~~- Add a timeline scrubber so the selected time range can be narrowed interactively and all panels (task list, insights, resource graph) filter to that window.~~
~~- Add a task search/quick-filter input at the top of the task list so tasks can be narrowed by name substring without opening the full filter panel.~~
~~- Add a permalink-to-task feature: selecting a task updates the URL hash (`#task=<id>`) so a specific task can be shared or bookmarked.~~
~~- Add a "Copy as JSON" button to the Inspector panel so a task's full payload can be copied to the clipboard for pasting into other tools.~~
~~- Add collapsible insight cards so long cancellation chains and resource contention groups can be collapsed to a one-line summary and expanded on demand.~~
~~- Add a task parent/child tree view panel (separate from the resource graph) that shows the full task hierarchy as a collapsible tree so parent-child relationships are visible at a glance.~~
~~- Add a dark/light mode toggle and persist the preference in localStorage so the UI respects the user's system theme by default but allows manual override.~~
~~- Add pagination or virtual scrolling to the task list so sessions with hundreds of tasks remain responsive.~~
~~- Add a session info header bar showing session name, duration, total events, and Python version so the capture context is visible without opening the summary panel.~~
~~- Add per-severity filtering to the Insights panel (error / warning / info toggle buttons) so users can quickly isolate critical issues.~~
~~- Split App.jsx (currently 841 lines) into focused sub-components (Timeline, FilterBar, SessionHeader, TaskDetail) so each file has a single responsibility and stays under 300 lines.~~

### Teaching Mode

~~- Add a lightweight "teaching mode" that overlays common asyncio patterns and explains why a queue, lock, semaphore, or gather shape looks suspicious, with links to the relevant asyncio documentation sections.~~
~~- Surface pattern explanations inline on insights so each insight kind includes a short "what this means" and "how to fix" hint instead of only the raw message string.~~

### Session & Capture

~~- Add capture diff fixtures for service-style workloads with multiple request labels and overlapping jobs.~~
~~- Add a `watch` mode for replay comparison so a saved baseline can be contrasted automatically against a newly captured run.~~ → promoted to Soon.

### Request/Job Views

~~- Add request-centric and job-centric dashboard views that collapse task noise into higher-level local service flows grouped by `request_label` and `job_label`.~~
~~- Add per-request and per-job timeline strips so the timeline panel can be switched from task-level to request-level granularity.~~ → promoted to Soon.

---

## Bugs / Technical Debt

- The UI currently fetches the full snapshot eagerly on connect; larger captures will eventually need incremental loading and stronger server-side pagination usage. (Tier 2)
- Built frontend assets are committed into `src/pyroscope/web_dist`, which is practical today but creates review noise and risks the committed assets diverging from `web/src`. → promoted to Next Up.
- SSE subscriber queue capacity (512) is a hard-coded constant with no back-pressure signal to the UI; a slow client silently drops events rather than receiving an error. → promoted to Soon.

---

## Future Ideas

- Add fixture minimization tooling that trims large captures into the smallest reproducible regression artifact. (Tier 1, depends on stable event model)
- Add a `pyroscope attach` mode for already-running processes via monkey-patching over a pipe or Unix socket, keeping the local model as the source of truth. (Tier 3)
- Add a structured NDJSON log sink so `pyroscope run` can optionally emit event logs alongside the in-memory session for post-mortem analysis of long-running services. (Tier 2, depends on stable event model)
- Add a web-based capture browser for comparing multiple saved `.json` captures in one UI session without restarting the server. (Tier 3, depends on incremental loading + stable model)
