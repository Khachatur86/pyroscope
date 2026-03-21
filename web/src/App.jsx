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

function formatInsightTitle(kind) {
  const titles = {
    queue_backpressure: "Queue Backpressure",
    lock_contention: "Lock Contention",
    semaphore_saturation: "Semaphore Saturation",
    stalled_gather_group: "Gather Stall",
    fan_out_explosion: "Fan-out Explosion",
    task_error: "Task Error",
    task_cancelled: "Task Cancelled",
    cancellation_chain: "Cancellation Chain",
  };
  return titles[kind] ?? kind.replaceAll("_", " ");
}

function insightMeta(item) {
  if (item.resource_id) {
    return item.resource_id;
  }
  if (item.blocked_reason && item.blocked_resource_id) {
    return `${item.blocked_reason} · ${item.blocked_resource_id}`;
  }
  if (item.blocked_reason) {
    return item.blocked_reason;
  }
  if (item.timeout_seconds) {
    return `timeout ${item.timeout_seconds}s`;
  }
  return null;
}

function insightResourceId(item) {
  if (item.resource_id) {
    return item.resource_id;
  }
  return item.blocked_resource_id ?? null;
}

function isCancellationInsight(item) {
  return item.kind === "cancellation_chain" || item.kind === "task_cancelled";
}

function isErrorInsight(item) {
  return item.kind === "task_error";
}

function taskBlockedReason(task) {
  return task.metadata?.blocked_reason ?? task.reason ?? null;
}

function taskResourceId(task) {
  return task.metadata?.blocked_resource_id ?? task.resource_id ?? null;
}

function taskRole(task) {
  return task.metadata?.task_role ?? null;
}

function filterOptions(tasks, valueFn) {
  return Array.from(new Set(tasks.map(valueFn).filter(Boolean))).sort();
}

function TaskFilters({
  totalCount,
  visibleCount,
  stateOptions,
  taskRoleOptions,
  cancellationOptions,
  blockedReasonOptions,
  resourceOptions,
  filters,
  onChange,
}) {
  return (
    <section className="panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Filters</p>
          <h2>Task filters</h2>
        </div>
        <p className="muted">{`Showing ${visibleCount} of ${totalCount}`}</p>
      </div>
      <div className="filter-grid">
        <label>
          <span>State</span>
          <select
            aria-label="State"
            value={filters.state}
            onChange={(event) => onChange("state", event.target.value)}
          >
            <option value="">All</option>
            {stateOptions.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Task role</span>
          <select
            aria-label="Task role"
            value={filters.taskRole}
            onChange={(event) => onChange("taskRole", event.target.value)}
          >
            <option value="">All</option>
            {taskRoleOptions.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Cancellation origin</span>
          <select
            aria-label="Cancellation origin"
            value={filters.cancellationOrigin}
            onChange={(event) => onChange("cancellationOrigin", event.target.value)}
          >
            <option value="">All</option>
            {cancellationOptions.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Blocked reason</span>
          <select
            aria-label="Blocked reason"
            value={filters.blockedReason}
            onChange={(event) => onChange("blockedReason", event.target.value)}
          >
            <option value="">All</option>
            {blockedReasonOptions.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Resource id</span>
          <select
            aria-label="Resource id"
            value={filters.resourceId}
            onChange={(event) => onChange("resourceId", event.target.value)}
          >
            <option value="">All</option>
            {resourceOptions.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
      </div>
    </section>
  );
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

function Insights({ items, onSelectResource }) {
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
            <button
              key={`${item.kind}-${index}`}
              className={`insight insight-${item.severity}`}
              onClick={() => onSelectResource(insightResourceId(item), item, index)}
              type="button"
            >
              <div className="insight-head">
                <div className="insight-kind">{formatInsightTitle(item.kind)}</div>
                {insightMeta(item) ? <div className="insight-meta">{insightMeta(item)}</div> : null}
              </div>
              <div>{item.message}</div>
            </button>
          ))
        ) : (
          <div className="empty">No findings yet.</div>
        )}
      </div>
    </section>
  );
}

function CancellationFocus({ insight, tasks, onSelectTask }) {
  const sourceTask = useMemo(() => {
    if (!insight) {
      return null;
    }
    return (
      tasks.find((task) => task.task_id === insight.source_task_id) ??
      tasks.find((task) => task.task_id === insight.task_id) ??
      null
    );
  }, [insight, tasks]);

  const affectedTasks = useMemo(() => {
    if (!insight) {
      return [];
    }
    const ids = insight.affected_task_ids ?? (insight.task_id ? [insight.task_id] : []);
    const idSet = new Set(ids);
    return tasks.filter((task) => idSet.has(task.task_id));
  }, [insight, tasks]);

  return (
    <section className="panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Cancellation focus</p>
          <h2>Drilldown</h2>
        </div>
      </div>
      {insight ? (
        <div className="resource-focus">
          <div className="key-grid">
            <div>Origin</div>
            <div>{insight.reason ?? insight.cancellation_origin ?? "n/a"}</div>
            <div>Affected</div>
            <div>{`${affectedTasks.length} task(s)`}</div>
          </div>
          <div className="resource-block">
            <h3>Source task</h3>
            {sourceTask ? (
              <div className="task-list">
                <button className="task-row" onClick={() => onSelectTask(sourceTask.task_id)} type="button">
                  <span className="task-title">{sourceTask.name}</span>
                  <span className={`state-pill state-${sourceTask.state.toLowerCase()}`}>
                    {sourceTask.state}
                  </span>
                </button>
              </div>
            ) : (
              <div className="muted">Source task is not available in the current filter scope.</div>
            )}
          </div>
          <div className="resource-block">
            <h3>Affected tasks</h3>
            {affectedTasks.length ? (
              <div className="task-list">
                {affectedTasks.map((task) => (
                  <button
                    key={task.task_id}
                    className="task-row"
                    onClick={() => onSelectTask(task.task_id)}
                    type="button"
                  >
                    <span className="task-title">{task.name}</span>
                    <span className={`state-pill state-${task.state.toLowerCase()}`}>{task.state}</span>
                  </button>
                ))}
              </div>
            ) : (
              <div className="muted">No affected tasks available in the current filter scope.</div>
            )}
          </div>
        </div>
      ) : (
        <div className="empty">Select a cancellation insight to inspect source and affected tasks.</div>
      )}
    </section>
  );
}

function ErrorFocus({ insight, tasks, onSelectTask }) {
  const errorTask = useMemo(() => {
    if (!insight) {
      return null;
    }
    return tasks.find((task) => task.task_id === insight.task_id) ?? null;
  }, [insight, tasks]);

  const isRootFailure =
    errorTask &&
    errorTask.parent_task_id == null &&
    (taskRole(errorTask) === "main" || taskRole(errorTask) === "root");

  return (
    <section className="panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Error focus</p>
          <h2>Drilldown</h2>
        </div>
      </div>
      {insight ? (
        <div className="resource-focus">
          <div className="key-grid">
            <div>Error kind</div>
            <div>{insight.reason ?? "task_error"}</div>
            <div>Root failure</div>
            <div>{isRootFailure ? "yes" : "no"}</div>
          </div>
          <div className="resource-block">
            <h3>Failed task</h3>
            {errorTask ? (
              <div className="task-list">
                <button
                  className="task-row"
                  onClick={() => onSelectTask(errorTask.task_id)}
                  type="button"
                >
                  <span className="task-title">{errorTask.name}</span>
                  <span className={`state-pill state-${errorTask.state.toLowerCase()}`}>
                    {errorTask.state}
                  </span>
                </button>
              </div>
            ) : (
              <div className="muted">Failed task is not available in the current filter scope.</div>
            )}
          </div>
          {insight.message ? <p className="exception">{insight.message}</p> : null}
        </div>
      ) : (
        <div className="empty">Select a task error insight to inspect the failed task.</div>
      )}
    </section>
  );
}

function ResourceFocus({ resource, tasks, onSelectTask }) {
  return (
    <section className="panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Resource focus</p>
          <h2>Drilldown</h2>
        </div>
      </div>
      {resource ? (
        <div className="resource-focus">
          <div className="key-grid">
            <div>Resource</div>
            <div>{resource.resource_id}</div>
            <div>Tasks</div>
            <div>{resource.task_ids.length}</div>
          </div>
          <div className="resource-block">
            <h3>Related tasks</h3>
            <div className="task-list">
              {tasks.map((task) => (
                <button
                  key={task.task_id}
                  className="task-row"
                  onClick={() => onSelectTask(task.task_id)}
                  type="button"
                >
                  <span className="task-title">{task.name}</span>
                  <span className={`state-pill state-${task.state.toLowerCase()}`}>{task.state}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      ) : (
        <div className="empty">Select a resource-focused insight to inspect waiting tasks.</div>
      )}
    </section>
  );
}

function Inspector({ task, resources }) {
  const relatedResources = useMemo(() => {
    if (!task) {
      return [];
    }
    return resources.filter((resource) => resource.task_ids?.includes(task.task_id));
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
            <div>Blocked on</div>
            <div>{task.metadata?.blocked_reason ?? "n/a"}</div>
            <div>Blocked resource</div>
            <div>{task.metadata?.blocked_resource_id ?? "n/a"}</div>
          </div>
          {task.exception ? <p className="exception">{task.exception}</p> : null}
          <pre>{JSON.stringify(task, null, 2)}</pre>
          <div className="resource-block">
            <h3>Related resources</h3>
            {relatedResources.length ? (
              <ul>
                {relatedResources.map((resource, index) => (
                  <li key={`${resource.resource_id}-${index}`}>
                    {resource.resource_id} · {resource.task_ids.length} task(s)
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
  const [selectedResourceId, setSelectedResourceId] = useState(null);
  const [selectedInsightIndex, setSelectedInsightIndex] = useState(null);
  const [error, setError] = useState(null);
  const [filters, setFilters] = useState({
    state: "",
    taskRole: "",
    cancellationOrigin: "",
    blockedReason: "",
    resourceId: "",
  });

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
        setSelectedResourceId((current) => {
          if (current && resourcePayload.some((resource) => resource.resource_id === current)) {
            return current;
          }
          return resourcePayload[0]?.resource_id ?? null;
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
  const stateOptions = useMemo(() => filterOptions(tasks, (task) => task.state), [tasks]);
  const taskRoleOptions = useMemo(() => filterOptions(tasks, taskRole), [tasks]);
  const cancellationOptions = useMemo(
    () => filterOptions(tasks, (task) => task.cancellation_origin),
    [tasks],
  );
  const blockedReasonOptions = useMemo(
    () => filterOptions(tasks, taskBlockedReason),
    [tasks],
  );
  const resourceOptions = useMemo(() => filterOptions(tasks, taskResourceId), [tasks]);
  const filteredTasks = useMemo(
    () =>
      tasks.filter((task) => {
        if (filters.state && task.state !== filters.state) {
          return false;
        }
        if (filters.taskRole && taskRole(task) !== filters.taskRole) {
          return false;
        }
        if (
          filters.cancellationOrigin &&
          task.cancellation_origin !== filters.cancellationOrigin
        ) {
          return false;
        }
        if (filters.blockedReason && taskBlockedReason(task) !== filters.blockedReason) {
          return false;
        }
        if (filters.resourceId && taskResourceId(task) !== filters.resourceId) {
          return false;
        }
        return true;
      }),
    [filters, tasks],
  );
  const filteredTaskIds = useMemo(
    () => new Set(filteredTasks.map((task) => task.task_id)),
    [filteredTasks],
  );
  const filteredSegments = useMemo(
    () => segments.filter((segment) => filteredTaskIds.has(segment.task_id)),
    [filteredTaskIds, segments],
  );
  const selectedTask = filteredTasks.find((task) => task.task_id === selectedTaskId) ?? null;
  const selectedResource =
    resources.find((resource) => resource.resource_id === selectedResourceId) ?? null;
  const selectedInsight =
    selectedInsightIndex === null ? null : insights[selectedInsightIndex] ?? null;
  const selectedResourceTasks = useMemo(() => {
    if (!selectedResource) {
      return [];
    }
    const ids = new Set(selectedResource.task_ids);
    return filteredTasks.filter((task) => ids.has(task.task_id));
  }, [filteredTasks, selectedResource]);
  const totalRuntime = useMemo(() => {
    if (!filteredSegments.length) {
      return 0;
    }
    const starts = filteredSegments.map((segment) => segment.start_ts_ns);
    const ends = filteredSegments.map((segment) => segment.end_ts_ns);
    return Math.max(...ends) - Math.min(...starts);
  }, [filteredSegments]);

  useEffect(() => {
    if (selectedTaskId && filteredTasks.some((task) => task.task_id === selectedTaskId)) {
      return;
    }
    setSelectedTaskId(filteredTasks[0]?.task_id ?? null);
  }, [filteredTasks, selectedTaskId]);

  function updateFilter(key, value) {
    setFilters((current) => ({ ...current, [key]: value }));
  }

  function handleInsightSelect(resourceId, insight, index) {
    setSelectedInsightIndex(index);
    if (resourceId) {
      setSelectedResourceId(resourceId);
    }
    if (isCancellationInsight(insight) || isErrorInsight(insight)) {
      setSelectedTaskId(insight.source_task_id ?? insight.task_id ?? null);
    }
  }

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
        <TaskFilters
          totalCount={tasks.length}
          visibleCount={filteredTasks.length}
          stateOptions={stateOptions}
          taskRoleOptions={taskRoleOptions}
          cancellationOptions={cancellationOptions}
          blockedReasonOptions={blockedReasonOptions}
          resourceOptions={resourceOptions}
          filters={filters}
          onChange={updateFilter}
        />
        <Insights
          items={insights}
          onSelectResource={(resourceId, insight, index) =>
            handleInsightSelect(resourceId, insight, index)
          }
        />
        <Timeline
          tasks={filteredTasks}
          segments={filteredSegments}
          selectedTaskId={selectedTaskId}
          onSelectTask={setSelectedTaskId}
        />
        <div className="grid-two">
          <TaskList
            tasks={filteredTasks}
            selectedTaskId={selectedTaskId}
            onSelectTask={setSelectedTaskId}
          />
          <Inspector task={selectedTask} resources={resources} />
        </div>
        <ResourceFocus
          resource={selectedResource}
          tasks={selectedResourceTasks}
          onSelectTask={setSelectedTaskId}
        />
        <CancellationFocus
          insight={selectedInsight && isCancellationInsight(selectedInsight) ? selectedInsight : null}
          tasks={filteredTasks}
          onSelectTask={setSelectedTaskId}
        />
        <ErrorFocus
          insight={selectedInsight && isErrorInsight(selectedInsight) ? selectedInsight : null}
          tasks={filteredTasks}
          onSelectTask={setSelectedTaskId}
        />
      </main>
    </div>
  );
}
