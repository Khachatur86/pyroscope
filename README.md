# Pyroscope

`Pyroscope` is a local `asyncio` concurrency inspector for Python programs.

It runs your target script or module through a local wrapper, captures task
lifecycles and blocking events, and serves a local browser UI with a timeline,
task inspector, and basic insights.

## Status

This repository contains a working MVP vertical slice:

- Python CLI with `run`, `replay`, `export`, `ui`, `demo`, and `version`
- `asyncio` runtime capture through monkeypatched task and primitive wrappers
- in-memory session store with timeline, task summaries, resource graph, and insights
- local HTTP + Server-Sent Events API
- React/Vite browser UI served as packaged static assets
- example demo programs and tests

## Quickstart

```bash
uv run pyroscope version
uv run pyroscope demo worker-pool --open-browser
uv run pyroscope run examples/cancellation_demo.py --save captures/demo.json
uv run pyroscope replay captures/demo.json
```

## Commands

```bash
uv run pyroscope run path/to/script.py
uv run pyroscope run -m package.module
uv run pyroscope demo worker-pool
uv run pyroscope run examples/taskgroup_cancellation.py
uv run pyroscope replay captures/session.json
uv run pyroscope export captures/session.json --format csv --output waits.csv
uv run pyroscope ui
uv run pyroscope version
```

## Captured behaviors

The MVP tracks:

- task creation, start, completion, failure, and cancellation
- `asyncio.sleep`
- `asyncio.gather`
- `asyncio.wait`
- `Queue.get` / `Queue.put`
- `Lock.acquire`
- `Semaphore.acquire`
- `Event.wait`
- `TaskGroup` cancellation propagation via normal task lifecycle signals

This is intentionally an MVP model. It is optimized for a stable, explainable
timeline instead of perfect reconstruction of all event loop internals.

## Development

```bash
uv run --group dev black .
uv run --group dev ty check src tests
uv run --group dev pytest
uv run --group dev pre-commit run --all-files
uv run pyroscope demo cancellation --hold-after-exit
cd web && npm install && npm run build && cd ..
python3 scripts/sync_web_dist.py
```
