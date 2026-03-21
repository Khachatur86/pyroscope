from __future__ import annotations

import json
from pathlib import Path
import urllib.error
import urllib.request
from typing import Any, cast

from pyroscope.api import PyroscopeServer
from pyroscope.model import Event
from pyroscope.session import SessionStore


def _build_store() -> SessionStore:
    store = SessionStore("api-contract")
    store.append_event(
        Event(
            session_id=store.session_id,
            seq=store.next_seq(),
            ts_ns=10,
            kind="task.create",
            task_id=1,
            task_name="worker",
            state="READY",
        )
    )
    store.append_event(
        Event(
            session_id=store.session_id,
            seq=store.next_seq(),
            ts_ns=20,
            kind="task.start",
            task_id=1,
            task_name="worker",
            state="RUNNING",
        )
    )
    store.append_event(
        Event(
            session_id=store.session_id,
            seq=store.next_seq(),
            ts_ns=30,
            kind="task.block",
            task_id=1,
            task_name="worker",
            state="BLOCKED",
            reason="sleep",
            resource_id="sleep",
        )
    )
    store.mark_completed()
    return store


def _get_json(url: str) -> Any:
    with urllib.request.urlopen(url) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_text(url: str) -> str:
    with urllib.request.urlopen(url) as response:
        return response.read().decode("utf-8")


def test_api_contract_endpoints() -> None:
    store = _build_store()
    server = PyroscopeServer(store, port=0)
    server.start()
    try:
        base = f"http://127.0.0.1:{server.port}"

        session_payload = cast(dict[str, Any], _get_json(f"{base}/api/v1/session"))
        assert isinstance(session_payload, dict)
        assert sorted(session_payload.keys()) == [
            "insights",
            "segments",
            "session",
            "tasks",
        ]
        assert session_payload["session"]["session_name"] == "api-contract"
        assert session_payload["session"]["task_count"] == 1

        tasks_payload = cast(list[dict[str, Any]], _get_json(f"{base}/api/v1/tasks"))
        assert isinstance(tasks_payload, list)
        assert len(tasks_payload) == 1
        assert tasks_payload[0]["task_id"] == 1

        task_payload = cast(dict[str, Any], _get_json(f"{base}/api/v1/tasks/1"))
        assert task_payload["task_id"] == 1
        assert task_payload["state"] == "BLOCKED"
        assert "children" in task_payload

        timeline_payload = cast(
            list[dict[str, Any]], _get_json(f"{base}/api/v1/timeline?state=BLOCKED")
        )
        assert isinstance(timeline_payload, list)
        assert timeline_payload
        assert all(item["state"] == "BLOCKED" for item in timeline_payload)

        insights_payload = cast(
            list[dict[str, Any]], _get_json(f"{base}/api/v1/insights")
        )
        assert isinstance(insights_payload, list)

        resources_payload = cast(
            list[dict[str, Any]], _get_json(f"{base}/api/v1/resources/graph")
        )
        assert isinstance(resources_payload, list)
        assert resources_payload[0]["resource_id"] == "sleep"

        try:
            urllib.request.urlopen(f"{base}/api/v1/tasks/not-a-number")
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
        else:
            raise AssertionError("expected invalid task id to return 400")
    finally:
        server.stop()


def test_serves_frontend_assets_and_spa_fallback(tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist"
    assets_dir = dist_dir / "assets"
    assets_dir.mkdir(parents=True)
    (dist_dir / "index.html").write_text(
        """<!doctype html>
<html>
  <body>
    <div id="root"></div>
    <script type="module" src="/assets/app.js"></script>
  </body>
</html>
""",
        encoding="utf-8",
    )
    (assets_dir / "app.js").write_text("console.log('pyroscope');\n", encoding="utf-8")

    store = _build_store()
    server = PyroscopeServer(store, port=0, frontend_dir=dist_dir)
    server.start()
    try:
        base = f"http://127.0.0.1:{server.port}"

        index_html = _get_text(f"{base}/")
        assert '<div id="root"></div>' in index_html

        asset_js = _get_text(f"{base}/assets/app.js")
        assert "pyroscope" in asset_js

        nested_route_html = _get_text(f"{base}/tasks/1")
        assert '<div id="root"></div>' in nested_route_html

        try:
            urllib.request.urlopen(f"{base}/assets/missing.js")
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
        else:
            raise AssertionError("expected missing asset to return 404")

        try:
            urllib.request.urlopen(f"{base}/api/v1/not-found")
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
        else:
            raise AssertionError("expected missing API route to return 404")
    finally:
        server.stop()


def test_replay_load_replaces_session_payload() -> None:
    live_store = SessionStore("live")
    server = PyroscopeServer(live_store, port=0)
    server.start()
    try:
        replay_store = _build_store()
        body = json.dumps(
            {
                "snapshot": replay_store.snapshot(),
                "events": replay_store.events(),
                "stacks": [],
                "resources": replay_store.resource_graph(),
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.port}/api/v1/replay/load",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request) as response:
            payload = json.loads(response.read().decode("utf-8"))
        assert payload["ok"] is True

        session_payload = cast(
            dict[str, Any],
            _get_json(f"http://127.0.0.1:{server.port}/api/v1/session"),
        )
        assert session_payload["session"]["session_name"] == "api-contract"
        assert session_payload["session"]["task_count"] == 1
        assert session_payload["segments"]
    finally:
        server.stop()
