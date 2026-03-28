import React from "react";

import {
  CompareCapturesPanel,
  FocusWorkspace,
  Inspector,
  Insights,
  RequestJobPanel,
  SessionPulse,
  StreamStatus,
  TaskFilters,
  TaskTree,
  TaskList,
} from "./dashboard-panels";
import { Timeline } from "./Timeline";
import { useAppState } from "./useAppState";
import {
  formatClockTime,
  formatDuration,
  formatInsightTitle,
  formatQueueSliceLabel,
  formatStreamStatus,
  insightMeta,
  insightResourceId,
  isCancellationInsight,
  isDeadlockInsight,
  isErrorInsight,
  isGroupedResourceInsight,
  summarizeStates,
  taskBlockedReason,
  taskJobLabel,
  taskRequestLabel,
  taskResourceId,
  taskResourceRole,
  taskRole,
} from "./utils";

export function App() {
  const {
    tasks,
    segments,
    insights,
    session,
    resources,
    streamStatus,
    lastUpdatedAt,
    error,
    theme,
    setTheme,
    teachingMode,
    setTeachingMode,
    filters,
    activePresetId,
    insightSeverity,
    setInsightSeverity,
    stateOptions,
    taskRoleOptions,
    cancellationOptions,
    blockedReasonOptions,
    resourceOptions,
    requestLabelOptions,
    jobLabelOptions,
    filteredTasks,
    filteredSegments,
    filteredInsights,
    totalRuntime,
    selectedTaskId,
    setSelectedTaskId,
    selectedResource,
    selectedInsight,
    selectedResourceInsight,
    selectedResourceTasks,
    selectedResourceOwnerTasks,
    selectedResourceCancelledTasks,
    selectedTask,
    focusTab,
    setFocusTab,
    setTimeWindow,
    updateFilter,
    applyPreset,
    clearFilters,
    handleInsightSelect,
    selectRequestLabel,
    selectJobLabel,
  } = useAppState();

  const minimizedExportHref = selectedInsight?.kind
    ? `/api/v1/export?format=minimized&kind=${encodeURIComponent(selectedInsight.kind)}`
    : "/api/v1/export?format=minimized";

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
          {session?.python_version ? (
            <div className="metric-card">
              <span>Python</span>
              <strong>{session.python_version}</strong>
            </div>
          ) : null}
          {session?.script_path ? (
            <div className="metric-card metric-card--wide">
              <span>Script</span>
              <strong>{session.script_path}</strong>
            </div>
          ) : null}
        </div>
        <div className="hero-actions">
          <button
            className="preset-chip"
            type="button"
            aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
            onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
          >
            {theme === "dark" ? "☀ Light" : "☾ Dark"}
          </button>
          <button
            className={teachingMode ? "preset-chip active" : "preset-chip"}
            type="button"
            aria-label={teachingMode ? "Disable teaching mode" : "Enable teaching mode"}
            onClick={() => setTeachingMode((m) => !m)}
          >
            {teachingMode ? "Teaching: On" : "Teaching: Off"}
          </button>
          {session ? (
            <>
              <a className="preset-chip" href="/api/v1/export?format=json" download>
                Export JSON
              </a>
              <a className="preset-chip" href="/api/v1/export?format=csv" download>
                Export CSV
              </a>
              <a className="preset-chip" href={minimizedExportHref} download>
                Export Minimized
              </a>
            </>
          ) : null}
        </div>
      </header>

      {error ? <div className="error-banner">{error}</div> : null}
      {streamStatus === "slow_client" ? (
        <div className="warning-banner">
          Connection too slow — some events were dropped. Reload to reconnect.
        </div>
      ) : null}

      <main className="dashboard">
        <StreamStatus
          status={streamStatus}
          lastUpdatedAt={lastUpdatedAt}
          formatClockTime={formatClockTime}
          formatStreamStatus={formatStreamStatus}
        />
        <CompareCapturesPanel />
        <SessionPulse
          tasks={filteredTasks}
          insights={insights}
          resources={resources}
          summarizeStates={summarizeStates}
        />
        <RequestJobPanel
          tasks={tasks}
          requestLabelFilter={filters.requestLabel}
          jobLabelFilter={filters.jobLabel}
          onSelectRequestLabel={selectRequestLabel}
          onSelectJobLabel={selectJobLabel}
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
          items={filteredInsights}
          activeSeverity={insightSeverity}
          onSeverityChange={setInsightSeverity}
          formatInsightTitle={formatInsightTitle}
          insightMeta={insightMeta}
          teachingMode={teachingMode}
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
          onTimeWindowChange={setTimeWindow}
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
        <TaskTree
          tasks={filteredTasks}
          selectedTaskId={selectedTaskId}
          onSelectTask={setSelectedTaskId}
        />
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
          deadlockProps={{
            insight: selectedInsight && isDeadlockInsight(selectedInsight) ? selectedInsight : null,
            tasks,
            onSelectTask: setSelectedTaskId,
          }}
          taskRole={taskRole}
        />
      </main>
    </div>
  );
}
