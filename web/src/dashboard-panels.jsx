import React, { useMemo } from "react";

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
  tasks,
  insight,
  onSelectTask,
  formatInsightTitle,
  formatQueueSliceLabel,
}) {
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

export function TaskList({
  tasks,
  selectedTaskId,
  onSelectTask,
  taskRole,
  taskBlockedReason,
  taskResourceId,
  taskRequestLabel,
  taskJobLabel,
}) {
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
    </section>
  );
}

export function Insights({ items, onSelectResource, formatInsightTitle, insightMeta }) {
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
              onClick={() => onSelectResource(item, index)}
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

export function FocusWorkspace({
  activeTab,
  onSelectTab,
  resourceProps,
  cancellationProps,
  errorProps,
  formatInsightTitle,
  formatQueueSliceLabel,
  taskRole,
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
      </div>
    </section>
  );
}

export function Inspector({ task, resources }) {
  const relatedResources = useMemo(() => {
    if (!task) {
      return [];
    }
    return resources.filter((resource) => resource.task_ids?.includes(task.task_id));
  }, [resources, task]);
  const stackFrames = task?.stack?.frames ?? [];

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
            <div>Request label</div>
            <div>{task.metadata?.request_label ?? "n/a"}</div>
            <div>Job label</div>
            <div>{task.metadata?.job_label ?? "n/a"}</div>
          </div>
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
