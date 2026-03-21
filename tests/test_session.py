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
    }
