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


def test_resource_graph_detailed_separates_owners_waiters_and_cancelled_waiters() -> None:
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

    assert store.resource_graph(detailed=True) == [
        {
            "resource_id": "lock:shared",
            "task_ids": [1, 2],
            "owner_task_ids": [1],
            "waiter_task_ids": [2],
            "cancelled_waiter_task_ids": [3],
        }
    ]
    assert store.task(1)["resource_roles"] == ["owner"]
    assert store.task(2)["resource_roles"] == ["waiter"]
    assert store.task(3)["resource_roles"] == ["cancelled waiter"]


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
        assert data["schema_version"] == "1.0"
        assert data["snapshot"]["session"]["schema_version"] == "1.0"
        replayed = SessionStore.from_capture(data)
        assert replayed.snapshot()["session"]["schema_version"] == "1.0"
        assert replayed.snapshot()["session"]["event_count"] == 1


def test_replay_fixture_restores_expected_snapshot_shape() -> None:
    fixture = json.loads((FIXTURES_DIR / "replay_capture.json").read_text())

    replayed = SessionStore.from_capture(fixture)
    snapshot = replayed.snapshot()

    assert snapshot["session"] == {
        "schema_version": "1.0",
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


def test_from_capture_supports_snapshot_only_payloads_with_missing_optional_fields() -> None:
    capture = {
        "snapshot": {
            "session": {
                "session_id": "sess_snapshot_only",
                "session_name": "snapshot-only",
                "started_ts_ns": 100,
                "completed_ts_ns": 240,
                "event_count": 0,
                "task_count": 2,
            },
            "tasks": [
                {
                    "task_id": 1,
                    "name": "root",
                    "parent_task_id": None,
                    "state": "DONE",
                    "created_ts_ns": 110,
                    "updated_ts_ns": 240,
                    "end_ts_ns": 240,
                },
                {
                    "task_id": 2,
                    "name": "worker",
                    "parent_task_id": 1,
                    "state": "BLOCKED",
                    "created_ts_ns": 120,
                    "updated_ts_ns": 180,
                    "reason": "queue_get",
                    "resource_id": "queue:jobs",
                },
            ],
            "segments": [
                {
                    "task_id": 1,
                    "task_name": "root",
                    "start_ts_ns": 110,
                    "end_ts_ns": 240,
                    "state": "DONE",
                },
                {
                    "task_id": 2,
                    "task_name": "worker",
                    "start_ts_ns": 120,
                    "end_ts_ns": 180,
                    "state": "BLOCKED",
                    "reason": "queue_get",
                    "resource_id": "queue:jobs",
                },
            ],
            "insights": [],
        },
        "resources": [{"resource_id": "queue:jobs", "task_ids": [2]}],
    }

    replayed = SessionStore.from_capture(capture)
    snapshot = replayed.snapshot()

    assert snapshot["session"]["schema_version"] == "1.0"
    assert snapshot["session"]["session_name"] == "snapshot-only"
    assert snapshot["session"]["event_count"] == 0
    assert snapshot["session"]["task_count"] == 2
    assert snapshot["segments"] == [
        {
            "task_id": 1,
            "task_name": "root",
            "start_ts_ns": 110,
            "end_ts_ns": 240,
            "state": "DONE",
            "reason": None,
            "resource_id": None,
        },
        {
            "task_id": 2,
            "task_name": "worker",
            "start_ts_ns": 120,
            "end_ts_ns": 180,
            "state": "BLOCKED",
            "reason": "queue_get",
            "resource_id": "queue:jobs",
        },
    ]

    root_task = replayed.task(1)
    assert root_task is not None
    assert root_task["children"] == [2]
    assert root_task["metadata"] == {}

    worker_task = replayed.task(2)
    assert worker_task is not None
    assert worker_task["reason"] == "queue_get"
    assert worker_task["resource_id"] == "queue:jobs"
    assert worker_task["metadata"] == {}
    assert replayed.resource_graph() == [{"resource_id": "queue:jobs", "task_ids": [2]}]


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


def test_fixture_replay_exports_summary_json_and_insights_csv() -> None:
    fixture = json.loads((FIXTURES_DIR / "replay_resource_contention.json").read_text())
    replayed = SessionStore.from_capture(fixture)

    with tempfile.TemporaryDirectory() as tmp:
        summary_path = replayed.export_summary_json(Path(tmp) / "summary.json")
        insights_path = replayed.export_insights_csv(Path(tmp) / "insights.csv")
        summary_payload = json.loads(summary_path.read_text())
        insight_rows = insights_path.read_text().strip().splitlines()

    assert summary_payload["schema_version"] == "1.0"
    assert summary_payload["session"]["session_name"] == "fixture-resource-contention"
    assert summary_payload["counts"]["tasks"] == 7
    assert summary_payload["counts"]["resources"] == 3
    assert summary_payload["counts"]["insights"] >= 3
    assert summary_payload["state_counts"]["BLOCKED"] == 7
    assert summary_payload["insight_counts"]["queue_backpressure"] == 1
    assert summary_payload["insight_counts"]["lock_contention"] == 1
    assert summary_payload["insight_counts"]["semaphore_saturation"] == 1

    assert insight_rows[0] == (
        "kind,severity,task_id,reason,resource_id,blocked_resource_id,message"
    )
    assert any(
        row.startswith("queue_backpressure,warning,") for row in insight_rows[1:]
    )
    assert any(row.startswith("lock_contention,warning,") for row in insight_rows[1:])
    assert any(
        row.startswith("semaphore_saturation,warning,") for row in insight_rows[1:]
    )


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


def test_resource_contention_insights_include_owner_context() -> None:
    store = SessionStore("resource-insight-owners")
    for task_id, task_name, resource_id in (
        (1, "lock-holder", "lock:shared"),
        (2, "sem-holder", "semaphore:gate"),
    ):
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
                kind="task.start",
                task_id=task_id,
                task_name=task_name,
                state="RUNNING",
                resource_id=resource_id,
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
                resource_id="lock:shared",
                metadata={"owner_task_ids": [1]},
            )
        )

    for task_id, task_name in ((5, "sem-waiter-a"), (6, "sem-waiter-b")):
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
                resource_id="semaphore:gate",
                metadata={"owner_task_ids": [2]},
            )
        )

    insights = store.insights()

    lock_insight = next(item for item in insights if item["kind"] == "lock_contention")
    assert lock_insight["owner_count"] == 1
    assert lock_insight["waiter_count"] == 2
    assert lock_insight["cancelled_waiter_count"] == 0
    assert lock_insight["owner_task_ids"] == [1]
    assert lock_insight["owner_task_names"] == ["lock-holder"]
    assert "held by lock-holder" in lock_insight["message"]

    semaphore_insight = next(
        item for item in insights if item["kind"] == "semaphore_saturation"
    )
    assert semaphore_insight["owner_count"] == 1
    assert semaphore_insight["waiter_count"] == 2
    assert semaphore_insight["cancelled_waiter_count"] == 0
    assert semaphore_insight["owner_task_ids"] == [2]
    assert semaphore_insight["owner_task_names"] == ["sem-holder"]
    assert "held by sem-holder" in semaphore_insight["message"]


def test_queue_put_fixture_replay_preserves_producer_backpressure_insight() -> None:
    fixture = json.loads(
        (FIXTURES_DIR / "replay_queue_put_backpressure.json").read_text()
    )
    replayed = SessionStore.from_capture(fixture)

    assert replayed.resource_graph() == fixture["resources"]

    producer_a = replayed.task(151)
    assert producer_a is not None
    assert producer_a["state"] == "BLOCKED"
    assert producer_a["reason"] == "queue_put"
    assert producer_a["resource_id"] == "queue:bounded"

    queue_insight = next(
        item for item in replayed.insights() if item["kind"] == "queue_backpressure"
    )
    assert queue_insight["reason"] == "queue_put"
    assert queue_insight["resource_id"] == "queue:bounded"
    assert queue_insight["blocked_task_ids"] == [151, 152]


def test_mixed_queue_fixture_replay_preserves_shared_backpressure_insight() -> None:
    fixture = json.loads(
        (FIXTURES_DIR / "replay_queue_mixed_contention.json").read_text()
    )
    replayed = SessionStore.from_capture(fixture)

    assert replayed.resource_graph() == fixture["resources"]

    insights = replayed.insights()
    queue_insight = next(
        item for item in insights if item["kind"] == "queue_backpressure"
    )
    assert queue_insight["resource_id"] == "queue:mixed"
    assert queue_insight["blocked_task_ids"] == [401, 402, 403, 404]
    assert {"consumer-a", "consumer-b", "producer-a", "producer-b"}.issubset(
        set(queue_insight["blocked_task_names"])
    )

    producer_task = replayed.task(403)
    assert producer_task is not None
    assert producer_task["reason"] == "queue_put"

    consumer_task = replayed.task(401)
    assert consumer_task is not None
    assert consumer_task["reason"] == "queue_get"


def test_queue_contention_cancel_fixture_preserves_contention_and_cancellation() -> (
    None
):
    fixture = json.loads(
        (FIXTURES_DIR / "replay_queue_contention_cancel.json").read_text()
    )
    replayed = SessionStore.from_capture(fixture)

    assert replayed.resource_graph() == fixture["resources"]

    queue_insight = next(
        item for item in replayed.insights() if item["kind"] == "queue_backpressure"
    )
    assert queue_insight["resource_id"] == "queue:shared"
    assert queue_insight["blocked_task_ids"] == [701, 702]

    cancelled_insight = next(
        item for item in replayed.insights() if item["kind"] == "task_cancelled"
    )
    assert cancelled_insight["task_id"] == 703
    assert cancelled_insight["blocked_reason"] == "queue_get"
    assert cancelled_insight["blocked_resource_id"] == "queue:shared"
    assert "queue_get (queue:shared)" in cancelled_insight["message"]

    cancelled_task = replayed.task(703)
    assert cancelled_task is not None
    assert cancelled_task["cancellation_origin"] == "parent_task"
    assert cancelled_task["metadata"]["blocked_resource_id"] == "queue:shared"


def test_queue_and_semaphore_contention_cancel_fixture_preserves_both_resource_contexts() -> (
    None
):
    fixture = json.loads(
        (FIXTURES_DIR / "replay_queue_semaphore_contention_cancel.json").read_text()
    )
    replayed = SessionStore.from_capture(fixture)

    assert replayed.resource_graph() == fixture["resources"]

    insights = replayed.insights()
    queue_insight = next(
        item for item in insights if item["kind"] == "queue_backpressure"
    )
    assert queue_insight["resource_id"] == "queue:shared"
    assert queue_insight["blocked_task_ids"] == [901, 902]
    assert queue_insight["cancelled_waiter_count"] == 1

    semaphore_insight = next(
        item for item in insights if item["kind"] == "semaphore_saturation"
    )
    assert semaphore_insight["resource_id"] == "semaphore:gate"
    assert semaphore_insight["blocked_task_ids"] == [903, 904]
    assert semaphore_insight["cancelled_waiter_count"] == 1

    cancelled_insights = {
        item["task_id"]: item for item in insights if item["kind"] == "task_cancelled"
    }
    assert cancelled_insights[905]["blocked_reason"] == "queue_put"
    assert cancelled_insights[905]["blocked_resource_id"] == "queue:shared"
    assert cancelled_insights[906]["blocked_reason"] == "semaphore_acquire"
    assert cancelled_insights[906]["blocked_resource_id"] == "semaphore:gate"

    assert replayed.resource_graph(detailed=True) == [
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
        "source_task_state": "FAILED",
        "source_task_reason": "RuntimeError",
        "source_task_error": None,
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


def test_parent_cancel_fixture_preserves_parent_task_cancellation_contract() -> None:
    fixture = json.loads((FIXTURES_DIR / "replay_parent_cancel.json").read_text())
    replayed = SessionStore.from_capture(fixture)

    child_task = replayed.task(92)
    assert child_task is not None
    assert child_task["state"] == "CANCELLED"
    assert child_task["cancelled_by_task_id"] == 91
    assert child_task["cancellation_origin"] == "parent_task"
    assert child_task["metadata"]["blocked_reason"] == "queue_get"
    assert child_task["metadata"]["blocked_resource_id"] == "queue:1"
    assert child_task["cancellation_source"] == {
        "task_id": 91,
        "task_name": "parent_worker",
        "state": "DONE",
    }

    cancelled_insight = next(
        item for item in replayed.insights() if item["kind"] == "task_cancelled"
    )
    assert cancelled_insight["cancellation_origin"] == "parent_task"
    assert cancelled_insight["blocked_reason"] == "queue_get"
    assert "queue_get (queue:1)" in cancelled_insight["message"]


def test_external_child_mix_fixture_preserves_mixed_cancellation_origins() -> None:
    fixture = json.loads((FIXTURES_DIR / "replay_external_child_mix.json").read_text())
    replayed = SessionStore.from_capture(fixture)

    external_child = replayed.task(102)
    assert external_child is not None
    assert external_child["cancellation_origin"] == "external"
    assert external_child["cancelled_by_task_id"] is None
    assert external_child["metadata"]["blocked_reason"] == "event_wait"

    parent_child = replayed.task(103)
    assert parent_child is not None
    assert parent_child["cancellation_origin"] == "parent_task"
    assert parent_child["cancelled_by_task_id"] == 101
    assert parent_child["metadata"]["blocked_reason"] == "semaphore_acquire"

    insights = replayed.insights()
    cancelled_task_ids = sorted(
        item["task_id"] for item in insights if item["kind"] == "task_cancelled"
    )
    assert cancelled_task_ids == [102, 103]
    chain_insight = next(
        item
        for item in insights
        if item["kind"] == "cancellation_chain" and item["reason"] == "parent_task"
    )
    assert chain_insight["source_task_id"] == 101
    assert chain_insight["affected_task_ids"] == [103]


def test_event_wait_fixture_preserves_external_cancellation_contract() -> None:
    fixture = json.loads((FIXTURES_DIR / "replay_event_wait_cancel.json").read_text())
    replayed = SessionStore.from_capture(fixture)

    child_task = replayed.task(112)
    assert child_task is not None
    assert child_task["state"] == "CANCELLED"
    assert child_task["cancellation_origin"] == "external"
    assert child_task["cancelled_by_task_id"] is None
    assert child_task["metadata"]["blocked_reason"] == "event_wait"
    assert child_task["metadata"]["blocked_resource_id"] == "event:1"
    assert replayed.resource_graph() == fixture["resources"]


def test_semaphore_cancel_fixture_preserves_parent_cancellation_contract() -> None:
    fixture = json.loads((FIXTURES_DIR / "replay_semaphore_cancel.json").read_text())
    replayed = SessionStore.from_capture(fixture)

    child_task = replayed.task(122)
    assert child_task is not None
    assert child_task["state"] == "CANCELLED"
    assert child_task["cancellation_origin"] == "parent_task"
    assert child_task["cancelled_by_task_id"] == 121
    assert child_task["metadata"]["blocked_reason"] == "semaphore_acquire"
    assert child_task["metadata"]["blocked_resource_id"] == "semaphore:1"

    cancelled_insight = next(
        item for item in replayed.insights() if item["kind"] == "task_cancelled"
    )
    assert cancelled_insight["blocked_reason"] == "semaphore_acquire"
    assert "semaphore_acquire (semaphore:1)" in cancelled_insight["message"]


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
                "queue_size": 0,
                "queue_maxsize": 16,
            },
        )
    )
    store.mark_completed()

    cancelled_insight = next(
        item for item in store.insights() if item["kind"] == "task_cancelled"
    )
    assert cancelled_insight["blocked_reason"] == "queue_get"
    assert cancelled_insight["blocked_resource_id"] == "queue:123"
    assert cancelled_insight["queue_size"] == 0
    assert cancelled_insight["queue_maxsize"] == 16
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


def test_multi_root_fixture_preserves_multiple_root_tasks() -> None:
    fixture = json.loads((FIXTURES_DIR / "replay_multi_root.json").read_text())
    replayed = SessionStore.from_capture(fixture)

    root_tasks = [
        task for task in replayed.snapshot()["tasks"] if task["parent_task_id"] is None
    ]
    assert [task["task_id"] for task in root_tasks] == [131, 132]

    root_alpha = replayed.task(131)
    assert root_alpha is not None
    assert root_alpha["children"] == [133]

    root_beta = replayed.task(132)
    assert root_beta is not None
    assert root_beta["state"] == "CANCELLED"
    assert root_beta["cancellation_origin"] == "external"
    assert root_beta["stack"]["stack_id"] == "stack_root_beta"

    child_task = replayed.task(133)
    assert child_task is not None
    assert child_task["parent_task_id"] == 131


def test_comparison_regression_fixture_preserves_replay_shape_and_insights() -> None:
    fixture = json.loads((FIXTURES_DIR / "replay_compare_regression.json").read_text())
    replayed = SessionStore.from_capture(fixture)

    assert replayed.resource_graph() == fixture["resources"]

    root_task = replayed.task(141)
    assert root_task is not None
    assert root_task["children"] == [142, 143]
    assert root_task["state"] == "BLOCKED"

    for task_id in (142, 143):
        task = replayed.task(task_id)
        assert task is not None
        assert task["state"] == "BLOCKED"
        assert task["reason"] == "queue_get"
        assert task["resource_id"] == "queue:1"

    queue_insight = next(
        item for item in replayed.insights() if item["kind"] == "queue_backpressure"
    )
    assert queue_insight["resource_id"] == "queue:1"
    assert queue_insight["blocked_task_ids"] == [141, 142, 143]


def test_multi_session_drift_fixtures_preserve_distinct_resource_graphs() -> None:
    baseline_fixture = json.loads(
        (FIXTURES_DIR / "replay_drift_baseline.json").read_text()
    )
    shifted_fixture = json.loads(
        (FIXTURES_DIR / "replay_drift_shifted.json").read_text()
    )

    baseline = SessionStore.from_capture(baseline_fixture)
    shifted = SessionStore.from_capture(shifted_fixture)

    assert baseline.resource_graph() == baseline_fixture["resources"]
    assert shifted.resource_graph() == shifted_fixture["resources"]

    baseline_kinds = {item["kind"] for item in baseline.insights()}
    shifted_kinds = {item["kind"] for item in shifted.insights()}
    assert {"queue_backpressure"}.issubset(baseline_kinds)
    assert {"queue_backpressure", "semaphore_saturation"}.issubset(shifted_kinds)

    shifted_queue_insight = next(
        item for item in shifted.insights() if item["kind"] == "queue_backpressure"
    )
    assert shifted_queue_insight["reason"] == "queue_put"
    assert shifted_queue_insight["blocked_task_ids"] == [301, 302]

    semaphore_insight = next(
        item for item in shifted.insights() if item["kind"] == "semaphore_saturation"
    )
    assert semaphore_insight["resource_id"] == "semaphore:workers"
    assert semaphore_insight["blocked_task_ids"] == [303, 304]


def test_multi_session_drift_fixtures_preserve_changed_cancellation_and_root_metadata() -> (
    None
):
    baseline_fixture = json.loads(
        (FIXTURES_DIR / "replay_drift_cancellation_baseline.json").read_text()
    )
    shifted_fixture = json.loads(
        (FIXTURES_DIR / "replay_drift_cancellation_shifted.json").read_text()
    )

    baseline = SessionStore.from_capture(baseline_fixture)
    shifted = SessionStore.from_capture(shifted_fixture)

    baseline_root = baseline.task(501)
    assert baseline_root is not None
    assert baseline_root["state"] == "CANCELLED"
    assert baseline_root["metadata"]["task_role"] == "main"
    assert baseline_root["metadata"]["runtime_origin"] == "asyncio.run"

    baseline_chain = next(
        item
        for item in baseline.insights()
        if item["kind"] == "cancellation_chain" and item["reason"] == "parent_task"
    )
    assert baseline_chain["source_task_id"] == 501
    assert baseline_chain["affected_task_ids"] == [502]

    shifted_root = shifted.task(601)
    assert shifted_root is not None
    assert shifted_root["state"] == "FAILED"
    assert shifted_root["metadata"]["task_role"] == "main"
    assert shifted_root["metadata"]["runtime_origin"] == "asyncio.run"
    assert "ExceptionGroup" in shifted_root["metadata"]["error"]

    shifted_chain = next(
        item
        for item in shifted.insights()
        if item["kind"] == "cancellation_chain" and item["reason"] == "sibling_failure"
    )
    assert shifted_chain["source_task_id"] == 602
    assert shifted_chain["affected_task_ids"] == [603]

    error_task_ids = sorted(
        item["task_id"] for item in shifted.insights() if item["kind"] == "task_error"
    )
    assert error_task_ids == [601, 602]


def test_multi_session_drift_fixtures_replace_root_completion_mode_and_resource_edges() -> (
    None
):
    baseline_fixture = json.loads(
        (FIXTURES_DIR / "replay_root_resource_baseline.json").read_text()
    )
    shifted_fixture = json.loads(
        (FIXTURES_DIR / "replay_root_resource_shifted.json").read_text()
    )

    baseline = SessionStore.from_capture(baseline_fixture)
    shifted = SessionStore.from_capture(shifted_fixture)

    baseline_root = baseline.task(701)
    assert baseline_root is not None
    assert baseline_root["state"] == "DONE"
    assert baseline_root["metadata"]["task_role"] == "main"
    assert baseline_root["metadata"]["runtime_origin"] == "asyncio.run"
    assert baseline.resource_graph() == baseline_fixture["resources"]

    shifted_root = shifted.task(801)
    assert shifted_root is not None
    assert shifted_root["state"] == "FAILED"
    assert shifted_root["metadata"]["task_role"] == "main"
    assert shifted_root["metadata"]["runtime_origin"] == "asyncio.run"
    assert "shifted root failed" in shifted_root["metadata"]["error"]
    assert shifted.resource_graph() == shifted_fixture["resources"]

    shifted_gate_waiter = shifted.task(802)
    assert shifted_gate_waiter is not None
    assert shifted_gate_waiter["resource_id"] == "event:gate"
    assert shifted_gate_waiter["reason"] == "event_wait"

    shifted_error = next(
        item for item in shifted.insights() if item["kind"] == "task_error"
    )
    assert shifted_error["task_id"] == 801


def test_compare_summary_detects_task_resource_and_reason_drift() -> None:
    baseline = SessionStore.from_capture(
        json.loads((FIXTURES_DIR / "replay_drift_baseline.json").read_text())
    )
    candidate = SessionStore.from_capture(
        json.loads((FIXTURES_DIR / "replay_drift_shifted.json").read_text())
    )

    summary = baseline.compare_summary(candidate)

    assert summary["baseline"]["session_name"] == "fixture-drift-baseline"
    assert summary["candidate"]["session_name"] == "fixture-drift-shifted"
    assert summary["counts"] == {
        "baseline_tasks": 3,
        "candidate_tasks": 4,
        "baseline_resources": 2,
        "candidate_resources": 2,
        "baseline_insights": 4,
        "candidate_insights": 6,
    }
    assert summary["states"]["added"] == {"BLOCKED": 1}
    assert summary["states"]["removed"] == {}
    assert summary["reasons"]["added"] == {"queue_put": 2, "semaphore_acquire": 2}
    assert summary["reasons"]["removed"] == {"lock_acquire": 1, "queue_get": 2}
    assert summary["resources"]["added"] == ["queue:outgoing", "semaphore:workers"]
    assert summary["resources"]["removed"] == ["lock:shared", "queue:incoming"]
    assert summary["task_names"]["added"] == [
        "queue-producer-a",
        "queue-producer-b",
        "semaphore-worker-a",
        "semaphore-worker-b",
    ]
    assert summary["task_names"]["removed"] == [
        "lock-waiter",
        "queue-consumer-a",
        "queue-consumer-b",
    ]


def test_compare_summary_reports_hot_tasks_and_label_drift() -> None:
    baseline = SessionStore("baseline-labels")
    baseline.append_event(
        Event(
            session_id=baseline.session_id,
            seq=baseline.next_seq(),
            ts_ns=10,
            kind="task.create",
            task_id=1,
            task_name="request-main",
            state="READY",
            metadata={
                "request_label": "GET /orders/1",
                "job_label": "job-1",
            },
        )
    )
    baseline.append_event(
        Event(
            session_id=baseline.session_id,
            seq=baseline.next_seq(),
            ts_ns=20,
            kind="task.block",
            task_id=1,
            task_name="request-main",
            state="BLOCKED",
            reason="queue_get",
            resource_id="queue:orders",
            metadata={
                "request_label": "GET /orders/1",
                "job_label": "job-1",
            },
        )
    )
    baseline.mark_completed()

    candidate = SessionStore("candidate-labels")
    candidate.append_event(
        Event(
            session_id=candidate.session_id,
            seq=candidate.next_seq(),
            ts_ns=10,
            kind="task.create",
            task_id=1,
            task_name="request-main",
            state="READY",
            metadata={
                "request_label": "GET /orders/2",
                "job_label": "job-2",
            },
        )
    )
    candidate.append_event(
        Event(
            session_id=candidate.session_id,
            seq=candidate.next_seq(),
            ts_ns=20,
            kind="task.block",
            task_id=1,
            task_name="request-main",
            state="BLOCKED",
            reason="lock_acquire",
            resource_id="lock:orders",
            metadata={
                "request_label": "GET /orders/2",
                "job_label": "job-2",
            },
        )
    )
    candidate.append_event(
        Event(
            session_id=candidate.session_id,
            seq=candidate.next_seq(),
            ts_ns=30,
            kind="task.create",
            task_id=2,
            task_name="request-child",
            state="READY",
            parent_task_id=1,
            metadata={
                "request_label": "GET /orders/2",
                "job_label": "job-2",
            },
        )
    )
    candidate.append_event(
        Event(
            session_id=candidate.session_id,
            seq=candidate.next_seq(),
            ts_ns=40,
            kind="task.fail",
            task_id=2,
            task_name="request-child",
            state="FAILED",
            reason="exception",
            metadata={
                "request_label": "GET /orders/2",
                "job_label": "job-2",
                "error": "boom",
            },
        )
    )
    candidate.mark_completed()

    summary = baseline.compare_summary(candidate)

    assert summary["hot_tasks"]["baseline"] == [
        {
            "task_id": 1,
            "name": "request-main",
            "state": "BLOCKED",
            "reason": "queue_get",
            "resource_id": "queue:orders",
        }
    ]
    assert summary["hot_tasks"]["candidate"] == [
        {
            "task_id": 1,
            "name": "request-main",
            "state": "BLOCKED",
            "reason": "lock_acquire",
            "resource_id": "lock:orders",
        },
        {
            "task_id": 2,
            "name": "request-child",
            "state": "FAILED",
            "reason": "exception",
            "resource_id": None,
        },
    ]
    assert summary["request_labels"]["added"] == {"GET /orders/2": 2}
    assert summary["request_labels"]["removed"] == {"GET /orders/1": 1}
    assert summary["job_labels"]["added"] == {"job-2": 2}
    assert summary["job_labels"]["removed"] == {"job-1": 1}
    assert summary["error_tasks"] == {
        "baseline": [],
        "candidate": [
            {
                "task_id": 2,
                "name": "request-child",
                "reason": "exception",
                "error": "boom",
                "stack_preview": None,
            }
        ],
    }


def test_headless_summary_reports_counts_states_and_top_resources() -> None:
    store = SessionStore.from_capture(
        json.loads((FIXTURES_DIR / "replay_resource_contention.json").read_text())
    )

    summary = store.headless_summary()

    assert summary["session"]["session_name"] == "fixture-resource-contention"
    assert summary["counts"] == {
        "tasks": 7,
        "resources": 3,
        "insights": 10,
        "segments": 14,
    }
    assert summary["states"] == {"BLOCKED": 7}
    assert summary["insights"] == {
        "lock_contention": 1,
        "queue_backpressure": 1,
        "semaphore_saturation": 1,
        "task_leak": 7,
    }
    assert summary["top_resources"] == [
        {"resource_id": "semaphore:1", "task_count": 3},
        {"resource_id": "lock:1", "task_count": 2},
        {"resource_id": "queue:1", "task_count": 2},
    ]
    assert summary["hot_tasks"] == [
        {
            "task_id": 81,
            "name": "queue-a",
            "state": "BLOCKED",
            "reason": "queue_get",
            "resource_id": "queue:1",
        },
        {
            "task_id": 83,
            "name": "lock-a",
            "state": "BLOCKED",
            "reason": "lock_acquire",
            "resource_id": "lock:1",
        },
        {
            "task_id": 85,
            "name": "sem-a",
            "state": "BLOCKED",
            "reason": "semaphore_acquire",
            "resource_id": "semaphore:1",
        },
    ]
    assert summary["error_tasks"] == []


def test_headless_summary_reports_error_tasks_with_stack_preview() -> None:
    store = SessionStore.from_capture(
        json.loads((FIXTURES_DIR / "replay_root_failed.json").read_text())
    )

    summary = store.headless_summary()

    assert summary["error_tasks"] == [
        {
            "task_id": 21,
            "name": "main_entry",
            "reason": "RuntimeError",
            "error": "RuntimeError('boom')",
            "stack_preview": "raise RuntimeError('boom') at fixture.py:6",
        }
    ]


def test_headless_summary_groups_request_and_job_labels() -> None:
    store = SessionStore("labels")
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
            kind="task.block",
            task_id=1,
            task_name="request-main",
            state="BLOCKED",
            reason="queue_get",
            resource_id="queue:jobs",
        )
    )
    store.append_event(
        Event(
            session_id=store.session_id,
            seq=store.next_seq(),
            ts_ns=30,
            kind="task.create",
            task_id=2,
            task_name="child-worker",
            parent_task_id=1,
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
            ts_ns=40,
            kind="task.block",
            task_id=2,
            task_name="child-worker",
            parent_task_id=1,
            state="BLOCKED",
            reason="lock_acquire",
            resource_id="lock:jobs",
        )
    )
    store.mark_completed()

    summary = store.headless_summary()

    assert summary["request_labels"] == [{"label": "GET /jobs/42", "task_count": 2}]
    assert summary["job_labels"] == [{"label": "job-42", "task_count": 2}]
