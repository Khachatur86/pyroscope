# Tasks

## Next Up

- Add API contract tests for `/api/v1/session`, `/api/v1/tasks`, `/api/v1/timeline`, and `/api/v1/insights`
- Improve task parent/child tracking so runtime relationships are more explicit in captures
- Add `TaskGroup` coverage in runtime capture and examples
- Expand replay/export regression coverage with stable fixture files

## In Progress

- Refine the event model from MVP shape toward a more stable contract for replay and UI consumers
- Add `black`, `ty`, and `pre-commit` project configuration wired through `uv`

## Later

- Decide whether to keep the built-in UI lightweight or move to a dedicated React/Vite frontend
- Add richer insights: cancellation chains, stalled gather groups, fan-out explosion hints
- Improve stack snapshot quality and symbol readability
- Add filtering and query parameters to the local API for larger captures
- Add CSV/JSON export options for more derived analysis views

## Bugs / Technical Debt

- `demo` and replay flows should get stricter contract tests around saved capture shape
- Current UI is intentionally lightweight; no focused frontend test coverage yet
- Runtime instrumentation is useful but still partial relative to full asyncio behavior
- Session payloads should be treated as versioned contracts before the project grows further

## Ideas

- Compare two captures and highlight regressions
- Add “teaching mode” overlays for common asyncio patterns
- Add a CLI summary mode for headless debugging
- Add optional request/job labels to tasks for local service debugging
