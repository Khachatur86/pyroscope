from __future__ import annotations

import argparse
import json
import runpy
import sys
import webbrowser
from pathlib import Path

from .api import PyroscopeServer, hold_forever
from .runtime import AsyncioTracer
from .session import SessionStore
from .version import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pyroscope")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("target", nargs="?")
    run_parser.add_argument("-m", "--module", help="Run a Python module")
    run_parser.add_argument("--host", default="127.0.0.1")
    run_parser.add_argument("--port", type=int, default=7070)
    run_parser.add_argument("--open-browser", action="store_true")
    run_parser.add_argument("--hold-after-exit", action="store_true")
    run_parser.add_argument("--no-ui-server", action="store_true")
    run_parser.add_argument("--save", help="Save capture to JSON")

    replay_parser = subparsers.add_parser("replay")
    replay_parser.add_argument("capture")
    replay_parser.add_argument("--host", default="127.0.0.1")
    replay_parser.add_argument("--port", type=int, default=7070)
    replay_parser.add_argument("--open-browser", action="store_true")

    summary_parser = subparsers.add_parser("summary")
    summary_parser.add_argument("capture")
    summary_parser.add_argument(
        "--format", choices=["json", "summary"], default="summary"
    )

    compare_parser = subparsers.add_parser("compare")
    compare_parser.add_argument("baseline")
    compare_parser.add_argument("candidate")
    compare_parser.add_argument(
        "--format", choices=["json", "summary"], default="summary"
    )

    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("capture")
    export_parser.add_argument(
        "--format",
        choices=["json", "csv", "summary-json", "insights-csv"],
        default="json",
    )
    export_parser.add_argument("--output", required=True)

    ui_parser = subparsers.add_parser("ui")
    ui_parser.add_argument("--host", default="127.0.0.1")
    ui_parser.add_argument("--port", type=int, default=7070)
    ui_parser.add_argument("--open-browser", action="store_true")

    demo_parser = subparsers.add_parser("demo")
    demo_parser.add_argument("scenario", choices=["worker-pool", "cancellation"])
    demo_parser.add_argument("--host", default="127.0.0.1")
    demo_parser.add_argument("--port", type=int, default=7070)
    demo_parser.add_argument("--open-browser", action="store_true")
    demo_parser.add_argument("--hold-after-exit", action="store_true")
    demo_parser.add_argument("--no-ui-server", action="store_true")
    demo_parser.add_argument("--save", help="Save capture to JSON")

    subparsers.add_parser("version")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command
    if command == "version":
        print(__version__)
        return 0
    if command == "run":
        return run_target(args)
    if command == "demo":
        return run_demo(args)
    if command == "replay":
        return replay_capture(args)
    if command == "summary":
        return summarize_capture(args)
    if command == "compare":
        return compare_captures(args)
    if command == "export":
        return export_capture(args)
    if command == "ui":
        return serve_empty_ui(args)
    parser.error(f"Unsupported command: {command}")
    return 2


def run_demo(args: argparse.Namespace) -> int:
    root = Path(__file__).resolve().parents[2]
    if args.scenario == "worker-pool":
        target = root / "examples" / "worker_pool.py"
    else:
        target = root / "examples" / "cancellation_demo.py"
    args.target = str(target)
    args.module = None
    return run_target(args)


def run_target(args: argparse.Namespace) -> int:
    if not args.target and not args.module:
        raise SystemExit("Specify a script path or -m module")
    session_name = args.module or Path(args.target).name
    store = SessionStore(session_name=session_name)
    tracer = AsyncioTracer(store)
    tracer.install()
    server: PyroscopeServer | None = None
    if not args.no_ui_server:
        server = PyroscopeServer(store, host=args.host, port=args.port)
        server.start()
        _maybe_open_browser(args.open_browser, args.host, server.port)
    exit_code = 0
    try:
        if args.module:
            sys.argv = [args.module]
            runpy.run_module(args.module, run_name="__main__")
        else:
            target_path = Path(args.target).resolve()
            sys.argv = [str(target_path)]
            runpy.run_path(str(target_path), run_name="__main__")
    except SystemExit as exc:
        exit_code = int(exc.code) if isinstance(exc.code, int) else 0
    finally:
        tracer.uninstall()
        store.mark_completed()
        if args.save:
            saved = store.save_json(args.save)
            print(f"Saved capture to {saved}")
    if args.hold_after_exit:
        if server is None:
            raise SystemExit("--hold-after-exit requires the UI server")
        print(f"UI available at http://{args.host}:{server.port} (Ctrl+C to stop)")
        try:
            hold_forever()
        finally:
            server.stop()
    elif server is not None:
        server.stop()
    return exit_code


def replay_capture(args: argparse.Namespace) -> int:
    data = json.loads(Path(args.capture).read_text())
    store = SessionStore.from_capture(data)
    server = PyroscopeServer(store, host=args.host, port=args.port)
    server.start()
    _maybe_open_browser(args.open_browser, args.host, server.port)
    print(
        f"Replaying {args.capture} at http://{args.host}:{server.port} (Ctrl+C to stop)"
    )
    try:
        hold_forever()
    finally:
        server.stop()
    return 0


def export_capture(args: argparse.Namespace) -> int:
    data = json.loads(Path(args.capture).read_text())
    store = SessionStore.from_capture(data)
    output = Path(args.output)
    if args.format == "json":
        saved = store.save_json(output)
    elif args.format == "csv":
        saved = store.export_csv(output)
    elif args.format == "summary-json":
        saved = store.export_summary_json(output)
    else:
        saved = store.export_insights_csv(output)
    print(saved)
    return 0


def compare_captures(args: argparse.Namespace) -> int:
    baseline = SessionStore.from_capture(json.loads(Path(args.baseline).read_text()))
    candidate = SessionStore.from_capture(json.loads(Path(args.candidate).read_text()))
    summary = baseline.compare_summary(candidate)
    if args.format == "json":
        print(json.dumps(summary, indent=2))
        return 0

    print(f"Baseline: {summary['baseline']['session_name']}")
    print(f"Candidate: {summary['candidate']['session_name']}")
    print(
        "Tasks: "
        f"{summary['counts']['baseline_tasks']} -> {summary['counts']['candidate_tasks']}"
    )
    print(
        "Resources: "
        f"{summary['counts']['baseline_resources']} -> {summary['counts']['candidate_resources']}"
    )
    print(
        "Insights: "
        f"{summary['counts']['baseline_insights']} -> {summary['counts']['candidate_insights']}"
    )
    print("Added resources: " + (", ".join(summary["resources"]["added"]) or "none"))
    print(
        "Removed resources: " + (", ".join(summary["resources"]["removed"]) or "none")
    )
    print(
        "Request labels added: "
        + (_format_count_diff(summary["request_labels"]["added"], "+") or "none")
    )
    print(
        "Request labels removed: "
        + (_format_count_diff(summary["request_labels"]["removed"], "-") or "none")
    )
    print(
        "Job labels added: "
        + (_format_count_diff(summary["job_labels"]["added"], "+") or "none")
    )
    print(
        "Job labels removed: "
        + (_format_count_diff(summary["job_labels"]["removed"], "-") or "none")
    )
    print(
        "Baseline hot tasks: "
        + (_format_hot_tasks(summary["hot_tasks"]["baseline"]) or "none")
    )
    print(
        "Candidate hot tasks: "
        + (_format_hot_tasks(summary["hot_tasks"]["candidate"]) or "none")
    )
    print(
        "Baseline errors: "
        + (_format_error_tasks(summary["error_tasks"]["baseline"]) or "none")
    )
    print(
        "Candidate errors: "
        + (_format_error_tasks(summary["error_tasks"]["candidate"]) or "none")
    )
    print(
        "Baseline cancellation: "
        + (
            _format_cancellation_insights(summary["cancellation_insights"]["baseline"])
            or "none"
        )
    )
    print(
        "Candidate cancellation: "
        + (
            _format_cancellation_insights(summary["cancellation_insights"]["candidate"])
            or "none"
        )
    )
    return 0


def summarize_capture(args: argparse.Namespace) -> int:
    store = SessionStore.from_capture(json.loads(Path(args.capture).read_text()))
    summary = store.headless_summary()
    if args.format == "json":
        print(json.dumps(summary, indent=2))
        return 0

    print(f"Session: {summary['session']['session_name']}")
    print(f"Tasks: {summary['counts']['tasks']}")
    print(f"Resources: {summary['counts']['resources']}")
    print(f"Insights: {summary['counts']['insights']}")
    print(f"Segments: {summary['counts']['segments']}")
    state_line = ", ".join(
        f"{state}={count}" for state, count in summary["states"].items()
    )
    print("States: " + (state_line or "none"))
    resource_line = ", ".join(
        f"{item['resource_id']} ({item['task_count']})"
        for item in summary["top_resources"]
    )
    print("Top resources: " + (resource_line or "none"))
    hot_task_line = ", ".join(
        f"{item['name']} [{item['state']}/{item['reason']}]"
        for item in summary["hot_tasks"]
    )
    print("Hot tasks: " + (hot_task_line or "none"))
    request_line = ", ".join(
        f"{item['label']} ({item['task_count']})"
        for item in summary["request_labels"][:3]
    )
    print("Request labels: " + (request_line or "none"))
    job_line = ", ".join(
        f"{item['label']} ({item['task_count']})" for item in summary["job_labels"][:3]
    )
    print("Job labels: " + (job_line or "none"))
    print("Error tasks: " + (_format_error_tasks(summary["error_tasks"]) or "none"))
    print(
        "Cancellation: "
        + (_format_cancellation_insights(summary["cancellation_insights"]) or "none")
    )
    return 0


def _format_count_diff(items: dict[str, int], sign: str) -> str:
    return ", ".join(f"{label} ({sign}{count})" for label, count in items.items())


def _format_hot_tasks(items: list[dict[str, object]]) -> str:
    return ", ".join(
        f"{item['name']} [{item['state']}/{item['reason']}]"
        for item in items
    )


def _format_error_tasks(items: list[dict[str, object]]) -> str:
    formatted: list[str] = []
    for item in items:
        line = f"{item['name']} [{item['reason']}] {item['error']}"
        if item["stack_preview"]:
            line += f" @ {item['stack_preview']}"
        formatted.append(line)
    return ", ".join(formatted)


def _format_cancellation_insights(items: list[dict[str, object]]) -> str:
    return ", ".join(str(item["message"]) for item in items)


def serve_empty_ui(args: argparse.Namespace) -> int:
    store = SessionStore(session_name="empty")
    server = PyroscopeServer(store, host=args.host, port=args.port)
    server.start()
    _maybe_open_browser(args.open_browser, args.host, server.port)
    print(f"UI available at http://{args.host}:{server.port} (Ctrl+C to stop)")
    try:
        hold_forever()
    finally:
        server.stop()
    return 0


def _maybe_open_browser(enabled: bool, host: str, port: int) -> None:
    if enabled:
        webbrowser.open(f"http://{host}:{port}")
