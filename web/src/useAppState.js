import { useEffect, useMemo, useState } from "react";

import {
  fetchJson,
  filterOptions,
  insightResourceId,
  isCancellationInsight,
  isDeadlockInsight,
  isErrorInsight,
  isGroupedResourceInsight,
  isBlockedPreset,
  isCancelledPreset,
  isFailurePreset,
  taskBlockedReason,
  taskJobLabel,
  taskRequestLabel,
  taskResourceId,
  taskRole,
} from "./utils";

function getInitialTheme() {
  const stored = localStorage.getItem("pyroscope-theme");
  if (stored === "dark" || stored === "light") {
    return stored;
  }
  return window.matchMedia?.("(prefers-color-scheme: dark)")?.matches ? "dark" : "light";
}

function parseHashTaskId() {
  const match = window.location.hash.match(/^#task=(\d+)$/);
  return match ? parseInt(match[1], 10) : null;
}

export function useAppState() {
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
  const [theme, setTheme] = useState(getInitialTheme);
  const [teachingMode, setTeachingMode] = useState(false);
  const [insightSeverity, setInsightSeverity] = useState(null);
  const [timeWindow, setTimeWindow] = useState(null);
  const [filters, setFilters] = useState({
    state: "",
    taskRole: "",
    cancellationOrigin: "",
    blockedReason: "",
    resourceId: "",
    requestLabel: "",
    jobLabel: "",
    nameFilter: "",
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
          const hashId = parseHashTaskId();
          if (hashId && sessionPayload.tasks.some((task) => task.task_id === hashId)) {
            return hashId;
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
      source.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === "error" && data.code === "slow_client") {
          setStreamStatus("slow_client");
          source.close();
          return;
        }
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

  const filteredInsights = useMemo(
    () =>
      insightSeverity
        ? insights.filter((item) => item.severity === insightSeverity)
        : insights,
    [insights, insightSeverity],
  );

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

  const timeWindowTaskIds = useMemo(() => {
    if (!timeWindow) {
      return null;
    }
    return new Set(
      segments
        .filter(
          (seg) => seg.start_ts_ns <= timeWindow.end && seg.end_ts_ns >= timeWindow.start,
        )
        .map((seg) => seg.task_id),
    );
  }, [timeWindow, segments]);

  const filteredTasks = useMemo(
    () =>
      tasks.filter((task) => {
        if (timeWindowTaskIds && !timeWindowTaskIds.has(task.task_id)) {
          return false;
        }
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
        if (
          filters.nameFilter &&
          !task.name.toLowerCase().includes(filters.nameFilter.toLowerCase())
        ) {
          return false;
        }
        return true;
      }),
    [filters, tasks, timeWindowTaskIds],
  );

  const filteredTaskIds = useMemo(
    () => new Set(filteredTasks.map((task) => task.task_id)),
    [filteredTasks],
  );

  const filteredSegments = useMemo(() => {
    let result = segments.filter((segment) => filteredTaskIds.has(segment.task_id));
    if (timeWindow) {
      result = result.filter(
        (seg) => seg.start_ts_ns <= timeWindow.end && seg.end_ts_ns >= timeWindow.start,
      );
    }
    return result;
  }, [filteredTaskIds, segments, timeWindow]);

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

  useEffect(() => {
    if (selectedTaskId && filteredTasks.some((task) => task.task_id === selectedTaskId)) {
      return;
    }
    setSelectedTaskId(filteredTasks[0]?.task_id ?? null);
  }, [filteredTasks, selectedTaskId]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("pyroscope-theme", theme);
  }, [theme]);

  useEffect(() => {
    if (selectedTaskId != null) {
      history.replaceState(null, "", `#task=${selectedTaskId}`);
    }
  }, [selectedTaskId]);

  useEffect(() => {
    function handleKeyDown(event) {
      const tag = event.target?.tagName?.toLowerCase();
      if (tag === "input" || tag === "select" || tag === "textarea") {
        return;
      }
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setSelectedTaskId((current) => {
          const idx = filteredTasks.findIndex((t) => t.task_id === current);
          if (idx === -1 || idx === filteredTasks.length - 1) {
            return current;
          }
          return filteredTasks[idx + 1].task_id;
        });
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        setSelectedTaskId((current) => {
          const idx = filteredTasks.findIndex((t) => t.task_id === current);
          if (idx <= 0) {
            return current;
          }
          return filteredTasks[idx - 1].task_id;
        });
      }
      if (event.key === "n" || event.key === "p") {
        if (!filteredInsights.length) {
          return;
        }
        const currentIdx = selectedInsight
          ? filteredInsights.indexOf(selectedInsight)
          : -1;
        let nextIdx;
        if (event.key === "n") {
          nextIdx =
            currentIdx === -1 ? 0 : Math.min(filteredInsights.length - 1, currentIdx + 1);
        } else {
          nextIdx = currentIdx <= 0 ? 0 : currentIdx - 1;
        }
        const insight = filteredInsights[nextIdx];
        const resourceId = insightResourceId(insight);
        setSelectedInsightIndex(nextIdx);
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
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [filteredTasks, filteredInsights, selectedInsight]);

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

  function selectRequestLabel(label) {
    updateFilter("requestLabel", label ?? "");
  }

  function selectJobLabel(label) {
    updateFilter("jobLabel", label ?? "");
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
      requestLabel: "",
      jobLabel: "",
      nameFilter: "",
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
    if (isDeadlockInsight(insight)) {
      setFocusTab("deadlock");
    }
    if (isErrorInsight(insight)) {
      setFocusTab("error");
      setSelectedTaskId(insight.source_task_id ?? insight.task_id ?? null);
    }
  }

  return {
    // session data
    tasks,
    segments,
    insights,
    session,
    resources,
    // stream/error
    streamStatus,
    lastUpdatedAt,
    error,
    // theme
    theme,
    setTheme,
    // teaching mode
    teachingMode,
    setTeachingMode,
    // filters & presets
    filters,
    activePresetId,
    insightSeverity,
    setInsightSeverity,
    // derived filter options
    stateOptions,
    taskRoleOptions,
    cancellationOptions,
    blockedReasonOptions,
    resourceOptions,
    requestLabelOptions,
    jobLabelOptions,
    // filtered derived
    filteredTasks,
    filteredSegments,
    filteredInsights,
    totalRuntime,
    // selections
    selectedTaskId,
    setSelectedTaskId,
    selectedResourceId,
    selectedResource,
    selectedInsight,
    selectedInsightIndex,
    selectedResourceInsight,
    selectedResourceTasks,
    selectedResourceOwnerTasks,
    selectedResourceCancelledTasks,
    selectedTask,
    // focus
    focusTab,
    setFocusTab,
    // time window
    setTimeWindow,
    // handlers
    updateFilter,
    applyPreset,
    clearFilters,
    handleInsightSelect,
    selectRequestLabel,
    selectJobLabel,
  };
}
