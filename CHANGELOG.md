# Changelog

## Unreleased

### Added

- Added `TASKS.md` as the working backlog for upcoming runtime, API, and tooling work
- Added project-level `pre-commit` hooks for formatting, type checks, tests, and basic file hygiene
- Added API contract tests for session, task, timeline, insight, resource graph, and replay endpoints

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
