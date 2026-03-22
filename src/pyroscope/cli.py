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
    return 0


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
