# Tasks

## Next Up

- Expand fixture coverage beyond the first replay/export golden capture
- Enrich cancellation metadata for timeout-driven and cross-resource cancellation cases
- Add richer insight payloads for stalled gather groups and fan-out explosions
- Add dedicated regression coverage for main/root task payloads in replay fixtures and API responses

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
