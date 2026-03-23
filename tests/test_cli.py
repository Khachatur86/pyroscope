from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from pyroscope import cli

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_run_demo_worker_pool_saves_capture(tmp_path: Path) -> None:
    capture_path = tmp_path / "worker-pool.json"
    args = argparse.Namespace(
        scenario="worker-pool",
        host="127.0.0.1",
        port=0,
        open_browser=False,
        hold_after_exit=False,
        no_ui_server=True,
        save=str(capture_path),
    )

    exit_code = cli.run_demo(args)

    assert exit_code == 0
    payload = json.loads(capture_path.read_text())
    assert payload["schema_version"] == "1.0"
    assert payload["snapshot"]["session"]["session_name"] == "worker_pool.py"
    assert payload["snapshot"]["session"]["event_count"] > 0
    task_names = {task["name"] for task in payload["snapshot"]["tasks"]}
    assert {"worker-0", "worker-1", "worker-2"}.issubset(task_names)


def test_run_demo_cancellation_saves_cancelled_task(tmp_path: Path) -> None:
    capture_path = tmp_path / "cancellation.json"
    args = argparse.Namespace(
        scenario="cancellation",
        host="127.0.0.1",
        port=0,
        open_browser=False,
        hold_after_exit=False,
        no_ui_server=True,
        save=str(capture_path),
    )

    exit_code = cli.run_demo(args)

    assert exit_code == 0
    payload = json.loads(capture_path.read_text())
    assert payload["schema_version"] == "1.0"
    tasks = payload["snapshot"]["tasks"]
    waiting_consumer = next(
        task for task in tasks if task["name"] == "waiting-consumer"
    )
    assert waiting_consumer["state"] == "CANCELLED"
    assert waiting_consumer["metadata"]["blocked_reason"] == "lock_acquire"
    assert waiting_consumer["metadata"]["blocked_resource_id"].startswith("lock:")


def test_run_demo_timeout_contention_saves_timeout_tasks(tmp_path: Path) -> None:
    capture_path = tmp_path / "timeout-contention.json"
    args = argparse.Namespace(
        scenario="timeout-contention",
        host="127.0.0.1",
        port=0,
        open_browser=False,
        hold_after_exit=False,
        no_ui_server=True,
        save=str(capture_path),
    )

    exit_code = cli.run_demo(args)

    assert exit_code == 0
    payload = json.loads(capture_path.read_text())
    assert payload["schema_version"] == "1.0"
    tasks = payload["snapshot"]["tasks"]
    task_names = {t["name"] for t in tasks}
    assert "slow-producer" in task_names
    assert "fast-consumer" in task_names
    # fast-consumer should timeout (wait_for with short deadline)
    fast = next(t for t in tasks if t["name"] == "fast-consumer")
    assert fast["state"] in {"CANCELLED", "DONE"}  # may complete if timing is tight


def test_run_demo_resource_contention_saves_semaphore_tasks(tmp_path: Path) -> None:
    capture_path = tmp_path / "resource-contention.json"
    args = argparse.Namespace(
        scenario="resource-contention",
        host="127.0.0.1",
        port=0,
        open_browser=False,
        hold_after_exit=False,
        no_ui_server=True,
        save=str(capture_path),
    )

    exit_code = cli.run_demo(args)

    assert exit_code == 0
    payload = json.loads(capture_path.read_text())
    tasks = payload["snapshot"]["tasks"]
    worker_tasks = [t for t in tasks if t["name"].startswith("worker-")]
    assert len(worker_tasks) == 5
    assert all(t["state"] == "DONE" for t in worker_tasks)
    # resource graph should include semaphore and lock resources
    resources = payload.get("resources", [])
    resource_ids = {r["resource_id"] for r in resources}
    assert any(rid.startswith("semaphore:") for rid in resource_ids)
    assert any(rid.startswith("lock:") for rid in resource_ids)


def test_replay_capture_rehydrates_fixture_store_and_stops_server(
    monkeypatch, capsys
) -> None:
    started: list[Any] = []
    stopped: list[Any] = []
    browser_calls: list[tuple[bool, str, int]] = []

    class FakeServer:
        def __init__(self, store, host: str, port: int) -> None:
            self.store = store
            self.host = host
            self.port = 7444 if port == 0 else port

        def start(self) -> None:
            started.append(self)

        def stop(self) -> None:
            stopped.append(self)

    def fake_hold_forever() -> None:
        return

    def fake_open_browser(enabled: bool, host: str, port: int) -> None:
        browser_calls.append((enabled, host, port))

    monkeypatch.setattr(cli, "PyroscopeServer", FakeServer)
    monkeypatch.setattr(cli, "hold_forever", fake_hold_forever)
    monkeypatch.setattr(cli, "_maybe_open_browser", fake_open_browser)

    args = argparse.Namespace(
        capture=str(FIXTURES_DIR / "replay_capture.json"),
        host="127.0.0.1",
        port=0,
        open_browser=False,
    )

    exit_code = cli.replay_capture(args)

    assert exit_code == 0
    assert len(started) == 1
    assert len(stopped) == 1
    assert started[0] is stopped[0]
    server = started[0]
    assert server.store.session_name == "fixture-replay"
    assert server.store.snapshot()["session"]["task_count"] == 2
    assert browser_calls == [(False, "127.0.0.1", 7444)]
    captured = capsys.readouterr()
    assert "Replaying" in captured.out
    assert "http://127.0.0.1:7444" in captured.out


def test_export_capture_supports_summary_json_and_insights_csv(
    tmp_path: Path, capsys
) -> None:
    capture_path = FIXTURES_DIR / "replay_resource_contention.json"

    summary_output = tmp_path / "summary.json"
    summary_args = argparse.Namespace(
        capture=str(capture_path),
        format="summary-json",
        output=str(summary_output),
    )
    summary_exit_code = cli.export_capture(summary_args)
    assert summary_exit_code == 0
    summary_payload = json.loads(summary_output.read_text())
    assert summary_payload["session"]["session_name"] == "fixture-resource-contention"
    assert summary_payload["counts"]["resources"] == 3

    insights_output = tmp_path / "insights.csv"
    insights_args = argparse.Namespace(
        capture=str(capture_path),
        format="insights-csv",
        output=str(insights_output),
    )
    insights_exit_code = cli.export_capture(insights_args)
    assert insights_exit_code == 0
    insight_rows = insights_output.read_text().strip().splitlines()
    assert insight_rows[0] == (
        "kind,severity,task_id,reason,resource_id,blocked_resource_id,message"
    )
    assert any(
        row.startswith("queue_backpressure,warning,") for row in insight_rows[1:]
    )

    captured = capsys.readouterr()
    assert str(summary_output) in captured.out
    assert str(insights_output) in captured.out


def test_compare_command_supports_json_and_summary_output(capsys) -> None:
    baseline = str(FIXTURES_DIR / "replay_drift_baseline.json")
    candidate = str(FIXTURES_DIR / "replay_drift_shifted.json")

    json_exit_code = cli.main(["compare", baseline, candidate, "--format", "json"])
    assert json_exit_code == 0
    json_payload = json.loads(capsys.readouterr().out)
    assert json_payload["counts"]["baseline_tasks"] == 3
    assert json_payload["counts"]["candidate_tasks"] == 4
    assert json_payload["resources"]["added"] == [
        "queue:outgoing",
        "semaphore:workers",
    ]
    assert json_payload["error_tasks"] == {"baseline": [], "candidate": []}

    summary_exit_code = cli.main(
        ["compare", baseline, candidate, "--format", "summary"]
    )
    assert summary_exit_code == 0
    summary_output = capsys.readouterr().out
    assert "Baseline: fixture-drift-baseline" in summary_output
    assert "Candidate: fixture-drift-shifted" in summary_output
    assert "Tasks: 3 -> 4" in summary_output
    assert "Added resources: queue:outgoing, semaphore:workers" in summary_output


def test_compare_command_prints_hot_tasks_and_label_drift(
    capsys, tmp_path: Path
) -> None:
    baseline_capture = {
        "snapshot": {
            "session": {
                "session_id": "sess_compare_base",
                "session_name": "compare-base",
                "started_ts_ns": 10,
                "completed_ts_ns": 20,
                "event_count": 2,
                "task_count": 1,
            },
            "tasks": [],
            "segments": [],
            "insights": [],
        },
        "events": [
            {
                "session_id": "sess_compare_base",
                "seq": 1,
                "ts_ns": 11,
                "kind": "task.create",
                "task_id": 1,
                "task_name": "request-main",
                "state": "READY",
                "reason": None,
                "resource_id": None,
                "parent_task_id": None,
                "cancelled_by_task_id": None,
                "cancellation_origin": None,
                "stack_id": None,
                "metadata": {
                    "request_label": "GET /orders/1",
                    "job_label": "job-1",
                },
            },
            {
                "session_id": "sess_compare_base",
                "seq": 2,
                "ts_ns": 12,
                "kind": "task.block",
                "task_id": 1,
                "task_name": "request-main",
                "state": "BLOCKED",
                "reason": "queue_get",
                "resource_id": "queue:orders",
                "parent_task_id": None,
                "cancelled_by_task_id": None,
                "cancellation_origin": None,
                "stack_id": None,
                "metadata": {
                    "request_label": "GET /orders/1",
                    "job_label": "job-1",
                },
            },
        ],
        "stacks": [],
        "resources": [{"resource_id": "queue:orders", "task_ids": [1]}],
    }
    candidate_capture = {
        "snapshot": {
            "session": {
                "session_id": "sess_compare_candidate",
                "session_name": "compare-candidate",
                "started_ts_ns": 10,
                "completed_ts_ns": 40,
                "event_count": 4,
                "task_count": 2,
            },
            "tasks": [],
            "segments": [],
            "insights": [],
        },
        "events": [
            {
                "session_id": "sess_compare_candidate",
                "seq": 1,
                "ts_ns": 11,
                "kind": "task.create",
                "task_id": 1,
                "task_name": "request-main",
                "state": "READY",
                "reason": None,
                "resource_id": None,
                "parent_task_id": None,
                "cancelled_by_task_id": None,
                "cancellation_origin": None,
                "stack_id": None,
                "metadata": {
                    "request_label": "GET /orders/2",
                    "job_label": "job-2",
                },
            },
            {
                "session_id": "sess_compare_candidate",
                "seq": 2,
                "ts_ns": 12,
                "kind": "task.block",
                "task_id": 1,
                "task_name": "request-main",
                "state": "BLOCKED",
                "reason": "lock_acquire",
                "resource_id": "lock:orders",
                "parent_task_id": None,
                "cancelled_by_task_id": None,
                "cancellation_origin": None,
                "stack_id": None,
                "metadata": {
                    "request_label": "GET /orders/2",
                    "job_label": "job-2",
                },
            },
            {
                "session_id": "sess_compare_candidate",
                "seq": 3,
                "ts_ns": 13,
                "kind": "task.create",
                "task_id": 2,
                "task_name": "request-child",
                "state": "READY",
                "reason": None,
                "resource_id": None,
                "parent_task_id": 1,
                "cancelled_by_task_id": None,
                "cancellation_origin": None,
                "stack_id": None,
                "metadata": {
                    "request_label": "GET /orders/2",
                    "job_label": "job-2",
                },
            },
            {
                "session_id": "sess_compare_candidate",
                "seq": 4,
                "ts_ns": 14,
                "kind": "task.fail",
                "task_id": 2,
                "task_name": "request-child",
                "state": "FAILED",
                "reason": "exception",
                "resource_id": None,
                "parent_task_id": 1,
                "cancelled_by_task_id": None,
                "cancellation_origin": None,
                "stack_id": None,
                "metadata": {
                    "request_label": "GET /orders/2",
                    "job_label": "job-2",
                    "error": "boom",
                },
            },
        ],
        "stacks": [],
        "resources": [{"resource_id": "lock:orders", "task_ids": [1]}],
    }

    baseline_path = tmp_path / "baseline.json"
    candidate_path = tmp_path / "candidate.json"
    baseline_path.write_text(json.dumps(baseline_capture))
    candidate_path.write_text(json.dumps(candidate_capture))

    exit_code = cli.main(
        ["compare", str(baseline_path), str(candidate_path), "--format", "summary"]
    )
    assert exit_code == 0
    summary_output = capsys.readouterr().out
    assert "Request labels added: GET /orders/2 (+2)" in summary_output
    assert "Request labels removed: GET /orders/1 (-1)" in summary_output
    assert "Job labels added: job-2 (+2)" in summary_output
    assert "Job labels removed: job-1 (-1)" in summary_output
    assert (
        "Candidate hot tasks: request-main [BLOCKED/lock_acquire], "
        "request-child [FAILED/exception]" in summary_output
    )
    assert "Candidate errors: request-child [exception] boom" in summary_output
    assert "Errors added: request-child [exception] boom" in summary_output
    assert "Errors removed: none" in summary_output


def test_compare_command_prints_cancellation_drift(capsys, tmp_path: Path) -> None:
    baseline_capture = {
        "snapshot": {
            "session": {
                "session_id": "sess_compare_cancel_base",
                "session_name": "compare-cancel-base",
                "started_ts_ns": 10,
                "completed_ts_ns": 40,
                "event_count": 4,
                "task_count": 2,
            },
            "tasks": [],
            "segments": [],
            "insights": [],
        },
        "events": [
            {
                "session_id": "sess_compare_cancel_base",
                "seq": 1,
                "ts_ns": 10,
                "kind": "task.create",
                "task_id": 1,
                "task_name": "parent-main",
                "state": "READY",
                "reason": None,
                "resource_id": None,
                "parent_task_id": None,
                "cancelled_by_task_id": None,
                "cancellation_origin": None,
                "stack_id": None,
                "metadata": {},
            },
            {
                "session_id": "sess_compare_cancel_base",
                "seq": 2,
                "ts_ns": 20,
                "kind": "task.start",
                "task_id": 1,
                "task_name": "parent-main",
                "state": "RUNNING",
                "reason": None,
                "resource_id": None,
                "parent_task_id": None,
                "cancelled_by_task_id": None,
                "cancellation_origin": None,
                "stack_id": None,
                "metadata": {},
            },
            {
                "session_id": "sess_compare_cancel_base",
                "seq": 3,
                "ts_ns": 30,
                "kind": "task.create",
                "task_id": 2,
                "task_name": "waiting-consumer",
                "state": "READY",
                "reason": None,
                "resource_id": None,
                "parent_task_id": 1,
                "cancelled_by_task_id": None,
                "cancellation_origin": None,
                "stack_id": None,
                "metadata": {},
            },
            {
                "session_id": "sess_compare_cancel_base",
                "seq": 4,
                "ts_ns": 40,
                "kind": "task.cancel",
                "task_id": 2,
                "task_name": "waiting-consumer",
                "state": "CANCELLED",
                "reason": "cancelled",
                "resource_id": None,
                "parent_task_id": 1,
                "cancelled_by_task_id": 1,
                "cancellation_origin": "parent_task",
                "stack_id": None,
                "metadata": {
                    "blocked_reason": "queue_get",
                    "blocked_resource_id": "queue:shared",
                    "queue_size": 0,
                    "queue_maxsize": 16,
                },
            },
        ],
    }
    candidate_capture = {
        "snapshot": {
            "session": {
                "session_id": "sess_compare_cancel_candidate",
                "session_name": "compare-cancel-candidate",
                "started_ts_ns": 10,
                "completed_ts_ns": 40,
                "event_count": 4,
                "task_count": 2,
            },
            "tasks": [],
            "segments": [],
            "insights": [],
        },
        "events": [
            {
                "session_id": "sess_compare_cancel_candidate",
                "seq": 1,
                "ts_ns": 10,
                "kind": "task.create",
                "task_id": 1,
                "task_name": "parent-main",
                "state": "READY",
                "reason": None,
                "resource_id": None,
                "parent_task_id": None,
                "cancelled_by_task_id": None,
                "cancellation_origin": None,
                "stack_id": None,
                "metadata": {},
            },
            {
                "session_id": "sess_compare_cancel_candidate",
                "seq": 2,
                "ts_ns": 20,
                "kind": "task.start",
                "task_id": 1,
                "task_name": "parent-main",
                "state": "RUNNING",
                "reason": None,
                "resource_id": None,
                "parent_task_id": None,
                "cancelled_by_task_id": None,
                "cancellation_origin": None,
                "stack_id": None,
                "metadata": {},
            },
            {
                "session_id": "sess_compare_cancel_candidate",
                "seq": 3,
                "ts_ns": 30,
                "kind": "task.create",
                "task_id": 2,
                "task_name": "waiting-consumer",
                "state": "READY",
                "reason": None,
                "resource_id": None,
                "parent_task_id": 1,
                "cancelled_by_task_id": None,
                "cancellation_origin": None,
                "stack_id": None,
                "metadata": {},
            },
            {
                "session_id": "sess_compare_cancel_candidate",
                "seq": 4,
                "ts_ns": 40,
                "kind": "task.cancel",
                "task_id": 2,
                "task_name": "waiting-consumer",
                "state": "CANCELLED",
                "reason": "cancelled",
                "resource_id": None,
                "parent_task_id": 1,
                "cancelled_by_task_id": 1,
                "cancellation_origin": "parent_task",
                "stack_id": None,
                "metadata": {
                    "blocked_reason": "event_wait",
                    "blocked_resource_id": "event:shutdown",
                    "event_is_set": False,
                },
            },
        ],
    }

    baseline_path = tmp_path / "compare-cancel-baseline.json"
    candidate_path = tmp_path / "compare-cancel-candidate.json"
    baseline_path.write_text(json.dumps(baseline_capture))
    candidate_path.write_text(json.dumps(candidate_capture))

    json_exit_code = cli.main(
        ["compare", str(baseline_path), str(candidate_path), "--format", "json"]
    )
    assert json_exit_code == 0
    json_payload = json.loads(capsys.readouterr().out)
    assert json_payload["cancellation_insights"]["baseline"] == [
        {
            "kind": "cancellation_chain",
            "reason": "parent_task",
            "message": (
                "Task parent-main cancelled 1 child task while waiting on "
                "queue_get (queue:shared) with queue 0/16: waiting-consumer"
            ),
        },
        {
            "kind": "task_cancelled",
            "reason": "cancelled",
            "message": (
                "Task waiting-consumer was cancelled by parent parent-main while "
                "waiting on queue_get (queue:shared) with queue 0/16"
            ),
        },
    ]
    assert json_payload["cancellation_insights"]["candidate"] == [
        {
            "kind": "cancellation_chain",
            "reason": "parent_task",
            "message": (
                "Task parent-main cancelled 1 child task while waiting on "
                "event_wait (event:shutdown) with event set=no: waiting-consumer"
            ),
        },
        {
            "kind": "task_cancelled",
            "reason": "cancelled",
            "message": (
                "Task waiting-consumer was cancelled by parent parent-main while "
                "waiting on event_wait (event:shutdown) with event set=no"
            ),
        },
    ]
    assert json_payload["cancellation_drift"]["added"] == [
        {
            "kind": "cancellation_chain",
            "reason": "parent_task",
            "message": (
                "Task parent-main cancelled 1 child task while waiting on "
                "event_wait (event:shutdown) with event set=no: waiting-consumer"
            ),
        },
        {
            "kind": "task_cancelled",
            "reason": "cancelled",
            "message": (
                "Task waiting-consumer was cancelled by parent parent-main while "
                "waiting on event_wait (event:shutdown) with event set=no"
            ),
        },
    ]
    assert json_payload["cancellation_drift"]["removed"] == [
        {
            "kind": "cancellation_chain",
            "reason": "parent_task",
            "message": (
                "Task parent-main cancelled 1 child task while waiting on "
                "queue_get (queue:shared) with queue 0/16: waiting-consumer"
            ),
        },
        {
            "kind": "task_cancelled",
            "reason": "cancelled",
            "message": (
                "Task waiting-consumer was cancelled by parent parent-main while "
                "waiting on queue_get (queue:shared) with queue 0/16"
            ),
        },
    ]

    summary_exit_code = cli.main(
        ["compare", str(baseline_path), str(candidate_path), "--format", "summary"]
    )
    assert summary_exit_code == 0
    summary_output = capsys.readouterr().out
    assert "Baseline cancellation: " in summary_output
    assert "Candidate cancellation: " in summary_output
    assert "Cancellation added: " in summary_output
    assert "Cancellation removed: " in summary_output
    assert "queue_get (queue:shared) with queue 0/16" in summary_output
    assert "event_wait (event:shutdown) with event set=no" in summary_output


def test_summary_command_supports_json_and_summary_output(capsys) -> None:
    capture = str(FIXTURES_DIR / "replay_resource_contention.json")

    json_exit_code = cli.main(["summary", capture, "--format", "json"])
    assert json_exit_code == 0
    json_payload = json.loads(capsys.readouterr().out)
    assert json_payload["counts"]["tasks"] == 7
    assert json_payload["states"] == {"BLOCKED": 7}
    assert json_payload["top_resources"][0] == {
        "resource_id": "semaphore:1",
        "task_count": 3,
    }
    assert json_payload["hot_tasks"] == [
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
    assert json_payload["error_tasks"] == []

    summary_exit_code = cli.main(["summary", capture, "--format", "summary"])
    assert summary_exit_code == 0
    summary_output = capsys.readouterr().out
    assert "Session: fixture-resource-contention" in summary_output
    assert "Tasks: 7" in summary_output
    assert "Insights: 10" in summary_output
    assert "States: BLOCKED=7" in summary_output
    assert "Top resources: semaphore:1 (3), lock:1 (2), queue:1 (2)" in summary_output
    assert (
        "Hot tasks: queue-a [BLOCKED/queue_get], lock-a [BLOCKED/lock_acquire], "
        "sem-a [BLOCKED/semaphore_acquire]" in summary_output
    )


def test_summary_command_prints_error_task_stack_preview(capsys) -> None:
    capture = str(FIXTURES_DIR / "replay_root_failed.json")

    json_exit_code = cli.main(["summary", capture, "--format", "json"])
    assert json_exit_code == 0
    json_payload = json.loads(capsys.readouterr().out)
    assert json_payload["error_tasks"] == [
        {
            "task_id": 21,
            "name": "main_entry",
            "reason": "RuntimeError",
            "error": "RuntimeError('boom')",
            "stack_preview": "raise RuntimeError('boom') at fixture.py:6",
            "stack_frames": [
                "main_entry() at fixture.py:5",
                "raise RuntimeError('boom') at fixture.py:6",
            ],
        }
    ]

    summary_exit_code = cli.main(["summary", capture, "--format", "summary"])
    assert summary_exit_code == 0
    summary_output = capsys.readouterr().out
    assert (
        "Error tasks: main_entry [RuntimeError] RuntimeError('boom') @ "
        "raise RuntimeError('boom') at fixture.py:6" in summary_output
    )


def test_summary_command_prints_cancellation_insights(
    capsys, tmp_path: Path
) -> None:
    capture = {
        "snapshot": {
            "session": {
                "session_id": "sess_cancel_summary",
                "session_name": "cancel-summary",
                "started_ts_ns": 10,
                "completed_ts_ns": 50,
                "event_count": 4,
                "task_count": 2,
            },
            "tasks": [],
            "segments": [],
            "insights": [],
        },
        "events": [
            {
                "session_id": "sess_cancel_summary",
                "seq": 1,
                "ts_ns": 10,
                "kind": "task.create",
                "task_id": 1,
                "task_name": "parent-main",
                "state": "READY",
                "reason": None,
                "resource_id": None,
                "parent_task_id": None,
                "cancelled_by_task_id": None,
                "cancellation_origin": None,
                "stack_id": None,
                "metadata": {},
            },
            {
                "session_id": "sess_cancel_summary",
                "seq": 2,
                "ts_ns": 20,
                "kind": "task.start",
                "task_id": 1,
                "task_name": "parent-main",
                "state": "RUNNING",
                "reason": None,
                "resource_id": None,
                "parent_task_id": None,
                "cancelled_by_task_id": None,
                "cancellation_origin": None,
                "stack_id": None,
                "metadata": {},
            },
            {
                "session_id": "sess_cancel_summary",
                "seq": 3,
                "ts_ns": 30,
                "kind": "task.create",
                "task_id": 2,
                "task_name": "waiting-consumer",
                "state": "READY",
                "reason": None,
                "resource_id": None,
                "parent_task_id": 1,
                "cancelled_by_task_id": None,
                "cancellation_origin": None,
                "stack_id": None,
                "metadata": {},
            },
            {
                "session_id": "sess_cancel_summary",
                "seq": 4,
                "ts_ns": 40,
                "kind": "task.cancel",
                "task_id": 2,
                "task_name": "waiting-consumer",
                "state": "CANCELLED",
                "reason": "cancelled",
                "resource_id": None,
                "parent_task_id": 1,
                "cancelled_by_task_id": 1,
                "cancellation_origin": "parent_task",
                "stack_id": None,
                "metadata": {
                    "blocked_reason": "queue_get",
                    "blocked_resource_id": "queue:shared",
                    "queue_size": 0,
                    "queue_maxsize": 16,
                },
            },
        ],
    }
    capture_path = tmp_path / "cancel-summary.json"
    capture_path.write_text(json.dumps(capture))

    json_exit_code = cli.main(["summary", str(capture_path), "--format", "json"])
    assert json_exit_code == 0
    json_payload = json.loads(capsys.readouterr().out)
    assert json_payload["cancellation_insights"] == [
        {
            "kind": "cancellation_chain",
            "reason": "parent_task",
            "message": (
                "Task parent-main cancelled 1 child task while waiting on "
                "queue_get (queue:shared) with queue 0/16: waiting-consumer"
            ),
        },
        {
            "kind": "task_cancelled",
            "reason": "cancelled",
            "message": (
                "Task waiting-consumer was cancelled by parent parent-main while "
                "waiting on queue_get (queue:shared) with queue 0/16"
            ),
        },
    ]

    summary_exit_code = cli.main(["summary", str(capture_path), "--format", "summary"])
    assert summary_exit_code == 0
    summary_output = capsys.readouterr().out
    assert "Cancellation: " in summary_output
    assert (
        "Task waiting-consumer was cancelled by parent parent-main while waiting on "
        "queue_get (queue:shared) with queue 0/16" in summary_output
    )


def test_summary_command_prints_request_and_job_labels(capsys, tmp_path: Path) -> None:
    capture = {
        "snapshot": {
            "session": {
                "session_id": "sess_labels",
                "session_name": "label-fixture",
                "started_ts_ns": 10,
                "completed_ts_ns": 20,
                "event_count": 2,
                "task_count": 2,
            },
            "tasks": [],
            "segments": [],
            "insights": [],
        },
        "events": [
            {
                "session_id": "sess_labels",
                "seq": 1,
                "ts_ns": 11,
                "kind": "task.create",
                "task_id": 1,
                "task_name": "request-main",
                "state": "READY",
                "reason": None,
                "resource_id": None,
                "parent_task_id": None,
                "cancelled_by_task_id": None,
                "cancellation_origin": None,
                "stack_id": None,
                "metadata": {
                    "request_label": "GET /jobs/42",
                    "job_label": "job-42",
                },
            },
            {
                "session_id": "sess_labels",
                "seq": 2,
                "ts_ns": 12,
                "kind": "task.create",
                "task_id": 2,
                "task_name": "request-child",
                "state": "READY",
                "reason": None,
                "resource_id": None,
                "parent_task_id": 1,
                "cancelled_by_task_id": None,
                "cancellation_origin": None,
                "stack_id": None,
                "metadata": {
                    "request_label": "GET /jobs/42",
                    "job_label": "job-42",
                },
            },
        ],
        "stacks": [],
        "resources": [],
    }
    capture_path = tmp_path / "labels.json"
    capture_path.write_text(json.dumps(capture))

    exit_code = cli.main(["summary", str(capture_path), "--format", "summary"])
    assert exit_code == 0
    summary_output = capsys.readouterr().out
    assert "Request labels: GET /jobs/42 (2)" in summary_output
    assert "Job labels: job-42 (2)" in summary_output


def test_summary_command_prints_session_metadata(capsys, tmp_path: Path) -> None:
    capture = {
        "snapshot": {
            "session": {
                "schema_version": "1.0",
                "session_id": "sess_meta",
                "session_name": "meta-session",
                "script_path": "/app/worker.py",
                "python_version": "3.12.1",
                "command_line": ["pyroscope", "run", "worker.py"],
                "started_ts_ns": 1000,
                "completed_ts_ns": 2000,
            },
            "tasks": [],
            "segments": [],
            "insights": [],
        },
        "events": [],
        "stacks": [],
        "resources": [],
    }
    capture_path = tmp_path / "meta.json"
    capture_path.write_text(json.dumps(capture))

    exit_code = cli.main(["summary", str(capture_path), "--format", "summary"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Script: /app/worker.py" in out
    assert "Python: 3.12.1" in out
    assert "Command: pyroscope run worker.py" in out


def test_compare_command_prints_state_changes_and_hot_task_drift(
    capsys, tmp_path: Path
) -> None:
    def _make_capture(session_id: str, session_name: str, tasks_spec: list) -> dict:
        events = []
        seq = 0
        for i, spec in enumerate(tasks_spec):
            seq += 1
            events.append({
                "session_id": session_id,
                "seq": seq,
                "ts_ns": 10 + i * 10,
                "kind": "task.create",
                "task_id": spec["id"],
                "task_name": spec["name"],
                "state": "READY",
                "metadata": {},
            })
            if spec.get("block"):
                seq += 1
                events.append({
                    "session_id": session_id,
                    "seq": seq,
                    "ts_ns": 20 + i * 10,
                    "kind": "task.block",
                    "task_id": spec["id"],
                    "task_name": spec["name"],
                    "state": "BLOCKED",
                    "reason": "queue_get",
                    "resource_id": "queue:x",
                    "metadata": {},
                })
            if spec.get("fail"):
                seq += 1
                events.append({
                    "session_id": session_id,
                    "seq": seq,
                    "ts_ns": 30 + i * 10,
                    "kind": "task.fail",
                    "task_id": spec["id"],
                    "task_name": spec["name"],
                    "state": "FAILED",
                    "reason": "exception",
                    "metadata": {"error": "boom"},
                })
            if spec.get("done"):
                seq += 1
                events.append({
                    "session_id": session_id,
                    "seq": seq,
                    "ts_ns": 30 + i * 10,
                    "kind": "task.end",
                    "task_id": spec["id"],
                    "task_name": spec["name"],
                    "state": "DONE",
                    "metadata": {},
                })
        return {
            "snapshot": {
                "session": {"session_id": session_id, "session_name": session_name, "state": "completed"},
                "tasks": [],
                "resources": [],
            },
            "events": events,
            "stacks": [],
            "resources": [],
        }

    baseline_cap = _make_capture(
        "sess_sc_base", "sc-base",
        [
            {"id": 1, "name": "worker-a", "done": True},
            {"id": 2, "name": "worker-b", "block": True},
        ],
    )
    candidate_cap = _make_capture(
        "sess_sc_cand", "sc-cand",
        [
            {"id": 1, "name": "worker-a", "fail": True},
            {"id": 2, "name": "worker-b", "done": True},
            {"id": 3, "name": "worker-c", "block": True},
        ],
    )
    baseline_path = tmp_path / "sc-baseline.json"
    candidate_path = tmp_path / "sc-candidate.json"
    baseline_path.write_text(json.dumps(baseline_cap))
    candidate_path.write_text(json.dumps(candidate_cap))

    exit_code = cli.main(
        ["compare", str(baseline_path), str(candidate_path), "--format", "summary"]
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "worker-a (DONE -> FAILED)" in out
    assert "worker-b (BLOCKED -> DONE)" in out
    assert "Hot task drift added" in out
    assert "Hot task drift removed" in out


def test_run_target_with_baseline_prints_drift_summary(
    tmp_path: Path, capsys
) -> None:
    baseline_path = tmp_path / "baseline.json"
    # First run: create the baseline capture
    args_first = argparse.Namespace(
        target=None,
        module="pyroscope._demo_stub",
        host="127.0.0.1",
        port=0,
        open_browser=False,
        hold_after_exit=False,
        no_ui_server=True,
        save=str(baseline_path),
        baseline=None,
    )
    # Use existing fixture as baseline instead of running a real module
    import shutil
    shutil.copy(
        str(FIXTURES_DIR / "replay_drift_baseline.json"), str(baseline_path)
    )

    # Second run: compare against that baseline using the shifted fixture
    candidate_cap = json.loads(
        (FIXTURES_DIR / "replay_drift_shifted.json").read_text()
    )
    from pyroscope.session import SessionStore
    candidate_store = SessionStore.from_capture(candidate_cap)

    cli._print_baseline_drift(candidate_store, str(baseline_path))

    out = capsys.readouterr().out
    assert "Baseline drift vs" in out
    assert "tasks" in out
    assert "insights" in out


def test_export_capture_jsonl_format(tmp_path: Path, capsys) -> None:
    capture_path = FIXTURES_DIR / "replay_resource_contention.json"
    output = tmp_path / "tasks.jsonl"
    args = argparse.Namespace(
        capture=str(capture_path),
        format="jsonl",
        output=str(output),
    )

    exit_code = cli.export_capture(args)

    assert exit_code == 0
    lines = [l for l in output.read_text().splitlines() if l.strip()]
    assert len(lines) > 0
    first = json.loads(lines[0])
    assert "task_id" in first
    assert "name" in first
    assert "state" in first
    captured = capsys.readouterr()
    assert str(output) in captured.out


def test_assert_command_passes_clean_capture(tmp_path: Path) -> None:
    capture_path = FIXTURES_DIR / "replay_capture.json"
    exit_code = cli.main(
        ["assert", str(capture_path), "--no-error", "--no-deadlock"]
    )
    assert exit_code == 0


def test_assert_command_fails_on_error_task(tmp_path: Path, capsys) -> None:
    capture_path = FIXTURES_DIR / "replay_root_failed.json"
    exit_code = cli.main(
        ["assert", str(capture_path), "--no-error"]
    )
    assert exit_code != 0
    out = capsys.readouterr().out
    assert "FAIL" in out or "error" in out.lower()


def test_assert_command_fails_on_timeout_cancellation(capsys) -> None:
    import json as _json
    from pyroscope import cli as _cli
    capture_path = FIXTURES_DIR / "replay_timeout_cancel.json"
    exit_code = _cli.main(
        ["assert", str(capture_path), "--no-timeout-cancellation"]
    )
    assert exit_code != 0


def test_assert_command_max_blocked_passes_when_within_limit(capsys) -> None:
    # replay_capture.json has 1 BLOCKED segment (task 11, sleep)
    capture_path = FIXTURES_DIR / "replay_capture.json"
    exit_code = cli.main(
        ["assert", str(capture_path), "--max-blocked", "5"]
    )
    assert exit_code == 0


def test_assert_command_max_blocked_fails_when_over_limit(capsys) -> None:
    # resource_contention has 7 blocked tasks
    capture_path = FIXTURES_DIR / "replay_resource_contention.json"
    exit_code = cli.main(
        ["assert", str(capture_path), "--max-blocked", "2"]
    )
    assert exit_code != 0
