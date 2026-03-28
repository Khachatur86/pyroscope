export const STATE_COLORS = {
  READY: "#4da6ff",
  RUNNING: "#10cfb8",
  BLOCKED: "#f43f5e",
  AWAITING: "#f59e0b",
  DONE: "#4b5563",
  FAILED: "#f43f5e",
  CANCELLED: "#8394a8",
};

export async function fetchJson(path) {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`Request failed for ${path}: ${response.status}`);
  }
  return await response.json();
}

export async function postJson(path, body) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`Request failed for ${path}: ${response.status}`);
  }
  return await response.json();
}

export function formatDuration(ns) {
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

export function formatClockTime(timestampMs) {
  if (!timestampMs) {
    return "n/a";
  }
  return new Date(timestampMs).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function formatStreamStatus(status) {
  const labels = {
    connecting: "Connecting",
    live: "Live",
    reconnecting: "Reconnecting",
    error: "Error",
    slow_client: "Connection slow",
  };
  return labels[status] ?? status;
}

export function formatInsightTitle(kind) {
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

export function formatInsightWaitState(item) {
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

export function insightMeta(item) {
  if (item.kind === "deadlock" && item.cycle_task_names?.length) {
    return item.cycle_task_names.join(" → ");
  }
  if (item.kind === "timeout_taskgroup_cascade" && item.group_task_name) {
    return item.timeout_seconds
      ? `${item.group_task_name} · ${item.timeout_seconds}s`
      : item.group_task_name;
  }
  if (item.resource_id) {
    const label = item.resource_label ?? item.resource_id;
    if (item.owner_task_names?.length) {
      return `${label} · held by ${item.owner_task_names.join(", ")}`;
    }
    return label;
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

export function insightResourceId(item) {
  if (item.resource_id) {
    return item.resource_id;
  }
  return item.blocked_resource_id ?? null;
}

export function isGroupedResourceInsight(item) {
  return [
    "queue_backpressure",
    "lock_contention",
    "semaphore_saturation",
  ].includes(item.kind);
}

export function isCancellationInsight(item) {
  return (
    item.kind === "cancellation_chain" ||
    item.kind === "task_cancelled" ||
    item.kind === "cancellation_cascade" ||
    item.kind === "mixed_cause_cascade" ||
    item.kind === "timeout_taskgroup_cascade"
  );
}

export function isErrorInsight(item) {
  return item.kind === "task_error";
}

export function isDeadlockInsight(item) {
  return item.kind === "deadlock";
}

export function isBlockedPreset(id) {
  return id === "blocked-main";
}

export function isCancelledPreset(id) {
  return id === "cancelled";
}

export function isFailurePreset(id) {
  return id === "failures";
}

export function taskBlockedReason(task) {
  return task.metadata?.blocked_reason ?? task.reason ?? null;
}

export function taskResourceId(task) {
  return task.metadata?.blocked_resource_id ?? task.resource_id ?? null;
}

export function taskRole(task) {
  return task.metadata?.task_role ?? null;
}

export function taskRequestLabel(task) {
  return task.metadata?.request_label ?? null;
}

export function taskJobLabel(task) {
  return task.metadata?.job_label ?? null;
}

export function taskResourceRole(task) {
  if (!task.resource_roles?.length) {
    return null;
  }
  return Array.from(new Set(task.resource_roles)).join(", ");
}

export function formatQueueSliceLabel(reason) {
  if (reason === "queue_get") {
    return "Consumers waiting";
  }
  if (reason === "queue_put") {
    return "Producers waiting";
  }
  return reason;
}

export function filterOptions(tasks, valueFn) {
  return Array.from(new Set(tasks.map(valueFn).filter(Boolean))).sort();
}

export function timelineGeometry(tasks, segments, width, height, viewStart = 0, viewEnd = 1) {
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
  const fullSpan = Math.max(1, maxTs - minTs);
  const visibleMinTs = minTs + fullSpan * viewStart;
  const visibleSpan = Math.max(1, fullSpan * (viewEnd - viewStart));
  const labelWidth = 220;
  const rowHeight = Math.max(28, Math.floor((height - 36) / Math.max(tasks.length, 1)));
  const usableWidth = width - labelWidth - 28;

  return {
    labelWidth,
    rowHeight,
    bounds: segments.map((segment) => {
      const row = rows.get(segment.task_id) ?? 0;
      const y = 18 + row * rowHeight;
      const x = labelWidth + ((segment.start_ts_ns - visibleMinTs) / visibleSpan) * usableWidth;
      const segmentWidth = Math.max(
        4,
        ((segment.end_ts_ns - segment.start_ts_ns) / visibleSpan) * usableWidth,
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

const _STATE_PRIORITY = { FAILED: 5, BLOCKED: 4, CANCELLED: 3, RUNNING: 2, AWAITING: 1, READY: 0, DONE: -1 };

export function groupTasksByLabel(tasks, segments, labelKey) {
  const groups = new Map();
  for (const task of tasks) {
    const label = task.metadata?.[labelKey] ?? null;
    if (!label) continue;
    if (!groups.has(label)) {
      groups.set(label, { label, taskIds: [], states: [] });
    }
    const g = groups.get(label);
    g.taskIds.push(task.task_id);
    g.states.push(task.state);
  }
  const segsByTask = new Map();
  for (const seg of segments) {
    if (!segsByTask.has(seg.task_id)) segsByTask.set(seg.task_id, []);
    segsByTask.get(seg.task_id).push(seg);
  }
  return Array.from(groups.values()).map(({ label, taskIds, states }) => {
    const groupSegs = taskIds.flatMap((id) => segsByTask.get(id) ?? []);
    const start_ts_ns = groupSegs.length ? Math.min(...groupSegs.map((s) => s.start_ts_ns)) : 0;
    const end_ts_ns = groupSegs.length ? Math.max(...groupSegs.map((s) => s.end_ts_ns)) : 0;
    const dominantState = states.reduce(
      (best, s) => ((_STATE_PRIORITY[s] ?? -1) > (_STATE_PRIORITY[best] ?? -1) ? s : best),
      "DONE",
    );
    return { label, taskIds, state: dominantState, start_ts_ns, end_ts_ns };
  });
}

export function summarizeStates(tasks) {
  const counts = new Map();
  for (const task of tasks) {
    counts.set(task.state, (counts.get(task.state) ?? 0) + 1);
  }
  return Array.from(counts.entries()).sort(([left], [right]) =>
    left.localeCompare(right),
  );
}
