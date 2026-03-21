from __future__ import annotations

import json
import tempfile
from pathlib import Path

from pyroscope.model import Event
from pyroscope.session import SessionStore

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_appends_events_and_builds_segments() -> None:
    store = SessionStore("unit")
    store.append_event(
        Event(
            session_id=store.session_id,
            seq=store.next_seq(),
            ts_ns=10,
            kind="task.create",
            task_id=1,
            task_name="demo",
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
            task_name="demo",
            state="RUNNING",
        )
    )
    store.append_event(
        Event(
            session_id=store.session_id,
            seq=store.next_seq(),
            ts_ns=35,
            kind="task.block",
            task_id=1,
            task_name="demo",
            state="BLOCKED",
            reason="sleep",
        )
    )
    store.append_event(
        Event(
            session_id=store.session_id,
            seq=store.next_seq(),
            ts_ns=50,
            kind="task.end",
            task_id=1,
            task_name="demo",
            state="DONE",
        )
    )
    timeline = [item.to_dict() for item in store.timeline()]
    assert len(timeline) >= 3
    task = store.task(1)
    assert task is not None
    assert task["state"] == "DONE"


def test_save_and_replay_roundtrip() -> None:
    store = SessionStore("roundtrip")
    store.append_event(
        Event(
            session_id=store.session_id,
            seq=store.next_seq(),
            ts_ns=10,
            kind="task.create",
            task_id=7,
            task_name="x",
            state="READY",
        )
    )
    store.mark_completed()
    with tempfile.TemporaryDirectory() as tmp:
        path = store.save_json(f"{tmp}/capture.json")
        data = json.loads(path.read_text())
        replayed = SessionStore.from_capture(data)
        assert replayed.snapshot()["session"]["event_count"] == 1


def test_replay_fixture_restores_expected_snapshot_shape() -> None:
    fixture = json.loads((FIXTURES_DIR / "replay_capture.json").read_text())

    replayed = SessionStore.from_capture(fixture)
    snapshot = replayed.snapshot()

    assert snapshot["session"] == {
        "session_id": "sess_fixture123",
        "session_name": "fixture-replay",
        "started_ts_ns": 1000,
        "completed_ts_ns": 2000,
        "event_count": 7,
        "task_count": 2,
    }
    assert snapshot["tasks"] == [
        {
            "task_id": 10,
            "name": "sample",
            "parent_task_id": None,
            "children": [11],
            "state": "DONE",
            "created_ts_ns": 1010,
            "updated_ts_ns": 1060,
            "cancelled_by_task_id": None,
            "cancellation_origin": None,
            "reason": None,
            "resource_id": None,
            "stack_id": None,
            "end_ts_ns": 1060,
            "metadata": {
                "task_role": "main",
                "runtime_origin": "asyncio.run",
            },
        },
        {
            "task_id": 11,
            "name": "child",
            "parent_task_id": 10,
            "children": [],
            "state": "DONE",
            "created_ts_ns": 1020,
            "updated_ts_ns": 1050,
            "cancelled_by_task_id": None,
            "cancellation_origin": None,
            "reason": None,
            "resource_id": None,
            "stack_id": "stack_fixture_child",
            "end_ts_ns": 1050,
            "metadata": {},
        },
    ]
    assert snapshot["segments"] == fixture["snapshot"]["segments"]
    assert replayed.resource_graph() == fixture["resources"]
    main_task = replayed.task(10)
    assert main_task is not None
    assert main_task["metadata"]["task_role"] == "main"
    assert main_task["metadata"]["runtime_origin"] == "asyncio.run"
    child_task = replayed.task(11)
    assert child_task is not None
    assert child_task["stack"]["stack_id"] == "stack_fixture_child"


def test_fixture_replay_exports_stable_csv() -> None:
    fixture = json.loads((FIXTURES_DIR / "replay_capture.json").read_text())
    replayed = SessionStore.from_capture(fixture)

    with tempfile.TemporaryDirectory() as tmp:
        csv_path = replayed.export_csv(Path(tmp) / "timeline.csv")
        rows = csv_path.read_text().strip().splitlines()

    assert rows == [
        "task_id,task_name,start_ts_ns,end_ts_ns,state,reason,resource_id",
        "10,sample,1010,1030,READY,,",
        "11,child,1020,1030,READY,,",
        "10,sample,1030,1060,RUNNING,,",
        "11,child,1030,1040,RUNNING,,",
        "11,child,1040,1050,BLOCKED,sleep,sleep",
        "11,child,1050,2000,DONE,,",
        "10,sample,1060,2000,DONE,,",
    ]


def test_timeout_fixture_replay_preserves_cancellation_context_and_csv() -> None:
    fixture = json.loads((FIXTURES_DIR / "replay_timeout_cancel.json").read_text())
    replayed = SessionStore.from_capture(fixture)

    child_task = replayed.task(42)
    assert child_task is not None
    assert child_task["state"] == "CANCELLED"
    assert child_task["cancellation_origin"] == "timeout"
    assert child_task["cancelled_by_task_id"] == 41
    assert child_task["metadata"]["timeout_seconds"] == 0.01
    assert child_task["cancellation_source"] == {
        "task_id": 41,
        "task_name": "sample",
        "state": "DONE",
    }

    insights = replayed.insights()
    cancelled_insight = next(
        item for item in insights if item["kind"] == "task_cancelled"
    )
    assert cancelled_insight["timeout_seconds"] == 0.01
    assert "wait_for timeout 0.01s" in cancelled_insight["message"]
    chain_insight = next(
        item for item in insights if item["kind"] == "cancellation_chain"
    )
    assert chain_insight["reason"] == "timeout"
    assert chain_insight["source_task_id"] == 41
    assert chain_insight["affected_task_ids"] == [42]

    with tempfile.TemporaryDirectory() as tmp:
        csv_path = replayed.export_csv(Path(tmp) / "timeout.csv")
        rows = csv_path.read_text().strip().splitlines()

    assert rows == [
        "task_id,task_name,start_ts_ns,end_ts_ns,state,reason,resource_id",
        "41,sample,5010,5020,READY,,",
        "41,sample,5020,5060,RUNNING,,",
        "42,child_worker,5030,5040,READY,,",
        "42,child_worker,5040,5050,RUNNING,,",
        "42,child_worker,5050,5600,CANCELLED,cancelled,",
        "41,sample,5060,5600,DONE,,",
    ]


def test_gather_fanout_fixture_replay_preserves_insights() -> None:
    fixture = json.loads((FIXTURES_DIR / "replay_gather_fanout.json").read_text())
    replayed = SessionStore.from_capture(fixture)

    coordinator = replayed.task(71)
    assert coordinator is not None
    assert coordinator["children"] == [72, 73, 74, 75, 76, 77]
    assert replayed.resource_graph() == fixture["resources"]

    insights = replayed.insights()
    gather_insight = next(
        item for item in insights if item["kind"] == "stalled_gather_group"
    )
    assert gather_insight["task_id"] == 71
    assert gather_insight["slow_task_id"] == 73
    assert gather_insight["child_task_ids"] == [72, 73, 74, 75, 76, 77]

    fan_out_insight = next(
        item for item in insights if item["kind"] == "fan_out_explosion"
    )
    assert fan_out_insight["task_id"] == 71
    assert fan_out_insight["child_count"] == 6


def test_resource_contention_fixture_replay_preserves_insights() -> None:
    fixture = json.loads((FIXTURES_DIR / "replay_resource_contention.json").read_text())
    replayed = SessionStore.from_capture(fixture)

    assert replayed.resource_graph() == sorted(
        fixture["resources"], key=lambda item: item["resource_id"]
    )
    insights = replayed.insights()

    queue_insight = next(
        item for item in insights if item["kind"] == "queue_backpressure"
    )
    assert queue_insight["resource_id"] == "queue:1"
    assert queue_insight["blocked_task_ids"] == [81, 82]

    lock_insight = next(item for item in insights if item["kind"] == "lock_contention")
    assert lock_insight["resource_id"] == "lock:1"
    assert lock_insight["blocked_task_ids"] == [83, 84]

    semaphore_insight = next(
        item for item in insights if item["kind"] == "semaphore_saturation"
    )
    assert semaphore_insight["resource_id"] == "semaphore:1"
    assert semaphore_insight["blocked_task_ids"] == [85, 86, 87]


def test_builds_grouped_cancellation_chain_insight() -> None:
    store = SessionStore("cancellation-chain")
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
    for task_id, task_name in ((3, "long-child-a"), (4, "long-child-b")):
        store.append_event(
            Event(
                session_id=store.session_id,
                seq=store.next_seq(),
                ts_ns=50 + task_id,
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
                ts_ns=60 + task_id,
                kind="task.cancel",
                task_id=task_id,
                task_name=task_name,
                parent_task_id=1,
                cancelled_by_task_id=2,
                cancellation_origin="sibling_failure",
                state="CANCELLED",
                reason="cancelled",
            )
        )
    store.mark_completed()

    cancellation_chain = next(
        item for item in store.insights() if item["kind"] == "cancellation_chain"
    )
    assert cancellation_chain == {
        "kind": "cancellation_chain",
        "task_id": 2,
        "severity": "warning",
        "message": (
            "Task failing-child triggered cancellation of 2 sibling tasks: "
            "long-child-a, long-child-b"
        ),
        "reason": "sibling_failure",
        "source_task_id": 2,
        "source_task_name": "failing-child",
        "affected_task_ids": [3, 4],
        "affected_task_names": ["long-child-a", "long-child-b"],
        "parent_task_id": 1,
        "timeout_seconds": None,
    }


def test_replay_root_failed_fixture_preserves_main_error_contract() -> None:
    fixture = json.loads((FIXTURES_DIR / "replay_root_failed.json").read_text())
    replayed = SessionStore.from_capture(fixture)

    main_task = replayed.task(21)
    assert main_task is not None
    assert main_task["state"] == "FAILED"
    assert main_task["parent_task_id"] is None
    assert main_task["metadata"]["task_role"] == "main"
    assert main_task["metadata"]["runtime_origin"] == "asyncio.run"
    assert main_task["metadata"]["error"] == "RuntimeError('boom')"
    assert main_task["stack"]["stack_id"] == "stack_root_failed"


def test_replay_root_cancelled_fixture_preserves_main_cancel_contract() -> None:
    fixture = json.loads((FIXTURES_DIR / "replay_root_cancelled.json").read_text())
    replayed = SessionStore.from_capture(fixture)

    main_task = replayed.task(31)
    assert main_task is not None
    assert main_task["state"] == "CANCELLED"
    assert main_task["parent_task_id"] is None
    assert main_task["metadata"]["task_role"] == "main"
    assert main_task["metadata"]["runtime_origin"] == "asyncio.run"
    assert main_task["cancellation_origin"] == "external"
    insights = replayed.insights()
    cancelled_insight = next(
        item for item in insights if item["kind"] == "task_cancelled"
    )
    assert cancelled_insight["task_id"] == 31
    assert cancelled_insight["cancellation_origin"] == "external"


def test_mixed_taskgroup_fixture_preserves_error_and_cancellation_contracts() -> None:
    fixture = json.loads((FIXTURES_DIR / "replay_mixed_taskgroup.json").read_text())
    replayed = SessionStore.from_capture(fixture)

    root_task = replayed.task(51)
    assert root_task is not None
    assert root_task["state"] == "DONE"
    assert root_task["children"] == [52, 53, 54]

    failed_child = replayed.task(52)
    assert failed_child is not None
    assert failed_child["state"] == "FAILED"
    assert failed_child["metadata"]["error"] == "RuntimeError('boom')"

    cancelled_child = replayed.task(53)
    assert cancelled_child is not None
    assert cancelled_child["state"] == "CANCELLED"
    assert cancelled_child["cancelled_by_task_id"] == 52
    assert cancelled_child["cancellation_origin"] == "sibling_failure"

    insights = replayed.insights()
    assert {item["kind"] for item in insights} >= {
        "task_error",
        "task_cancelled",
        "cancellation_chain",
    }


def test_root_group_failed_fixture_preserves_root_and_child_failures() -> None:
    fixture = json.loads((FIXTURES_DIR / "replay_root_group_failed.json").read_text())
    replayed = SessionStore.from_capture(fixture)

    root_task = replayed.task(61)
    assert root_task is not None
    assert root_task["state"] == "FAILED"
    assert root_task["metadata"]["task_role"] == "main"
    assert root_task["metadata"]["runtime_origin"] == "asyncio.run"
    assert "ExceptionGroup" in root_task["metadata"]["error"]

    failed_child = replayed.task(62)
    assert failed_child is not None
    assert failed_child["state"] == "FAILED"
    cancelled_sibling = replayed.task(63)
    assert cancelled_sibling is not None
    assert cancelled_sibling["state"] == "CANCELLED"
    assert cancelled_sibling["cancelled_by_task_id"] == 62

    error_task_ids = sorted(
        item["task_id"] for item in replayed.insights() if item["kind"] == "task_error"
    )
    assert error_task_ids == [61, 62]


def test_builds_timeout_cancellation_insights() -> None:
    store = SessionStore("timeout-cancellation")
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

    cancelled_insight = next(
        item for item in store.insights() if item["kind"] == "task_cancelled"
    )
    assert cancelled_insight["cancelled_by_task_id"] == 1
    assert cancelled_insight["cancellation_origin"] == "timeout"
    assert cancelled_insight["timeout_seconds"] == 0.01
    assert "wait_for timeout 0.01s" in cancelled_insight["message"]

    cancellation_chain = next(
        item for item in store.insights() if item["kind"] == "cancellation_chain"
    )
    assert cancellation_chain["reason"] == "timeout"
    assert cancellation_chain["source_task_id"] == 1
    assert cancellation_chain["affected_task_ids"] == [2]
    assert cancellation_chain["timeout_seconds"] == 0.01
    assert "wait_for timeout 0.01s" in cancellation_chain["message"]


def test_cancellation_insight_includes_blocked_resource_context() -> None:
    store = SessionStore("resource-cancel")
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
            },
        )
    )
    store.mark_completed()

    cancelled_insight = next(
        item for item in store.insights() if item["kind"] == "task_cancelled"
    )
    assert cancelled_insight["blocked_reason"] == "queue_get"
    assert cancelled_insight["blocked_resource_id"] == "queue:123"
    assert "while waiting on queue_get (queue:123)" in cancelled_insight["message"]


def test_builds_stalled_gather_group_insight() -> None:
    store = SessionStore("stalled-gather")
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
    for task_id, task_name in ((2, "fast-child"), (3, "slow-child")):
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
                ts_ns=40 + task_id,
                kind="task.start",
                task_id=task_id,
                task_name=task_name,
                parent_task_id=1,
                state="RUNNING",
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

    gather_insight = next(
        item for item in store.insights() if item["kind"] == "stalled_gather_group"
    )
    assert gather_insight["task_id"] == 1
    assert gather_insight["slow_task_id"] == 3
    assert gather_insight["slow_task_name"] == "slow-child"
    assert gather_insight["child_task_ids"] == [2, 3]
    assert gather_insight["duration_ms"] >= 200
    assert "slow-child" in gather_insight["message"]


def test_builds_fan_out_explosion_insight() -> None:
    store = SessionStore("fan-out")
    store.append_event(
        Event(
            session_id=store.session_id,
            seq=store.next_seq(),
            ts_ns=10,
            kind="task.create",
            task_id=1,
            task_name="dispatcher",
            state="READY",
        )
    )
    for task_id in range(2, 8):
        store.append_event(
            Event(
                session_id=store.session_id,
                seq=store.next_seq(),
                ts_ns=20 + task_id,
                kind="task.create",
                task_id=task_id,
                task_name=f"child-{task_id}",
                parent_task_id=1,
                state="READY",
            )
        )
    store.mark_completed()

    fan_out_insight = next(
        item for item in store.insights() if item["kind"] == "fan_out_explosion"
    )
    assert fan_out_insight["task_id"] == 1
    assert fan_out_insight["child_count"] == 6
    assert fan_out_insight["child_task_ids"] == [2, 3, 4, 5, 6, 7]
    assert "dispatcher" in fan_out_insight["message"]


def test_builds_queue_lock_and_semaphore_resource_insights() -> None:
    store = SessionStore("resource-insights")
    for task_id, task_name in ((1, "queue-waiter-a"), (2, "queue-waiter-b")):
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

    for task_id, task_name in ((3, "lock-waiter-a"), (4, "lock-waiter-b")):
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
            )
        )

    for task_id, task_name in (
        (5, "semaphore-waiter-a"),
        (6, "semaphore-waiter-b"),
        (7, "semaphore-waiter-c"),
    ):
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
            )
        )

    store.mark_completed()

    insights = store.insights()

    queue_insight = next(
        item for item in insights if item["kind"] == "queue_backpressure"
    )
    assert queue_insight["resource_id"] == "queue:1"
    assert queue_insight["blocked_task_ids"] == [1, 2]
    assert queue_insight["blocked_count"] == 2

    lock_insight = next(item for item in insights if item["kind"] == "lock_contention")
    assert lock_insight["resource_id"] == "lock:1"
    assert lock_insight["blocked_task_ids"] == [3, 4]
    assert lock_insight["blocked_count"] == 2

    semaphore_insight = next(
        item for item in insights if item["kind"] == "semaphore_saturation"
    )
    assert semaphore_insight["resource_id"] == "semaphore:1"
    assert semaphore_insight["blocked_task_ids"] == [5, 6, 7]
    assert semaphore_insight["blocked_count"] == 3
