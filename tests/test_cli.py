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

    summary_exit_code = cli.main(
        ["compare", baseline, candidate, "--format", "summary"]
    )
    assert summary_exit_code == 0
    summary_output = capsys.readouterr().out
    assert "Baseline: fixture-drift-baseline" in summary_output
    assert "Candidate: fixture-drift-shifted" in summary_output
    assert "Tasks: 3 -> 4" in summary_output
    assert "Added resources: queue:outgoing, semaphore:workers" in summary_output


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
