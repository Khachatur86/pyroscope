import React, { useMemo, useState } from "react";

import { postJson } from "./utils";

const COMPARE_HISTORY_KEY = "pyroscope-compare-history";

function loadCompareHistory() {
  try {
    const raw = localStorage.getItem(COMPARE_HISTORY_KEY);
    if (!raw) {
      return [];
    }
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function storeCompareHistory(history) {
  localStorage.setItem(COMPARE_HISTORY_KEY, JSON.stringify(history));
}

function CompareDrilldownSection({ title, items, renderItem, itemKey, defaultOpen = false }) {
  if (!items?.length) {
    return null;
  }

  return (
    <details className="resource-block" open={defaultOpen}>
      <summary>{`${title} (${items.length})`}</summary>
      <div className="reason-list">
        {items.map((item, index) => (
          <div key={itemKey(item, index)} className="reason-chip">
            {renderItem(item, index)}
          </div>
        ))}
      </div>
    </details>
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
    const ids =
      insight.cancelled_task_ids ??
      insight.affected_task_ids ??
      (insight.task_id ? [insight.task_id] : []);
    const idSet = new Set(ids);
    return tasks.filter((task) => idSet.has(task.task_id));
  }, [insight, tasks]);
  const waitStateRows = useMemo(() => {
    if (!insight) {
      return [];
    }
    const rows = [];
    if (insight.queue_size != null) {
      rows.push(["Queue size", insight.queue_size]);
    }
    if (insight.queue_maxsize != null) {
      rows.push(["Queue max", insight.queue_maxsize]);
    }
    if (insight.event_is_set != null) {
      rows.push(["Event set", insight.event_is_set ? "yes" : "no"]);
    }
    return rows;
  }, [insight]);

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
            <h3>Source context</h3>
            <div className="key-grid">
              <div>State</div>
              <div>{insight.source_task_state ?? sourceTask?.state ?? "n/a"}</div>
              <div>Reason</div>
              <div>{insight.source_task_reason ?? sourceTask?.reason ?? "n/a"}</div>
              <div>Error</div>
              <div>{insight.source_task_error ?? sourceTask?.metadata?.error ?? "n/a"}</div>
            </div>
          </div>
          {waitStateRows.length ? (
            <div className="resource-block">
              <h3>Wait state</h3>
              <div className="key-grid">
                {waitStateRows.map(([label, value]) => (
                  <React.Fragment key={label}>
                    <div>{label}</div>
                    <div>{String(value)}</div>
                  </React.Fragment>
                ))}
              </div>
            </div>
          ) : null}
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

function ErrorFocus({ insight, tasks, onSelectTask, taskRole }) {
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

function ResourceFocus({
  resource,
  owners,
  tasks,
  cancelledTasks,
  insight,
  onSelectTask,
  formatInsightTitle,
  formatQueueSliceLabel,
}) {
  const contentionTasks = useMemo(() => {
    const byId = new Map();
    for (const task of [...tasks.filter((task) => !owners?.some((owner) => owner.task_id === task.task_id)), ...(cancelledTasks ?? [])]) {
      byId.set(task.task_id, task);
    }
    return Array.from(byId.values());
  }, [cancelledTasks, owners, tasks]);

  const reasonCounts = useMemo(() => {
    const counts = new Map();
    for (const task of contentionTasks) {
      const reason = task.reason ?? task.metadata?.blocked_reason ?? "unknown";
      counts.set(reason, (counts.get(reason) ?? 0) + 1);
    }
    return Array.from(counts.entries()).sort(([left], [right]) =>
      left.localeCompare(right),
    );
  }, [contentionTasks]);

  const reasonGroups = useMemo(() => {
    const groups = new Map();
    for (const task of contentionTasks) {
      const reason = task.reason ?? task.metadata?.blocked_reason ?? "unknown";
      if (!groups.has(reason)) {
        groups.set(reason, []);
      }
      groups.get(reason).push(task);
    }
    return Array.from(groups.entries()).sort(([left], [right]) =>
      left.localeCompare(right),
    );
  }, [contentionTasks]);

  const isMixedQueueContention =
    insight?.kind === "queue_backpressure" &&
    reasonGroups.some(([reason]) => reason === "queue_get") &&
    reasonGroups.some(([reason]) => reason === "queue_put");
  const ownerCount =
    insight?.owner_count ??
    owners?.length ??
    resource?.owner_task_ids?.length ??
    0;
  const waiterCount =
    insight?.waiter_count ??
    resource?.waiter_task_ids?.length ??
    tasks.length;
  const cancelledWaiterCount =
    insight?.cancelled_waiter_count ??
    resource?.cancelled_waiter_task_ids?.length ??
    cancelledTasks?.length ??
    0;

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
            <div>{resource.resource_label ?? resource.resource_id}</div>
            <div>Tasks</div>
            <div>{resource.task_ids.length}</div>
            <div>Owners</div>
            <div>{ownerCount}</div>
            <div>Waiters</div>
            <div>{waiterCount}</div>
            <div>Cancelled</div>
            <div>{cancelledWaiterCount}</div>
            {insight ? (
              <>
                <div>Insight</div>
                <div>{formatInsightTitle(insight.kind)}</div>
                <div>Blocked</div>
                <div>{insight.blocked_count ?? contentionTasks.length}</div>
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
          {owners?.length ? (
            <div className="resource-block">
              <h3>Owners</h3>
              <div className="task-list">
                {owners.map((task) => (
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
          {cancelledTasks?.length ? (
            <div className="resource-block">
              <h3>Cancelled waiters</h3>
              <div className="task-list">
                {cancelledTasks.map((task) => (
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
          ) : null}
        </div>
      ) : (
        <div className="empty">Select a resource-focused insight to inspect waiting tasks.</div>
      )}
    </section>
  );
}

export function TaskFilters({
  totalCount,
  visibleCount,
  stateOptions,
  taskRoleOptions,
  cancellationOptions,
  blockedReasonOptions,
  resourceOptions,
  requestLabelOptions,
  jobLabelOptions,
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
      <div className="filter-search">
        <label>
          <span>Task name</span>
          <input
            aria-label="Task name"
            type="search"
            placeholder="Filter by name…"
            value={filters.nameFilter}
            onChange={(event) => onChange("nameFilter", event.target.value)}
          />
        </label>
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
        <label>
          <span>Request label</span>
          <select
            aria-label="Request label"
            value={filters.requestLabel}
            onChange={(event) => onChange("requestLabel", event.target.value)}
          >
            <option value="">All</option>
            {requestLabelOptions.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Job label</span>
          <select
            aria-label="Job label"
            value={filters.jobLabel}
            onChange={(event) => onChange("jobLabel", event.target.value)}
          >
            <option value="">All</option>
            {jobLabelOptions.map((option) => (
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

export function StreamStatus({ status, lastUpdatedAt, formatStreamStatus, formatClockTime }) {
  return (
    <section className="panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Stream</p>
          <h2>Connection</h2>
        </div>
        <div className={`status-pill status-${status}`}>{formatStreamStatus(status)}</div>
      </div>
      <div className="key-grid">
        <div>State</div>
        <div>{formatStreamStatus(status)}</div>
        <div>Last refresh</div>
        <div>{formatClockTime(lastUpdatedAt)}</div>
      </div>
    </section>
  );
}

export function CompareCapturesPanel({ onLoadCapture }) {
  const [baselineFile, setBaselineFile] = useState(null);
  const [candidateFile, setCandidateFile] = useState(null);
  const [baselineCapture, setBaselineCapture] = useState(null);
  const [candidateCapture, setCandidateCapture] = useState(null);
  const [compareCandidateCapture, setCompareCandidateCapture] = useState(null);
  const [baselineLabel, setBaselineLabel] = useState(null);
  const [candidateLabel, setCandidateLabel] = useState(null);
  const [summary, setSummary] = useState(null);
  const [history, setHistory] = useState(loadCompareHistory);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [activeDriftFilter, setActiveDriftFilter] = useState(null);

  async function handleCompare() {
    if (!baselineFile || !candidateFile) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const [baseline, candidate] = await Promise.all([
        baselineCapture
          ? Promise.resolve(baselineCapture)
          : baselineFile.text().then((text) => JSON.parse(text)),
        compareCandidateCapture
          ? Promise.resolve(compareCandidateCapture)
          : candidateFile.text().then((text) => JSON.parse(text)),
      ]);
      setBaselineCapture(baseline);
      setCompareCandidateCapture(candidate);
      setCandidateCapture(candidate);
      const payload = await postJson("/api/v1/replay/compare", {
        baseline,
        candidate,
      });
      setSummary(payload);
      setActiveDriftFilter(null);
      setHistory((current) => {
        const next = [
          {
            summary: payload,
            baselineCapture: baseline,
            candidateCapture: candidate,
            baselineLabel: baselineLabel ?? payload.baseline.session_name,
            candidateLabel: candidateLabel ?? payload.candidate.session_name,
          },
          ...current,
        ].slice(0, 5);
        storeCompareHistory(next);
        return next;
      });
    } catch (compareError) {
      setError(compareError.message);
    } finally {
      setLoading(false);
    }
  }

  function removeHistoryItem(indexToRemove) {
    setHistory((current) => {
      const removed = current[indexToRemove];
      const next = current.filter((_, index) => index !== indexToRemove);
      if (
        removed &&
        summary?.baseline.session_name === removed.summary.baseline.session_name &&
        summary?.candidate.session_name === removed.summary.candidate.session_name
      ) {
        setSummary(null);
        setCandidateCapture(null);
        setActiveDriftFilter(null);
      }
      storeCompareHistory(next);
      return next;
    });
  }

  function swapArmedInputs() {
    const nextBaselineFile = candidateFile;
    const nextCandidateFile = baselineFile;
    const nextBaselineCapture = compareCandidateCapture;
    const nextCandidateCapture = baselineCapture;
    const nextBaselineLabel = candidateLabel;
    const nextCandidateLabel = baselineLabel;

    setBaselineFile(nextBaselineFile);
    setCandidateFile(nextCandidateFile);
    setBaselineCapture(nextBaselineCapture);
    setCompareCandidateCapture(nextCandidateCapture);
    setBaselineLabel(nextBaselineLabel);
    setCandidateLabel(nextCandidateLabel);
  }

  return (
    <section className="panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Capture compare</p>
          <h2>Browser</h2>
        </div>
      </div>
      <p className="muted">
        Load two saved captures and compare them in the current UI session.
      </p>
      <div className="key-grid">
        <label>
          Baseline capture
          <input
            aria-label="Baseline capture"
            type="file"
            accept=".json,application/json"
            onChange={(event) => {
              setBaselineCapture(null);
              const nextFile = event.target.files?.[0] ?? null;
              setBaselineFile(nextFile);
              setBaselineLabel(nextFile?.name ?? null);
            }}
          />
        </label>
        <label>
          Candidate capture
          <input
            aria-label="Candidate capture"
            type="file"
            accept=".json,application/json"
            onChange={(event) => {
              setCompareCandidateCapture(null);
              const nextFile = event.target.files?.[0] ?? null;
              setCandidateFile(nextFile);
              setCandidateLabel(nextFile?.name ?? null);
            }}
          />
        </label>
      </div>
      {baselineLabel || candidateLabel ? (
        <div className="key-grid">
          <div>Armed baseline</div>
          <div>{baselineLabel ?? "none"}</div>
          <div>Armed candidate</div>
          <div>{candidateLabel ?? "none"}</div>
        </div>
      ) : null}
      {(baselineLabel || candidateLabel) ? (
        <button
          className="preset-chip"
          type="button"
          onClick={swapArmedInputs}
          disabled={!baselineLabel && !candidateLabel}
        >
          Swap
        </button>
      ) : null}
      <button
        className="preset-chip"
        type="button"
        onClick={() => void handleCompare()}
        disabled={
          (!baselineFile && !baselineCapture) ||
          (!candidateFile && !compareCandidateCapture) ||
          loading
        }
      >
        {loading ? "Comparing..." : "Compare Captures"}
      </button>
      {history.length ? (
        <button
          className="preset-chip"
          type="button"
          onClick={() => {
            setHistory([]);
            setSummary(null);
            setBaselineCapture(null);
            setCompareCandidateCapture(null);
            setBaselineLabel(null);
            setCandidateLabel(null);
            setCandidateCapture(null);
            setActiveDriftFilter(null);
            storeCompareHistory([]);
          }}
        >
          Clear History
        </button>
      ) : null}
      {error ? <div className="error-banner">{error}</div> : null}
      {summary ? (
        <div className="resource-block">
          <div className="key-grid">
            <div>Baseline</div>
            <div>{summary.baseline.session_name}</div>
            <div>Candidate</div>
            <div>{summary.candidate.session_name}</div>
            <div>Tasks</div>
            <div>{`${summary.counts.baseline_tasks} -> ${summary.counts.candidate_tasks}`}</div>
            <div>Insights</div>
            <div>
              {`${summary.counts.baseline_insights} -> ${summary.counts.candidate_insights}`}
            </div>
          </div>
          <div className="reason-list">
            <button
              className={activeDriftFilter === "state_changes" ? "reason-chip active" : "reason-chip"}
              type="button"
              onClick={() => setActiveDriftFilter("state_changes")}
            >
              {`State changes: ${summary.state_changes?.length ?? 0}`}
            </button>
            <button
              className={activeDriftFilter === "error_drift" ? "reason-chip active" : "reason-chip"}
              type="button"
              onClick={() => setActiveDriftFilter("error_drift")}
            >
              {`Errors added: ${summary.error_drift?.added?.length ?? 0}`}
            </button>
            <button
              className={activeDriftFilter === "cancellation_drift" ? "reason-chip active" : "reason-chip"}
              type="button"
              onClick={() => setActiveDriftFilter("cancellation_drift")}
            >
              {`Cancellation added: ${summary.cancellation_drift?.added?.length ?? 0}`}
            </button>
            <button
              className={activeDriftFilter === "hot_task_drift" ? "reason-chip active" : "reason-chip"}
              type="button"
              onClick={() => setActiveDriftFilter("hot_task_drift")}
            >
              {`Hot tasks added: ${summary.hot_task_drift?.added?.length ?? 0}`}
            </button>
            {activeDriftFilter ? (
              <button
                className="reason-chip active"
                type="button"
                onClick={() => setActiveDriftFilter(null)}
              >
                Show all
              </button>
            ) : null}
          </div>
          {activeDriftFilter == null || activeDriftFilter === "state_changes" ? (
            <CompareDrilldownSection
              title="State changes"
              items={summary.state_changes}
              defaultOpen
              itemKey={(item) => `${item.name}-${item.baseline_state}-${item.candidate_state}`}
              renderItem={(item) => `${item.name} (${item.baseline_state} -> ${item.candidate_state})`}
            />
          ) : null}
          {activeDriftFilter == null || activeDriftFilter === "error_drift" ? (
            <CompareDrilldownSection
              title="Errors added"
              items={summary.error_drift?.added}
              itemKey={(item) => `${item.name}-${item.reason}-${item.error}`}
              renderItem={(item) => `${item.name} [${item.reason}] ${item.error}`}
            />
          ) : null}
          {activeDriftFilter == null || activeDriftFilter === "cancellation_drift" ? (
            <CompareDrilldownSection
              title="Cancellation added"
              items={summary.cancellation_drift?.added}
              itemKey={(item, index) => `${item.message}-${index}`}
              renderItem={(item) => item.message}
            />
          ) : null}
          {activeDriftFilter == null || activeDriftFilter === "hot_task_drift" ? (
            <CompareDrilldownSection
              title="Hot tasks added"
              items={summary.hot_task_drift?.added}
              itemKey={(item) => `${item.name}-${item.state}-${item.reason}`}
              renderItem={(item) => `${item.name} [${item.state}/${item.reason}]`}
            />
          ) : null}
          {baselineCapture ? (
            <button
              className="preset-chip"
              type="button"
              onClick={() => void onLoadCapture(baselineCapture)}
            >
              Load Baseline
            </button>
          ) : null}
          {candidateCapture ? (
            <button
              className="preset-chip"
              type="button"
              onClick={() => void onLoadCapture(candidateCapture)}
            >
              Load Candidate
            </button>
          ) : null}
        </div>
      ) : null}
      {history.length ? (
        <div className="resource-block">
          <h3>Recent comparisons</h3>
          <div className="reason-list">
            {history.map((item, index) => (
              <div
                key={`${item.summary.baseline.session_name}-${item.summary.candidate.session_name}-${index}`}
                className="reason-chip"
              >
                <button
                  type="button"
                  onClick={() => {
                    setSummary(item.summary);
                    setBaselineCapture(item.baselineCapture);
                    setCompareCandidateCapture(item.candidateCapture);
                    setBaselineLabel(item.baselineLabel ?? item.summary.baseline.session_name);
                    setCandidateLabel(item.candidateLabel ?? item.summary.candidate.session_name);
                    setCandidateCapture(item.candidateCapture);
                    setActiveDriftFilter(null);
                  }}
                >
                  {`${item.summary.baseline.session_name} -> ${item.summary.candidate.session_name}`}
                </button>
                <button
                  aria-label={`Use ${item.summary.baseline.session_name} -> ${item.summary.candidate.session_name} as baseline`}
                  type="button"
                  onClick={() => {
                    setBaselineCapture(item.baselineCapture);
                    setBaselineLabel(item.baselineLabel ?? item.summary.baseline.session_name);
                  }}
                >
                  baseline
                </button>
                <button
                  aria-label={`Use ${item.summary.baseline.session_name} -> ${item.summary.candidate.session_name} as candidate`}
                  type="button"
                  onClick={() => {
                    setCompareCandidateCapture(item.candidateCapture);
                    setCandidateLabel(item.candidateLabel ?? item.summary.candidate.session_name);
                  }}
                >
                  candidate
                </button>
                <button
                  aria-label={`Remove comparison ${item.summary.baseline.session_name} -> ${item.summary.candidate.session_name}`}
                  type="button"
                  onClick={() => removeHistoryItem(index)}
                >
                  x
                </button>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}

export function SessionPulse({ tasks, insights, resources, summarizeStates }) {
  const stateSummary = useMemo(() => summarizeStates(tasks), [tasks, summarizeStates]);
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

const TASK_PAGE_SIZE = 25;

export function TaskList({
  tasks,
  selectedTaskId,
  onSelectTask,
  taskRole,
  taskResourceRole,
  taskBlockedReason,
  taskResourceId,
  taskRequestLabel,
  taskJobLabel,
}) {
  const [page, setPage] = useState(1);
  const totalPages = Math.max(1, Math.ceil(tasks.length / TASK_PAGE_SIZE));

  // Reset to page 1 whenever the task list changes
  React.useEffect(() => {
    setPage(1);
  }, [tasks]);

  const pageTasks = tasks.slice((page - 1) * TASK_PAGE_SIZE, page * TASK_PAGE_SIZE);

  return (
    <section className="panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Workload</p>
          <h2>Tasks</h2>
        </div>
      </div>
      <div className="task-list">
        {pageTasks.length ? (
          pageTasks.map((task) => (
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
                  {taskResourceRole(task) ? (
                    <span className="task-meta-chip">{taskResourceRole(task)}</span>
                  ) : null}
                  {taskBlockedReason(task) ? (
                    <span className="task-meta-chip">{taskBlockedReason(task)}</span>
                  ) : null}
                  {taskResourceId(task) ? (
                    <span className="task-meta-chip">{taskResourceId(task)}</span>
                  ) : null}
                  {taskRequestLabel(task) ? (
                    <span className="task-meta-chip">{taskRequestLabel(task)}</span>
                  ) : null}
                  {taskJobLabel(task) ? (
                    <span className="task-meta-chip">{taskJobLabel(task)}</span>
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
      {tasks.length > 0 ? (
        <div className="task-pagination">
          {totalPages > 1 && (
            <button
              className="preset-chip"
              type="button"
              aria-label="Previous page"
              disabled={page <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
            >
              ‹
            </button>
          )}
          <span className="page-indicator">Page {page} of {totalPages}</span>
          {totalPages > 1 && (
            <button
              className="preset-chip"
              type="button"
              aria-label="Next page"
              disabled={page >= totalPages}
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            >
              ›
            </button>
          )}
        </div>
      ) : null}
    </section>
  );
}

export function RequestJobPanel({ tasks, requestLabelFilter, jobLabelFilter, onSelectRequestLabel, onSelectJobLabel }) {
  const requestCounts = useMemo(() => {
    const counts = new Map();
    for (const task of tasks) {
      const label = task.metadata?.request_label;
      if (!label) continue;
      const entry = counts.get(label) ?? { total: 0, states: {} };
      entry.total += 1;
      entry.states[task.state] = (entry.states[task.state] ?? 0) + 1;
      counts.set(label, entry);
    }
    return Array.from(counts.entries())
      .sort((a, b) => b[1].total - a[1].total || a[0].localeCompare(b[0]));
  }, [tasks]);

  const jobCounts = useMemo(() => {
    const counts = new Map();
    for (const task of tasks) {
      const label = task.metadata?.job_label;
      if (!label) continue;
      const entry = counts.get(label) ?? { total: 0, states: {} };
      entry.total += 1;
      entry.states[task.state] = (entry.states[task.state] ?? 0) + 1;
      counts.set(label, entry);
    }
    return Array.from(counts.entries())
      .sort((a, b) => b[1].total - a[1].total || a[0].localeCompare(b[0]));
  }, [tasks]);

  if (!requestCounts.length && !jobCounts.length) {
    return null;
  }

  return (
    <section className="panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Service flows</p>
          <h2>Requests &amp; Jobs</h2>
        </div>
      </div>
      <div className="rj-grid">
        {requestCounts.length > 0 && (
          <div className="rj-group">
            <p className="eyebrow">By request</p>
            {requestCounts.map(([label, { total, states }]) => (
              <button
                key={label}
                className={requestLabelFilter === label ? "rj-row active" : "rj-row"}
                type="button"
                onClick={() => onSelectRequestLabel(requestLabelFilter === label ? null : label)}
              >
                <span className="rj-label">{label}</span>
                <span className="rj-count">{total}</span>
                <span className="rj-states">
                  {Object.entries(states).map(([state, count]) => (
                    <span key={state} className={`rj-state rj-state-${state.toLowerCase()}`}>
                      {state.charAt(0)}{count}
                    </span>
                  ))}
                </span>
              </button>
            ))}
          </div>
        )}
        {jobCounts.length > 0 && (
          <div className="rj-group">
            <p className="eyebrow">By job</p>
            {jobCounts.map(([label, { total, states }]) => (
              <button
                key={label}
                className={jobLabelFilter === label ? "rj-row active" : "rj-row"}
                type="button"
                onClick={() => onSelectJobLabel(jobLabelFilter === label ? null : label)}
              >
                <span className="rj-label">{label}</span>
                <span className="rj-count">{total}</span>
                <span className="rj-states">
                  {Object.entries(states).map(([state, count]) => (
                    <span key={state} className={`rj-state rj-state-${state.toLowerCase()}`}>
                      {state.charAt(0)}{count}
                    </span>
                  ))}
                </span>
              </button>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

const SEVERITY_LEVELS = ["error", "warning", "info"];

export function Insights({ items, activeSeverity, onSeverityChange, onSelectResource, formatInsightTitle, insightMeta, teachingMode }) {
  return (
    <section className="panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Analysis</p>
          <h2>Insights</h2>
        </div>
        <div className="severity-filters">
          <button
            className={activeSeverity === null ? "preset-chip active" : "preset-chip"}
            onClick={() => onSeverityChange(null)}
            type="button"
          >
            All
          </button>
          {SEVERITY_LEVELS.map((level) => (
            <button
              key={level}
              className={activeSeverity === level ? "preset-chip active" : "preset-chip"}
              onClick={() => onSeverityChange(level)}
              type="button"
            >
              {level.charAt(0).toUpperCase() + level.slice(1)}
            </button>
          ))}
        </div>
      </div>
      <div className="insight-list">
        {items.length ? (
          items.map((item, index) => (
            <InsightCard
              key={`${item.kind}-${index}`}
              item={item}
              index={index}
              formatInsightTitle={formatInsightTitle}
              insightMeta={insightMeta}
              teachingMode={teachingMode}
              onSelect={onSelectResource}
            />
          ))
        ) : (
          <div className="empty">No findings yet.</div>
        )}
      </div>
    </section>
  );
}

function InsightCard({ item, index, formatInsightTitle, insightMeta, teachingMode, onSelect }) {
  const [collapsed, setCollapsed] = useState(false);
  return (
    <div className={`insight insight-${item.severity}`}>
      <button
        className="insight-select"
        onClick={() => onSelect(item, index)}
        type="button"
      >
        <div className="insight-head">
          <div className="insight-kind">{formatInsightTitle(item.kind)}</div>
          {insightMeta(item) ? <div className="insight-meta">{insightMeta(item)}</div> : null}
        </div>
        {collapsed ? null : <div className="insight-body">{item.message}</div>}
        {!collapsed && teachingMode && item.explanation ? (
          <div className="insight-explanation">
            {item.explanation.what ? (
              <p className="explanation-what"><strong>What:</strong> {item.explanation.what}</p>
            ) : null}
            {item.explanation.how ? (
              <p className="explanation-how"><strong>How to fix:</strong> {item.explanation.how}</p>
            ) : null}
          </div>
        ) : null}
      </button>
      <button
        className="insight-toggle"
        aria-label={collapsed ? "Expand" : "Collapse"}
        onClick={() => setCollapsed((prev) => !prev)}
        type="button"
      >
        {collapsed ? "▶" : "▼"}
      </button>
    </div>
  );
}

function DeadlockFocus({ insight, tasks, onSelectTask }) {
  const cycleTasks = useMemo(() => {
    if (!insight) return [];
    const ids = new Set(insight.cycle_task_ids ?? []);
    return tasks.filter((t) => ids.has(t.task_id));
  }, [insight, tasks]);

  return (
    <section className="panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Deadlock focus</p>
          <h2>Cycle</h2>
        </div>
      </div>
      {insight ? (
        <div className="resource-focus">
          <div className="key-grid">
            <div>Cycle</div>
            <div>{(insight.cycle_task_names ?? []).join(" → ")}</div>
          </div>
          <div className="resource-block">
            <h3>Deadlocked tasks</h3>
            <div className="reason-list">
              {cycleTasks.map((task) => (
                <button
                  key={task.task_id}
                  className="reason-chip"
                  type="button"
                  onClick={() => onSelectTask(task.task_id)}
                >
                  {task.name}
                </button>
              ))}
            </div>
          </div>
        </div>
      ) : (
        <div className="empty">Select a deadlock insight to inspect the cycle.</div>
      )}
    </section>
  );
}

export function FocusWorkspace({
  activeTab,
  onSelectTab,
  resourceProps,
  cancellationProps,
  errorProps,
  deadlockProps,
  formatInsightTitle,
  formatQueueSliceLabel,
  taskRole,
}) {
  const tabs = [
    { id: "resource", label: "Resource" },
    { id: "cancellation", label: "Cancellation" },
    { id: "error", label: "Error" },
    { id: "deadlock", label: "Deadlock" },
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
        {activeTab === "resource" ? (
          <ResourceFocus
            {...resourceProps}
            formatInsightTitle={formatInsightTitle}
            formatQueueSliceLabel={formatQueueSliceLabel}
          />
        ) : null}
        {activeTab === "cancellation" ? <CancellationFocus {...cancellationProps} /> : null}
        {activeTab === "error" ? (
          <ErrorFocus {...errorProps} taskRole={taskRole} />
        ) : null}
        {activeTab === "deadlock" ? <DeadlockFocus {...(deadlockProps ?? {})} /> : null}
      </div>
    </section>
  );
}

function BlockExplainer({ task, resources }) {
  if (!task) {
    return null;
  }
  const blockedReason = task.metadata?.blocked_reason ?? task.reason ?? null;
  const blockedResourceId = task.metadata?.blocked_resource_id ?? task.resource_id ?? null;
  const resource = blockedResourceId
    ? resources.find((r) => r.resource_id === blockedResourceId)
    : null;

  if (task.state === "BLOCKED" && blockedReason) {
    const ownerCount = resource?.owner_task_ids?.length ?? 0;
    const waiterCount = Math.max(0, (resource?.waiter_task_ids?.length ?? 0) - 1);
    const cancelledCount = resource?.cancelled_waiter_task_ids?.length ?? 0;
    return (
      <div className="resource-block">
        <h3>Why blocked?</h3>
        <p>
          Waiting on <strong>{blockedReason}</strong>
          {blockedResourceId ? (
            <>
              {" "}for <strong>{blockedResourceId}</strong>
            </>
          ) : null}.
        </p>
        {resource ? (
          <ul className="reason-list">
            <li className="reason-chip">
              {ownerCount
                ? `Held by ${ownerCount} task(s).`
                : "No task currently holds this resource."}
            </li>
            {waiterCount > 0 ? (
              <li className="reason-chip">{waiterCount} other task(s) also waiting.</li>
            ) : null}
            {cancelledCount > 0 ? (
              <li className="reason-chip">{cancelledCount} task(s) cancelled while waiting.</li>
            ) : null}
          </ul>
        ) : null}
      </div>
    );
  }

  if (task.state === "CANCELLED" && task.cancellation_source) {
    return (
      <div className="resource-block">
        <h3>Why cancelled?</h3>
        <p>
          Cancelled by <strong>{task.cancellation_source.task_name}</strong> via{" "}
          <strong>{task.cancellation_origin}</strong> cancellation.
          {blockedReason && blockedResourceId
            ? ` Was waiting on ${blockedReason} for ${blockedResourceId} when cancelled.`
            : null}
        </p>
      </div>
    );
  }

  if (task.state === "FAILED" && task.exception) {
    return (
      <div className="resource-block">
        <h3>Why failed?</h3>
        <p>
          Failed with <strong>{task.exception}</strong>.
          {task.parent_task_id ? null : " This was a root task (no parent)."}
        </p>
      </div>
    );
  }

  return null;
}

function copyTaskJson(task) {
  if (!navigator?.clipboard?.writeText) {
    return;
  }
  void navigator.clipboard.writeText(JSON.stringify(task, null, 2));
}

export function Inspector({ task, resources, taskResourceRole }) {
  const relatedResources = useMemo(() => {
    if (!task) {
      return [];
    }
    return resources
      .filter((resource) => {
        const relatedTaskIds = new Set([
          ...(resource.task_ids ?? []),
          ...(resource.waiter_task_ids ?? []),
          ...(resource.cancelled_waiter_task_ids ?? []),
        ]);
        return relatedTaskIds.has(task.task_id);
      })
      .map((resource) => ({
        ...resource,
        role: [
          (resource.owner_task_ids ?? []).includes(task.task_id) ? "owner" : null,
          (resource.waiter_task_ids ?? []).includes(task.task_id) ? "waiter" : null,
          (resource.cancelled_waiter_task_ids ?? []).includes(task.task_id)
            ? "cancelled waiter"
            : null,
        ]
          .filter(Boolean)
          .join(", "),
        related_task_count: new Set([
          ...(resource.task_ids ?? []),
          ...(resource.waiter_task_ids ?? []),
          ...(resource.cancelled_waiter_task_ids ?? []),
        ]).size,
      }));
  }, [resources, task]);
  const stackFrames = task?.stack?.frames ?? [];

  return (
    <section className="panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Selection</p>
          <h2>Inspector</h2>
        </div>
        {task ? (
          <button className="preset-chip" onClick={() => copyTaskJson(task)} type="button">
            Copy as JSON
          </button>
        ) : null}
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
            <div>Resource role</div>
            <div>{taskResourceRole(task) ?? "n/a"}</div>
            <div>Request label</div>
            <div>{task.metadata?.request_label ?? "n/a"}</div>
            <div>Job label</div>
            <div>{task.metadata?.job_label ?? "n/a"}</div>
          </div>
          <BlockExplainer task={task} resources={resources} />
          {task.exception ? <p className="exception">{task.exception}</p> : null}
          {stackFrames.length ? (
            <div className="resource-block">
              <h3>Stack snapshot</h3>
              <div className="stack-block">
                {stackFrames.map((frame, index) => (
                  <code key={`${task.stack.stack_id}-${index}`} className="stack-frame">
                    {frame}
                  </code>
                ))}
              </div>
            </div>
          ) : null}
          <pre>{JSON.stringify(task, null, 2)}</pre>
          <div className="resource-block">
            <h3>Related resources</h3>
            {relatedResources.length ? (
              <ul>
                {relatedResources.map((resource, index) => (
                  <li key={`${resource.resource_id}-${index}`}>
                    {resource.resource_id}
                    {resource.role ? ` · ${resource.role}` : ""}
                    {" · "}
                    {resource.related_task_count} task(s)
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

function TreeNode({ task, taskMap, selectedTaskId, onSelectTask, depth }) {
  const [expanded, setExpanded] = useState(true);
  const children = (task.children ?? []).map((id) => taskMap.get(id)).filter(Boolean);
  return (
    <div className="tree-node" style={{ paddingLeft: depth * 20 }}>
      <div className="tree-row">
        {children.length > 0 ? (
          <button
            className="tree-toggle"
            type="button"
            aria-label={expanded ? "Collapse" : "Expand"}
            onClick={() => setExpanded((e) => !e)}
          >
            {expanded ? "▼" : "▶"}
          </button>
        ) : (
          <span className="tree-leaf" aria-hidden="true">·</span>
        )}
        <button
          className={`tree-task${task.task_id === selectedTaskId ? " selected" : ""}`}
          type="button"
          onClick={() => onSelectTask(task.task_id)}
        >
          {task.name} <span className="tree-state">{task.state}</span>
        </button>
      </div>
      {expanded
        ? children.map((child) => (
            <TreeNode
              key={child.task_id}
              task={child}
              taskMap={taskMap}
              selectedTaskId={selectedTaskId}
              onSelectTask={onSelectTask}
              depth={depth + 1}
            />
          ))
        : null}
    </div>
  );
}

export function TaskTree({ tasks, selectedTaskId, onSelectTask }) {
  const taskMap = useMemo(() => new Map(tasks.map((t) => [t.task_id, t])), [tasks]);
  const roots = useMemo(() => tasks.filter((t) => !t.parent_task_id), [tasks]);

  return (
    <section className="panel task-tree-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Hierarchy view</p>
          <h2>Task tree</h2>
        </div>
        <p className="muted">Full parent-child task hierarchy.</p>
      </div>
      <div className="task-tree">
        {roots.length ? (
          roots.map((root) => (
            <TreeNode
              key={root.task_id}
              task={root}
              taskMap={taskMap}
              selectedTaskId={selectedTaskId}
              onSelectTask={onSelectTask}
              depth={0}
            />
          ))
        ) : (
          <div className="empty">No tasks.</div>
        )}
      </div>
    </section>
  );
}
