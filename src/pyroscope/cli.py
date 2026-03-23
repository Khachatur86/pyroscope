from __future__ import annotations

import argparse
import json
import runpy
import sys
import time
import webbrowser
from pathlib import Path
from platform import python_version as _python_version

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
    run_parser.add_argument(
        "--baseline", help="Compare against this baseline capture after run"
    )

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
        choices=["json", "csv", "jsonl", "otlp-json", "summary-json", "insights-csv"],
        default="json",
    )
    export_parser.add_argument("--output", required=True)

    ui_parser = subparsers.add_parser("ui")
    ui_parser.add_argument("--host", default="127.0.0.1")
    ui_parser.add_argument("--port", type=int, default=7070)
    ui_parser.add_argument("--open-browser", action="store_true")

    demo_parser = subparsers.add_parser("demo")
    demo_parser.add_argument(
        "scenario",
        choices=[
            "worker-pool",
            "cancellation",
            "timeout-contention",
            "resource-contention",
        ],
    )
    demo_parser.add_argument("--host", default="127.0.0.1")
    demo_parser.add_argument("--port", type=int, default=7070)
    demo_parser.add_argument("--open-browser", action="store_true")
    demo_parser.add_argument("--hold-after-exit", action="store_true")
    demo_parser.add_argument("--no-ui-server", action="store_true")
    demo_parser.add_argument("--save", help="Save capture to JSON")

    watch_parser = subparsers.add_parser("watch")
    watch_parser.add_argument("target", nargs="?")
    watch_parser.add_argument("-m", "--module", help="Run a Python module")
    watch_parser.add_argument("--interval", type=float, default=5.0, metavar="SECONDS")
    watch_parser.add_argument(
        "--max-runs", type=int, default=None, metavar="N", help="Stop after N runs"
    )
    watch_parser.add_argument("--save-dir", help="Directory to save each run's capture")
    watch_parser.add_argument("--no-ui-server", action="store_true")

    assert_parser = subparsers.add_parser("assert")
    assert_parser.add_argument("capture")
    assert_parser.add_argument(
        "--no-error", action="store_true", help="Fail if any task has an error"
    )
    assert_parser.add_argument(
        "--no-deadlock", action="store_true", help="Fail if a deadlock insight exists"
    )
    assert_parser.add_argument(
        "--no-timeout-cancellation",
        action="store_true",
        help="Fail if any cancellation_origin=timeout task exists",
    )
    assert_parser.add_argument(
        "--max-blocked",
        type=int,
        metavar="N",
        help="Fail if more than N tasks are in BLOCKED state",
    )

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
    if command == "watch":
        return watch_target(args)
    if command == "assert":
        return assert_capture(args)
    if command == "ui":
        return serve_empty_ui(args)
    parser.error(f"Unsupported command: {command}")
    return 2


def run_demo(args: argparse.Namespace) -> int:
    root = Path(__file__).resolve().parents[2]
    if args.scenario == "worker-pool":
        target = root / "examples" / "worker_pool.py"
    elif args.scenario == "cancellation":
        target = root / "examples" / "cancellation_demo.py"
    elif args.scenario == "timeout-contention":
        target = root / "examples" / "timeout_contention.py"
    else:
        target = root / "examples" / "resource_contention.py"
    args.target = str(target)
    args.module = None
    return run_target(args)


def run_target(args: argparse.Namespace) -> int:
    if not args.target and not args.module:
        raise SystemExit("Specify a script path or -m module")
    session_name = args.module or Path(args.target).name
    store = SessionStore(
        session_name=session_name,
        script_path=str(Path(args.target).resolve()) if args.target else None,
        python_version=_python_version(),
        command_line=sys.argv[:],
    )
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
    if getattr(args, "baseline", None):
        _print_baseline_drift(store, args.baseline)
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


def _load_capture(path: str) -> SessionStore:
    try:
        data = json.loads(Path(path).read_text())
    except FileNotFoundError:
        raise SystemExit(f"Capture file not found: {path}") from None
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON in {path}: {exc}") from exc
    return SessionStore.from_capture(data)


def replay_capture(args: argparse.Namespace) -> int:
    store = _load_capture(args.capture)
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


def _run_once(
    target: str | None, module: str | None, session_name: str
) -> SessionStore:
    store = SessionStore(
        session_name=session_name,
        script_path=str(Path(target).resolve()) if target else None,
        python_version=_python_version(),
        command_line=sys.argv[:],
    )
    tracer = AsyncioTracer(store)
    tracer.install()
    try:
        if module:
            sys.argv = [module]
            runpy.run_module(module, run_name="__main__")
        else:
            if target is None:
                raise SystemExit("No target provided")
            target_path = Path(target).resolve()
            sys.argv = [str(target_path)]
            runpy.run_path(str(target_path), run_name="__main__")
    except SystemExit:
        pass
    finally:
        tracer.uninstall()
        store.mark_completed()
    return store


def _print_watch_drift(previous: SessionStore, current: SessionStore) -> None:
    summary = previous.compare_summary(current)
    counts = summary["counts"]
    print(
        f"  Drift: tasks {counts['baseline_tasks']}->{counts['candidate_tasks']},"
        f" insights {counts['baseline_insights']}->{counts['candidate_insights']}"
    )
    sc = summary.get("state_changes", [])
    if sc:
        print("  State changes: " + _format_state_changes(sc))
    ea = summary.get("error_drift", {}).get("added", [])
    if ea:
        print("  Errors added: " + _format_error_tasks(ea))


def watch_target(args: argparse.Namespace) -> int:
    if not args.target and not args.module:
        raise SystemExit("Specify a script path or -m module")
    save_dir = Path(args.save_dir) if args.save_dir else None
    if save_dir:
        save_dir.mkdir(parents=True, exist_ok=True)
    session_name = args.module or Path(args.target).name
    previous_store: SessionStore | None = None
    run_count = 0
    try:
        while args.max_runs is None or run_count < args.max_runs:
            run_count += 1
            suffix = "" if args.max_runs is None else f"/{args.max_runs}"
            print(f"Run {run_count}{suffix}: {session_name}")
            store = _run_once(args.target, args.module, session_name)
            if save_dir:
                store.save_json(save_dir / f"run_{run_count:04d}.json")
            if previous_store is not None:
                _print_watch_drift(previous_store, store)
            previous_store = store
            if (
                args.max_runs is None or run_count < args.max_runs
            ) and args.interval > 0:
                time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    return 0


def assert_capture(args: argparse.Namespace) -> int:
    store = _load_capture(args.capture)
    tasks = store.tasks()
    insights = store.insights()
    failures: list[str] = []

    if args.no_error:
        error_tasks = [t for t in tasks if t.get("state") == "FAILED"]
        if error_tasks:
            names = ", ".join(t["name"] for t in error_tasks)
            failures.append(
                f"FAIL --no-error: {len(error_tasks)} error task(s): {names}"
            )

    if args.no_deadlock:
        deadlocks = [i for i in insights if i["kind"] == "deadlock"]
        if deadlocks:
            failures.append(f"FAIL --no-deadlock: {len(deadlocks)} deadlock insight(s)")

    if args.no_timeout_cancellation:
        timeout_cancelled = [
            t for t in tasks if t.get("cancellation_origin") == "timeout"
        ]
        if timeout_cancelled:
            names = ", ".join(t["name"] for t in timeout_cancelled)
            failures.append(
                f"FAIL --no-timeout-cancellation: {len(timeout_cancelled)} timeout-cancelled task(s): {names}"
            )

    if args.max_blocked is not None:
        blocked = [t for t in tasks if t.get("state") == "BLOCKED"]
        if len(blocked) > args.max_blocked:
            failures.append(
                f"FAIL --max-blocked {args.max_blocked}: {len(blocked)} blocked task(s)"
            )

    if failures:
        for msg in failures:
            print(msg)
        return 1

    print(f"OK: all assertions passed ({args.capture})")
    return 0


def export_capture(args: argparse.Namespace) -> int:
    store = _load_capture(args.capture)
    output = Path(args.output)
    if args.format == "json":
        saved = store.save_json(output)
    elif args.format == "csv":
        saved = store.export_csv(output)
    elif args.format == "jsonl":
        saved = store.export_jsonl(output)
    elif args.format == "otlp-json":
        saved = store.export_otlp_json(output)
    elif args.format == "summary-json":
        saved = store.export_summary_json(output)
    else:
        saved = store.export_insights_csv(output)
    print(saved)
    return 0


def compare_captures(args: argparse.Namespace) -> int:
    baseline = _load_capture(args.baseline)
    candidate = _load_capture(args.candidate)
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
        "Errors added: "
        + (_format_error_tasks(summary["error_drift"]["added"]) or "none")
    )
    print(
        "Errors removed: "
        + (_format_error_tasks(summary["error_drift"]["removed"]) or "none")
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
    print(
        "Cancellation added: "
        + (
            _format_cancellation_insights(summary["cancellation_drift"]["added"])
            or "none"
        )
    )
    print(
        "Cancellation removed: "
        + (
            _format_cancellation_insights(summary["cancellation_drift"]["removed"])
            or "none"
        )
    )
    print(
        "State changes: " + (_format_state_changes(summary["state_changes"]) or "none")
    )
    print(
        "Hot task drift added: "
        + (_format_hot_tasks(summary["hot_task_drift"]["added"]) or "none")
    )
    print(
        "Hot task drift removed: "
        + (_format_hot_tasks(summary["hot_task_drift"]["removed"]) or "none")
    )
    return 0


def summarize_capture(args: argparse.Namespace) -> int:
    store = _load_capture(args.capture)
    summary = store.headless_summary()
    if args.format == "json":
        print(json.dumps(summary, indent=2))
        return 0

    sess = summary["session"]
    print(f"Session: {sess['session_name']}")
    if sess.get("script_path"):
        print(f"Script: {sess['script_path']}")
    if sess.get("python_version"):
        print(f"Python: {sess['python_version']}")
    if sess.get("command_line"):
        print(f"Command: {' '.join(sess['command_line'])}")
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
        f"{item['name']} [{item['state']}/{item['reason']}]" for item in items
    )


def _format_error_tasks(items: list[dict[str, object]]) -> str:
    formatted: list[str] = []
    for item in items:
        line = f"{item['name']} [{item['reason']}] {item['error']}"
        frames = item.get("stack_frames") or []
        if frames:
            line += " @ " + frames[-1]
        elif item.get("stack_preview"):
            line += f" @ {item['stack_preview']}"
        formatted.append(line)
    return ", ".join(formatted)


def _format_cancellation_insights(items: list[dict[str, object]]) -> str:
    return ", ".join(str(item["message"]) for item in items)


def _format_state_changes(items: list[dict[str, object]]) -> str:
    return ", ".join(
        f"{item['name']} ({item['baseline_state']} -> {item['candidate_state']})"
        for item in items
    )


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


def _print_baseline_drift(candidate: SessionStore, baseline_path: str) -> None:
    baseline = _load_capture(baseline_path)
    summary = baseline.compare_summary(candidate)
    counts = summary["counts"]
    print(
        f"\nBaseline drift vs {baseline_path}:"
        f" tasks {counts['baseline_tasks']}->{counts['candidate_tasks']},"
        f" insights {counts['baseline_insights']}->{counts['candidate_insights']}"
    )
    state_changes = summary.get("state_changes", [])
    if state_changes:
        print("  State changes: " + _format_state_changes(state_changes))
    hot_added = summary.get("hot_task_drift", {}).get("added", [])
    if hot_added:
        print("  Hot tasks added: " + _format_hot_tasks(hot_added))
    error_added = summary.get("error_drift", {}).get("added", [])
    if error_added:
        print("  Errors added: " + _format_error_tasks(error_added))
    cancel_added = summary.get("cancellation_drift", {}).get("added", [])
    if cancel_added:
        print("  Cancellation added: " + _format_cancellation_insights(cancel_added))


def _maybe_open_browser(enabled: bool, host: str, port: int) -> None:
    if enabled:
        webbrowser.open(f"http://{host}:{port}")
