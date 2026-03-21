# Tasks

## Next Up

- Surface blocked-resource cancellation context more explicitly in the UI inspector and insights panel
- Add UI rendering for queue/lock/semaphore contention insights with resource-focused drilldown
- Add replay fixtures for event waits and semaphore cancellation flows
- Add replay fixtures for multi-root or multi-session comparison scenarios

## In Progress

- Refine the event model from MVP shape toward a more stable contract for replay and UI consumers
- Improve cancellation analysis beyond the current TaskGroup/cascade heuristics

## Later

- Add richer insights: cancellation chains, stalled gather groups, fan-out explosion hints
- Improve stack snapshot quality and symbol readability
- Add filtering and query parameters to the local API for larger captures
- Add CSV/JSON export options for more derived analysis views

## Bugs / Technical Debt

- `demo` and replay flows should get broader contract coverage beyond the current golden replay fixture
- React/Vite UI now has smoke coverage, but interaction and reconnect behavior are still lightly tested
- Runtime instrumentation is useful but still partial relative to full asyncio behavior
- Session payloads should be treated as versioned contracts before the project grows further

## Ideas

- Compare two captures and highlight regressions
- Add “teaching mode” overlays for common asyncio patterns
- Add a CLI summary mode for headless debugging
- Add optional request/job labels to tasks for local service debugging
