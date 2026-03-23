import React, { useEffect, useMemo, useRef, useState } from "react";

import {
  FocusWorkspace,
  Inspector,
  Insights,
  SessionPulse,
  StreamStatus,
  TaskFilters,
  TaskList,
} from "./dashboard-panels";

const STATE_COLORS = {
  READY: "#4da6ff",
  RUNNING: "#10cfb8",
  BLOCKED: "#f43f5e",
  AWAITING: "#f59e0b",
  DONE: "#4b5563",
  FAILED: "#f43f5e",
  CANCELLED: "#8394a8",
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

function formatClockTime(timestampMs) {
  if (!timestampMs) {
    return "n/a";
  }
  return new Date(timestampMs).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatStreamStatus(status) {
  const labels = {
    connecting: "Connecting",
    live: "Live",
    reconnecting: "Reconnecting",
    error: "Error",
  };
  return labels[status] ?? status;
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

function formatInsightWaitState(item) {
  const parts = [];
  if (item.queue_size != null && item.queue_maxsize != null) {
    parts.push(`queue ${item.queue_size}/${item.queue_maxsize}`);
  } else if (item.queue_size != null) {
    parts.push(`queue ${item.queue_size}`);
  } else if (item.queue_maxsize != null) {
    parts.push(`queue max ${item.queue_maxsize}`);
  }
  if (item.event_is_set != null) {
    parts.push(`event set=${item.event_is_set ? "yes" : "no"}`);
  }
  return parts.join(" · ") || null;
}

function insightMeta(item) {
  if (item.resource_id) {
    if (item.owner_task_names?.length) {
      return `${item.resource_id} · held by ${item.owner_task_names.join(", ")}`;
    }
    return item.resource_id;
  }
  if (item.blocked_reason && item.blocked_resource_id) {
    return `${item.blocked_reason} · ${item.blocked_resource_id}`;
  }
  if (item.blocked_reason) {
    return item.blocked_reason;
  }
  const waitState = formatInsightWaitState(item);
  if (item.timeout_seconds) {
    return waitState
      ? `timeout ${item.timeout_seconds}s · ${waitState}`
      : `timeout ${item.timeout_seconds}s`;
  }
  return waitState;
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

function taskRequestLabel(task) {
  return task.metadata?.request_label ?? null;
}

function taskJobLabel(task) {
  return task.metadata?.job_label ?? null;
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

function Timeline({ tasks, segments, selectedTaskId, onSelectTask, taskResourceRole }) {
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
  const detailTask = useMemo(() => {
    if (!detailSegment) {
      return null;
    }
    return tasks.find((task) => task.task_id === detailSegment.task_id) ?? null;
  }, [detailSegment, tasks]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) {
      return;
    }
    const context = canvas.getContext("2d");
    const width = canvas.width;
    const height = canvas.height;
    context.clearRect(0, 0, width, height);
    context.fillStyle = "#0d1117";
    context.fillRect(0, 0, width, height);

    if (!segments.length) {
      context.fillStyle = "#dbe4ee";
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
      context.fillStyle = "#dbe4ee";
      context.fillText(task.name, 18, y + (rowHeight - 4) / 2);
    });

    bounds.forEach(({ segment, x, y, width: segmentWidth, height: segmentHeight }) => {
      context.fillStyle = STATE_COLORS[segment.state] || "#6bb9ff";
      context.fillRect(x, y, segmentWidth, segmentHeight);
      if (segment.task_id === selectedTaskId) {
        context.strokeStyle = "#f8fafc";
        context.lineWidth = 2;
        context.strokeRect(x, y, segmentWidth, segmentHeight);
      }
      if (
        hoveredSegment &&
        hoveredSegment.task_id === segment.task_id &&
        hoveredSegment.start_ts_ns === segment.start_ts_ns &&
        hoveredSegment.end_ts_ns === segment.end_ts_ns
      ) {
        context.strokeStyle = "#dbe4ee";
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
                <div>Resource role</div>
                <div>{detailTask ? taskResourceRole(detailTask) ?? "n/a" : "n/a"}</div>
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

export function App() {
  const [snapshot, setSnapshot] = useState(null);
  const [resources, setResources] = useState([]);
  const [selectedTaskId, setSelectedTaskId] = useState(null);
  const [selectedResourceId, setSelectedResourceId] = useState(null);
  const [selectedInsightIndex, setSelectedInsightIndex] = useState(null);
  const [focusTab, setFocusTab] = useState("resource");
  const [streamStatus, setStreamStatus] = useState("connecting");
  const [lastUpdatedAt, setLastUpdatedAt] = useState(null);
  const [error, setError] = useState(null);
  const [activePresetId, setActivePresetId] = useState(null);
  const [filters, setFilters] = useState({
    state: "",
    taskRole: "",
    cancellationOrigin: "",
    blockedReason: "",
    resourceId: "",
    requestLabel: "",
    jobLabel: "",
  });

  useEffect(() => {
    let active = true;
    let reconnectTimer = null;
    let source = null;

    async function refresh() {
      try {
        const [sessionPayload, resourcePayload] = await Promise.all([
          fetchJson("/api/v1/session"),
          fetchJson("/api/v1/resources/graph?detail=detailed"),
        ]);
        if (!active) {
          return;
        }
        setSnapshot(sessionPayload);
        setResources(resourcePayload);
        setLastUpdatedAt(Date.now());
        setStreamStatus("live");
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
          setStreamStatus("error");
          setError(refreshError.message);
        }
      }
    }

    function connectStream() {
      setStreamStatus((current) => (current === "live" ? "live" : "connecting"));
      source = new EventSource("/api/v1/stream");
      source.onmessage = () => {
        setStreamStatus("live");
        void refresh();
      };
      source.onerror = () => {
        source?.close();
        if (!active) {
          return;
        }
        setStreamStatus("reconnecting");
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
  const requestLabelOptions = useMemo(
    () => filterOptions(tasks, taskRequestLabel),
    [tasks],
  );
  const jobLabelOptions = useMemo(() => filterOptions(tasks, taskJobLabel), [tasks]);
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
        if (filters.requestLabel && taskRequestLabel(task) !== filters.requestLabel) {
          return false;
        }
        if (filters.jobLabel && taskJobLabel(task) !== filters.jobLabel) {
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
  const selectedResourceInsight =
    selectedInsight &&
    isGroupedResourceInsight(selectedInsight) &&
    insightResourceId(selectedInsight) === selectedResourceId
      ? selectedInsight
      : null;
  const selectedResourceTasks = useMemo(() => {
    if (!selectedResource && !selectedResourceInsight) {
      return [];
    }
    const ids = new Set(
      selectedResourceInsight?.blocked_task_ids?.length
        ? selectedResourceInsight.blocked_task_ids
        : selectedResource?.waiter_task_ids?.length
          ? selectedResource.waiter_task_ids
          : selectedResource?.task_ids ?? [],
    );
    return tasks.filter((task) => ids.has(task.task_id));
  }, [selectedResource, selectedResourceInsight, tasks]);
  const selectedResourceOwnerTasks = useMemo(() => {
    const ownerTaskIds =
      selectedResourceInsight?.owner_task_ids?.length
        ? selectedResourceInsight.owner_task_ids
        : selectedResource?.owner_task_ids ?? [];
    if (!ownerTaskIds.length) {
      return [];
    }
    const ids = new Set(ownerTaskIds);
    return tasks.filter((task) => ids.has(task.task_id));
  }, [selectedResource, selectedResourceInsight, tasks]);
  const selectedResourceCancelledTasks = useMemo(() => {
    const cancelledTaskIds =
      selectedResourceInsight?.cancelled_waiter_task_ids?.length
        ? selectedResourceInsight.cancelled_waiter_task_ids
        : selectedResource?.cancelled_waiter_task_ids ?? [];
    if (!cancelledTaskIds.length) {
      return [];
    }
    const ids = new Set(cancelledTaskIds);
    return tasks.filter((task) => ids.has(task.task_id));
  }, [selectedResource, selectedResourceInsight, tasks]);
  const totalRuntime = useMemo(() => {
    if (!filteredSegments.length) {
      return 0;
    }
    const starts = filteredSegments.map((segment) => segment.start_ts_ns);
    const ends = filteredSegments.map((segment) => segment.end_ts_ns);
    return Math.max(...ends) - Math.min(...starts);
  }, [filteredSegments]);

  function taskResourceRole(task) {
    if (!task.resource_roles?.length) {
      return null;
    }
    return Array.from(new Set(task.resource_roles)).join(", ");
  }

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
        if (item.blocked_task_ids?.some((taskId) => filteredTaskIds.has(taskId))) {
          return true;
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
  }, [activePresetId, filteredTaskIds, filteredTasks, insights]);

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
        <StreamStatus
          status={streamStatus}
          lastUpdatedAt={lastUpdatedAt}
          formatClockTime={formatClockTime}
          formatStreamStatus={formatStreamStatus}
        />
        <SessionPulse
          tasks={filteredTasks}
          insights={insights}
          resources={resources}
          summarizeStates={summarizeStates}
        />
        <TaskFilters
          totalCount={tasks.length}
          visibleCount={filteredTasks.length}
          stateOptions={stateOptions}
          taskRoleOptions={taskRoleOptions}
          cancellationOptions={cancellationOptions}
          blockedReasonOptions={blockedReasonOptions}
          resourceOptions={resourceOptions}
          requestLabelOptions={requestLabelOptions}
          jobLabelOptions={jobLabelOptions}
          filters={filters}
          onChange={updateFilter}
          activePresetId={activePresetId}
          onApplyPreset={applyPreset}
          onClearFilters={clearFilters}
        />
        <Insights
          items={insights}
          formatInsightTitle={formatInsightTitle}
          insightMeta={insightMeta}
          onSelectResource={(insight, index) =>
            handleInsightSelect(insightResourceId(insight), insight, index)
          }
        />
        <Timeline
          tasks={filteredTasks}
          segments={filteredSegments}
          selectedTaskId={selectedTaskId}
          onSelectTask={setSelectedTaskId}
          taskResourceRole={taskResourceRole}
        />
        <div className="grid-two">
        <TaskList
          tasks={filteredTasks}
          selectedTaskId={selectedTaskId}
          onSelectTask={setSelectedTaskId}
          taskResourceRole={taskResourceRole}
          taskBlockedReason={taskBlockedReason}
          taskResourceId={taskResourceId}
          taskRole={taskRole}
          taskRequestLabel={taskRequestLabel}
          taskJobLabel={taskJobLabel}
        />
        <Inspector task={selectedTask} resources={resources} taskResourceRole={taskResourceRole} />
        </div>
        <FocusWorkspace
          activeTab={focusTab}
          onSelectTab={setFocusTab}
          formatInsightTitle={formatInsightTitle}
          formatQueueSliceLabel={formatQueueSliceLabel}
          resourceProps={{
            resource: selectedResource,
            owners: selectedResourceOwnerTasks,
            tasks: selectedResourceTasks,
            cancelledTasks: selectedResourceCancelledTasks,
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
          taskRole={taskRole}
        />
      </main>
    </div>
  );
}
