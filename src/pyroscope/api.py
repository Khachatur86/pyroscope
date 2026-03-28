from __future__ import annotations

import json
import mimetypes
import queue
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .session import SessionStore


def _default_frontend_dir() -> Path | None:
    package_dist = Path(__file__).with_name("web_dist")
    if package_dist.exists():
        return package_dist

    repo_dist = Path(__file__).resolve().parents[2] / "web" / "dist"
    if repo_dist.exists():
        return repo_dist

    return None


class PyroscopeServer:
    def __init__(
        self,
        store: SessionStore,
        host: str = "127.0.0.1",
        port: int = 7070,
        frontend_dir: str | Path | None = None,
    ) -> None:
        self.store = store
        self.host = host
        self.port = port
        self.frontend_dir = (
            Path(frontend_dir).resolve()
            if frontend_dir is not None
            else _default_frontend_dir()
        )
        self._thread: threading.Thread | None = None
        self._server: ThreadingHTTPServer | None = None

    def start(self) -> None:
        handler = self._make_handler()

        # Subclass to raise request_queue_size (default 5) so many concurrent
        # test servers don't exhaust the OS accept backlog.
        class _Server(ThreadingHTTPServer):
            request_queue_size = 64

        self._server = _Server((self.host, self.port), handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _make_handler(self) -> type[BaseHTTPRequestHandler]:
        store = self.store
        frontend_dir = self.frontend_dir

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                path = parsed.path
                query = parse_qs(parsed.query)
                try:
                    self._dispatch_get(path, query)
                except ValueError as exc:
                    self.send_error(HTTPStatus.BAD_REQUEST, str(exc))

            def _dispatch_get(self, path: str, query: dict[str, list[str]]) -> None:
                if path == "/api/v1/session":
                    self._write_json(
                        store.session_payload(
                            task_limit=self._query_int(query, "task_limit") or 100,
                            segment_limit=self._query_int(query, "segment_limit")
                            or 500,
                            insight_limit=self._query_int(query, "insight_limit")
                            or 100,
                        )
                    )
                    return
                if path == "/api/v1/summary":
                    self._write_json(store.headless_summary())
                    return
                if path == "/api/v1/tasks/count":
                    self._write_json(store.task_counts())
                    return
                if path == "/api/v1/tasks":
                    self._write_json(
                        store.tasks(
                            state=self._query_value(query, "state"),
                            role=self._query_value(query, "role"),
                            reason=self._query_value(query, "reason"),
                            resource_id=self._query_value(query, "resource_id"),
                            cancellation_origin=self._query_value(
                                query, "cancellation_origin"
                            ),
                            request_label=self._query_value(query, "request_label"),
                            job_label=self._query_value(query, "job_label"),
                            q=self._query_value(query, "q"),
                            limit=self._query_int(query, "limit"),
                            offset=self._query_int(query, "offset") or 0,
                        )
                    )
                    return
                if path.startswith("/api/v1/tasks/"):
                    pieces = path.strip("/").split("/")
                    if len(pieces) >= 4:
                        try:
                            task_id = int(pieces[3])
                        except ValueError:
                            self.send_error(HTTPStatus.BAD_REQUEST, "Invalid task id")
                            return
                        if len(pieces) == 5 and pieces[4] == "children":
                            children = [
                                task
                                for task in store.tasks()
                                if task["parent_task_id"] == task_id
                            ]
                            self._write_json(children)
                            return
                        task = store.task(task_id)
                        if task is None:
                            self.send_error(HTTPStatus.NOT_FOUND, "Task not found")
                            return
                        self._write_json(task)
                        return
                if path == "/api/v1/timeline":
                    segments = [
                        segment.to_dict()
                        for segment in store.timeline(
                            state=self._query_value(query, "state"),
                            reason=self._query_value(query, "reason"),
                            resource_id=self._query_value(query, "resource_id"),
                            task_id=self._query_int(query, "task_id"),
                            limit=self._query_int(query, "limit"),
                            offset=self._query_int(query, "offset") or 0,
                        )
                    ]
                    self._write_json(segments)
                    return
                if path == "/api/v1/insights":
                    self._write_json(
                        store.insights(
                            kind=self._query_value(query, "kind"),
                            severity=self._query_value(query, "severity"),
                            task_id=self._query_int(query, "task_id"),
                            limit=self._query_int(query, "limit"),
                            offset=self._query_int(query, "offset") or 0,
                        )
                    )
                    return
                if path == "/api/v1/resources/graph":
                    self._write_json(
                        store.resource_graph(
                            resource_id=self._query_value(query, "resource_id"),
                            task_id=self._query_int(query, "task_id"),
                            detailed=self._query_value(query, "detail") == "detailed",
                            limit=self._query_int(query, "limit"),
                            offset=self._query_int(query, "offset") or 0,
                        )
                    )
                    return
                if path == "/api/v1/stacks":
                    self._write_json(
                        store.stacks(
                            task_id=self._query_int(query, "task_id"),
                            limit=self._query_int(query, "limit"),
                            offset=self._query_int(query, "offset") or 0,
                        )
                    )
                    return
                if path == "/api/v1/export":
                    fmt = self._query_value(query, "format") or "json"
                    kind = self._query_value(query, "kind")
                    session_name = (
                        store.snapshot()
                        .get("session", {})
                        .get("session_name", "session")
                    )
                    if fmt == "csv":
                        payload = store.capture_csv_bytes()
                        filename = f"{session_name}.csv"
                        self.send_response(200)
                        self.send_header("Content-Type", "text/csv; charset=utf-8")
                        self.send_header("Content-Length", str(len(payload)))
                        self.send_header(
                            "Content-Disposition",
                            f'attachment; filename="{filename}"',
                        )
                        self.end_headers()
                        self.wfile.write(payload)
                    elif fmt == "minimized":
                        mini = store.minimize_dict(kind=kind)
                        payload = json.dumps(mini).encode("utf-8")
                        filename = (
                            f"{session_name}.{kind}.minimized.json"
                            if kind
                            else f"{session_name}.minimized.json"
                        )
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Content-Length", str(len(payload)))
                        self.send_header(
                            "Content-Disposition",
                            f'attachment; filename="{filename}"',
                        )
                        self.end_headers()
                        self.wfile.write(payload)
                    else:
                        payload = json.dumps(store.capture_dict()).encode("utf-8")
                        filename = f"{session_name}.json"
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Content-Length", str(len(payload)))
                        self.send_header(
                            "Content-Disposition",
                            f'attachment; filename="{filename}"',
                        )
                        self.end_headers()
                        self.wfile.write(payload)
                    return
                if path == "/api/v1/stream":
                    self._stream_events()
                    return
                if path.startswith("/api/"):
                    self.send_error(HTTPStatus.NOT_FOUND, "Not found")
                    return
                if self._serve_frontend(path):
                    return
                self.send_error(HTTPStatus.NOT_FOUND, "Not found")

            def do_POST(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                if parsed.path not in {"/api/v1/replay/load", "/api/v1/replay/compare"}:
                    self.send_error(HTTPStatus.NOT_FOUND, "Not found")
                    return
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                data = json.loads(body.decode("utf-8"))
                if parsed.path == "/api/v1/replay/compare":
                    baseline_store = SessionStore.from_capture(data["baseline"])
                    candidate_store = SessionStore.from_capture(data["candidate"])
                    self._write_json(baseline_store.compare_summary(candidate_store))
                    return
                replay_store = SessionStore.from_capture(data)
                store.replace_with(replay_store)
                self._write_json({"ok": True, "session_id": store.session_id})

            def log_message(self, format: str, *args: Any) -> None:
                return

            def _write_json(self, data: Any, status: int = 200) -> None:
                payload = json.dumps(data).encode("utf-8")
                self._write_bytes(payload, "application/json", status=status)

            def _query_value(
                self, query: dict[str, list[str]], name: str
            ) -> str | None:
                return query.get(name, [None])[0]

            def _query_int(self, query: dict[str, list[str]], name: str) -> int | None:
                raw = self._query_value(query, name)
                if raw in (None, ""):
                    return None
                try:
                    return int(raw)
                except ValueError:
                    raise ValueError(f"Invalid integer for {name}") from None

            def _write_bytes(
                self, payload: bytes, content_type: str, status: int = 200
            ) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def _stream_events(self) -> None:
                subscriber = store.subscribe()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                try:
                    initial = json.dumps({"type": "snapshot"})
                    self.wfile.write(f"data: {initial}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    while True:
                        try:
                            item = subscriber.get(timeout=1.0)
                        except queue.Empty:
                            self.wfile.write(b": keep-alive\n\n")
                            self.wfile.flush()
                            continue
                        payload = json.dumps(item)
                        self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                        self.wfile.flush()
                        if item.get("type") == "error":
                            return
                except (BrokenPipeError, ConnectionResetError):
                    return
                finally:
                    store.unsubscribe(subscriber)

            def _serve_frontend(self, path: str) -> bool:
                if frontend_dir is None:
                    return False

                index_path = frontend_dir / "index.html"
                if not index_path.exists():
                    return False

                requested_path = path.lstrip("/") or "index.html"
                candidate = (frontend_dir / requested_path).resolve()
                try:
                    candidate.relative_to(frontend_dir)
                except ValueError:
                    self.send_error(HTTPStatus.FORBIDDEN, "Forbidden")
                    return True

                if candidate.is_file():
                    self._write_file(candidate)
                    return True

                if requested_path.startswith("assets/"):
                    self.send_error(HTTPStatus.NOT_FOUND, "Not found")
                    return True

                self._write_file(index_path, content_type="text/html; charset=utf-8")
                return True

            def _write_file(
                self, file_path: Path, content_type: str | None = None
            ) -> None:
                payload = file_path.read_bytes()
                if content_type is None:
                    guessed_type, _ = mimetypes.guess_type(file_path.name)
                    content_type = guessed_type or "application/octet-stream"
                self._write_bytes(payload, content_type)

        return Handler


def hold_forever() -> None:
    try:
        while True:
            time.sleep(0.25)
    except KeyboardInterrupt:
        return
