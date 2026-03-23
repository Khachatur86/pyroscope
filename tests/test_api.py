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


def _build_cancellation_store() -> SessionStore:
    store = SessionStore("api-cancellation")
    store.append_event(
        Event(
            session_id=store.session_id,
            seq=store.next_seq(),
            ts_ns=10,
            kind="task.create",
            task_id=1,
            task_name="parent",
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
            task_name="parent",
            state="RUNNING",
        )
    )
    store.append_event(
        Event(
            session_id=store.session_id,
            seq=store.next_seq(),
            ts_ns=30,
            kind="task.create",
            task_id=2,
            task_name="failing-child",
            parent_task_id=1,
            state="READY",
        )
    )
    store.append_event(
        Event(
            session_id=store.session_id,
            seq=store.next_seq(),
            ts_ns=40,
            kind="task.error",
            task_id=2,
            task_name="failing-child",
            parent_task_id=1,
            state="FAILED",
            reason="RuntimeError",
        )
    )
    store.append_event(
        Event(
            session_id=store.session_id,
            seq=store.next_seq(),
            ts_ns=50,
            kind="task.create",
            task_id=3,
            task_name="cancelled-child",
            parent_task_id=1,
            state="READY",
        )
    )
    store.append_event(
        Event(
            session_id=store.session_id,
            seq=store.next_seq(),
            ts_ns=60,
            kind="task.cancel",
            task_id=3,
            task_name="cancelled-child",
            parent_task_id=1,
            cancelled_by_task_id=2,
            cancellation_origin="sibling_failure",
            state="CANCELLED",
            reason="cancelled",
            metadata={
                "blocked_reason": "queue_get",
                "blocked_resource_id": "queue:shared",
                "queue_size": 0,
                "queue_maxsize": 16,
            },
        )
    )
    store.mark_completed()
    return store


def _build_timeout_cancellation_store() -> SessionStore:
    store = SessionStore("api-timeout-cancellation")
    store.append_event(
        Event(
            session_id=store.session_id,
            seq=store.next_seq(),
            ts_ns=10,
            kind="task.create",
            task_id=1,
            task_name="sample",
            state="READY",
            metadata={"task_role": "main", "runtime_origin": "asyncio.run"},
        )
    )
    store.append_event(
        Event(
            session_id=store.session_id,
            seq=store.next_seq(),
            ts_ns=20,
            kind="task.start",
            task_id=1,
            task_name="sample",
            state="RUNNING",
        )
    )
    store.append_event(
        Event(
            session_id=store.session_id,
            seq=store.next_seq(),
            ts_ns=30,
            kind="task.create",
            task_id=2,
            task_name="child_worker",
            parent_task_id=1,
            state="READY",
        )
    )
    store.append_event(
        Event(
            session_id=store.session_id,
            seq=store.next_seq(),
            ts_ns=40,
            kind="task.cancel",
            task_id=2,
            task_name="child_worker",
            parent_task_id=1,
            cancelled_by_task_id=1,
            cancellation_origin="timeout",
            state="CANCELLED",
            reason="cancelled",
            metadata={"timeout_seconds": 0.01},
        )
    )
    store.mark_completed()
    return store


def _build_resource_cancellation_store() -> SessionStore:
    store = SessionStore("api-resource-cancellation")
    store.append_event(
        Event(
            session_id=store.session_id,
            seq=store.next_seq(),
            ts_ns=10,
            kind="task.create",
            task_id=1,
            task_name="parent",
            state="READY",
        )
    )
    store.append_event(
        Event(
            session_id=store.session_id,
            seq=store.next_seq(),
            ts_ns=20,
            kind="task.create",
            task_id=2,
            task_name="queue-child",
            parent_task_id=1,
            state="READY",
        )
    )
    store.append_event(
        Event(
            session_id=store.session_id,
            seq=store.next_seq(),
            ts_ns=30,
            kind="task.cancel",
            task_id=2,
            task_name="queue-child",
            parent_task_id=1,
            cancelled_by_task_id=1,
            cancellation_origin="parent_task",
            state="CANCELLED",
            reason="cancelled",
            metadata={
                "blocked_reason": "queue_get",
                "blocked_resource_id": "queue:123",
                "queue_size": 0,
                "queue_maxsize": 16,
            },
        )
    )
    store.mark_completed()
    return store


def _build_resource_insight_store() -> SessionStore:
    store = SessionStore("api-resource-insights")
    for task_id, task_name in ((1, "queue-a"), (2, "queue-b")):
        store.append_event(
            Event(
                session_id=store.session_id,
                seq=store.next_seq(),
                ts_ns=10 + task_id,
                kind="task.create",
                task_id=task_id,
                task_name=task_name,
                state="READY",
            )
        )
        store.append_event(
            Event(
                session_id=store.session_id,
                seq=store.next_seq(),
                ts_ns=20 + task_id,
                kind="task.block",
                task_id=task_id,
                task_name=task_name,
                state="BLOCKED",
                reason="queue_get",
                resource_id="queue:1",
            )
        )
    for task_id, task_name, resource_id in (
        (8, "lock-holder", "lock:1"),
        (9, "sem-holder", "semaphore:1"),
    ):
        store.append_event(
            Event(
                session_id=store.session_id,
                seq=store.next_seq(),
                ts_ns=70 + task_id,
                kind="task.create",
                task_id=task_id,
                task_name=task_name,
                state="READY",
            )
        )
        store.append_event(
            Event(
                session_id=store.session_id,
                seq=store.next_seq(),
                ts_ns=80 + task_id,
                kind="task.start",
                task_id=task_id,
                task_name=task_name,
                state="RUNNING",
                resource_id=resource_id,
            )
        )
    for task_id, task_name in ((3, "lock-a"), (4, "lock-b")):
        store.append_event(
            Event(
                session_id=store.session_id,
                seq=store.next_seq(),
                ts_ns=30 + task_id,
                kind="task.create",
                task_id=task_id,
                task_name=task_name,
                state="READY",
            )
        )
        store.append_event(
            Event(
                session_id=store.session_id,
                seq=store.next_seq(),
                ts_ns=40 + task_id,
                kind="task.block",
                task_id=task_id,
                task_name=task_name,
                state="BLOCKED",
                reason="lock_acquire",
                resource_id="lock:1",
                metadata={"owner_task_ids": [8]},
            )
        )
    for task_id, task_name in ((5, "sem-a"), (6, "sem-b"), (7, "sem-c")):
        store.append_event(
            Event(
                session_id=store.session_id,
                seq=store.next_seq(),
                ts_ns=50 + task_id,
                kind="task.create",
                task_id=task_id,
                task_name=task_name,
                state="READY",
            )
        )
        store.append_event(
            Event(
                session_id=store.session_id,
                seq=store.next_seq(),
                ts_ns=60 + task_id,
                kind="task.block",
                task_id=task_id,
                task_name=task_name,
                state="BLOCKED",
                reason="semaphore_acquire",
                resource_id="semaphore:1",
                metadata={"owner_task_ids": [9]},
            )
        )
    store.mark_completed()
    return store


def _build_filterable_store() -> SessionStore:
    store = SessionStore("api-filterable")
    store.append_event(
        Event(
            session_id=store.session_id,
            seq=store.next_seq(),
            ts_ns=10,
            kind="task.create",
            task_id=1,
            task_name="main-root",
            state="READY",
            metadata={"task_role": "main", "runtime_origin": "asyncio.run"},
        )
    )
    store.append_event(
        Event(
            session_id=store.session_id,
            seq=store.next_seq(),
            ts_ns=20,
            kind="task.start",
            task_id=1,
            task_name="main-root",
            state="RUNNING",
            metadata={"task_role": "main", "runtime_origin": "asyncio.run"},
        )
    )
    store.append_event(
        Event(
            session_id=store.session_id,
            seq=store.next_seq(),
            ts_ns=30,
            kind="task.create",
            task_id=2,
            task_name="queue-producer",
            parent_task_id=1,
            state="READY",
        )
    )
    store.append_event(
        Event(
            session_id=store.session_id,
            seq=store.next_seq(),
            ts_ns=40,
            kind="task.block",
            task_id=2,
            task_name="queue-producer",
            parent_task_id=1,
            state="BLOCKED",
            reason="queue_put",
            resource_id="queue:jobs",
        )
    )
    store.append_event(
        Event(
            session_id=store.session_id,
            seq=store.next_seq(),
            ts_ns=50,
            kind="task.create",
            task_id=3,
            task_name="cancelled-child",
            parent_task_id=1,
            state="READY",
        )
    )
    store.append_event(
        Event(
            session_id=store.session_id,
            seq=store.next_seq(),
            ts_ns=60,
            kind="task.cancel",
            task_id=3,
            task_name="cancelled-child",
            parent_task_id=1,
            cancelled_by_task_id=1,
            cancellation_origin="external",
            state="CANCELLED",
            reason="cancelled",
            metadata={
                "blocked_reason": "queue_get",
                "blocked_resource_id": "queue:jobs",
            },
        )
    )
    store.append_event(
        Event(
            session_id=store.session_id,
            seq=store.next_seq(),
            ts_ns=70,
            kind="task.create",
            task_id=4,
            task_name="lock-worker",
            parent_task_id=1,
            state="READY",
        )
    )
    store.append_event(
        Event(
            session_id=store.session_id,
            seq=store.next_seq(),
            ts_ns=80,
            kind="task.block",
            task_id=4,
            task_name="lock-worker",
            parent_task_id=1,
            state="BLOCKED",
            reason="lock_acquire",
            resource_id="lock:jobs",
        )
    )
    store.append_event(
        Event(
            session_id=store.session_id,
            seq=store.next_seq(),
            ts_ns=90,
            kind="task.create",
            task_id=5,
            task_name="failing-worker",
            parent_task_id=1,
            state="READY",
        )
    )
    store.append_event(
        Event(
            session_id=store.session_id,
            seq=store.next_seq(),
            ts_ns=100,
            kind="task.error",
            task_id=5,
            task_name="failing-worker",
            parent_task_id=1,
            state="FAILED",
            reason="RuntimeError",
        )
    )
    store.mark_completed()
    return store


def _build_gather_and_fanout_store() -> SessionStore:
    store = SessionStore("api-gather-fanout")
    store.append_event(
        Event(
            session_id=store.session_id,
            seq=store.next_seq(),
            ts_ns=10,
            kind="task.create",
            task_id=1,
            task_name="coordinator",
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
            task_name="coordinator",
            state="RUNNING",
        )
    )
    for task_id, task_name in (
        (2, "fast-child"),
        (3, "slow-child"),
        (4, "extra-child-4"),
        (5, "extra-child-5"),
        (6, "extra-child-6"),
        (7, "extra-child-7"),
    ):
        store.append_event(
            Event(
                session_id=store.session_id,
                seq=store.next_seq(),
                ts_ns=30 + task_id,
                kind="task.create",
                task_id=task_id,
                task_name=task_name,
                parent_task_id=1,
                state="READY",
            )
        )
    store.append_event(
        Event(
            session_id=store.session_id,
            seq=store.next_seq(),
            ts_ns=50,
            kind="task.block",
            task_id=1,
            task_name="coordinator",
            state="BLOCKED",
            reason="gather",
            resource_id="gather",
        )
    )
    store.append_event(
        Event(
            session_id=store.session_id,
            seq=store.next_seq(),
            ts_ns=60,
            kind="task.end",
            task_id=2,
            task_name="fast-child",
            parent_task_id=1,
            state="DONE",
        )
    )
    store.append_event(
        Event(
            session_id=store.session_id,
            seq=store.next_seq(),
            ts_ns=250_000_000,
            kind="task.end",
            task_id=3,
            task_name="slow-child",
            parent_task_id=1,
            state="DONE",
        )
    )
    store.append_event(
        Event(
            session_id=store.session_id,
            seq=store.next_seq(),
            ts_ns=260_000_000,
            kind="task.unblock",
            task_id=1,
            task_name="coordinator",
            state="RUNNING",
            reason="gather",
            resource_id="gather",
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
        assert session_payload["session"]["schema_version"] == "1.0"
        assert session_payload["session"]["session_name"] == "api-contract"
        assert session_payload["session"]["task_count"] == 1
        assert session_payload["tasks"][0]["resource_roles"] == ["waiter"]

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


def test_api_query_filters_for_tasks_timeline_and_insights() -> None:
    store = _build_filterable_store()
    server = PyroscopeServer(store, port=0)
    server.start()
    try:
        base = f"http://127.0.0.1:{server.port}"

        blocked_queue_tasks = cast(
            list[dict[str, Any]],
            _get_json(
                f"{base}/api/v1/tasks?state=BLOCKED&reason=queue_put&resource_id=queue:jobs"
            ),
        )
        assert [task["task_id"] for task in blocked_queue_tasks] == [2]

        main_tasks = cast(
            list[dict[str, Any]],
            _get_json(f"{base}/api/v1/tasks?role=main&limit=1"),
        )
        assert [task["task_id"] for task in main_tasks] == [1]

        paged_tasks = cast(
            list[dict[str, Any]],
            _get_json(f"{base}/api/v1/tasks?offset=1&limit=2"),
        )
        assert [task["task_id"] for task in paged_tasks] == [2, 3]

        searched_tasks = cast(
            list[dict[str, Any]],
            _get_json(f"{base}/api/v1/tasks?q=failing"),
        )
        assert [task["task_id"] for task in searched_tasks] == [5]

        filtered_timeline = cast(
            list[dict[str, Any]],
            _get_json(
                f"{base}/api/v1/timeline?state=BLOCKED&reason=queue_put&task_id=2&limit=1"
            ),
        )
        assert len(filtered_timeline) == 1
        assert filtered_timeline[0]["task_id"] == 2
        assert filtered_timeline[0]["reason"] == "queue_put"

        paged_timeline = cast(
            list[dict[str, Any]],
            _get_json(f"{base}/api/v1/timeline?offset=1&limit=2"),
        )
        assert len(paged_timeline) == 2
        assert [segment["task_id"] for segment in paged_timeline] == [1, 2]

        cancelled_insights = cast(
            list[dict[str, Any]],
            _get_json(f"{base}/api/v1/insights?kind=task_cancelled&task_id=3&limit=1"),
        )
        assert len(cancelled_insights) == 1
        assert cancelled_insights[0]["kind"] == "task_cancelled"
        assert cancelled_insights[0]["task_id"] == 3

        error_insights = cast(
            list[dict[str, Any]],
            _get_json(f"{base}/api/v1/insights?severity=error"),
        )
        assert error_insights
        assert all(item["severity"] == "error" for item in error_insights)
        assert any(item["kind"] == "task_error" for item in error_insights)

        paged_insights = cast(
            list[dict[str, Any]],
            _get_json(f"{base}/api/v1/insights?offset=1&limit=2"),
        )
        assert len(paged_insights) == 2

        queue_resources = cast(
            list[dict[str, Any]],
            _get_json(
                f"{base}/api/v1/resources/graph?resource_id=queue:jobs&task_id=2&limit=1"
            ),
        )
        assert queue_resources == [{"resource_id": "queue:jobs", "task_ids": [2]}]

        paged_resources = cast(
            list[dict[str, Any]],
            _get_json(f"{base}/api/v1/resources/graph?offset=1&limit=1"),
        )
        assert len(paged_resources) == 1
    finally:
        server.stop()


def test_tasks_api_supports_request_and_job_label_filters() -> None:
    store = SessionStore("api-labels")
    store.append_event(
        Event(
            session_id=store.session_id,
            seq=store.next_seq(),
            ts_ns=10,
            kind="task.create",
            task_id=1,
            task_name="request-main",
            state="READY",
            metadata={
                "request_label": "GET /jobs/42",
                "job_label": "job-42",
            },
        )
    )
    store.append_event(
        Event(
            session_id=store.session_id,
            seq=store.next_seq(),
            ts_ns=20,
            kind="task.create",
            task_id=2,
            task_name="other-request",
            state="READY",
            metadata={
                "request_label": "POST /jobs",
                "job_label": "job-43",
            },
        )
    )
    server = PyroscopeServer(store, port=0)
    server.start()
    try:
        base = f"http://127.0.0.1:{server.port}"
        request_tasks = cast(
            list[dict[str, Any]],
            _get_json(f"{base}/api/v1/tasks?request_label=GET%20/jobs/42"),
        )
        assert [task["task_id"] for task in request_tasks] == [1]

        job_tasks = cast(
            list[dict[str, Any]],
            _get_json(f"{base}/api/v1/tasks?job_label=job-43"),
        )
        assert [task["task_id"] for task in job_tasks] == [2]
    finally:
        server.stop()


def test_api_rejects_invalid_integer_query_params() -> None:
    store = _build_filterable_store()
    server = PyroscopeServer(store, port=0)
    server.start()
    try:
        base = f"http://127.0.0.1:{server.port}"
        invalid_urls = [
            f"{base}/api/v1/tasks?offset=oops",
            f"{base}/api/v1/timeline?task_id=nope",
            f"{base}/api/v1/insights?limit=NaN",
            f"{base}/api/v1/resources/graph?task_id=bad",
        ]
        for url in invalid_urls:
            try:
                urllib.request.urlopen(url)
            except urllib.error.HTTPError as exc:
                assert exc.code == 400
            else:
                raise AssertionError(f"expected 400 for {url}")
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


def test_replay_fixture_preserves_main_task_metadata_in_api_payloads() -> None:
    live_store = SessionStore("live")
    server = PyroscopeServer(live_store, port=0)
    server.start()
    try:
        fixture = json.loads(
            (Path(__file__).parent / "fixtures" / "replay_capture.json").read_text()
        )
        body = json.dumps(fixture).encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.port}/api/v1/replay/load",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request):
            pass

        main_task = cast(
            dict[str, Any],
            _get_json(f"http://127.0.0.1:{server.port}/api/v1/tasks/10"),
        )
        assert main_task["name"] == "sample"
        assert main_task["metadata"]["task_role"] == "main"
        assert main_task["metadata"]["runtime_origin"] == "asyncio.run"

        session_payload = cast(
            dict[str, Any],
            _get_json(f"http://127.0.0.1:{server.port}/api/v1/session"),
        )
        replayed_main_task = next(
            task for task in session_payload["tasks"] if task["task_id"] == 10
        )
        assert replayed_main_task["metadata"]["task_role"] == "main"
    finally:
        server.stop()


def test_task_detail_and_insights_include_cancellation_context() -> None:
    store = _build_cancellation_store()
    server = PyroscopeServer(store, port=0)
    server.start()
    try:
        base = f"http://127.0.0.1:{server.port}"

        task_payload = cast(dict[str, Any], _get_json(f"{base}/api/v1/tasks/3"))
        assert task_payload["cancellation_origin"] == "sibling_failure"
        assert task_payload["cancelled_by_task_id"] == 2
        assert task_payload["cancellation_source"] == {
            "task_id": 2,
            "task_name": "failing-child",
            "state": "FAILED",
        }

        insights_payload = cast(
            list[dict[str, Any]], _get_json(f"{base}/api/v1/insights")
        )
        cancelled_insight = next(
            item for item in insights_payload if item["kind"] == "task_cancelled"
        )
        assert cancelled_insight["cancelled_by_task_id"] == 2
        assert cancelled_insight["cancellation_origin"] == "sibling_failure"
        assert "failing-child" in cancelled_insight["message"]
        chain_insight = next(
            item for item in insights_payload if item["kind"] == "cancellation_chain"
        )
        assert chain_insight["source_task_id"] == 2
        assert chain_insight["source_task_name"] == "failing-child"
        assert chain_insight["source_task_state"] == "FAILED"
        assert chain_insight["source_task_reason"] == "RuntimeError"
        assert chain_insight["source_task_error"] is None
        assert chain_insight["affected_task_ids"] == [3]
        assert chain_insight["affected_task_names"] == ["cancelled-child"]
        assert (
            "while waiting on queue_get (queue:shared) with queue 0/16"
            in chain_insight["message"]
        )
        assert chain_insight["blocked_reason"] == "queue_get"
        assert chain_insight["blocked_resource_id"] == "queue:shared"
        assert chain_insight["queue_size"] == 0
        assert chain_insight["queue_maxsize"] == 16
    finally:
        server.stop()


def test_timeout_cancellation_contract_is_served_through_api() -> None:
    store = _build_timeout_cancellation_store()
    server = PyroscopeServer(store, port=0)
    server.start()
    try:
        base = f"http://127.0.0.1:{server.port}"

        task_payload = cast(dict[str, Any], _get_json(f"{base}/api/v1/tasks/2"))
        assert task_payload["cancellation_origin"] == "timeout"
        assert task_payload["cancelled_by_task_id"] == 1
        assert task_payload["metadata"]["timeout_seconds"] == 0.01
        assert task_payload["cancellation_source"] == {
            "task_id": 1,
            "task_name": "sample",
            "state": "RUNNING",
        }

        insights_payload = cast(
            list[dict[str, Any]], _get_json(f"{base}/api/v1/insights")
        )
        cancelled_insight = next(
            item for item in insights_payload if item["kind"] == "task_cancelled"
        )
        assert cancelled_insight["cancellation_origin"] == "timeout"
        assert cancelled_insight["timeout_seconds"] == 0.01
        assert "wait_for timeout 0.01s" in cancelled_insight["message"]

        chain_insight = next(
            item for item in insights_payload if item["kind"] == "cancellation_chain"
        )
        assert chain_insight["source_task_id"] == 1
        assert chain_insight["affected_task_ids"] == [2]
        assert chain_insight["timeout_seconds"] == 0.01
        assert "wait_for timeout 0.01s" in chain_insight["message"]
    finally:
        server.stop()


def test_gather_and_fanout_insights_are_served_through_api() -> None:
    store = _build_gather_and_fanout_store()
    server = PyroscopeServer(store, port=0)
    server.start()
    try:
        insights_payload = cast(
            list[dict[str, Any]],
            _get_json(f"http://127.0.0.1:{server.port}/api/v1/insights"),
        )
        gather_insight = next(
            item for item in insights_payload if item["kind"] == "stalled_gather_group"
        )
        assert gather_insight["task_id"] == 1
        assert gather_insight["slow_task_id"] == 3
        assert gather_insight["slow_task_name"] == "slow-child"
        assert gather_insight["child_task_ids"] == [2, 3, 4, 5, 6, 7]
        assert gather_insight["duration_ms"] >= 200

        fan_out_insight = next(
            item for item in insights_payload if item["kind"] == "fan_out_explosion"
        )
        assert fan_out_insight["task_id"] == 1
        assert fan_out_insight["child_count"] == 6
        assert fan_out_insight["child_task_ids"] == [2, 3, 4, 5, 6, 7]
    finally:
        server.stop()


def test_resource_cancellation_context_is_served_through_api() -> None:
    store = _build_resource_cancellation_store()
    server = PyroscopeServer(store, port=0)
    server.start()
    try:
        base = f"http://127.0.0.1:{server.port}"

        task_payload = cast(dict[str, Any], _get_json(f"{base}/api/v1/tasks/2"))
        assert task_payload["metadata"]["blocked_reason"] == "queue_get"
        assert task_payload["metadata"]["blocked_resource_id"] == "queue:123"

        insights_payload = cast(
            list[dict[str, Any]], _get_json(f"{base}/api/v1/insights")
        )
        cancelled_insight = next(
            item for item in insights_payload if item["kind"] == "task_cancelled"
        )
        assert cancelled_insight["blocked_reason"] == "queue_get"
        assert cancelled_insight["blocked_resource_id"] == "queue:123"
        assert cancelled_insight["queue_size"] == 0
        assert cancelled_insight["queue_maxsize"] == 16
        assert "while waiting on queue_get (queue:123)" in cancelled_insight["message"]
    finally:
        server.stop()


def test_resource_level_insights_are_served_through_api() -> None:
    store = _build_resource_insight_store()
    server = PyroscopeServer(store, port=0)
    server.start()
    try:
        insights_payload = cast(
            list[dict[str, Any]],
            _get_json(f"http://127.0.0.1:{server.port}/api/v1/insights"),
        )

        queue_insight = next(
            item for item in insights_payload if item["kind"] == "queue_backpressure"
        )
        assert queue_insight["resource_id"] == "queue:1"
        assert queue_insight["blocked_task_ids"] == [1, 2]
        assert queue_insight["owner_count"] == 0
        assert queue_insight["waiter_count"] == 2
        assert queue_insight["cancelled_waiter_count"] == 0

        lock_insight = next(
            item for item in insights_payload if item["kind"] == "lock_contention"
        )
        assert lock_insight["resource_id"] == "lock:1"
        assert lock_insight["blocked_task_ids"] == [3, 4]
        assert lock_insight["owner_count"] == 1
        assert lock_insight["waiter_count"] == 2
        assert lock_insight["cancelled_waiter_count"] == 0
        assert lock_insight["owner_task_ids"] == [8]
        assert lock_insight["owner_task_names"] == ["lock-holder"]
        assert "held by lock-holder" in lock_insight["message"]

        semaphore_insight = next(
            item for item in insights_payload if item["kind"] == "semaphore_saturation"
        )
        assert semaphore_insight["resource_id"] == "semaphore:1"
        assert semaphore_insight["blocked_task_ids"] == [5, 6, 7]
        assert semaphore_insight["owner_count"] == 1
        assert semaphore_insight["waiter_count"] == 3
        assert semaphore_insight["cancelled_waiter_count"] == 0
        assert semaphore_insight["owner_task_ids"] == [9]
        assert semaphore_insight["owner_task_names"] == ["sem-holder"]
        assert "held by sem-holder" in semaphore_insight["message"]
    finally:
        server.stop()


def test_replay_root_edge_case_fixtures_are_served_through_api() -> None:
    live_store = SessionStore("live")
    server = PyroscopeServer(live_store, port=0)
    server.start()
    try:
        fixtures_dir = Path(__file__).parent / "fixtures"
        for filename, task_id, expected_state in (
            ("replay_root_failed.json", 21, "FAILED"),
            ("replay_root_cancelled.json", 31, "CANCELLED"),
        ):
            fixture = json.loads((fixtures_dir / filename).read_text())
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.port}/api/v1/replay/load",
                data=json.dumps(fixture).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request):
                pass

            task_payload = cast(
                dict[str, Any],
                _get_json(f"http://127.0.0.1:{server.port}/api/v1/tasks/{task_id}"),
            )
            assert task_payload["state"] == expected_state
            assert task_payload["metadata"]["task_role"] == "main"
            assert task_payload["metadata"]["runtime_origin"] == "asyncio.run"
            assert task_payload["parent_task_id"] is None
    finally:
        server.stop()


def test_timeout_replay_fixture_is_served_through_api() -> None:
    live_store = SessionStore("live")
    server = PyroscopeServer(live_store, port=0)
    server.start()
    try:
        fixture = json.loads(
            (
                Path(__file__).parent / "fixtures" / "replay_timeout_cancel.json"
            ).read_text()
        )
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.port}/api/v1/replay/load",
            data=json.dumps(fixture).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request):
            pass

        task_payload = cast(
            dict[str, Any],
            _get_json(f"http://127.0.0.1:{server.port}/api/v1/tasks/42"),
        )
        assert task_payload["state"] == "CANCELLED"
        assert task_payload["cancellation_origin"] == "timeout"
        assert task_payload["metadata"]["timeout_seconds"] == 0.01

        insights_payload = cast(
            list[dict[str, Any]],
            _get_json(f"http://127.0.0.1:{server.port}/api/v1/insights"),
        )
        cancelled_insight = next(
            item for item in insights_payload if item["kind"] == "task_cancelled"
        )
        assert cancelled_insight["timeout_seconds"] == 0.01
        chain_insight = next(
            item for item in insights_payload if item["kind"] == "cancellation_chain"
        )
        assert chain_insight["reason"] == "timeout"
        assert chain_insight["affected_task_ids"] == [42]
    finally:
        server.stop()


def test_gather_fanout_and_resource_contention_fixtures_are_served_through_api() -> (
    None
):
    live_store = SessionStore("live")
    server = PyroscopeServer(live_store, port=0)
    server.start()
    try:
        fixtures_dir = Path(__file__).parent / "fixtures"
        for filename, expected_kinds in (
            (
                "replay_gather_fanout.json",
                {"stalled_gather_group", "fan_out_explosion"},
            ),
            (
                "replay_resource_contention.json",
                {
                    "queue_backpressure",
                    "lock_contention",
                    "semaphore_saturation",
                },
            ),
        ):
            fixture = json.loads((fixtures_dir / filename).read_text())
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.port}/api/v1/replay/load",
                data=json.dumps(fixture).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request):
                pass

            insights_payload = cast(
                list[dict[str, Any]],
                _get_json(f"http://127.0.0.1:{server.port}/api/v1/insights"),
            )
            insight_kinds = {item["kind"] for item in insights_payload}
            assert expected_kinds.issubset(insight_kinds)
    finally:
        server.stop()


def test_queue_put_backpressure_fixture_is_served_through_api() -> None:
    live_store = SessionStore("live")
    server = PyroscopeServer(live_store, port=0)
    server.start()
    try:
        fixture = json.loads(
            (
                Path(__file__).parent
                / "fixtures"
                / "replay_queue_put_backpressure.json"
            ).read_text()
        )
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.port}/api/v1/replay/load",
            data=json.dumps(fixture).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request):
            pass

        task_payload = cast(
            dict[str, Any],
            _get_json(f"http://127.0.0.1:{server.port}/api/v1/tasks/151"),
        )
        assert task_payload["reason"] == "queue_put"
        assert task_payload["resource_id"] == "queue:bounded"

        insights_payload = cast(
            list[dict[str, Any]],
            _get_json(f"http://127.0.0.1:{server.port}/api/v1/insights"),
        )
        queue_insight = next(
            item for item in insights_payload if item["kind"] == "queue_backpressure"
        )
        assert queue_insight["reason"] == "queue_put"
        assert queue_insight["resource_id"] == "queue:bounded"
        assert queue_insight["blocked_task_ids"] == [151, 152]
    finally:
        server.stop()


def test_mixed_queue_contention_fixture_is_served_through_api() -> None:
    live_store = SessionStore("live")
    server = PyroscopeServer(live_store, port=0)
    server.start()
    try:
        fixture = json.loads(
            (
                Path(__file__).parent
                / "fixtures"
                / "replay_queue_mixed_contention.json"
            ).read_text()
        )
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.port}/api/v1/replay/load",
            data=json.dumps(fixture).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request):
            pass

        resources_payload = cast(
            list[dict[str, Any]],
            _get_json(f"http://127.0.0.1:{server.port}/api/v1/resources/graph"),
        )
        assert resources_payload == fixture["resources"]

        producer_task = cast(
            dict[str, Any],
            _get_json(f"http://127.0.0.1:{server.port}/api/v1/tasks/403"),
        )
        assert producer_task["reason"] == "queue_put"
        assert producer_task["resource_id"] == "queue:mixed"

        insights_payload = cast(
            list[dict[str, Any]],
            _get_json(f"http://127.0.0.1:{server.port}/api/v1/insights"),
        )
        queue_insight = next(
            item for item in insights_payload if item["kind"] == "queue_backpressure"
        )
        assert queue_insight["resource_id"] == "queue:mixed"
        assert queue_insight["blocked_task_ids"] == [401, 402, 403, 404]
        assert {"consumer-a", "consumer-b", "producer-a", "producer-b"}.issubset(
            set(queue_insight["blocked_task_names"])
        )
    finally:
        server.stop()


def test_queue_contention_cancel_fixture_is_served_through_api() -> None:
    live_store = SessionStore("live")
    server = PyroscopeServer(live_store, port=0)
    server.start()
    try:
        fixture = json.loads(
            (
                Path(__file__).parent
                / "fixtures"
                / "replay_queue_contention_cancel.json"
            ).read_text()
        )
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.port}/api/v1/replay/load",
            data=json.dumps(fixture).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request):
            pass

        resources_payload = cast(
            list[dict[str, Any]],
            _get_json(f"http://127.0.0.1:{server.port}/api/v1/resources/graph"),
        )
        assert resources_payload == fixture["resources"]

        cancelled_task = cast(
            dict[str, Any],
            _get_json(f"http://127.0.0.1:{server.port}/api/v1/tasks/703"),
        )
        assert cancelled_task["cancellation_origin"] == "parent_task"
        assert cancelled_task["metadata"]["blocked_resource_id"] == "queue:shared"

        insights_payload = cast(
            list[dict[str, Any]],
            _get_json(f"http://127.0.0.1:{server.port}/api/v1/insights"),
        )
        queue_insight = next(
            item for item in insights_payload if item["kind"] == "queue_backpressure"
        )
        assert queue_insight["resource_id"] == "queue:shared"
        assert queue_insight["blocked_task_ids"] == [701, 702]

        cancelled_insight = next(
            item for item in insights_payload if item["kind"] == "task_cancelled"
        )
        assert cancelled_insight["task_id"] == 703
        assert cancelled_insight["blocked_resource_id"] == "queue:shared"
    finally:
        server.stop()


def test_queue_and_semaphore_contention_cancel_fixture_is_served_through_api() -> None:
    live_store = SessionStore("live")
    server = PyroscopeServer(live_store, port=0)
    server.start()
    try:
        fixture = json.loads(
            (
                Path(__file__).parent
                / "fixtures"
                / "replay_queue_semaphore_contention_cancel.json"
            ).read_text()
        )
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.port}/api/v1/replay/load",
            data=json.dumps(fixture).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request):
            pass

        resources_payload = cast(
            list[dict[str, Any]],
            _get_json(f"http://127.0.0.1:{server.port}/api/v1/resources/graph"),
        )
        assert resources_payload == fixture["resources"]

        detailed_resources_payload = cast(
            list[dict[str, Any]],
            _get_json(
                f"http://127.0.0.1:{server.port}/api/v1/resources/graph?detail=detailed"
            ),
        )
        assert detailed_resources_payload == [
            {
                "resource_id": "queue:shared",
                "task_ids": [901, 902],
                "owner_task_ids": [],
                "waiter_task_ids": [901, 902],
                "cancelled_waiter_task_ids": [905],
            },
            {
                "resource_id": "semaphore:gate",
                "task_ids": [903, 904],
                "owner_task_ids": [],
                "waiter_task_ids": [903, 904],
                "cancelled_waiter_task_ids": [906],
            },
        ]

        insights_payload = cast(
            list[dict[str, Any]],
            _get_json(f"http://127.0.0.1:{server.port}/api/v1/insights"),
        )
        queue_insight = next(
            item for item in insights_payload if item["kind"] == "queue_backpressure"
        )
        assert queue_insight["resource_id"] == "queue:shared"
        assert queue_insight["blocked_task_ids"] == [901, 902]

        semaphore_insight = next(
            item for item in insights_payload if item["kind"] == "semaphore_saturation"
        )
        assert semaphore_insight["resource_id"] == "semaphore:gate"
        assert semaphore_insight["blocked_task_ids"] == [903, 904]

        cancelled_tasks = {
            task_id: cast(
                dict[str, Any],
                _get_json(f"http://127.0.0.1:{server.port}/api/v1/tasks/{task_id}"),
            )
            for task_id in (905, 906)
        }
        assert cancelled_tasks[905]["metadata"]["blocked_resource_id"] == "queue:shared"
        assert (
            cancelled_tasks[906]["metadata"]["blocked_resource_id"] == "semaphore:gate"
        )
    finally:
        server.stop()


def test_resource_graph_detailed_serves_owner_waiter_split() -> None:
    store = SessionStore("resource-owners")
    store.append_event(
        Event(
            session_id=store.session_id,
            seq=store.next_seq(),
            ts_ns=10,
            kind="task.create",
            task_id=1,
            task_name="lock-holder",
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
            task_name="lock-holder",
            state="RUNNING",
            resource_id="lock:shared",
        )
    )
    store.append_event(
        Event(
            session_id=store.session_id,
            seq=store.next_seq(),
            ts_ns=30,
            kind="task.create",
            task_id=2,
            task_name="lock-waiter",
            state="READY",
        )
    )
    store.append_event(
        Event(
            session_id=store.session_id,
            seq=store.next_seq(),
            ts_ns=40,
            kind="task.block",
            task_id=2,
            task_name="lock-waiter",
            state="BLOCKED",
            reason="lock_acquire",
            resource_id="lock:shared",
        )
    )
    store.append_event(
        Event(
            session_id=store.session_id,
            seq=store.next_seq(),
            ts_ns=50,
            kind="task.create",
            task_id=3,
            task_name="cancelled-waiter",
            state="READY",
        )
    )
    store.append_event(
        Event(
            session_id=store.session_id,
            seq=store.next_seq(),
            ts_ns=60,
            kind="task.cancel",
            task_id=3,
            task_name="cancelled-waiter",
            state="CANCELLED",
            reason="cancelled",
            metadata={
                "blocked_reason": "lock_acquire",
                "blocked_resource_id": "lock:shared",
            },
        )
    )

    server = PyroscopeServer(store, port=0)
    server.start()
    try:
        payload = cast(
            list[dict[str, Any]],
            _get_json(
                f"http://127.0.0.1:{server.port}/api/v1/resources/graph?detail=detailed"
            ),
        )
        assert payload == [
            {
                "resource_id": "lock:shared",
                "task_ids": [1, 2],
                "owner_task_ids": [1],
                "waiter_task_ids": [2],
                "cancelled_waiter_task_ids": [3],
            }
        ]
        owner_task = cast(
            dict[str, Any],
            _get_json(f"http://127.0.0.1:{server.port}/api/v1/tasks/1"),
        )
        waiter_task = cast(
            dict[str, Any],
            _get_json(f"http://127.0.0.1:{server.port}/api/v1/tasks/2"),
        )
        cancelled_task = cast(
            dict[str, Any],
            _get_json(f"http://127.0.0.1:{server.port}/api/v1/tasks/3"),
        )
        assert owner_task["resource_roles"] == ["owner"]
        assert waiter_task["resource_roles"] == ["waiter"]
        assert cancelled_task["resource_roles"] == ["cancelled waiter"]
    finally:
        server.stop()


def test_mixed_and_root_group_failure_fixtures_are_served_through_api() -> None:
    live_store = SessionStore("live")
    server = PyroscopeServer(live_store, port=0)
    server.start()
    try:
        fixtures_dir = Path(__file__).parent / "fixtures"
        for filename, root_task_id, expected_root_state in (
            ("replay_mixed_taskgroup.json", 51, "DONE"),
            ("replay_root_group_failed.json", 61, "FAILED"),
        ):
            fixture = json.loads((fixtures_dir / filename).read_text())
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.port}/api/v1/replay/load",
                data=json.dumps(fixture).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request):
                pass

            task_payload = cast(
                dict[str, Any],
                _get_json(
                    f"http://127.0.0.1:{server.port}/api/v1/tasks/{root_task_id}"
                ),
            )
            assert task_payload["state"] == expected_root_state

            insights_payload = cast(
                list[dict[str, Any]],
                _get_json(f"http://127.0.0.1:{server.port}/api/v1/insights"),
            )
            insight_kinds = {item["kind"] for item in insights_payload}
            assert "task_error" in insight_kinds
            assert "cancellation_chain" in insight_kinds
    finally:
        server.stop()


def test_parent_and_external_child_cancellation_fixtures_are_served_through_api() -> (
    None
):
    live_store = SessionStore("live")
    server = PyroscopeServer(live_store, port=0)
    server.start()
    try:
        fixtures_dir = Path(__file__).parent / "fixtures"
        for filename, task_id, expected_origin in (
            ("replay_parent_cancel.json", 92, "parent_task"),
            ("replay_external_child_mix.json", 102, "external"),
        ):
            fixture = json.loads((fixtures_dir / filename).read_text())
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.port}/api/v1/replay/load",
                data=json.dumps(fixture).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request):
                pass

            task_payload = cast(
                dict[str, Any],
                _get_json(f"http://127.0.0.1:{server.port}/api/v1/tasks/{task_id}"),
            )
            assert task_payload["cancellation_origin"] == expected_origin

            insights_payload = cast(
                list[dict[str, Any]],
                _get_json(f"http://127.0.0.1:{server.port}/api/v1/insights"),
            )
            cancelled_insight = next(
                item for item in insights_payload if item["kind"] == "task_cancelled"
            )
            assert cancelled_insight["cancellation_origin"] == expected_origin

        fixture = json.loads(
            (fixtures_dir / "replay_external_child_mix.json").read_text()
        )
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.port}/api/v1/replay/load",
            data=json.dumps(fixture).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request):
            pass
        insights_payload = cast(
            list[dict[str, Any]],
            _get_json(f"http://127.0.0.1:{server.port}/api/v1/insights"),
        )
        chain_insight = next(
            item
            for item in insights_payload
            if item["kind"] == "cancellation_chain" and item["reason"] == "parent_task"
        )
        assert chain_insight["source_task_id"] == 101
        assert chain_insight["affected_task_ids"] == [103]
    finally:
        server.stop()


def test_event_wait_and_semaphore_fixtures_are_served_through_api() -> None:
    live_store = SessionStore("live")
    server = PyroscopeServer(live_store, port=0)
    server.start()
    try:
        fixtures_dir = Path(__file__).parent / "fixtures"
        for filename, task_id, expected_origin, expected_reason in (
            ("replay_event_wait_cancel.json", 112, "external", "event_wait"),
            ("replay_semaphore_cancel.json", 122, "parent_task", "semaphore_acquire"),
        ):
            fixture = json.loads((fixtures_dir / filename).read_text())
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.port}/api/v1/replay/load",
                data=json.dumps(fixture).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request):
                pass

            task_payload = cast(
                dict[str, Any],
                _get_json(f"http://127.0.0.1:{server.port}/api/v1/tasks/{task_id}"),
            )
            assert task_payload["cancellation_origin"] == expected_origin
            assert task_payload["metadata"]["blocked_reason"] == expected_reason

            insights_payload = cast(
                list[dict[str, Any]],
                _get_json(f"http://127.0.0.1:{server.port}/api/v1/insights"),
            )
            cancelled_insight = next(
                item for item in insights_payload if item["kind"] == "task_cancelled"
            )
            assert cancelled_insight["cancellation_origin"] == expected_origin
            assert cancelled_insight["blocked_reason"] == expected_reason
    finally:
        server.stop()


def test_replay_multi_root_fixture_preserves_multiple_root_tasks_in_api() -> None:
    live_store = SessionStore("live")
    server = PyroscopeServer(live_store, port=0)
    server.start()
    try:
        fixture = json.loads(
            (Path(__file__).parent / "fixtures" / "replay_multi_root.json").read_text()
        )
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.port}/api/v1/replay/load",
            data=json.dumps(fixture).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request):
            pass

        session_payload = cast(
            dict[str, Any],
            _get_json(f"http://127.0.0.1:{server.port}/api/v1/session"),
        )
        root_tasks = [
            task for task in session_payload["tasks"] if task["parent_task_id"] is None
        ]
        assert [task["task_id"] for task in root_tasks] == [131, 132]

        root_beta = cast(
            dict[str, Any],
            _get_json(f"http://127.0.0.1:{server.port}/api/v1/tasks/132"),
        )
        assert root_beta["cancellation_origin"] == "external"
        assert root_beta["stack"]["stack_id"] == "stack_root_beta"
    finally:
        server.stop()


def test_replay_load_replaces_state_between_distinct_comparison_fixtures() -> None:
    live_store = SessionStore("live")
    server = PyroscopeServer(live_store, port=0)
    server.start()
    try:
        fixtures_dir = Path(__file__).parent / "fixtures"
        baseline_fixture = json.loads(
            (fixtures_dir / "replay_capture.json").read_text()
        )
        regression_fixture = json.loads(
            (fixtures_dir / "replay_compare_regression.json").read_text()
        )

        for fixture in (baseline_fixture, regression_fixture):
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.port}/api/v1/replay/load",
                data=json.dumps(fixture).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request):
                pass

        session_payload = cast(
            dict[str, Any],
            _get_json(f"http://127.0.0.1:{server.port}/api/v1/session"),
        )
        assert (
            session_payload["session"]["session_name"] == "fixture-compare-regression"
        )
        assert sorted(task["task_id"] for task in session_payload["tasks"]) == [
            141,
            142,
            143,
        ]

        try:
            urllib.request.urlopen(f"http://127.0.0.1:{server.port}/api/v1/tasks/10")
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
        else:
            raise AssertionError(
                "expected old replay task to disappear after replacement"
            )

        insights_payload = cast(
            list[dict[str, Any]],
            _get_json(f"http://127.0.0.1:{server.port}/api/v1/insights"),
        )
        queue_insight = next(
            item for item in insights_payload if item["kind"] == "queue_backpressure"
        )
        assert queue_insight["resource_id"] == "queue:1"
        assert queue_insight["blocked_task_ids"] == [141, 142, 143]
    finally:
        server.stop()


def test_replay_load_replaces_resource_graphs_across_drifted_sessions() -> None:
    live_store = SessionStore("live")
    server = PyroscopeServer(live_store, port=0)
    server.start()
    try:
        fixtures_dir = Path(__file__).parent / "fixtures"
        baseline_fixture = json.loads(
            (fixtures_dir / "replay_drift_baseline.json").read_text()
        )
        shifted_fixture = json.loads(
            (fixtures_dir / "replay_drift_shifted.json").read_text()
        )

        for fixture in (baseline_fixture, shifted_fixture):
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.port}/api/v1/replay/load",
                data=json.dumps(fixture).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request):
                pass

        session_payload = cast(
            dict[str, Any],
            _get_json(f"http://127.0.0.1:{server.port}/api/v1/session"),
        )
        assert session_payload["session"]["session_name"] == "fixture-drift-shifted"
        assert sorted(task["task_id"] for task in session_payload["tasks"]) == [
            301,
            302,
            303,
            304,
        ]

        resources_payload = cast(
            list[dict[str, Any]],
            _get_json(f"http://127.0.0.1:{server.port}/api/v1/resources/graph"),
        )
        assert resources_payload == shifted_fixture["resources"]

        try:
            urllib.request.urlopen(f"http://127.0.0.1:{server.port}/api/v1/tasks/201")
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
        else:
            raise AssertionError(
                "expected baseline replay task to disappear after drift replacement"
            )

        resource_ids = {item["resource_id"] for item in resources_payload}
        assert resource_ids == {"queue:outgoing", "semaphore:workers"}
        assert "queue:incoming" not in resource_ids
        assert "lock:shared" not in resource_ids

        insights_payload = cast(
            list[dict[str, Any]],
            _get_json(f"http://127.0.0.1:{server.port}/api/v1/insights"),
        )
        insight_kinds = {item["kind"] for item in insights_payload}
        assert {"queue_backpressure", "semaphore_saturation"}.issubset(insight_kinds)
        shifted_queue_insight = next(
            item for item in insights_payload if item["kind"] == "queue_backpressure"
        )
        assert shifted_queue_insight["reason"] == "queue_put"
        assert shifted_queue_insight["blocked_task_ids"] == [301, 302]
    finally:
        server.stop()


def test_replay_load_replaces_cancellation_chains_and_root_metadata_across_drifted_sessions() -> (
    None
):
    live_store = SessionStore("live")
    server = PyroscopeServer(live_store, port=0)
    server.start()
    try:
        fixtures_dir = Path(__file__).parent / "fixtures"
        baseline_fixture = json.loads(
            (fixtures_dir / "replay_drift_cancellation_baseline.json").read_text()
        )
        shifted_fixture = json.loads(
            (fixtures_dir / "replay_drift_cancellation_shifted.json").read_text()
        )

        for fixture in (baseline_fixture, shifted_fixture):
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.port}/api/v1/replay/load",
                data=json.dumps(fixture).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request):
                pass

        session_payload = cast(
            dict[str, Any],
            _get_json(f"http://127.0.0.1:{server.port}/api/v1/session"),
        )
        assert (
            session_payload["session"]["session_name"] == "fixture-drift-cancel-shifted"
        )
        assert sorted(task["task_id"] for task in session_payload["tasks"]) == [
            601,
            602,
            603,
        ]

        try:
            urllib.request.urlopen(f"http://127.0.0.1:{server.port}/api/v1/tasks/501")
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
        else:
            raise AssertionError(
                "expected baseline cancellation task to disappear after drift replacement"
            )

        root_task = cast(
            dict[str, Any],
            _get_json(f"http://127.0.0.1:{server.port}/api/v1/tasks/601"),
        )
        assert root_task["state"] == "FAILED"
        assert root_task["metadata"]["task_role"] == "main"
        assert root_task["metadata"]["runtime_origin"] == "asyncio.run"
        assert "ExceptionGroup" in root_task["metadata"]["error"]

        insights_payload = cast(
            list[dict[str, Any]],
            _get_json(f"http://127.0.0.1:{server.port}/api/v1/insights"),
        )
        insight_kinds = {item["kind"] for item in insights_payload}
        assert {"task_error", "cancellation_chain"}.issubset(insight_kinds)

        shifted_chain = next(
            item
            for item in insights_payload
            if item["kind"] == "cancellation_chain"
            and item["reason"] == "sibling_failure"
        )
        assert shifted_chain["source_task_id"] == 602
        assert shifted_chain["affected_task_ids"] == [603]
    finally:
        server.stop()


def test_replay_load_replaces_root_completion_mode_and_resource_edges() -> None:
    live_store = SessionStore("live")
    server = PyroscopeServer(live_store, port=0)
    server.start()
    try:
        fixtures_dir = Path(__file__).parent / "fixtures"
        baseline_fixture = json.loads(
            (fixtures_dir / "replay_root_resource_baseline.json").read_text()
        )
        shifted_fixture = json.loads(
            (fixtures_dir / "replay_root_resource_shifted.json").read_text()
        )

        for fixture in (baseline_fixture, shifted_fixture):
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.port}/api/v1/replay/load",
                data=json.dumps(fixture).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request):
                pass

        session_payload = cast(
            dict[str, Any],
            _get_json(f"http://127.0.0.1:{server.port}/api/v1/session"),
        )
        assert (
            session_payload["session"]["session_name"]
            == "fixture-root-resource-shifted"
        )
        assert sorted(task["task_id"] for task in session_payload["tasks"]) == [
            801,
            802,
        ]

        try:
            urllib.request.urlopen(f"http://127.0.0.1:{server.port}/api/v1/tasks/701")
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
        else:
            raise AssertionError(
                "expected baseline root task to disappear after replay replacement"
            )

        root_task = cast(
            dict[str, Any],
            _get_json(f"http://127.0.0.1:{server.port}/api/v1/tasks/801"),
        )
        assert root_task["state"] == "FAILED"
        assert root_task["metadata"]["task_role"] == "main"
        assert root_task["metadata"]["runtime_origin"] == "asyncio.run"
        assert "shifted root failed" in root_task["metadata"]["error"]

        resources_payload = cast(
            list[dict[str, Any]],
            _get_json(f"http://127.0.0.1:{server.port}/api/v1/resources/graph"),
        )
        assert resources_payload == shifted_fixture["resources"]
        resource_ids = {item["resource_id"] for item in resources_payload}
        assert resource_ids == {"event:gate"}
        assert "queue:jobs" not in resource_ids

        insights_payload = cast(
            list[dict[str, Any]],
            _get_json(f"http://127.0.0.1:{server.port}/api/v1/insights"),
        )
        shifted_error = next(
            item for item in insights_payload if item["kind"] == "task_error"
        )
        assert shifted_error["task_id"] == 801
    finally:
        server.stop()
