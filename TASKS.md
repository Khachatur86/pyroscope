# Tasks

## Next Up

## In Progress

- Refine the event model from MVP shape toward a more stable contract for replay and UI consumers
- Improve cancellation analysis beyond the current TaskGroup/cascade heuristics

## Later

- Add richer insights: cancellation chains, stalled gather groups, fan-out explosion hints
- Add query parameters to the local API for insights/resources pagination on larger captures

## Bugs / Technical Debt

- Runtime instrumentation is useful but still partial relative to full asyncio behavior
- Timeline canvas still needs deeper interaction coverage beyond the current hover-detail smoke path

## Ideas

- Compare two captures and highlight regressions
- Add “teaching mode” overlays for common asyncio patterns
- Add a CLI summary mode for headless debugging
- Add optional request/job labels to tasks for local service debugging
