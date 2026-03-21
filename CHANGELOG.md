# Changelog

## Unreleased

### Changed

- Replaced the embedded string-based browser UI with a React/Vite frontend served from packaged static assets.

### Added

- Added replay fixtures for multi-session drift where the root task completion mode and resource graph both change, extending replay replacement coverage beyond queue-only and cancellation-only drift cases.
- Added preset-backed UI drilldown focus so the built-in `Blocked main`, `Cancelled`, and `Failures` slices immediately open the relevant resource, cancellation, or error panel instead of only filtering the task list.
- Added queue contention drilldown slices in the React/Vite UI so mixed `queue_get` and `queue_put` pressure on the same queue is split into consumer and producer groups inside the resource panel.
- Added timeout-aware cancellation capture for `asyncio.wait_for`, including traced child-task cancellation metadata and API/insight coverage for `timeout` cancellation origin.
- Added `stalled_gather_group` and `fan_out_explosion` insights so the API/UI can flag slow gather waits and unusually wide child-task fan-out from one parent task.
- Added a second committed replay/export fixture covering timeout-driven cancellation, extending golden-capture regression coverage beyond the original happy-path replay file.
- Added replay fixtures for mixed TaskGroup error+cancellation sessions and root-level `ExceptionGroup` failures so replay/API tests cover multi-task failure shapes instead of only single-task root edges.
- Added blocked-resource cancellation attribution for queue and lock waits so cancelled tasks and cancellation insights can report which `asyncio` primitive the task was waiting on at the moment of cancellation.
- Added resource-level contention insights for queues, locks, and semaphores so the API can flag backpressure, lock contention, and semaphore saturation from blocked task groups.
- Added replay fixtures for stalled gather/fan-out sessions and resource-contention sessions so replay/API tests cover derived insight shapes, not only lifecycle and cancellation contracts.
- Added replay fixtures for explicit `parent_task` child cancellation and mixed `external`/`parent_task` child-cancellation sessions so replay/API tests cover blocked-resource cancellation variants.
- Added replay fixtures for multi-root sessions and multi-replay replacement scenarios so replay/API tests cover multiple root tasks and clean state replacement between distinct captures.
- Updated the React/Vite UI so the inspector shows blocked-resource cancellation context and the insights list highlights resource-focused queue/lock/semaphore findings instead of only raw insight kind strings.
- Added a resource-focused drilldown panel in the React/Vite UI so clicking queue/lock/semaphore insights highlights the affected resource and related tasks.
- Added UI task filters for `cancellation_origin`, blocked reason, and resource id so the task list and timeline can be narrowed to the relevant asyncio failure slice.
- Added cancellation-focused drilldown in the React/Vite UI so clicking cancellation insights selects the source task and lists the affected tasks for direct inspection.
- Added replay fixtures for producer-side `queue.put` backpressure waits so replay/API tests cover blocked producers, not only blocked consumers.
- Added replay fixtures for multi-session drift with changed task ids and resource graphs so replay/API tests verify clean replacement of resources and derived insights between distinct captures.
- Added UI filtering by task `state` and `task_role` so task lists and timeline slices can be narrowed by lifecycle state or main/background role.
- Added UI error drilldown for `task_error` insights so failed tasks, including failed root/main tasks, can be selected directly from insights and inspected in a dedicated panel.
- Added replay fixtures for mixed `queue_get` and `queue_put` contention on one queue so replay/API tests cover shared consumer/producer backpressure on the same resource.
- Added replay fixtures for drift between cancellation-heavy and root-failure sessions so replay/API tests verify replacement of cancellation chains and root-task metadata across distinct captures.
- Added grouped UI filter presets for common debugging slices such as blocked main tasks, cancellations, and failures so common task/timeline slices can be applied with one click.
- Added focused UI drilldown for grouped queue/semaphore contention insights so resource focus shows grouped contention summary, blocked count, and reason breakdown instead of only related tasks.
- Added replay fixtures for mixed queue contention and queue-wait cancellation on the same resource so replay/API tests cover blocked and cancelled tasks sharing one queue context.
- Added dedicated replay fixtures for `event_wait` and `semaphore_acquire` cancellation flows so replay/API tests cover those blocked-resource variants directly instead of only through mixed-session fixtures.
- Added static asset serving and SPA fallback coverage to the local API contract tests.
- Added a `web/` frontend workspace and a sync script for copying built assets into `src/pyroscope/web_dist`.
- Added focused Vitest coverage for the React/Vite UI render and inspector/error flows.
- Added explicit `children` relationships to task payloads so parent/child links survive snapshot and replay without recomputing them only in detail views.
- Added fixture-based replay and CSV export regression tests using a committed golden capture.
- Added first-class cancellation fields on task/event payloads so cancelled tasks now expose `cancelled_by_task_id` and `cancellation_origin`.
- Improved TaskGroup cancellation attribution so sibling tasks cancelled after a child failure are tagged as `sibling_failure` instead of generic parent cancellation.
- Added regression coverage for `external` root-task cancellation and explicit `parent_task` child cancellation, locking the three current cancellation origins.
- Added cancellation source context to task detail payloads and cancellation insight messages so the API/UI can show who cancelled a task and why.
- Added grouped `cancellation_chain` insights that summarize a source task and the full list of affected cancelled tasks.
- Added explicit lifecycle capture for the `asyncio.run` main task, including root-task metadata and stable parent links from spawned child tasks.
- Added replay fixture and API regression coverage for main/root task metadata so the `asyncio.run` root-task contract is preserved across replay flows.
- Added replay fixture coverage for failed and externally cancelled root/main task sessions.

### Added

- Added `TASKS.md` as the working backlog for upcoming runtime, API, and tooling work
- Added project-level `pre-commit` hooks for formatting, type checks, tests, and basic file hygiene
- Added API contract tests for session, task, timeline, insight, resource graph, and replay endpoints
- Added TaskGroup-focused runtime coverage and a cancellation demo scenario
- Added cancellation cascade insight heuristics for grouped child task shutdown

### Changed

- Standardized project tooling around `uv`, `black`, `ty`, and `pytest`
- Tightened replay/session handling so replayed captures replace the in-memory session state cleanly

## 0.1.0

### Added

- Added the first `pyroscope` MVP vertical slice as a local `asyncio` concurrency inspector
- Added CLI commands for `run`, `demo`, `replay`, `export`, `ui`, and `version`
- Added runtime capture for task lifecycle plus selected `asyncio` primitives such as `sleep`, `gather`, `wait`, `Queue`, `Lock`, `Semaphore`, and `Event`
- Added in-memory session storage with timeline segments, task summaries, resource graph output, and basic insights
- Added local HTTP + SSE API with an embedded browser UI
- Added replay and export support for saved session captures
- Added example scenarios for worker-pool and cancellation behavior
- Added project-level defaults in `AGENTS.md` for `uv`, `pytest`, `ty`, `black`, and TDD-first development

### Changed

- Switched the project test suite from `unittest` style to `pytest`
