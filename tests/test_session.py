from __future__ import annotations

import json
import tempfile

from pyroscope.model import Event
from pyroscope.session import SessionStore


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
