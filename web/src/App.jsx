import React, { useEffect, useMemo, useRef, useState } from "react";

const STATE_COLORS = {
  READY: "#6bb9ff",
  RUNNING: "#44d492",
  BLOCKED: "#ff9f45",
  AWAITING: "#ffcd57",
  DONE: "#97a7ba",
  FAILED: "#ff5f7a",
  CANCELLED: "#f1b74a",
};

async function fetchJson(path) {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`Request failed for ${path}: ${response.status}`);
  }
  return await response.json();
}

function formatDuration(ns) {
  if (!ns) {
    return "0 ms";
  }
  const ms = ns / 1_000_000;
  if (ms < 1) {
    return `${ms.toFixed(2)} ms`;
  }
  if (ms < 1000) {
    return `${ms.toFixed(1)} ms`;
  }
  return `${(ms / 1000).toFixed(2)} s`;
}

function Timeline({ tasks, segments, selectedTaskId, onSelectTask }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) {
      return;
    }
    const context = canvas.getContext("2d");
    const width = canvas.width;
    const height = canvas.height;
    context.clearRect(0, 0, width, height);
    context.fillStyle = "#07131d";
    context.fillRect(0, 0, width, height);

    if (!segments.length) {
      context.fillStyle = "#9cb0bf";
      context.font = "14px IBM Plex Mono, monospace";
      context.fillText("No timeline data yet.", 24, 36);
      return;
    }

    const rows = new Map(tasks.map((task, index) => [task.task_id, index]));
    const minTs = Math.min(...segments.map((segment) => segment.start_ts_ns));
    const maxTs = Math.max(...segments.map((segment) => segment.end_ts_ns));
    const span = Math.max(1, maxTs - minTs);
    const labelWidth = 220;
    const rowHeight = Math.max(28, Math.floor((height - 36) / Math.max(tasks.length, 1)));

    context.font = "12px IBM Plex Mono, monospace";
    context.textBaseline = "middle";

    tasks.forEach((task, index) => {
      const y = 18 + index * rowHeight;
      context.fillStyle =
        task.task_id === selectedTaskId ? "rgba(93, 175, 255, 0.14)" : "rgba(255, 255, 255, 0.03)";
      context.fillRect(0, y, width, rowHeight - 4);
      context.fillStyle = "#c9d5df";
      context.fillText(task.name, 18, y + (rowHeight - 4) / 2);
    });

    segments.forEach((segment) => {
      const row = rows.get(segment.task_id) ?? 0;
      const y = 18 + row * rowHeight;
      const x =
        labelWidth + ((segment.start_ts_ns - minTs) / span) * (width - labelWidth - 28);
      const segmentWidth = Math.max(
        4,
        ((segment.end_ts_ns - segment.start_ts_ns) / span) * (width - labelWidth - 28),
      );

      context.fillStyle = STATE_COLORS[segment.state] || "#6bb9ff";
      context.fillRect(x, y + 4, segmentWidth, rowHeight - 12);
      if (segment.task_id === selectedTaskId) {
        context.strokeStyle = "#f6f7fb";
        context.lineWidth = 2;
        context.strokeRect(x, y + 4, segmentWidth, rowHeight - 12);
      }
    });
  }, [segments, selectedTaskId, tasks]);

  return (
    <section className="panel timeline-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Runtime view</p>
          <h2>Timeline</h2>
        </div>
        <p className="muted">Live task states and wait intervals.</p>
      </div>
      <canvas
        ref={canvasRef}
        className="timeline-canvas"
        width={1400}
        height={460}
        onClick={() => onSelectTask(selectedTaskId)}
      />
    </section>
  );
}

function TaskList({ tasks, selectedTaskId, onSelectTask }) {
  return (
    <section className="panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Workload</p>
          <h2>Tasks</h2>
        </div>
      </div>
      <div className="task-list">
        {tasks.length ? (
          tasks.map((task) => (
            <button
              key={task.task_id}
              className={task.task_id === selectedTaskId ? "task-row selected" : "task-row"}
              onClick={() => onSelectTask(task.task_id)}
              type="button"
            >
              <span className="task-title">{task.name}</span>
              <span className={`state-pill state-${task.state.toLowerCase()}`}>{task.state}</span>
            </button>
          ))
        ) : (
          <div className="empty">No tasks captured yet.</div>
        )}
      </div>
    </section>
  );
}

function Insights({ items }) {
  return (
    <section className="panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Analysis</p>
          <h2>Insights</h2>
        </div>
      </div>
      <div className="insight-list">
        {items.length ? (
          items.map((item, index) => (
            <article key={`${item.kind}-${index}`} className={`insight insight-${item.severity}`}>
              <div className="insight-kind">{item.kind}</div>
              <div>{item.message}</div>
            </article>
          ))
        ) : (
          <div className="empty">No findings yet.</div>
        )}
      </div>
    </section>
  );
}

function Inspector({ task, resources }) {
  const relatedResources = useMemo(() => {
    if (!task) {
      return [];
    }
    return resources.filter((resource) => resource.task_id === task.task_id);
  }, [resources, task]);

  return (
    <section className="panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Selection</p>
          <h2>Inspector</h2>
        </div>
      </div>
      {task ? (
        <div className="inspector">
          <div className="key-grid">
            <div>Task ID</div>
            <div>{task.task_id}</div>
            <div>Name</div>
            <div>{task.name}</div>
            <div>State</div>
            <div>{task.state}</div>
            <div>Parent</div>
            <div>{task.parent_task_id ?? "root"}</div>
            <div>Children</div>
            <div>{task.children.length}</div>
          <div>Cancelled by</div>
          <div>{task.cancelled_by_task_id ?? "n/a"}</div>
          <div>Cancel origin</div>
          <div>{task.cancellation_origin ?? "n/a"}</div>
          <div>Cancel source</div>
          <div>{task.cancellation_source?.task_name ?? "n/a"}</div>
          </div>
          {task.exception ? <p className="exception">{task.exception}</p> : null}
          <pre>{JSON.stringify(task, null, 2)}</pre>
          <div className="resource-block">
            <h3>Related resources</h3>
            {relatedResources.length ? (
              <ul>
                {relatedResources.map((resource, index) => (
                  <li key={`${resource.resource_id}-${index}`}>
                    {resource.resource_id} · {resource.action}
                  </li>
                ))}
              </ul>
            ) : (
              <div className="muted">No resource edges for this task.</div>
            )}
          </div>
        </div>
      ) : (
        <div className="empty">Select a task to inspect its state and relationships.</div>
      )}
    </section>
  );
}

export function App() {
  const [snapshot, setSnapshot] = useState(null);
  const [resources, setResources] = useState([]);
  const [selectedTaskId, setSelectedTaskId] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let active = true;
    let reconnectTimer = null;
    let source = null;

    async function refresh() {
      try {
        const [sessionPayload, resourcePayload] = await Promise.all([
          fetchJson("/api/v1/session"),
          fetchJson("/api/v1/resources/graph"),
        ]);
        if (!active) {
          return;
        }
        setSnapshot(sessionPayload);
        setResources(resourcePayload);
        setSelectedTaskId((current) => {
          if (current && sessionPayload.tasks.some((task) => task.task_id === current)) {
            return current;
          }
          return sessionPayload.tasks[0]?.task_id ?? null;
        });
        setError(null);
      } catch (refreshError) {
        if (active) {
          setError(refreshError.message);
        }
      }
    }

    function connectStream() {
      source = new EventSource("/api/v1/stream");
      source.onmessage = () => {
        void refresh();
      };
      source.onerror = () => {
        source?.close();
        if (!active) {
          return;
        }
        reconnectTimer = setTimeout(() => {
          if (active) {
            void refresh();
            connectStream();
          }
        }, 1000);
      };
    }

    connectStream();
    void refresh();
    return () => {
      active = false;
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
      }
      source?.close();
    };
  }, []);

  const tasks = snapshot?.tasks ?? [];
  const segments = snapshot?.segments ?? [];
  const insights = snapshot?.insights ?? [];
  const session = snapshot?.session;
  const selectedTask = tasks.find((task) => task.task_id === selectedTaskId) ?? null;
  const totalRuntime = useMemo(() => {
    if (!segments.length) {
      return 0;
    }
    const starts = segments.map((segment) => segment.start_ts_ns);
    const ends = segments.map((segment) => segment.end_ts_ns);
    return Math.max(...ends) - Math.min(...starts);
  }, [segments]);

  return (
    <div className="app-shell">
      <header className="hero">
        <div>
          <p className="eyebrow">Local asyncio inspector</p>
          <h1>Pyroscope</h1>
          <p className="hero-copy">
            Trace task lifecycles, waiting points, and cancellation fallout from a single local
            session.
          </p>
        </div>
        <div className="hero-metrics">
          <div className="metric-card">
            <span>Session</span>
            <strong>{session?.session_name ?? "loading"}</strong>
          </div>
          <div className="metric-card">
            <span>Tasks</span>
            <strong>{session?.task_count ?? 0}</strong>
          </div>
          <div className="metric-card">
            <span>Events</span>
            <strong>{session?.event_count ?? 0}</strong>
          </div>
          <div className="metric-card">
            <span>Runtime</span>
            <strong>{formatDuration(totalRuntime)}</strong>
          </div>
        </div>
      </header>

      {error ? <div className="error-banner">{error}</div> : null}

      <main className="dashboard">
        <Insights items={insights} />
        <Timeline
          tasks={tasks}
          segments={segments}
          selectedTaskId={selectedTaskId}
          onSelectTask={setSelectedTaskId}
        />
        <div className="grid-two">
          <TaskList tasks={tasks} selectedTaskId={selectedTaskId} onSelectTask={setSelectedTaskId} />
          <Inspector task={selectedTask} resources={resources} />
        </div>
      </main>
    </div>
  );
}
