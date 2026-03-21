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

function isGroupedResourceInsight(item) {
  return [
    "queue_backpressure",
    "lock_contention",
    "semaphore_saturation",
  ].includes(item.kind);
}

function isCancellationInsight(item) {
  return item.kind === "cancellation_chain" || item.kind === "task_cancelled";
}

function isErrorInsight(item) {
  return item.kind === "task_error";
}

function isBlockedPreset(id) {
  return id === "blocked-main";
}

function isCancelledPreset(id) {
  return id === "cancelled";
}

function isFailurePreset(id) {
  return id === "failures";
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

function formatQueueSliceLabel(reason) {
  if (reason === "queue_get") {
    return "Consumers waiting";
  }
  if (reason === "queue_put") {
    return "Producers waiting";
  }
  return reason;
}

function filterOptions(tasks, valueFn) {
  return Array.from(new Set(tasks.map(valueFn).filter(Boolean))).sort();
}

function timelineGeometry(tasks, segments, width, height) {
  if (!tasks.length || !segments.length) {
    return {
      labelWidth: 220,
      rowHeight: Math.max(28, Math.floor((height - 36) / Math.max(tasks.length, 1))),
      bounds: [],
    };
  }

  const rows = new Map(tasks.map((task, index) => [task.task_id, index]));
  const minTs = Math.min(...segments.map((segment) => segment.start_ts_ns));
  const maxTs = Math.max(...segments.map((segment) => segment.end_ts_ns));
  const span = Math.max(1, maxTs - minTs);
  const labelWidth = 220;
  const rowHeight = Math.max(28, Math.floor((height - 36) / Math.max(tasks.length, 1)));
  const usableWidth = width - labelWidth - 28;

  return {
    labelWidth,
    rowHeight,
    bounds: segments.map((segment) => {
      const row = rows.get(segment.task_id) ?? 0;
      const y = 18 + row * rowHeight;
      const x = labelWidth + ((segment.start_ts_ns - minTs) / span) * usableWidth;
      const segmentWidth = Math.max(
        4,
        ((segment.end_ts_ns - segment.start_ts_ns) / span) * usableWidth,
      );
      return {
        segment,
        x,
        y: y + 4,
        width: segmentWidth,
        height: rowHeight - 12,
      };
    }),
  };
}

function summarizeStates(tasks) {
  const counts = new Map();
  for (const task of tasks) {
    counts.set(task.state, (counts.get(task.state) ?? 0) + 1);
  }
  return Array.from(counts.entries()).sort(([left], [right]) =>
    left.localeCompare(right),
  );
}

const FILTER_PRESETS = [
  {
    id: "blocked-main",
    label: "Blocked main",
    filters: {
      state: "BLOCKED",
      taskRole: "main",
    },
  },
  {
    id: "cancelled",
    label: "Cancelled",
    filters: {
      state: "CANCELLED",
    },
  },
  {
    id: "failures",
    label: "Failures",
    filters: {
      state: "FAILED",
    },
  },
];

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
  activePresetId,
  onApplyPreset,
  onClearFilters,
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
      <div className="preset-row">
        {FILTER_PRESETS.map((preset) => (
          <button
            key={preset.id}
            className={activePresetId === preset.id ? "preset-chip active" : "preset-chip"}
            onClick={() => onApplyPreset(preset)}
            type="button"
          >
            {preset.label}
          </button>
        ))}
        <button className="preset-chip" onClick={onClearFilters} type="button">
          Clear
        </button>
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
  const [hoveredSegment, setHoveredSegment] = useState(null);
  const geometry = useMemo(
    () => timelineGeometry(tasks, segments, 1400, 460),
    [segments, tasks],
  );
  const selectedTaskSegments = useMemo(
    () => segments.filter((segment) => segment.task_id === selectedTaskId),
    [segments, selectedTaskId],
  );
  const detailSegment =
    hoveredSegment ??
    selectedTaskSegments[selectedTaskSegments.length - 1] ??
    segments[segments.length - 1] ??
    null;

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
    const { labelWidth, rowHeight, bounds } = geometry;

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

    bounds.forEach(({ segment, x, y, width: segmentWidth, height: segmentHeight }) => {
      context.fillStyle = STATE_COLORS[segment.state] || "#6bb9ff";
      context.fillRect(x, y, segmentWidth, segmentHeight);
      if (segment.task_id === selectedTaskId) {
        context.strokeStyle = "#f6f7fb";
        context.lineWidth = 2;
        context.strokeRect(x, y, segmentWidth, segmentHeight);
      }
      if (
        hoveredSegment &&
        hoveredSegment.task_id === segment.task_id &&
        hoveredSegment.start_ts_ns === segment.start_ts_ns &&
        hoveredSegment.end_ts_ns === segment.end_ts_ns
      ) {
        context.strokeStyle = "#7bd9ff";
        context.lineWidth = 2;
        context.strokeRect(x, y, segmentWidth, segmentHeight);
      }
    });
  }, [geometry, hoveredSegment, segments, selectedTaskId, tasks]);

  function handlePointerMove(event) {
    const canvas = canvasRef.current;
    if (!canvas) {
      return;
    }
    const rect = canvas.getBoundingClientRect();
    const x = ((event.clientX - rect.left) / rect.width) * canvas.width;
    const y = ((event.clientY - rect.top) / rect.height) * canvas.height;
    const hit = geometry.bounds.find(
      (bound) =>
        x >= bound.x &&
        x <= bound.x + bound.width &&
        y >= bound.y &&
        y <= bound.y + bound.height,
    );
    setHoveredSegment(hit?.segment ?? null);
  }

  return (
    <section className="panel timeline-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Runtime view</p>
          <h2>Timeline</h2>
        </div>
        <p className="muted">Live task states and wait intervals.</p>
      </div>
      <div className="timeline-layout">
        <canvas
          ref={canvasRef}
          className="timeline-canvas"
          width={1400}
          height={460}
          onClick={() => onSelectTask((hoveredSegment ?? detailSegment)?.task_id ?? selectedTaskId)}
          onMouseLeave={() => setHoveredSegment(null)}
          onMouseMove={handlePointerMove}
        />
        <aside className="timeline-detail">
          <p className="eyebrow">Timeline detail</p>
          {detailSegment ? (
            <>
              <h3>{detailSegment.task_name}</h3>
              <div className="key-grid">
                <div>State</div>
                <div>{detailSegment.state}</div>
                <div>Duration</div>
                <div>{formatDuration(detailSegment.end_ts_ns - detailSegment.start_ts_ns)}</div>
                <div>Reason</div>
                <div>{detailSegment.reason ?? "n/a"}</div>
                <div>Resource</div>
                <div>{detailSegment.resource_id ?? "n/a"}</div>
              </div>
              <div className="resource-block">
                <h3>Task timeline states</h3>
                <div className="reason-list">
                  {selectedTaskSegments.length ? (
                    selectedTaskSegments.map((segment, index) => (
                      <div key={`${segment.task_id}-${segment.start_ts_ns}-${index}`} className="reason-chip">
                        {segment.state} · {formatDuration(segment.end_ts_ns - segment.start_ts_ns)}
                      </div>
                    ))
                  ) : (
                    <div className="muted">Select a task to inspect its state intervals.</div>
                  )}
                </div>
              </div>
            </>
          ) : (
            <div className="empty">Hover a segment to inspect timing and wait metadata.</div>
          )}
        </aside>
      </div>
    </section>
  );
}

function SessionPulse({ tasks, insights, resources }) {
  const stateSummary = useMemo(() => summarizeStates(tasks), [tasks]);
  const failureCount = tasks.filter((task) => task.state === "FAILED").length;
  const cancelledCount = tasks.filter((task) => task.state === "CANCELLED").length;
  const blockedCount = tasks.filter((task) => task.state === "BLOCKED").length;

  return (
    <section className="panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Pulse</p>
          <h2>Session summary</h2>
        </div>
        <p className="muted">High-signal counts from the current filtered workspace.</p>
      </div>
      <div className="summary-grid">
        <div className="summary-card">
          <span>Blocked</span>
          <strong>{blockedCount}</strong>
        </div>
        <div className="summary-card">
          <span>Cancelled</span>
          <strong>{cancelledCount}</strong>
        </div>
        <div className="summary-card">
          <span>Failures</span>
          <strong>{failureCount}</strong>
        </div>
        <div className="summary-card">
          <span>Insights</span>
          <strong>{insights.length}</strong>
        </div>
        <div className="summary-card">
          <span>Resources</span>
          <strong>{resources.length}</strong>
        </div>
      </div>
      <div className="summary-chips">
        {stateSummary.length ? (
          stateSummary.map(([state, count]) => (
            <div key={state} className="reason-chip">
              {state} · {count}
            </div>
          ))
        ) : (
          <div className="muted">No task activity yet.</div>
        )}
      </div>
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
              <div className="task-main">
                <span className="task-title">{task.name}</span>
                <div className="task-meta-line">
                  {taskRole(task) ? <span className="task-meta-chip">{taskRole(task)}</span> : null}
                  {taskBlockedReason(task) ? (
                    <span className="task-meta-chip">{taskBlockedReason(task)}</span>
                  ) : null}
                  {taskResourceId(task) ? (
                    <span className="task-meta-chip">{taskResourceId(task)}</span>
                  ) : null}
                  {task.children?.length ? (
                    <span className="task-meta-chip">{`${task.children.length} child`}</span>
                  ) : null}
                </div>
              </div>
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

function ResourceFocus({ resource, tasks, insight, onSelectTask }) {
  const reasonCounts = useMemo(() => {
    const counts = new Map();
    for (const task of tasks) {
      const reason = task.reason ?? task.metadata?.blocked_reason ?? "unknown";
      counts.set(reason, (counts.get(reason) ?? 0) + 1);
    }
    return Array.from(counts.entries()).sort(([left], [right]) =>
      left.localeCompare(right),
    );
  }, [tasks]);

  const reasonGroups = useMemo(() => {
    const groups = new Map();
    for (const task of tasks) {
      const reason = task.reason ?? task.metadata?.blocked_reason ?? "unknown";
      if (!groups.has(reason)) {
        groups.set(reason, []);
      }
      groups.get(reason).push(task);
    }
    return Array.from(groups.entries()).sort(([left], [right]) =>
      left.localeCompare(right),
    );
  }, [tasks]);

  const isMixedQueueContention =
    insight?.kind === "queue_backpressure" &&
    reasonGroups.some(([reason]) => reason === "queue_get") &&
    reasonGroups.some(([reason]) => reason === "queue_put");

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
            {insight ? (
              <>
                <div>Insight</div>
                <div>{formatInsightTitle(insight.kind)}</div>
                <div>Blocked</div>
                <div>{insight.blocked_count ?? tasks.length}</div>
              </>
            ) : null}
          </div>
          {insight ? (
            <div className="resource-block">
              <h3>Contention summary</h3>
              <p className="muted">{insight.message}</p>
              <div className="reason-list">
                {reasonCounts.map(([reason, count]) => (
                  <div key={reason} className="reason-chip">
                    {reason} · {count}
                  </div>
                ))}
              </div>
            </div>
          ) : null}
          {isMixedQueueContention ? (
            <div className="resource-block">
              <h3>Queue slices</h3>
              <div className="reason-groups">
                {reasonGroups.map(([reason, groupedTasks]) => (
                  <div key={reason} className="reason-group">
                    <div className="reason-group-head">
                      <strong>{formatQueueSliceLabel(reason)}</strong>
                      <span className="reason-chip">
                        {reason} · {groupedTasks.length}
                      </span>
                    </div>
                    <div className="task-list">
                      {groupedTasks.map((task) => (
                        <button
                          key={task.task_id}
                          className="task-row"
                          onClick={() => onSelectTask(task.task_id)}
                          type="button"
                        >
                          <span className="task-title">{task.name}</span>
                          <span className={`state-pill state-${task.state.toLowerCase()}`}>
                            {task.state}
                          </span>
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
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

function FocusWorkspace({
  activeTab,
  onSelectTab,
  resourceProps,
  cancellationProps,
  errorProps,
}) {
  const tabs = [
    { id: "resource", label: "Resource" },
    { id: "cancellation", label: "Cancellation" },
    { id: "error", label: "Error" },
  ];

  return (
    <section className="panel focus-workspace">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Workspace</p>
          <h2>Focus workspace</h2>
        </div>
        <p className="muted">Pivot between resource pressure, cancellation chains, and task failures.</p>
      </div>
      <div className="focus-tabs" role="tablist" aria-label="Focus workspace">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            aria-selected={activeTab === tab.id}
            className={activeTab === tab.id ? "focus-tab active" : "focus-tab"}
            onClick={() => onSelectTab(tab.id)}
            role="tab"
            type="button"
          >
            {tab.label}
          </button>
        ))}
      </div>
      <div className="focus-panel">
        {activeTab === "resource" ? <ResourceFocus {...resourceProps} /> : null}
        {activeTab === "cancellation" ? <CancellationFocus {...cancellationProps} /> : null}
        {activeTab === "error" ? <ErrorFocus {...errorProps} /> : null}
      </div>
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
  const [focusTab, setFocusTab] = useState("resource");
  const [error, setError] = useState(null);
  const [activePresetId, setActivePresetId] = useState(null);
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

  useEffect(() => {
    if (!activePresetId) {
      return;
    }

    if (isFailurePreset(activePresetId)) {
      const failureInsightIndex = insights.findIndex((item) => isErrorInsight(item));
      if (failureInsightIndex !== -1) {
        const failureInsight = insights[failureInsightIndex];
        setSelectedInsightIndex(failureInsightIndex);
        setFocusTab("error");
        setSelectedTaskId(failureInsight.task_id ?? filteredTasks[0]?.task_id ?? null);
      }
      return;
    }

    if (isCancelledPreset(activePresetId)) {
      const cancellationInsightIndex = insights.findIndex((item) => isCancellationInsight(item));
      if (cancellationInsightIndex !== -1) {
        const cancellationInsight = insights[cancellationInsightIndex];
        setSelectedInsightIndex(cancellationInsightIndex);
        setFocusTab("cancellation");
        setSelectedTaskId(
          cancellationInsight.source_task_id ??
            cancellationInsight.task_id ??
            filteredTasks[0]?.task_id ??
            null,
        );
        const cancellationResourceId = insightResourceId(cancellationInsight);
        if (cancellationResourceId) {
          setSelectedResourceId(cancellationResourceId);
        }
      }
      return;
    }

    if (isBlockedPreset(activePresetId)) {
      const blockedInsightIndex = insights.findIndex((item) => {
        if (!isGroupedResourceInsight(item)) {
          return false;
        }
        const resourceId = insightResourceId(item);
        return filteredTasks.some((task) => taskResourceId(task) === resourceId);
      });
      if (blockedInsightIndex !== -1) {
        const blockedInsight = insights[blockedInsightIndex];
        setSelectedInsightIndex(blockedInsightIndex);
        setFocusTab("resource");
        setSelectedResourceId(insightResourceId(blockedInsight));
      }
      setSelectedTaskId(filteredTasks[0]?.task_id ?? null);
    }
  }, [activePresetId, filteredTasks, insights]);

  function updateFilter(key, value) {
    setActivePresetId(null);
    setFilters((current) => ({ ...current, [key]: value }));
  }

  function applyPreset(preset) {
    setActivePresetId(preset.id);
    setFilters({
      state: "",
      taskRole: "",
      cancellationOrigin: "",
      blockedReason: "",
      resourceId: "",
      ...preset.filters,
    });
  }

  function clearFilters() {
    setActivePresetId(null);
    setSelectedInsightIndex(null);
    setFocusTab("resource");
    setFilters({
      state: "",
      taskRole: "",
      cancellationOrigin: "",
      blockedReason: "",
      resourceId: "",
    });
  }

  function handleInsightSelect(resourceId, insight, index) {
    setSelectedInsightIndex(index);
    if (resourceId) {
      setSelectedResourceId(resourceId);
    }
    if (isGroupedResourceInsight(insight)) {
      setFocusTab("resource");
    }
    if (isCancellationInsight(insight)) {
      setFocusTab("cancellation");
    }
    if (isErrorInsight(insight)) {
      setFocusTab("error");
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
        <SessionPulse tasks={filteredTasks} insights={insights} resources={resources} />
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
          activePresetId={activePresetId}
          onApplyPreset={applyPreset}
          onClearFilters={clearFilters}
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
        <FocusWorkspace
          activeTab={focusTab}
          onSelectTab={setFocusTab}
          resourceProps={{
            resource: selectedResource,
            tasks: selectedResourceTasks,
            insight:
              selectedInsight && isGroupedResourceInsight(selectedInsight)
                ? selectedInsight
                : null,
            onSelectTask: setSelectedTaskId,
          }}
          cancellationProps={{
            insight:
              selectedInsight && isCancellationInsight(selectedInsight)
                ? selectedInsight
                : null,
            tasks,
            onSelectTask: setSelectedTaskId,
          }}
          errorProps={{
            insight: selectedInsight && isErrorInsight(selectedInsight) ? selectedInsight : null,
            tasks,
            onSelectTask: setSelectedTaskId,
          }}
        />
      </main>
    </div>
  );
}
