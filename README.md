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
- embedded browser UI with timeline and inspector
- example demo programs and tests

## Quickstart

```bash
python3 -m pyroscope version
python3 -m pyroscope demo worker-pool --open-browser
python3 -m pyroscope run examples/cancellation_demo.py --save captures/demo.json
python3 -m pyroscope replay captures/demo.json
```

## Commands

```bash
python3 -m pyroscope run path/to/script.py
python3 -m pyroscope run -m package.module
python3 -m pyroscope demo worker-pool
python3 -m pyroscope replay captures/session.json
python3 -m pyroscope export captures/session.json --format csv --output waits.csv
python3 -m pyroscope ui
python3 -m pyroscope version
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

This is intentionally an MVP model. It is optimized for a stable, explainable
timeline instead of perfect reconstruction of all event loop internals.

## Development

```bash
python3 -m unittest discover -s tests -v
python3 -m pyroscope demo cancellation --hold-after-exit
```
