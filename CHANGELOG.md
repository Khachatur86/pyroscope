# Changelog

## Unreleased

### Changed

- Replaced the embedded string-based browser UI with a React/Vite frontend served from packaged static assets.

### Added

- Added timeout-aware cancellation capture for `asyncio.wait_for`, including traced child-task cancellation metadata and API/insight coverage for `timeout` cancellation origin.
- Added `stalled_gather_group` and `fan_out_explosion` insights so the API/UI can flag slow gather waits and unusually wide child-task fan-out from one parent task.
- Added a second committed replay/export fixture covering timeout-driven cancellation, extending golden-capture regression coverage beyond the original happy-path replay file.
- Added replay fixtures for mixed TaskGroup error+cancellation sessions and root-level `ExceptionGroup` failures so replay/API tests cover multi-task failure shapes instead of only single-task root edges.
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
