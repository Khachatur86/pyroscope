# Pyroscope Agent Notes

Default working set for this repository:

- `pyroscope-project`
- `python-asyncio`
- `python-tdd`
- `backend-debugging`

Add as needed:

- `python-packaging` for `pyproject.toml`, layout, entrypoints, and tooling changes
- `pre-commit-tools` for local quality gates
- `python-modern-tooling` for repo-wide tooling defaults

Project defaults:

- Python `3.12+`
- `uv` for env/deps/command execution when available
- `pytest` for tests
- `ty` for type checking unless the repo standard changes
- `black` for formatting unless the repo standard changes
- TDD-first for new features and bug fixes

Repository shape to preserve:

- CLI-first local debugging tool
- `asyncio` runtime capture
- in-memory session and analysis model
- local HTTP/SSE API
- browser UI as inspection surface
- replay/export flows as first-class features
