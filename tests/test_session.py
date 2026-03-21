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
            "name": "parent",
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
            "metadata": {},
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
        "10,parent,1010,1030,READY,,",
        "11,child,1020,1030,READY,,",
        "10,parent,1030,1060,RUNNING,,",
        "11,child,1030,1040,RUNNING,,",
        "11,child,1040,1050,BLOCKED,sleep,sleep",
        "11,child,1050,2000,DONE,,",
        "10,parent,1060,2000,DONE,,",
    ]
