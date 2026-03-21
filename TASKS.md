# Tasks

## Next Up

## In Progress

- Refine the event model from MVP shape toward a more stable contract for replay and UI consumers
- Improve cancellation analysis beyond the current TaskGroup/cascade heuristics

## Later

- Add richer insights: cancellation chains, stalled gather groups, fan-out explosion hints
- Improve stack snapshot quality and symbol readability
- Add CSV/JSON export options for more derived analysis views
- Add query parameters to the local API for insights/resources pagination on larger captures

## Bugs / Technical Debt

- `demo` and replay flows should get broader contract coverage beyond the current golden replay fixture
- React/Vite UI now has basic smoke, hover, and reconnect coverage, but longer-lived stream recovery behavior is still lightly tested
- Runtime instrumentation is useful but still partial relative to full asyncio behavior
- Timeline canvas still needs deeper interaction coverage beyond the current hover-detail smoke path
- API pagination/filter coverage is still focused on task/timeline/insight/resource happy paths rather than malformed query combinations

## Ideas

- Compare two captures and highlight regressions
- Add “teaching mode” overlays for common asyncio patterns
- Add a CLI summary mode for headless debugging
- Add optional request/job labels to tasks for local service debugging
