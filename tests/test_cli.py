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
