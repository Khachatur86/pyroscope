# pyroscope-asyncio — project conventions for Claude

## What this project is

Local asyncio concurrency inspector. `AsyncioTracer` patches asyncio primitives
and records events into `SessionStore`. A local HTTP server + React UI visualises
the live session. CLI commands: `run`, `demo`, `replay`, `summary`, `compare`,
`export`, `watch`, `assert`, `ui`.

## Repository layout

```
src/pyroscope/   Python package (runtime, session, api, cli, model)
tests/           pytest suite (test_session, test_api, test_cli, test_runtime)
tests/fixtures/  JSON captures used as regression fixtures
web/src/         React + Vite frontend (App.jsx, dashboard-panels.jsx)
web/src/test/    Vitest tests (App.test.jsx)
```

## Development workflow

### Python backend — strict TDD

1. Write a failing test first (RED)
2. Implement the minimum code to pass (GREEN)
3. Run the full suite: `uv run pytest`
4. Commit only when all tests pass

### Frontend — Vitest + React Testing Library

- New components and behaviour changes must have Vitest tests in `App.test.jsx`
- Run tests: `cd web && npm test`
- Build assets: `cd web && npm run build` — commit result to `src/pyroscope/web_dist/`

## Commands

```bash
uv run pytest                   # full Python test suite
uv run pytest tests/test_X.py -k name   # run specific test
uv run ruff check src tests     # lint
uv run black src tests          # format
uv run pre-commit run --all-files  # all hooks (ruff + black + ty + pytest)

cd web && npm test              # Vitest frontend tests
cd web && npm run build         # rebuild web_dist assets
```

## Code conventions

- **TDD mandatory** for every Python feature and bug fix (RED → GREEN → commit)
- **No magic numbers** — use named constants in `session.py`
- **No bare `except`** — always catch a specific exception
- **`from __future__ import annotations`** in every Python file
- **Black line length 88**, target Python 3.12+
- **Forward-compatible loading** — strip unknown fields before constructing
  `Event`/`StackSnapshot` (see `_EVENT_FIELDS` / `_STACK_FIELDS` in session.py)
- **Pre-commit hooks** run automatically on every commit: ruff → black → ty → pytest

## Key invariants

- `SESSION_SCHEMA_VERSION = "1.0"` — bump when adding required fields
- `from_capture()` must never crash on older or newer captures
- `insights()` always includes an `explanation` field on every insight
- `cancellation_cascade` payload always has `parent_task_name`, `affected_task_names`
- All CLI commands exit 0 on success, non-zero on assertion/load failure

## Fixtures

When adding a new capture fixture to `tests/fixtures/`:
- Use `store.save_json(path)` to generate it from a programmatic store
- Add a test that loads it with `SessionStore.from_capture()` and checks key fields
- Schema compatibility fixtures live as `replay_schema_*.json`
