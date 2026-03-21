from __future__ import annotations

import json
import queue
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .session import SessionStore

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Pyroscope</title>
  <link rel="stylesheet" href="/styles.css">
</head>
<body>
  <div id="app">
    <header class="topbar">
      <div>
        <h1>Pyroscope</h1>
        <p class="subtitle">asyncio timeline inspector</p>
      </div>
      <div id="session-meta" class="session-meta"></div>
    </header>
    <main class="layout">
      <section class="panel">
        <h2>Insights</h2>
        <div id="insights"></div>
      </section>
      <section class="panel">
        <h2>Timeline</h2>
        <canvas id="timeline" width="1280" height="420"></canvas>
      </section>
      <section class="panel columns">
        <div>
          <h2>Tasks</h2>
          <div id="tasks"></div>
        </div>
        <div>
          <h2>Inspector</h2>
          <pre id="inspector">Select a task</pre>
        </div>
      </section>
    </main>
  </div>
  <script src="/app.js"></script>
</body>
</html>
"""

APP_JS = """const stateColors = {
  READY: '#5db0ff',
  RUNNING: '#3ecf8e',
  BLOCKED: '#ff8a3d',
  AWAITING: '#ff8a3d',
  DONE: '#9aa4b2',
  FAILED: '#ff4d6d',
  CANCELLED: '#f7b801'
};

let snapshot = null;

async function fetchJson(path) {
  const res = await fetch(path);
  return await res.json();
}

function byId(id) {
  return document.getElementById(id);
}

function renderMeta(session) {
  byId('session-meta').innerHTML = `
    <div><strong>${session.session_name}</strong></div>
    <div>${session.task_count} tasks</div>
    <div>${session.event_count} events</div>
  `;
}

function renderInsights(items) {
  if (!items.length) {
    byId('insights').innerHTML = '<div class="muted">No findings yet.</div>';
    return;
  }
  byId('insights').innerHTML = items.map((item) => `
    <div class="insight insight-${item.severity}">
      <strong>${item.kind}</strong> · ${item.message}
    </div>
  `).join('');
}

function renderTasks(tasks) {
  byId('tasks').innerHTML = tasks.map((task) => `
    <button class="task-row" data-task-id="${task.task_id}">
      <span>${task.name}</span>
      <span class="pill">${task.state}</span>
    </button>
  `).join('');
  document.querySelectorAll('.task-row').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const task = await fetchJson(`/api/v1/tasks/${btn.dataset.taskId}`);
      byId('inspector').textContent = JSON.stringify(task, null, 2);
    });
  });
}

function renderTimeline(tasks, segments) {
  const canvas = byId('timeline');
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = '#07111f';
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  if (!segments.length) {
    ctx.fillStyle = '#b6c2cf';
    ctx.fillText('No timeline data yet', 24, 24);
    return;
  }

  const rows = new Map(tasks.map((task, index) => [task.task_id, index]));
  const minTs = Math.min(...segments.map((segment) => segment.start_ts_ns));
  const maxTs = Math.max(...segments.map((segment) => segment.end_ts_ns));
  const duration = Math.max(1, maxTs - minTs);
  const rowHeight = Math.max(20, Math.floor((canvas.height - 40) / Math.max(tasks.length, 1)));

  ctx.font = '12px monospace';
  segments.forEach((segment) => {
    const row = rows.get(segment.task_id) ?? 0;
    const x = 180 + ((segment.start_ts_ns - minTs) / duration) * (canvas.width - 220);
    const width = Math.max(3, ((segment.end_ts_ns - segment.start_ts_ns) / duration) * (canvas.width - 220));
    const y = 20 + row * rowHeight;

    ctx.fillStyle = stateColors[segment.state] || '#5db0ff';
    ctx.fillRect(x, y, width, rowHeight - 4);
    ctx.fillStyle = '#d7e0ea';
    ctx.fillText(segment.task_name, 12, y + 14);
  });
}

async function refresh() {
  snapshot = await fetchJson('/api/v1/session');
  renderMeta(snapshot.session);
  renderInsights(snapshot.insights);
  renderTasks(snapshot.tasks);
  renderTimeline(snapshot.tasks, snapshot.segments);
}

function connectStream() {
  const source = new EventSource('/api/v1/stream');
  source.onmessage = () => refresh();
  source.onerror = () => {
    source.close();
    setTimeout(connectStream, 1000);
  };
}

refresh();
connectStream();
"""

STYLES = """body {
  margin: 0;
  font-family: Menlo, Monaco, monospace;
  background: radial-gradient(circle at top, #122033 0%, #07111f 60%);
  color: #e8eef5;
}
.topbar {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  padding: 24px 28px 12px;
}
.subtitle, .muted {
  color: #9fb0c2;
}
.layout {
  display: grid;
  gap: 16px;
  padding: 0 24px 24px;
}
.panel {
  background: rgba(4, 12, 23, 0.75);
  border: 1px solid rgba(120, 148, 176, 0.25);
  border-radius: 16px;
  padding: 16px;
  box-shadow: 0 18px 60px rgba(0, 0, 0, 0.3);
}
.columns {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.session-meta {
  text-align: right;
  color: #b6c2cf;
}
.task-row {
  width: 100%;
  display: flex;
  justify-content: space-between;
  margin-bottom: 8px;
  padding: 10px 12px;
  border: 1px solid rgba(120, 148, 176, 0.2);
  border-radius: 10px;
  background: rgba(17, 31, 49, 0.85);
  color: #e8eef5;
}
.task-row:hover {
  background: rgba(35, 61, 95, 0.9);
  cursor: pointer;
}
.pill {
  color: #9fd2ff;
}
.insight {
  margin-bottom: 8px;
  padding: 10px 12px;
  border-radius: 10px;
}
.insight-warning { background: rgba(255, 138, 61, 0.18); }
.insight-error { background: rgba(255, 77, 109, 0.18); }
.insight-info { background: rgba(93, 176, 255, 0.18); }
pre {
  overflow: auto;
  white-space: pre-wrap;
}
canvas {
  width: 100%;
  border-radius: 12px;
}
"""


class PyroscopeServer:
    def __init__(
        self, store: SessionStore, host: str = "127.0.0.1", port: int = 7070
    ) -> None:
        self.store = store
        self.host = host
        self.port = port
        self._thread: threading.Thread | None = None
        self._server: ThreadingHTTPServer | None = None

    def start(self) -> None:
        handler = self._make_handler()
        self._server = ThreadingHTTPServer((self.host, self.port), handler)
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

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                path = parsed.path
                if path == "/":
                    self._write_html(INDEX_HTML)
                    return
                if path == "/app.js":
                    self._write_bytes(APP_JS.encode("utf-8"), "application/javascript")
                    return
                if path == "/styles.css":
                    self._write_bytes(STYLES.encode("utf-8"), "text/css")
                    return
                if path == "/api/v1/session":
                    self._write_json(store.session_payload())
                    return
                if path == "/api/v1/tasks":
                    self._write_json(store.tasks())
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
                    query = parse_qs(parsed.query)
                    state = query.get("state", [None])[0]
                    segments = [segment.to_dict() for segment in store.timeline()]
                    if state:
                        segments = [
                            segment for segment in segments if segment["state"] == state
                        ]
                    self._write_json(segments)
                    return
                if path == "/api/v1/insights":
                    self._write_json(store.insights())
                    return
                if path == "/api/v1/resources/graph":
                    self._write_json(store.resource_graph())
                    return
                if path == "/api/v1/stream":
                    self._stream_events()
                    return
                self.send_error(HTTPStatus.NOT_FOUND, "Not found")

            def do_POST(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                if parsed.path != "/api/v1/replay/load":
                    self.send_error(HTTPStatus.NOT_FOUND, "Not found")
                    return
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                data = json.loads(body.decode("utf-8"))
                replay_store = SessionStore.from_capture(data)
                store.replace_with(replay_store)
                self._write_json({"ok": True, "session_id": store.session_id})

            def log_message(self, format: str, *args: Any) -> None:
                return

            def _write_json(self, data: Any, status: int = 200) -> None:
                payload = json.dumps(data).encode("utf-8")
                self._write_bytes(payload, "application/json", status=status)

            def _write_html(self, html: str, status: int = 200) -> None:
                self._write_bytes(
                    html.encode("utf-8"), "text/html; charset=utf-8", status=status
                )

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
                except (BrokenPipeError, ConnectionResetError):
                    return
                finally:
                    store.unsubscribe(subscriber)

        return Handler


def hold_forever() -> None:
    try:
        while True:
            time.sleep(0.25)
    except KeyboardInterrupt:
        return
