# Pyroscope MVP Plan

- Build a local `asyncio` inspector similar in product shape to `goroscope`.
- Keep the backend and UI local-only, with a single-process MVP.
- Prioritize real debugging and teaching equally by using one shared event model.
- Implement a runnable vertical slice:
  - CLI wrapper
  - runtime capture
  - analysis/session store
  - HTTP + SSE API
  - embedded browser UI
  - replay/export
  - demos and tests

## MVP defaults

- `asyncio` only
- no attach to an already-running process
- run through `pyroscope run` or `pyroscope demo`
- replay via JSON capture files
- no external dependencies required

