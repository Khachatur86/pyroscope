import React from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import { groupTasksByLabel } from "./utils";

const SESSION_PAYLOAD = {
  session: {
    session_name: "demo-session",
    task_count: 2,
    event_count: 12,
  },
  tasks: [
    {
      task_id: 1,
      name: "worker-1",
      state: "BLOCKED",
      resource_roles: ["waiter"],
      reason: "queue_get",
      resource_id: "queue:jobs",
      parent_task_id: null,
      children: [2],
      exception: null,
      metadata: {
        task_role: "main",
        blocked_reason: "queue_get",
        blocked_resource_id: "queue:jobs",
        request_label: "GET /jobs/42",
        job_label: "job-42",
      },
    },
    {
      task_id: 2,
      name: "worker-2",
      state: "CANCELLED",
      resource_roles: ["cancelled waiter"],
      parent_task_id: 1,
      children: [],
      exception: "boom",
      cancelled_by_task_id: 1,
      cancellation_origin: "parent_task",
      cancellation_source: {
        task_id: 1,
        task_name: "worker-1",
        state: "BLOCKED",
      },
      metadata: {
        task_role: "background",
        blocked_reason: "queue_get",
        blocked_resource_id: "queue:jobs",
        request_label: "GET /jobs/42",
        job_label: "job-42",
      },
      stack: {
        stack_id: "stack-worker-2",
        task_id: 2,
        ts_ns: 123456789,
        frames: [
          "examples/cancellation_demo.py:11 in waiting_consumer",
          "await lock.acquire()",
        ],
      },
    },
  ],
  segments: [
    {
      task_id: 1,
      task_name: "worker-1",
      state: "BLOCKED",
      start_ts_ns: 0,
      end_ts_ns: 4_500_000,
    },
    {
      task_id: 2,
      task_name: "worker-2",
      state: "RUNNING",
      start_ts_ns: 4_500_000,
      end_ts_ns: 9_000_000,
    },
  ],
  insights: [
    {
      kind: "queue_backpressure",
      severity: "warning",
      message: "Queue queue:jobs is backing up with 2 waiting tasks: worker-1, worker-2",
      resource_id: "queue:jobs",
    },
    {
      kind: "cancellation_chain",
      severity: "warning",
      message: "Task worker-1 triggered cancellation of 1 sibling task: worker-2",
      source_task_id: 1,
      source_task_name: "worker-1",
      source_task_state: "BLOCKED",
      source_task_reason: "queue_get",
      source_task_error: null,
      affected_task_ids: [2],
      affected_task_names: ["worker-2"],
      reason: "parent_task",
      queue_size: 0,
      queue_maxsize: 16,
    },
  ],
};

const RESOURCES_PAYLOAD = [
  {
    resource_id: "sleep",
    task_ids: [1],
    owner_task_ids: [],
    waiter_task_ids: [1],
    cancelled_waiter_task_ids: [],
  },
  {
    resource_id: "queue:jobs",
    task_ids: [1],
    owner_task_ids: [],
    waiter_task_ids: [1],
    cancelled_waiter_task_ids: [2],
  },
];

const FAILED_ROOT_PAYLOAD = {
  session: {
    session_name: "failed-root-session",
    task_count: 1,
    event_count: 4,
  },
  tasks: [
    {
      task_id: 21,
      name: "root-main",
      state: "FAILED",
      parent_task_id: null,
      children: [],
      exception: "RuntimeError('boom')",
      metadata: {
        task_role: "main",
        runtime_origin: "asyncio.run",
      },
    },
  ],
  segments: [
    {
      task_id: 21,
      task_name: "root-main",
      state: "RUNNING",
      start_ts_ns: 0,
      end_ts_ns: 8_000_000,
    },
    {
      task_id: 21,
      task_name: "root-main",
      state: "FAILED",
      start_ts_ns: 8_000_000,
      end_ts_ns: 10_000_000,
    },
  ],
  insights: [
    {
      kind: "task_error",
      severity: "error",
      task_id: 21,
      reason: "RuntimeError",
      message: "Task root-main failed with RuntimeError('boom')",
    },
  ],
};

const MIXED_QUEUE_PAYLOAD = {
  session: {
    session_name: "mixed-queue-session",
    task_count: 4,
    event_count: 8,
  },
  tasks: [
    {
      task_id: 401,
      name: "consumer-a",
      state: "BLOCKED",
      resource_roles: ["waiter"],
      reason: "queue_get",
      resource_id: "queue:mixed",
      parent_task_id: null,
      children: [],
      metadata: {
        blocked_reason: "queue_get",
        blocked_resource_id: "queue:mixed",
      },
    },
    {
      task_id: 402,
      name: "consumer-b",
      state: "BLOCKED",
      resource_roles: ["waiter"],
      reason: "queue_get",
      resource_id: "queue:mixed",
      parent_task_id: null,
      children: [],
      metadata: {
        blocked_reason: "queue_get",
        blocked_resource_id: "queue:mixed",
      },
    },
    {
      task_id: 403,
      name: "producer-a",
      state: "BLOCKED",
      resource_roles: ["waiter"],
      reason: "queue_put",
      resource_id: "queue:mixed",
      parent_task_id: null,
      children: [],
      metadata: {
        blocked_reason: "queue_put",
        blocked_resource_id: "queue:mixed",
      },
    },
    {
      task_id: 404,
      name: "producer-b",
      state: "BLOCKED",
      resource_roles: ["waiter"],
      reason: "queue_put",
      resource_id: "queue:mixed",
      parent_task_id: null,
      children: [],
      metadata: {
        blocked_reason: "queue_put",
        blocked_resource_id: "queue:mixed",
      },
    },
  ],
  segments: [
    { task_id: 401, task_name: "consumer-a", state: "BLOCKED", start_ts_ns: 0, end_ts_ns: 4_000_000 },
    { task_id: 402, task_name: "consumer-b", state: "BLOCKED", start_ts_ns: 0, end_ts_ns: 4_000_000 },
    { task_id: 403, task_name: "producer-a", state: "BLOCKED", start_ts_ns: 0, end_ts_ns: 4_000_000 },
    { task_id: 404, task_name: "producer-b", state: "BLOCKED", start_ts_ns: 0, end_ts_ns: 4_000_000 }
  ],
  insights: [
    {
      kind: "queue_backpressure",
      severity: "warning",
      message:
        "Queue queue:mixed is backing up with 4 waiting tasks: consumer-a, consumer-b, producer-a, producer-b",
      resource_id: "queue:mixed",
      blocked_count: 4,
    },
  ],
};

const MIXED_QUEUE_RESOURCES = [
  { resource_id: "queue:mixed", task_ids: [401, 402, 403, 404] },
];

const OWNER_SESSION_PAYLOAD = {
  session: {
    session_name: "owner-session",
    task_count: 2,
    event_count: 6,
  },
  tasks: [
    {
      task_id: 501,
      name: "lock-holder",
      state: "RUNNING",
      resource_roles: ["owner"],
      resource_id: "lock:shared",
      parent_task_id: null,
      children: [],
      metadata: {},
    },
    {
      task_id: 502,
      name: "lock-waiter",
      state: "BLOCKED",
      resource_roles: ["waiter"],
      reason: "lock_acquire",
      resource_id: "lock:shared",
      parent_task_id: null,
      children: [],
      metadata: {
        blocked_reason: "lock_acquire",
        blocked_resource_id: "lock:shared",
      },
    },
  ],
  segments: [
    { task_id: 501, task_name: "lock-holder", state: "RUNNING", start_ts_ns: 0, end_ts_ns: 5_000_000 },
    { task_id: 502, task_name: "lock-waiter", state: "BLOCKED", start_ts_ns: 1_000_000, end_ts_ns: 5_000_000 },
  ],
  insights: [
    {
      kind: "lock_contention",
      severity: "warning",
      message: "Lock lock:shared has 1 waiting task held by lock-holder: lock-waiter",
      resource_id: "lock:shared",
      blocked_count: 1,
      owner_task_ids: [501],
      owner_task_names: ["lock-holder"],
    },
  ],
};

const OWNER_RESOURCES_PAYLOAD = [
  {
    resource_id: "lock:shared",
    task_ids: [501, 502],
    owner_task_ids: [501],
    waiter_task_ids: [502],
    cancelled_waiter_task_ids: [],
  },
];

const INSIGHT_COUNT_SESSION_PAYLOAD = {
  session: {
    session_name: "insight-count-session",
    task_count: 4,
    event_count: 8,
  },
  tasks: [
    {
      task_id: 700,
      name: "lock-holder",
      state: "RUNNING",
      resource_roles: ["owner"],
      resource_id: "lock:summary",
      parent_task_id: null,
      children: [],
      metadata: {},
    },
    {
      task_id: 701,
      name: "lock-waiter",
      state: "BLOCKED",
      resource_roles: ["waiter"],
      reason: "lock_acquire",
      resource_id: "lock:summary",
      parent_task_id: null,
      children: [],
      metadata: {
        blocked_reason: "lock_acquire",
        blocked_resource_id: "lock:summary",
      },
    },
    {
      task_id: 702,
      name: "lock-waiter-b",
      state: "BLOCKED",
      resource_roles: ["waiter"],
      reason: "lock_acquire",
      resource_id: "lock:summary",
      parent_task_id: null,
      children: [],
      metadata: {
        blocked_reason: "lock_acquire",
        blocked_resource_id: "lock:summary",
      },
    },
    {
      task_id: 703,
      name: "lock-cancelled",
      state: "CANCELLED",
      resource_roles: ["cancelled waiter"],
      parent_task_id: null,
      children: [],
      metadata: {
        blocked_reason: "lock_acquire",
        blocked_resource_id: "lock:summary",
      },
    },
  ],
  segments: [
    { task_id: 700, task_name: "lock-holder", state: "RUNNING", start_ts_ns: 0, end_ts_ns: 5_000_000 },
    { task_id: 701, task_name: "lock-waiter", state: "BLOCKED", start_ts_ns: 0, end_ts_ns: 5_000_000 },
    { task_id: 702, task_name: "lock-waiter-b", state: "BLOCKED", start_ts_ns: 0, end_ts_ns: 5_000_000 },
  ],
  insights: [
    {
      kind: "lock_contention",
      severity: "warning",
      message: "Lock lock:summary has 3 waiting tasks held by lock-holder: lock-waiter, lock-waiter-b",
      resource_id: "lock:summary",
      blocked_count: 3,
      owner_count: 2,
      waiter_count: 3,
      cancelled_waiter_count: 1,
      blocked_task_ids: [701, 702],
      blocked_task_names: ["lock-waiter", "lock-waiter-b"],
      owner_task_ids: [700],
      owner_task_names: ["lock-holder"],
      cancelled_waiter_task_ids: [703],
    },
  ],
};

const INSIGHT_COUNT_RESOURCES_PAYLOAD = [
  {
    resource_id: "lock:summary",
    task_ids: [701],
  },
];

const BLOCKED_PRESET_INSIGHT_PAYLOAD = {
  session: {
    session_name: "blocked-preset-insight-session",
    task_count: 2,
    event_count: 4,
  },
  tasks: [
    {
      task_id: 801,
      name: "main-waiter",
      state: "BLOCKED",
      resource_roles: ["waiter"],
      reason: "lock_acquire",
      parent_task_id: null,
      children: [],
      metadata: {
        task_role: "main",
      },
    },
    {
      task_id: 802,
      name: "cancelled-waiter",
      state: "CANCELLED",
      resource_roles: ["cancelled waiter"],
      parent_task_id: null,
      children: [],
      metadata: {
        task_role: "background",
      },
    },
  ],
  segments: [
    { task_id: 801, task_name: "main-waiter", state: "BLOCKED", start_ts_ns: 0, end_ts_ns: 5_000_000 },
  ],
  insights: [
    {
      kind: "lock_contention",
      severity: "warning",
      message: "Lock lock:preset has 1 waiting task held by root-holder: main-waiter",
      resource_id: "lock:preset",
      blocked_count: 1,
      owner_count: 1,
      waiter_count: 1,
      cancelled_waiter_count: 1,
      blocked_task_ids: [801],
      blocked_task_names: ["main-waiter"],
      owner_task_ids: [803],
      owner_task_names: ["root-holder"],
      cancelled_waiter_task_ids: [802],
    },
  ],
};

const BLOCKED_PRESET_INSIGHT_RESOURCES_PAYLOAD = [
  {
    resource_id: "lock:preset",
    task_ids: [],
  },
];

const TASK_ROLE_PAYLOAD_SESSION = {
  session: {
    session_name: "task-role-payload-session",
    task_count: 2,
    event_count: 2,
  },
  tasks: [
    {
      task_id: 901,
      name: "payload-owner",
      state: "RUNNING",
      parent_task_id: null,
      children: [],
      resource_roles: ["owner"],
      metadata: {},
    },
    {
      task_id: 902,
      name: "payload-cancelled",
      state: "CANCELLED",
      parent_task_id: null,
      children: [],
      resource_roles: ["cancelled waiter"],
      metadata: {},
    },
  ],
  segments: [
    { task_id: 901, task_name: "payload-owner", state: "RUNNING", start_ts_ns: 0, end_ts_ns: 5_000_000 },
  ],
  insights: [],
};

const TIME_WINDOW_PAYLOAD = {
  session: { session_name: "time-window-session", task_count: 2, event_count: 4 },
  tasks: [
    { task_id: 101, name: "early-task", state: "DONE", resource_roles: [], parent_task_id: null, children: [], exception: null, metadata: {} },
    { task_id: 102, name: "late-task", state: "DONE", resource_roles: [], parent_task_id: null, children: [], exception: null, metadata: {} },
  ],
  segments: [
    { task_id: 101, task_name: "early-task", state: "RUNNING", start_ts_ns: 0, end_ts_ns: 3_000_000 },
    { task_id: 102, task_name: "late-task", state: "RUNNING", start_ts_ns: 6_000_000, end_ts_ns: 9_000_000 },
  ],
  insights: [],
};

const RECOVERED_SESSION_PAYLOAD = {
  session: {
    session_name: "demo-session-recovered",
    task_count: 3,
    event_count: 16,
  },
  tasks: [
    ...SESSION_PAYLOAD.tasks,
    {
      task_id: 3,
      name: "worker-3",
      state: "RUNNING",
      parent_task_id: 1,
      children: [],
      metadata: {
        task_role: "background",
      },
    },
  ],
  segments: [
    ...SESSION_PAYLOAD.segments,
    {
      task_id: 3,
      task_name: "worker-3",
      state: "RUNNING",
      start_ts_ns: 9_000_000,
      end_ts_ns: 12_000_000,
    },
  ],
  insights: SESSION_PAYLOAD.insights,
};

const CANCELLATION_CASCADE_PAYLOAD = {
  session: {
    session_name: "cascade-session",
    task_count: 3,
    event_count: 10,
  },
  tasks: [
    {
      task_id: 11,
      name: "parent-task",
      state: "BLOCKED",
      resource_roles: ["waiter"],
      reason: "sleep",
      resource_id: "sleep",
      parent_task_id: null,
      children: [12, 13],
      metadata: {},
    },
    {
      task_id: 12,
      name: "child-a",
      state: "CANCELLED",
      resource_roles: [],
      parent_task_id: 11,
      children: [],
      cancellation_origin: "parent_task",
      metadata: {},
    },
    {
      task_id: 13,
      name: "child-b",
      state: "CANCELLED",
      resource_roles: [],
      parent_task_id: 11,
      children: [],
      cancellation_origin: "parent_task",
      metadata: {},
    },
  ],
  segments: [
    { task_id: 11, task_name: "parent-task", state: "BLOCKED", start_ts_ns: 0, end_ts_ns: 5_000_000 },
    { task_id: 12, task_name: "child-a", state: "CANCELLED", start_ts_ns: 3_000_000, end_ts_ns: 5_000_000 },
    { task_id: 13, task_name: "child-b", state: "CANCELLED", start_ts_ns: 3_000_000, end_ts_ns: 5_000_000 },
  ],
  insights: [
    {
      kind: "cancellation_cascade",
      severity: "error",
      message: "Cascade: parent-task was cancelled, propagating to 2 children: child-a, child-b",
      source_task_id: 11,
      source_task_name: "parent-task",
      source_task_state: "BLOCKED",
      source_task_reason: "sleep",
      source_task_error: null,
      affected_task_ids: [12, 13],
      affected_task_names: ["child-a", "child-b"],
      reason: "parent_task",
    },
  ],
};

class MockEventSource {
  static instances = [];

  constructor(url) {
    this.url = url;
    this.onmessage = null;
    this.onerror = null;
    MockEventSource.instances.push(this);
  }

  close() {}
}

describe("App", () => {
  beforeEach(() => {
    global.EventSource = MockEventSource;
    MockEventSource.instances = [];
    vi.useRealTimers();
  });

  it("renders session metrics and updates the inspector when a task is selected", async () => {
    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") {
        return Promise.resolve({
          ok: true,
          json: async () => SESSION_PAYLOAD,
        });
      }
      if (String(path).startsWith("/api/v1/resources/graph")) {
        return Promise.resolve({
          ok: true,
          json: async () => RESOURCES_PAYLOAD,
        });
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    const { container } = render(<App />);

    expect(await screen.findByText("demo-session")).toBeInTheDocument();
    expect(
      screen.getByText("Queue queue:jobs is backing up with 2 waiting tasks: worker-1, worker-2"),
    ).toBeInTheDocument();
    expect(screen.getByText("Session summary")).toBeInTheDocument();
    expect(screen.getByText("Connection")).toBeInTheDocument();
    expect(screen.getAllByText("Live").length).toBeGreaterThan(0);
    const tasksMetric = screen.getAllByText("Tasks")[0].closest(".metric-card");
    expect(tasksMetric).not.toBeNull();
    expect(within(tasksMetric).getByText("2")).toBeInTheDocument();
    expect(screen.getByText("9.0 ms")).toBeInTheDocument();
    expect(screen.getByText("Timeline detail")).toBeInTheDocument();

    const canvas = container.querySelector("canvas");
    expect(canvas).not.toBeNull();
    canvas.getBoundingClientRect = () => ({
      x: 0,
      y: 0,
      top: 0,
      left: 0,
      bottom: 460,
      right: 1400,
      width: 1400,
      height: 460,
      toJSON: () => ({}),
    });

    fireEvent.mouseMove(canvas, { clientX: 920, clientY: 260 });

    await waitFor(() => {
      const timelineDetail = screen.getByText("Timeline detail").closest("aside");
      expect(timelineDetail).not.toBeNull();
      expect(within(timelineDetail).getByText("worker-2")).toBeInTheDocument();
      expect(within(timelineDetail).getByText("RUNNING")).toBeInTheDocument();
      expect(within(timelineDetail).getByText("cancelled waiter")).toBeInTheDocument();
    });

    const tasksSection = screen.getByRole("heading", { name: "Tasks" }).closest("section");
    expect(tasksSection).not.toBeNull();
    fireEvent.click(within(tasksSection).getByRole("button", { name: /worker-2/i }));

    await waitFor(() => {
      const inspector = screen.getByText("Inspector").closest("section");
      expect(inspector).not.toBeNull();
      expect(screen.getByText("boom")).toBeInTheDocument();
      const relatedResourcesList = within(inspector).getByRole("list");
      expect(
        within(relatedResourcesList).getByText(
          (_, node) =>
            node?.tagName === "LI" &&
            node?.textContent === "queue:jobs · cancelled waiter · 2 task(s)",
        ),
      ).toBeInTheDocument();
      expect(within(inspector).getAllByText("parent_task").length).toBeGreaterThan(0);
      expect(screen.getByText("Cancel source")).toBeInTheDocument();
      expect(within(inspector).getAllByText("queue_get").length).toBeGreaterThan(0);
      expect(screen.getAllByText("queue:jobs").length).toBeGreaterThan(1);
      expect(screen.getByText("Queue Backpressure")).toBeInTheDocument();
      expect(screen.getByText("Stack snapshot")).toBeInTheDocument();
      expect(screen.getAllByText("GET /jobs/42").length).toBeGreaterThan(0);
      expect(screen.getAllByText("job-42").length).toBeGreaterThan(0);
      expect(
        screen.getByText("examples/cancellation_demo.py:11 in waiting_consumer"),
      ).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /Queue queue:jobs is backing up/i }));

    await waitFor(() => {
      const workspace = screen.getByText("Focus workspace").closest("section");
      expect(workspace).not.toBeNull();
      expect(within(workspace).getByRole("tab", { name: "Resource" })).toHaveClass("active");
      expect(within(workspace).getByText("Resource focus")).toBeInTheDocument();
      expect(within(workspace).getByText("Contention summary")).toBeInTheDocument();
      expect(within(workspace).getByText("Queue Backpressure")).toBeInTheDocument();
      expect(within(workspace).getByText("queue_get · 2")).toBeInTheDocument();
      expect(within(workspace).getByText("Related tasks")).toBeInTheDocument();
      expect(within(workspace).getByText("Cancelled waiters")).toBeInTheDocument();
      expect(screen.getAllByText("queue:jobs").length).toBeGreaterThan(2);
      expect(screen.getAllByRole("button", { name: /worker-1/i }).length).toBeGreaterThan(1);
      expect(screen.getAllByRole("button", { name: /worker-2/i }).length).toBeGreaterThan(1);
    });
  });

  it("filters tasks by cancellation origin, blocked reason, and resource id", async () => {
    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") {
        return Promise.resolve({
          ok: true,
          json: async () => SESSION_PAYLOAD,
        });
      }
      if (String(path).startsWith("/api/v1/resources/graph")) {
        return Promise.resolve({
          ok: true,
          json: async () => RESOURCES_PAYLOAD,
        });
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    render(<App />);

    expect(await screen.findByText("demo-session")).toBeInTheDocument();
    expect(screen.getByText("Showing 2 of 2")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Cancellation origin"), {
      target: { value: "parent_task" },
    });

    await waitFor(() => {
      expect(screen.getByText("Showing 1 of 2")).toBeInTheDocument();
      expect(screen.getAllByRole("button", { name: /worker-2/i }).length).toBeGreaterThan(0);
      expect(screen.queryByRole("button", { name: /^worker-1$/i })).not.toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText("Blocked reason"), {
      target: { value: "queue_get" },
    });
    fireEvent.change(screen.getByLabelText("Resource id"), {
      target: { value: "queue:jobs" },
    });

    await waitFor(() => {
      const inspector = screen.getByText("Inspector").closest("section");
      expect(inspector).not.toBeNull();
      expect(screen.getByText("Showing 1 of 2")).toBeInTheDocument();
      expect(screen.getAllByText("worker-2").length).toBeGreaterThan(0);
      expect(within(inspector).getAllByText("parent_task").length).toBeGreaterThan(0);
      expect(within(inspector).getAllByText("queue_get").length).toBeGreaterThan(0);
      expect(screen.getAllByText("queue:jobs").length).toBeGreaterThan(0);
    });
  });

  it("shows owners separately in the resource drilldown when detailed graph includes them", async () => {
    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") {
        return Promise.resolve({
          ok: true,
          json: async () => OWNER_SESSION_PAYLOAD,
        });
      }
      if (String(path).startsWith("/api/v1/resources/graph")) {
        return Promise.resolve({
          ok: true,
          json: async () => OWNER_RESOURCES_PAYLOAD,
        });
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    render(<App />);

    expect(await screen.findByText("owner-session")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Lock lock:shared has 1 waiting task held by lock-holder/i }));

    await waitFor(() => {
      const workspace = screen.getByText("Focus workspace").closest("section");
      expect(workspace).not.toBeNull();
      expect(within(workspace).getByRole("heading", { name: "Owners" })).toBeInTheDocument();
      expect(within(workspace).getByText("Waiters")).toBeInTheDocument();
      expect(within(workspace).getByText("Cancelled")).toBeInTheDocument();
      const ownersBlock = within(workspace)
        .getByRole("heading", { name: "Owners" })
        .closest(".resource-block");
      expect(ownersBlock).not.toBeNull();
      expect(within(ownersBlock).getByRole("button", { name: /lock-holder/i })).toBeInTheDocument();
      expect(within(workspace).getByRole("button", { name: /lock-waiter/i })).toBeInTheDocument();
    });
  });

  it("prefers insight role counts in resource summary when graph detail is partial", async () => {
    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") {
        return Promise.resolve({
          ok: true,
          json: async () => INSIGHT_COUNT_SESSION_PAYLOAD,
        });
      }
      if (String(path).startsWith("/api/v1/resources/graph")) {
        return Promise.resolve({
          ok: true,
          json: async () => INSIGHT_COUNT_RESOURCES_PAYLOAD,
        });
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    render(<App />);

    expect(await screen.findByText("insight-count-session")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Lock lock:summary has 3 waiting tasks held by lock-holder/i }));

    await waitFor(() => {
      const workspace = screen.getByText("Focus workspace").closest("section");
      expect(workspace).not.toBeNull();
      const ownersLabel = within(workspace).getAllByText("Owners")[0];
      const waitersLabel = within(workspace).getByText("Waiters");
      const cancelledLabel = within(workspace).getByText("Cancelled");
      expect(ownersLabel.nextElementSibling?.textContent).toBe("2");
      expect(waitersLabel.nextElementSibling?.textContent).toBe("3");
      expect(cancelledLabel.nextElementSibling?.textContent).toBe("1");
    });
  });

  it("prefers insight task ids for resource drilldown lists when graph detail is partial", async () => {
    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") {
        return Promise.resolve({
          ok: true,
          json: async () => INSIGHT_COUNT_SESSION_PAYLOAD,
        });
      }
      if (String(path).startsWith("/api/v1/resources/graph")) {
        return Promise.resolve({
          ok: true,
          json: async () => INSIGHT_COUNT_RESOURCES_PAYLOAD,
        });
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    render(<App />);

    expect(await screen.findByText("insight-count-session")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Lock lock:summary has 3 waiting tasks held by lock-holder/i }));

    await waitFor(() => {
      const workspace = screen.getByText("Focus workspace").closest("section");
      expect(workspace).not.toBeNull();
      const ownersBlock = within(workspace)
        .getByRole("heading", { name: "Owners" })
        .closest(".resource-block");
      const relatedBlock = within(workspace)
        .getByRole("heading", { name: "Related tasks" })
        .closest(".resource-block");
      const cancelledBlock = within(workspace)
        .getByRole("heading", { name: "Cancelled waiters" })
        .closest(".resource-block");
      expect(ownersBlock).not.toBeNull();
      expect(relatedBlock).not.toBeNull();
      expect(cancelledBlock).not.toBeNull();
      expect(within(ownersBlock).getByRole("button", { name: /lock-holder/i })).toBeInTheDocument();
      expect(within(relatedBlock).getByRole("button", { name: /^lock-waiter BLOCKED$/i })).toBeInTheDocument();
      expect(within(relatedBlock).getByRole("button", { name: /^lock-waiter-b BLOCKED$/i })).toBeInTheDocument();
      expect(within(cancelledBlock).getByRole("button", { name: /lock-cancelled/i })).toBeInTheDocument();
    });
  });

  it("prefers insight roles for task list and inspector when graph detail is partial", async () => {
    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") {
        return Promise.resolve({
          ok: true,
          json: async () => INSIGHT_COUNT_SESSION_PAYLOAD,
        });
      }
      if (String(path).startsWith("/api/v1/resources/graph")) {
        return Promise.resolve({
          ok: true,
          json: async () => INSIGHT_COUNT_RESOURCES_PAYLOAD,
        });
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    render(<App />);

    expect(await screen.findByText("insight-count-session")).toBeInTheDocument();

    const tasksSection = screen.getByRole("heading", { name: "Tasks" }).closest("section");
    expect(tasksSection).not.toBeNull();
    expect(within(tasksSection).getAllByText("owner").length).toBeGreaterThan(0);
    expect(within(tasksSection).getAllByText("waiter").length).toBeGreaterThan(0);
    expect(within(tasksSection).getAllByText("cancelled waiter").length).toBeGreaterThan(0);

    fireEvent.click(within(tasksSection).getByRole("button", { name: /lock-cancelled/i }));

    await waitFor(() => {
      const inspector = screen.getByText("Inspector").closest("section");
      expect(inspector).not.toBeNull();
      expect(within(inspector).getByText("cancelled waiter")).toBeInTheDocument();
    });
  });

  it("prefers task resource_roles when graph and insights do not provide roles", async () => {
    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") {
        return Promise.resolve({
          ok: true,
          json: async () => TASK_ROLE_PAYLOAD_SESSION,
        });
      }
      if (String(path).startsWith("/api/v1/resources/graph")) {
        return Promise.resolve({
          ok: true,
          json: async () => [],
        });
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    render(<App />);

    expect(await screen.findByText("task-role-payload-session")).toBeInTheDocument();

    const tasksSection = screen.getByRole("heading", { name: "Tasks" }).closest("section");
    expect(tasksSection).not.toBeNull();
    expect(within(tasksSection).getAllByText("owner").length).toBeGreaterThan(0);
    expect(within(tasksSection).getAllByText("cancelled waiter").length).toBeGreaterThan(0);

    fireEvent.click(within(tasksSection).getByRole("button", { name: /payload-cancelled/i }));

    await waitFor(() => {
      const inspector = screen.getByText("Inspector").closest("section");
      expect(inspector).not.toBeNull();
      expect(within(inspector).getByText("cancelled waiter")).toBeInTheDocument();
    });
  });

  it("shows resource roles in the inspector for waiter and cancelled waiter tasks", async () => {
    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") {
        return Promise.resolve({
          ok: true,
          json: async () => SESSION_PAYLOAD,
        });
      }
      if (String(path).startsWith("/api/v1/resources/graph")) {
        return Promise.resolve({
          ok: true,
          json: async () => RESOURCES_PAYLOAD,
        });
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    render(<App />);

    expect(await screen.findByText("demo-session")).toBeInTheDocument();

    const tasksSection = screen.getByRole("heading", { name: "Tasks" }).closest("section");
    expect(tasksSection).not.toBeNull();
    fireEvent.click(within(tasksSection).getByRole("button", { name: /worker-1/i }));

    await waitFor(() => {
      const inspector = screen.getByText("Inspector").closest("section");
      expect(inspector).not.toBeNull();
      expect(within(inspector).getByText("queue:jobs · waiter · 2 task(s)")).toBeInTheDocument();
      expect(within(inspector).getByText("waiter")).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText("Cancellation origin"), {
      target: { value: "parent_task" },
    });

    await waitFor(() => {
      const inspector = screen.getByText("Inspector").closest("section");
      expect(inspector).not.toBeNull();
      expect(within(inspector).getByText("queue:jobs · cancelled waiter · 2 task(s)")).toBeInTheDocument();
      expect(within(inspector).getByText("cancelled waiter")).toBeInTheDocument();
    });
  });

  it("drives cancellation and blocked drilldowns from filter presets", async () => {
    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") {
        return Promise.resolve({
          ok: true,
          json: async () => SESSION_PAYLOAD,
        });
      }
      if (String(path).startsWith("/api/v1/resources/graph")) {
        return Promise.resolve({
          ok: true,
          json: async () => RESOURCES_PAYLOAD,
        });
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    render(<App />);

    expect(await screen.findByText("demo-session")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Cancelled" }));

    await waitFor(() => {
      expect(screen.getByText("Showing 1 of 2")).toBeInTheDocument();
      const workspace = screen.getByText("Focus workspace").closest("section");
      expect(workspace).not.toBeNull();
      expect(within(workspace).getByRole("tab", { name: "Cancellation" })).toHaveClass("active");
      expect(within(workspace).getByText("Cancellation focus")).toBeInTheDocument();
      expect(within(workspace).getByText("parent_task")).toBeInTheDocument();
      expect(within(workspace).getByText("Source context")).toBeInTheDocument();
      expect(within(workspace).getByText("Wait state")).toBeInTheDocument();
      expect(within(workspace).getByText("Queue size")).toBeInTheDocument();
      expect(within(workspace).getByText("0")).toBeInTheDocument();
      expect(within(workspace).getByText("Queue max")).toBeInTheDocument();
      expect(within(workspace).getByText("16")).toBeInTheDocument();
      expect(within(workspace).getAllByText("BLOCKED").length).toBeGreaterThan(0);
      expect(within(workspace).getAllByText("queue_get").length).toBeGreaterThan(0);
      expect(within(workspace).getByRole("button", { name: /worker-1/i })).toBeInTheDocument();
      expect(within(workspace).getByRole("button", { name: /worker-2/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Blocked main" }));

    await waitFor(() => {
      expect(screen.getByText("Showing 1 of 2")).toBeInTheDocument();
      const workspace = screen.getByText("Focus workspace").closest("section");
      expect(workspace).not.toBeNull();
      expect(within(workspace).getByRole("tab", { name: "Resource" })).toHaveClass("active");
      expect(within(workspace).getByText("Queue Backpressure")).toBeInTheDocument();
      expect(within(workspace).getByText("queue_get · 2")).toBeInTheDocument();
      expect(within(workspace).getByRole("button", { name: /worker-1/i })).toBeInTheDocument();
      expect(within(workspace).getByText("Cancelled waiters")).toBeInTheDocument();
    });
  });

  it("drives blocked preset from insight task ids when task resource metadata is missing", async () => {
    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") {
        return Promise.resolve({
          ok: true,
          json: async () => BLOCKED_PRESET_INSIGHT_PAYLOAD,
        });
      }
      if (String(path).startsWith("/api/v1/resources/graph")) {
        return Promise.resolve({
          ok: true,
          json: async () => BLOCKED_PRESET_INSIGHT_RESOURCES_PAYLOAD,
        });
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    render(<App />);

    expect(await screen.findByText("blocked-preset-insight-session")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Blocked main" }));

    await waitFor(() => {
      expect(screen.getByText("Showing 1 of 2")).toBeInTheDocument();
      const workspace = screen.getByText("Focus workspace").closest("section");
      expect(workspace).not.toBeNull();
      expect(within(workspace).getByRole("tab", { name: "Resource" })).toHaveClass("active");
      expect(within(workspace).getByText("Lock Contention")).toBeInTheDocument();
      expect(within(workspace).getByRole("button", { name: /main-waiter/i })).toBeInTheDocument();
      expect(within(workspace).getByText("Cancelled waiters")).toBeInTheDocument();
    });
  });

  it("opens the error drilldown from the failures preset", async () => {
    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") {
        return Promise.resolve({
          ok: true,
          json: async () => FAILED_ROOT_PAYLOAD,
        });
      }
      if (String(path).startsWith("/api/v1/resources/graph")) {
        return Promise.resolve({
          ok: true,
          json: async () => [],
        });
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    render(<App />);

    expect(await screen.findByText("failed-root-session")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Failures" }));

    await waitFor(() => {
      expect(screen.getByText("Showing 1 of 1")).toBeInTheDocument();
      const workspace = screen.getByText("Focus workspace").closest("section");
      expect(workspace).not.toBeNull();
      expect(within(workspace).getByRole("tab", { name: "Error" })).toHaveClass("active");
      expect(within(workspace).getByText("yes")).toBeInTheDocument();
      expect(within(workspace).getByRole("button", { name: /root-main/i })).toBeInTheDocument();
      expect(within(workspace).getByText("RuntimeError")).toBeInTheDocument();
    });
  });

  it("shows queue get and put slices inside mixed queue contention drilldown", async () => {
    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") {
        return Promise.resolve({
          ok: true,
          json: async () => MIXED_QUEUE_PAYLOAD,
        });
      }
      if (String(path).startsWith("/api/v1/resources/graph")) {
        return Promise.resolve({
          ok: true,
          json: async () => MIXED_QUEUE_RESOURCES,
        });
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    render(<App />);

    expect(await screen.findByText("mixed-queue-session")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Queue queue:mixed is backing up/i }));

    await waitFor(() => {
      const workspace = screen.getByText("Focus workspace").closest("section");
      expect(workspace).not.toBeNull();
      expect(within(workspace).getByText("Queue slices")).toBeInTheDocument();
      expect(within(workspace).getByText("Consumers waiting")).toBeInTheDocument();
      expect(within(workspace).getByText("Producers waiting")).toBeInTheDocument();
      expect(within(workspace).getAllByText("queue_get · 2").length).toBeGreaterThan(0);
      expect(within(workspace).getAllByText("queue_put · 2").length).toBeGreaterThan(0);
      expect(
        within(workspace).getAllByRole("button", { name: /consumer-a/i }).length,
      ).toBeGreaterThan(0);
      expect(
        within(workspace).getAllByRole("button", { name: /producer-a/i }).length,
      ).toBeGreaterThan(0);
    });
  });

  it("filters tasks by state and task role", async () => {
    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") {
        return Promise.resolve({
          ok: true,
          json: async () => SESSION_PAYLOAD,
        });
      }
      if (String(path).startsWith("/api/v1/resources/graph")) {
        return Promise.resolve({
          ok: true,
          json: async () => RESOURCES_PAYLOAD,
        });
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    render(<App />);

    expect(await screen.findByText("demo-session")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("State"), {
      target: { value: "BLOCKED" },
    });
    fireEvent.change(screen.getByLabelText("Task role"), {
      target: { value: "main" },
    });

    await waitFor(() => {
      const tasksSection = screen.getByRole("heading", { name: "Tasks" }).closest("section");
      expect(tasksSection).not.toBeNull();
      expect(screen.getByText("Showing 1 of 2")).toBeInTheDocument();
      expect(within(tasksSection).getByRole("button", { name: /worker-1/i })).toBeInTheDocument();
      expect(within(tasksSection).getByText("waiter")).toBeInTheDocument();
      expect(within(tasksSection).queryByRole("button", { name: /worker-2/i })).not.toBeInTheDocument();

      const inspector = screen.getByText("Inspector").closest("section");
      expect(inspector).not.toBeNull();
      expect(within(inspector).getByText("worker-1")).toBeInTheDocument();
      expect(within(inspector).getByText("BLOCKED")).toBeInTheDocument();
      expect(within(inspector).getByText("waiter")).toBeInTheDocument();
    });
  });

  it("filters tasks by request and job labels", async () => {
    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") {
        return Promise.resolve({
          ok: true,
          json: async () => SESSION_PAYLOAD,
        });
      }
      if (String(path).startsWith("/api/v1/resources/graph")) {
        return Promise.resolve({
          ok: true,
          json: async () => RESOURCES_PAYLOAD,
        });
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    render(<App />);

    expect(await screen.findByText("demo-session")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Request label"), {
      target: { value: "GET /jobs/42" },
    });
    fireEvent.change(screen.getByLabelText("Job label"), {
      target: { value: "job-42" },
    });

    await waitFor(() => {
      expect(screen.getByText("Showing 2 of 2")).toBeInTheDocument();
      expect(screen.getAllByText("GET /jobs/42").length).toBeGreaterThan(0);
      expect(screen.getAllByText("job-42").length).toBeGreaterThan(0);
    });
  });

  it("applies grouped filter presets and clears them", async () => {
    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") {
        return Promise.resolve({
          ok: true,
          json: async () => SESSION_PAYLOAD,
        });
      }
      if (String(path).startsWith("/api/v1/resources/graph")) {
        return Promise.resolve({
          ok: true,
          json: async () => RESOURCES_PAYLOAD,
        });
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    render(<App />);

    expect(await screen.findByText("demo-session")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Blocked main" }));

    await waitFor(() => {
      const tasksSection = screen.getByRole("heading", { name: "Tasks" }).closest("section");
      expect(tasksSection).not.toBeNull();
      expect(screen.getByText("Showing 1 of 2")).toBeInTheDocument();
      expect(within(tasksSection).getByRole("button", { name: /worker-1/i })).toBeInTheDocument();
      expect(within(tasksSection).queryByRole("button", { name: /worker-2/i })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Blocked main" })).toHaveClass("active");
    });

    fireEvent.click(screen.getByRole("button", { name: "Clear" }));

    await waitFor(() => {
      expect(screen.getByText("Showing 2 of 2")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Blocked main" })).not.toHaveClass("active");
      expect(screen.getAllByRole("button", { name: /worker-1/i }).length).toBeGreaterThan(0);
      expect(screen.getAllByRole("button", { name: /worker-2/i }).length).toBeGreaterThan(0);
    });
  });

  it("shows an error banner when the initial refresh fails", async () => {
    global.fetch = vi.fn(() =>
      Promise.resolve({
        ok: false,
        status: 500,
      }),
    );

    render(<App />);

    expect(
      await screen.findByText("Request failed for /api/v1/session: 500"),
    ).toBeInTheDocument();
  });

  it("shows reconnecting stream status when the event stream errors", async () => {
    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") {
        return Promise.resolve({
          ok: true,
          json: async () => SESSION_PAYLOAD,
        });
      }
      if (String(path).startsWith("/api/v1/resources/graph")) {
        return Promise.resolve({
          ok: true,
          json: async () => RESOURCES_PAYLOAD,
        });
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    render(<App />);

    expect(await screen.findByText("demo-session")).toBeInTheDocument();
    expect(MockEventSource.instances.length).toBeGreaterThan(0);

    act(() => {
      MockEventSource.instances[0].onerror?.();
    });

    await waitFor(() => {
      expect(screen.getAllByText("Reconnecting").length).toBeGreaterThan(0);
    });
  });

  it("recovers after stream errors and reconnects with a fresh snapshot", async () => {
    let sessionFetchCount = 0;
    let resourceFetchCount = 0;

    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") {
        sessionFetchCount += 1;
        const payload =
          sessionFetchCount >= 2 ? RECOVERED_SESSION_PAYLOAD : SESSION_PAYLOAD;
        return Promise.resolve({
          ok: true,
          json: async () => payload,
        });
      }
      if (String(path).startsWith("/api/v1/resources/graph")) {
        resourceFetchCount += 1;
        return Promise.resolve({
          ok: true,
          json: async () => RESOURCES_PAYLOAD,
        });
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    render(<App />);

    expect(await screen.findByText("demo-session")).toBeInTheDocument();
    expect(screen.getAllByText("Live").length).toBeGreaterThan(0);
    expect(MockEventSource.instances).toHaveLength(1);

    act(() => {
      MockEventSource.instances[0].onerror?.();
    });

    await waitFor(() => {
      expect(screen.getAllByText("Reconnecting").length).toBeGreaterThan(0);
    });

    await act(async () => {
      await new Promise((resolve) => {
        setTimeout(resolve, 1100);
      });
    });

    await waitFor(() => {
      expect(MockEventSource.instances).toHaveLength(2);
      expect(screen.getByText("demo-session-recovered")).toBeInTheDocument();
      expect(screen.getAllByText("Live").length).toBeGreaterThan(0);
      expect(screen.getByText("Showing 3 of 3")).toBeInTheDocument();
      expect(screen.getAllByText("Last refresh").length).toBeGreaterThan(0);
    });

    expect(sessionFetchCount).toBeGreaterThanOrEqual(2);
    expect(resourceFetchCount).toBeGreaterThanOrEqual(2);
  }, 10000);

  it("opens cancellation drilldown from cancellation insights", async () => {
    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") {
        return Promise.resolve({
          ok: true,
          json: async () => SESSION_PAYLOAD,
        });
      }
      if (String(path).startsWith("/api/v1/resources/graph")) {
        return Promise.resolve({
          ok: true,
          json: async () => RESOURCES_PAYLOAD,
        });
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    render(<App />);

    expect(await screen.findByText("demo-session")).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", {
        name: /Task worker-1 triggered cancellation of 1 sibling task: worker-2/i,
      }),
    );

    await waitFor(() => {
      const workspace = screen.getByText("Focus workspace").closest("section");
      expect(workspace).not.toBeNull();
      expect(within(workspace).getByRole("tab", { name: "Cancellation" })).toHaveClass("active");
      expect(within(workspace).getByText("Cancellation focus")).toBeInTheDocument();
      expect(within(workspace).getByText("Source task")).toBeInTheDocument();
      expect(within(workspace).getByText("Affected tasks")).toBeInTheDocument();
      expect(screen.getAllByRole("button", { name: /worker-1/i }).length).toBeGreaterThan(1);
      expect(screen.getAllByRole("button", { name: /worker-2/i }).length).toBeGreaterThan(1);
      expect(screen.getByText("1 task(s)")).toBeInTheDocument();
    });
  });

  it("opens error drilldown for failed root-task insights", async () => {
    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") {
        return Promise.resolve({
          ok: true,
          json: async () => FAILED_ROOT_PAYLOAD,
        });
      }
      if (String(path).startsWith("/api/v1/resources/graph")) {
        return Promise.resolve({
          ok: true,
          json: async () => [],
        });
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    render(<App />);

    expect(await screen.findByText("failed-root-session")).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", {
        name: /Task root-main failed with RuntimeError/i,
      }),
    );

    await waitFor(() => {
      const workspace = screen.getByText("Focus workspace").closest("section");
      expect(workspace).not.toBeNull();
      expect(within(workspace).getByRole("tab", { name: "Error" })).toHaveClass("active");
      expect(within(workspace).getByText("Failed task")).toBeInTheDocument();
      expect(within(workspace).getByText("yes")).toBeInTheDocument();
      expect(within(workspace).getByRole("button", { name: /root-main/i })).toBeInTheDocument();

      const inspector = screen.getByText("Inspector").closest("section");
      expect(inspector).not.toBeNull();
      expect(within(inspector).getByText("root-main")).toBeInTheDocument();
      expect(within(inspector).getByText("FAILED")).toBeInTheDocument();
    });
  });

  it("shows owner context in resource insight meta", async () => {
    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") {
        return Promise.resolve({
          ok: true,
          json: async () => OWNER_SESSION_PAYLOAD,
        });
      }
      if (String(path).startsWith("/api/v1/resources/graph")) {
        return Promise.resolve({
          ok: true,
          json: async () => OWNER_RESOURCES_PAYLOAD,
        });
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    render(<App />);

    expect(await screen.findByText("owner-session")).toBeInTheDocument();
    expect(screen.getByText("lock:shared · held by lock-holder")).toBeInTheDocument();
  });

  it("shows resource_label instead of resource_id in the resource panel and insight meta", async () => {
    const LABELLED_SESSION_PAYLOAD = {
      session: { session_name: "labelled-session", task_count: 2, event_count: 4 },
      tasks: [
        {
          task_id: 601,
          name: "worker-a",
          state: "BLOCKED",
          resource_roles: ["waiter"],
          reason: "queue_get",
          resource_id: "queue:9999",
          parent_task_id: null,
          children: [],
          metadata: { blocked_reason: "queue_get", blocked_resource_id: "queue:9999" },
        },
        {
          task_id: 602,
          name: "worker-b",
          state: "BLOCKED",
          resource_roles: ["waiter"],
          reason: "queue_get",
          resource_id: "queue:9999",
          parent_task_id: null,
          children: [],
          metadata: { blocked_reason: "queue_get", blocked_resource_id: "queue:9999" },
        },
      ],
      segments: [
        { task_id: 601, task_name: "worker-a", state: "BLOCKED", start_ts_ns: 0, end_ts_ns: 4_000_000 },
        { task_id: 602, task_name: "worker-b", state: "BLOCKED", start_ts_ns: 0, end_ts_ns: 4_000_000 },
      ],
      insights: [
        {
          kind: "queue_backpressure",
          severity: "warning",
          message: "Queue queue:9999 is backing up with 2 tasks: worker-a, worker-b",
          resource_id: "queue:9999",
          resource_label: "orders-queue",
          blocked_count: 2,
          blocked_task_ids: [601, 602],
          owner_task_ids: [],
          owner_task_names: [],
          cancelled_waiter_task_ids: [],
        },
      ],
    };

    const LABELLED_RESOURCES_PAYLOAD = [
      {
        resource_id: "queue:9999",
        resource_label: "orders-queue",
        task_ids: [601, 602],
        owner_task_ids: [],
        waiter_task_ids: [601, 602],
        cancelled_waiter_task_ids: [],
      },
    ];

    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") {
        return Promise.resolve({ ok: true, json: async () => LABELLED_SESSION_PAYLOAD });
      }
      if (String(path).startsWith("/api/v1/resources/graph")) {
        return Promise.resolve({ ok: true, json: async () => LABELLED_RESOURCES_PAYLOAD });
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    render(<App />);
    expect(await screen.findByText("labelled-session")).toBeInTheDocument();

    // Insight meta should prefer resource_label over resource_id.
    // "orders-queue" appears in both the insight-meta chip and the resource focus panel
    // (first resource is selected by default), so use getAllByText.
    expect(screen.getAllByText("orders-queue").length).toBeGreaterThan(0);

    // The insight-meta chip specifically should show the label, not the raw id
    const insightMeta = document.querySelector(".insight-meta");
    expect(insightMeta).not.toBeNull();
    expect(insightMeta.textContent).toBe("orders-queue");

    // Open resource drilldown — resource panel key-grid must show label not raw id.
    // The tab button is also labeled "Resource", so use the resource focus heading to
    // navigate to the key-grid value cell.
    fireEvent.click(screen.getByRole("button", { name: /Queue queue:9999 is backing up/i }));

    await waitFor(() => {
      const workspace = screen.getByText("Focus workspace").closest("section");
      expect(workspace).not.toBeNull();
      // The key-grid in ResourceFocus is a div with children [label, value, label, value, ...]
      // "orders-queue" must appear there (from resource.resource_label)
      expect(within(workspace).getAllByText("orders-queue").length).toBeGreaterThan(0);
      // The raw resource_id should not appear as a standalone text node in the key-grid
      const keyGrids = workspace.querySelectorAll(".key-grid");
      const resourceKeyGrid = Array.from(keyGrids).find((grid) =>
        Array.from(grid.children).some((child) => child.textContent === "Resource"),
      );
      expect(resourceKeyGrid).not.toBeNull();
      const resourceValueCell = Array.from(resourceKeyGrid.children).find(
        (child, idx, arr) =>
          idx > 0 && arr[idx - 1].textContent === "Resource",
      );
      expect(resourceValueCell?.textContent).toBe("orders-queue");
    });
  });

  it("task name search narrows the task list and clears on reset", async () => {
    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") {
        return Promise.resolve({ ok: true, json: async () => SESSION_PAYLOAD });
      }
      if (String(path).startsWith("/api/v1/resources/graph")) {
        return Promise.resolve({ ok: true, json: async () => RESOURCES_PAYLOAD });
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    render(<App />);
    expect(await screen.findByText("demo-session")).toBeInTheDocument();
    expect(screen.getByText("Showing 2 of 2")).toBeInTheDocument();

    // Type a substring that matches only worker-1
    fireEvent.change(screen.getByLabelText("Task name"), { target: { value: "worker-1" } });

    await waitFor(() => {
      expect(screen.getByText("Showing 1 of 2")).toBeInTheDocument();
      const tasksSection = screen.getByRole("heading", { name: "Tasks" }).closest("section");
      expect(within(tasksSection).getByRole("button", { name: /worker-1/i })).toBeInTheDocument();
      expect(within(tasksSection).queryByRole("button", { name: /^worker-2/i })).not.toBeInTheDocument();
    });

    // Clearing via the Clear button resets search
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));

    await waitFor(() => {
      expect(screen.getByText("Showing 2 of 2")).toBeInTheDocument();
      expect(screen.getByLabelText("Task name")).toHaveValue("");
    });
  });

  it("per-severity toggle buttons filter the insights panel", async () => {
    // Use SESSION_PAYLOAD which has: queue_backpressure (warning) + cancellation_chain (warning)
    // Add an error-severity insight via a payload that mixes severities
    const MIXED_SEVERITY_PAYLOAD = {
      ...SESSION_PAYLOAD,
      session: { ...SESSION_PAYLOAD.session, session_name: "mixed-severity-session" },
      insights: [
        {
          kind: "queue_backpressure",
          severity: "warning",
          message: "Queue queue:jobs is backing up",
          resource_id: "queue:jobs",
        },
        {
          kind: "task_error",
          severity: "error",
          task_id: 1,
          message: "Task worker-1 failed with RuntimeError",
          reason: "RuntimeError",
        },
        {
          kind: "task_cancelled",
          severity: "info",
          task_id: 2,
          message: "Task worker-2 was cancelled",
          reason: "parent_task",
        },
      ],
    };

    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") {
        return Promise.resolve({ ok: true, json: async () => MIXED_SEVERITY_PAYLOAD });
      }
      if (String(path).startsWith("/api/v1/resources/graph")) {
        return Promise.resolve({ ok: true, json: async () => RESOURCES_PAYLOAD });
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    render(<App />);
    expect(await screen.findByText("mixed-severity-session")).toBeInTheDocument();

    // All 3 insights visible by default
    expect(screen.getByText("Queue queue:jobs is backing up")).toBeInTheDocument();
    expect(screen.getByText("Task worker-1 failed with RuntimeError")).toBeInTheDocument();
    expect(screen.getByText("Task worker-2 was cancelled")).toBeInTheDocument();

    // Click "Error" toggle — only error insights visible
    fireEvent.click(screen.getByRole("button", { name: "Error" }));

    await waitFor(() => {
      expect(screen.queryByText("Queue queue:jobs is backing up")).not.toBeInTheDocument();
      expect(screen.getByText("Task worker-1 failed with RuntimeError")).toBeInTheDocument();
      expect(screen.queryByText("Task worker-2 was cancelled")).not.toBeInTheDocument();
    });

    // Click "Warning" toggle — only warning insights visible
    fireEvent.click(screen.getByRole("button", { name: "Warning" }));

    await waitFor(() => {
      expect(screen.getByText("Queue queue:jobs is backing up")).toBeInTheDocument();
      expect(screen.queryByText("Task worker-1 failed with RuntimeError")).not.toBeInTheDocument();
      expect(screen.queryByText("Task worker-2 was cancelled")).not.toBeInTheDocument();
    });

    // Click "All" toggle — all insights back
    fireEvent.click(screen.getByRole("button", { name: "All" }));

    await waitFor(() => {
      expect(screen.getByText("Queue queue:jobs is backing up")).toBeInTheDocument();
      expect(screen.getByText("Task worker-1 failed with RuntimeError")).toBeInTheDocument();
      expect(screen.getByText("Task worker-2 was cancelled")).toBeInTheDocument();
    });
  });

  it("Copy as JSON button copies task payload to clipboard", async () => {
    const written = [];
    vi.stubGlobal("navigator", {
      clipboard: { writeText: vi.fn((text) => { written.push(text); return Promise.resolve(); }) },
    });

    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") {
        return Promise.resolve({ ok: true, json: async () => SESSION_PAYLOAD });
      }
      if (String(path).startsWith("/api/v1/resources/graph")) {
        return Promise.resolve({ ok: true, json: async () => RESOURCES_PAYLOAD });
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    render(<App />);
    expect(await screen.findByText("demo-session")).toBeInTheDocument();

    const inspector = screen.getByText("Inspector").closest("section");
    expect(inspector).not.toBeNull();

    fireEvent.click(within(inspector).getByRole("button", { name: /copy as json/i }));

    await waitFor(() => {
      expect(written).toHaveLength(1);
      const parsed = JSON.parse(written[0]);
      expect(parsed.task_id).toBe(1);
      expect(parsed.name).toBe("worker-1");
    });
  });

  it("insight cards collapse and expand on header click", async () => {
    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") {
        return Promise.resolve({ ok: true, json: async () => SESSION_PAYLOAD });
      }
      if (String(path).startsWith("/api/v1/resources/graph")) {
        return Promise.resolve({ ok: true, json: async () => RESOURCES_PAYLOAD });
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    render(<App />);
    expect(await screen.findByText("demo-session")).toBeInTheDocument();

    // Both insight messages visible by default
    const insightMessage = "Queue queue:jobs is backing up with 2 waiting tasks: worker-1, worker-2";
    expect(screen.getByText(insightMessage)).toBeInTheDocument();

    // Click the collapse toggle on the first insight card (there are 2 insights → 2 toggles)
    fireEvent.click(screen.getAllByRole("button", { name: /collapse/i })[0]);

    await waitFor(() => {
      expect(screen.queryByText(insightMessage)).not.toBeInTheDocument();
    });

    // Click the expand toggle to restore
    fireEvent.click(screen.getByRole("button", { name: /expand/i }));

    await waitFor(() => {
      expect(screen.getByText(insightMessage)).toBeInTheDocument();
    });
  });

  it("hero header shows python_version when session carries it", async () => {
    const SESSION_WITH_META = {
      ...SESSION_PAYLOAD,
      session: {
        ...SESSION_PAYLOAD.session,
        session_name: "meta-session",
        python_version: "3.12.3",
        script_path: "/app/main.py",
      },
    };

    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") {
        return Promise.resolve({ ok: true, json: async () => SESSION_WITH_META });
      }
      if (String(path).startsWith("/api/v1/resources/graph")) {
        return Promise.resolve({ ok: true, json: async () => RESOURCES_PAYLOAD });
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    render(<App />);
    expect(await screen.findByText("meta-session")).toBeInTheDocument();

    // Python version metric card must be visible in the hero
    const pythonCard = screen.getAllByText("Python")[0].closest(".metric-card");
    expect(pythonCard).not.toBeNull();
    expect(within(pythonCard).getByText("3.12.3")).toBeInTheDocument();

    // Script path must also be visible
    expect(screen.getByText("/app/main.py")).toBeInTheDocument();
  });

  it("shows live wait state in cancellation insight meta", async () => {
    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") {
        return Promise.resolve({
          ok: true,
          json: async () => SESSION_PAYLOAD,
        });
      }
      if (String(path).startsWith("/api/v1/resources/graph")) {
        return Promise.resolve({
          ok: true,
          json: async () => RESOURCES_PAYLOAD,
        });
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    render(<App />);

    expect(await screen.findByText("demo-session")).toBeInTheDocument();
    expect(screen.getByText("queue 0/16")).toBeInTheDocument();
  });

  it("task list paginates and resets to page 1 when filters change", async () => {
    const manyTasks = Array.from({ length: 30 }, (_, i) => ({
      task_id: i + 1,
      name: `task-${i + 1}`,
      state: i < 25 ? "BLOCKED" : "DONE",
      resource_roles: [],
      parent_task_id: null,
      children: [],
      exception: null,
      metadata: {},
    }));
    const MANY_TASKS_PAYLOAD = {
      session: { session_name: "many-tasks-session", task_count: 30, event_count: 0 },
      tasks: manyTasks,
      segments: manyTasks.map((t, i) => ({
        task_id: t.task_id, task_name: t.name, state: t.state,
        start_ts_ns: i * 1_000_000, end_ts_ns: (i + 1) * 1_000_000,
      })),
      insights: [],
    };

    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") {
        return Promise.resolve({ ok: true, json: async () => MANY_TASKS_PAYLOAD });
      }
      if (String(path).startsWith("/api/v1/resources/graph")) {
        return Promise.resolve({ ok: true, json: async () => [] });
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    render(<App />);
    expect(await screen.findByText("many-tasks-session")).toBeInTheDocument();

    // Page 1: first 25 tasks visible
    const taskSection = screen.getByRole("heading", { name: "Tasks" }).closest("section");
    expect(within(taskSection).getByRole("button", { name: /^task-1 /i })).toBeInTheDocument();
    expect(within(taskSection).queryByRole("button", { name: /^task-26 /i })).not.toBeInTheDocument();
    expect(within(taskSection).getByText(/page 1 of 2/i)).toBeInTheDocument();

    // Next page
    fireEvent.click(within(taskSection).getByRole("button", { name: /next page/i }));
    await waitFor(() => {
      expect(within(taskSection).getByRole("button", { name: /^task-26 /i })).toBeInTheDocument();
      expect(within(taskSection).queryByRole("button", { name: /^task-1 /i })).not.toBeInTheDocument();
      expect(within(taskSection).getByText(/page 2 of 2/i)).toBeInTheDocument();
    });

    // Previous page
    fireEvent.click(within(taskSection).getByRole("button", { name: /previous page/i }));
    await waitFor(() => {
      expect(within(taskSection).getByRole("button", { name: /^task-1 /i })).toBeInTheDocument();
      expect(within(taskSection).getByText(/page 1 of 2/i)).toBeInTheDocument();
    });

    // Filter to DONE tasks (only 5) → resets to page 1 automatically
    fireEvent.change(screen.getByLabelText("State"), { target: { value: "DONE" } });
    await waitFor(() => {
      expect(within(taskSection).getByText(/page 1 of 1/i)).toBeInTheDocument();
      expect(within(taskSection).queryByRole("button", { name: /next page/i })).not.toBeInTheDocument();
    });
  });

  it("loads additional task and timeline pages when session bootstrap is truncated", async () => {
    const manyTasks = Array.from({ length: 130 }, (_, i) => ({
      task_id: i + 1,
      name: `task-${i + 1}`,
      state: "BLOCKED",
      resource_roles: [],
      parent_task_id: null,
      children: [],
      exception: null,
      metadata: {},
    }));
    const manySegments = manyTasks.map((task, i) => ({
      task_id: task.task_id,
      task_name: task.name,
      state: task.state,
      start_ts_ns: i * 1_000_000,
      end_ts_ns: (i + 1) * 1_000_000,
    }));
    const pagedBootstrap = {
      session: { session_name: "paged-session", task_count: 130, event_count: 0 },
      tasks: manyTasks.slice(0, 100),
      segments: manySegments,
      insights: [],
      pagination: {
        tasks: { offset: 0, limit: 100, total: 130, has_more: true, next_offset: 100 },
        segments: { offset: 0, limit: 500, total: 130, has_more: false, next_offset: null },
        insights: { offset: 0, limit: 100, total: 0, has_more: false, next_offset: null },
      },
    };

    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") {
        return Promise.resolve({ ok: true, json: async () => pagedBootstrap });
      }
      if (path === "/api/v1/tasks?offset=100&limit=100") {
        return Promise.resolve({ ok: true, json: async () => manyTasks.slice(100) });
      }
      if (String(path).startsWith("/api/v1/resources/graph")) {
        return Promise.resolve({ ok: true, json: async () => [] });
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    render(<App />);
    expect(await screen.findByText("paged-session")).toBeInTheDocument();

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith("/api/v1/tasks?offset=100&limit=100");
    });

    const taskSection = screen.getByRole("heading", { name: "Tasks" }).closest("section");
    expect(taskSection).not.toBeNull();

    fireEvent.click(within(taskSection).getByRole("button", { name: /next page/i }));
    fireEvent.click(within(taskSection).getByRole("button", { name: /next page/i }));
    fireEvent.click(within(taskSection).getByRole("button", { name: /next page/i }));
    fireEvent.click(within(taskSection).getByRole("button", { name: /next page/i }));
    fireEvent.click(within(taskSection).getByRole("button", { name: /next page/i }));

    await waitFor(() => {
      expect(within(taskSection).getByRole("button", { name: /^task-126 /i })).toBeInTheDocument();
      expect(within(taskSection).getByText(/page 6 of 6/i)).toBeInTheDocument();
    });
  });

  it("dark/light mode toggle switches theme and persists to localStorage", async () => {
    localStorage.clear();
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })),
    });

    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") {
        return Promise.resolve({ ok: true, json: async () => SESSION_PAYLOAD });
      }
      if (String(path).startsWith("/api/v1/resources/graph")) {
        return Promise.resolve({ ok: true, json: async () => RESOURCES_PAYLOAD });
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    render(<App />);
    expect(await screen.findByText("demo-session")).toBeInTheDocument();

    // Default: light (matchMedia returns false = not dark)
    expect(document.documentElement.dataset.theme).toBe("light");

    // Button says "Switch to dark mode"
    const toDark = screen.getByRole("button", { name: /switch to dark mode/i });
    fireEvent.click(toDark);

    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(localStorage.getItem("pyroscope-theme")).toBe("dark");
    expect(screen.getByRole("button", { name: /switch to light mode/i })).toBeInTheDocument();

    // Toggle back to light
    fireEvent.click(screen.getByRole("button", { name: /switch to light mode/i }));
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(localStorage.getItem("pyroscope-theme")).toBe("light");
  });

  it("task tree panel shows hierarchy, selects on click, and collapses nodes", async () => {
    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") {
        return Promise.resolve({ ok: true, json: async () => SESSION_PAYLOAD });
      }
      if (String(path).startsWith("/api/v1/resources/graph")) {
        return Promise.resolve({ ok: true, json: async () => RESOURCES_PAYLOAD });
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    render(<App />);
    expect(await screen.findByText("demo-session")).toBeInTheDocument();

    const tree = screen.getByRole("heading", { name: "Task tree" }).closest("section");
    expect(tree).not.toBeNull();

    // Both tasks visible in the tree
    expect(within(tree).getAllByRole("button", { name: /worker-1/i }).length).toBeGreaterThan(0);
    expect(within(tree).getAllByRole("button", { name: /worker-2/i }).length).toBeGreaterThan(0);

    // Clicking worker-2 in the tree updates the inspector
    fireEvent.click(within(tree).getAllByRole("button", { name: /worker-2/i })[0]);
    await waitFor(() => {
      const inspector = screen.getByText("Inspector").closest("section");
      expect(within(inspector).getByText("worker-2")).toBeInTheDocument();
    });

    // Collapsing worker-1 hides worker-2 from the tree
    const collapseBtn = within(tree).getAllByRole("button", { name: /collapse/i })[0];
    fireEvent.click(collapseBtn);
    await waitFor(() => {
      expect(within(tree).queryByRole("button", { name: /worker-2/i })).not.toBeInTheDocument();
    });

    // Expanding again shows worker-2
    const expandBtn = within(tree).getAllByRole("button", { name: /expand/i })[0];
    fireEvent.click(expandBtn);
    await waitFor(() => {
      expect(within(tree).getAllByRole("button", { name: /worker-2/i }).length).toBeGreaterThan(0);
    });
  });

  it("time window scrubber filters the task list to the selected window", async () => {
    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") {
        return Promise.resolve({ ok: true, json: async () => TIME_WINDOW_PAYLOAD });
      }
      if (String(path).startsWith("/api/v1/resources/graph")) {
        return Promise.resolve({ ok: true, json: async () => [] });
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    render(<App />);
    expect(await screen.findByText("time-window-session")).toBeInTheDocument();
    expect(screen.getByText("Showing 2 of 2")).toBeInTheDocument();

    // Narrow window end to 50 % → only early-task (0–33 %) is visible
    fireEvent.change(screen.getByLabelText("Window end"), { target: { value: "50" } });
    await waitFor(() => {
      expect(screen.getByText("Showing 1 of 2")).toBeInTheDocument();
      const tasks = screen.getByRole("heading", { name: "Tasks" }).closest("section");
      expect(within(tasks).getByRole("button", { name: /early-task/i })).toBeInTheDocument();
      expect(within(tasks).queryByRole("button", { name: /late-task/i })).not.toBeInTheDocument();
    });

    // Clear time filter → both tasks visible again
    fireEvent.click(screen.getByRole("button", { name: /clear time filter/i }));
    await waitFor(() => {
      expect(screen.getByText("Showing 2 of 2")).toBeInTheDocument();
    });
  });

  it("block explainer shows blocking/cancellation context for selected task", async () => {
    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") {
        return Promise.resolve({ ok: true, json: async () => SESSION_PAYLOAD });
      }
      if (String(path).startsWith("/api/v1/resources/graph")) {
        return Promise.resolve({ ok: true, json: async () => RESOURCES_PAYLOAD });
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    render(<App />);
    expect(await screen.findByText("demo-session")).toBeInTheDocument();

    // worker-1 is selected by default (BLOCKED on queue_get / queue:jobs)
    const inspector = () => screen.getByText("Inspector").closest("section");
    expect(within(inspector()).getByText("worker-1")).toBeInTheDocument();

    // Explainer shows for BLOCKED task
    await waitFor(() => {
      expect(within(inspector()).getByText("Why blocked?")).toBeInTheDocument();
      // resource has no holder
      expect(within(inspector()).getByText(/No task currently holds/)).toBeInTheDocument();
    });

    // Select worker-2 (CANCELLED)
    const tasksSection = screen.getByRole("heading", { name: "Tasks" }).closest("section");
    fireEvent.click(within(tasksSection).getAllByRole("button", { name: /worker-2/i })[0]);

    await waitFor(() => {
      // Cancelled task shows why-cancelled explainer
      expect(within(inspector()).getByText("Why cancelled?")).toBeInTheDocument();
      expect(within(inspector()).getAllByText(/worker-1/).length).toBeGreaterThan(0);
      expect(within(inspector()).getAllByText(/parent_task/).length).toBeGreaterThan(0);
    });

    // reset hash so subsequent tests start clean
    window.location.hash = "";
  });

  it("keyboard shortcuts navigate tasks (ArrowDown/ArrowUp) and insights (n/p)", async () => {
    window.location.hash = "";
    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") {
        return Promise.resolve({ ok: true, json: async () => SESSION_PAYLOAD });
      }
      if (String(path).startsWith("/api/v1/resources/graph")) {
        return Promise.resolve({ ok: true, json: async () => RESOURCES_PAYLOAD });
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    render(<App />);
    expect(await screen.findByText("demo-session")).toBeInTheDocument();

    // Initially worker-1 is selected
    let inspector = screen.getByText("Inspector").closest("section");
    expect(within(inspector).getByText("worker-1")).toBeInTheDocument();

    // ArrowDown → worker-2
    fireEvent.keyDown(document, { key: "ArrowDown" });
    await waitFor(() => {
      inspector = screen.getByText("Inspector").closest("section");
      expect(within(inspector).getByText("worker-2")).toBeInTheDocument();
    });

    // ArrowUp → back to worker-1
    fireEvent.keyDown(document, { key: "ArrowUp" });
    await waitFor(() => {
      inspector = screen.getByText("Inspector").closest("section");
      expect(within(inspector).getByText("worker-1")).toBeInTheDocument();
    });

    // n → select first insight (queue_backpressure → Resource tab active)
    fireEvent.keyDown(document, { key: "n" });
    await waitFor(() => {
      const workspace = screen.getByText("Focus workspace").closest("section");
      expect(within(workspace).getByRole("tab", { name: "Resource" })).toHaveClass("active");
    });

    // n → select second insight (cancellation_chain → Cancellation tab active)
    fireEvent.keyDown(document, { key: "n" });
    await waitFor(() => {
      const workspace = screen.getByText("Focus workspace").closest("section");
      expect(within(workspace).getByRole("tab", { name: "Cancellation" })).toHaveClass("active");
    });

    // p → back to first insight (queue_backpressure → Resource tab)
    fireEvent.keyDown(document, { key: "p" });
    await waitFor(() => {
      const workspace = screen.getByText("Focus workspace").closest("section");
      expect(within(workspace).getByRole("tab", { name: "Resource" })).toHaveClass("active");
    });
  });

  it("timeline zoom controls appear and respond to click and reset", async () => {
    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") {
        return Promise.resolve({ ok: true, json: async () => SESSION_PAYLOAD });
      }
      if (String(path).startsWith("/api/v1/resources/graph")) {
        return Promise.resolve({ ok: true, json: async () => RESOURCES_PAYLOAD });
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    render(<App />);
    expect(await screen.findByText("demo-session")).toBeInTheDocument();

    // Zoom controls must be visible
    const zoomInBtn = screen.getByRole("button", { name: /zoom in/i });
    const zoomOutBtn = screen.getByRole("button", { name: /zoom out/i });
    const resetBtn = screen.getByRole("button", { name: /reset zoom/i });

    // Initially at 1×
    expect(screen.getByText("1×")).toBeInTheDocument();

    // Zoom in → 2×
    fireEvent.click(zoomInBtn);
    await waitFor(() => expect(screen.getByText("2×")).toBeInTheDocument());

    // Zoom out → back to 1×
    fireEvent.click(zoomOutBtn);
    await waitFor(() => expect(screen.getByText("1×")).toBeInTheDocument());

    // Zoom in twice → 4×
    fireEvent.click(zoomInBtn);
    fireEvent.click(zoomInBtn);
    await waitFor(() => expect(screen.getByText("4×")).toBeInTheDocument());

    // Reset → 1×
    fireEvent.click(resetBtn);
    await waitFor(() => expect(screen.getByText("1×")).toBeInTheDocument());
  });

  it("permalink: selecting a task updates the URL hash", async () => {
    window.location.hash = "";

    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") {
        return Promise.resolve({ ok: true, json: async () => SESSION_PAYLOAD });
      }
      if (String(path).startsWith("/api/v1/resources/graph")) {
        return Promise.resolve({ ok: true, json: async () => RESOURCES_PAYLOAD });
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    render(<App />);
    expect(await screen.findByText("demo-session")).toBeInTheDocument();

    // Initial selection (worker-1, task_id=1) should set the hash
    await waitFor(() => {
      expect(window.location.hash).toBe("#task=1");
    });

    // Click worker-2 in the task list
    const tasksSection = screen.getByRole("heading", { name: "Tasks" }).closest("section");
    fireEvent.click(within(tasksSection).getAllByRole("button", { name: /worker-2/i })[0]);

    await waitFor(() => {
      expect(window.location.hash).toBe("#task=2");
    });
  });

  it("permalink: initial hash pre-selects the task on load", async () => {
    window.location.hash = "#task=2";

    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") {
        return Promise.resolve({ ok: true, json: async () => SESSION_PAYLOAD });
      }
      if (String(path).startsWith("/api/v1/resources/graph")) {
        return Promise.resolve({ ok: true, json: async () => RESOURCES_PAYLOAD });
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    render(<App />);
    expect(await screen.findByText("demo-session")).toBeInTheDocument();

    await waitFor(() => {
      const inspector = screen.getByText("Inspector").closest("section");
      expect(inspector).not.toBeNull();
      expect(within(inspector).getByText("worker-2")).toBeInTheDocument();
      expect(within(inspector).getByText("CANCELLED")).toBeInTheDocument();
    });

    window.location.hash = "";
  });

  it("export links appear in the hero and point to the export endpoints", async () => {
    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") {
        return Promise.resolve({ ok: true, json: async () => SESSION_PAYLOAD });
      }
      if (String(path).startsWith("/api/v1/resources/graph")) {
        return Promise.resolve({ ok: true, json: async () => RESOURCES_PAYLOAD });
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    render(<App />);
    expect(await screen.findByText("demo-session")).toBeInTheDocument();

    const jsonLink = screen.getByRole("link", { name: /export json/i });
    expect(jsonLink).toHaveAttribute("href", "/api/v1/export?format=json");
    expect(jsonLink).toHaveAttribute("download");

    const csvLink = screen.getByRole("link", { name: /export csv/i });
    expect(csvLink).toHaveAttribute("href", "/api/v1/export?format=csv");
    expect(csvLink).toHaveAttribute("download");
  });

  it("clears timeline hover detail on mouseLeave and restores selected task", async () => {
    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") {
        return Promise.resolve({ ok: true, json: async () => SESSION_PAYLOAD });
      }
      if (String(path).startsWith("/api/v1/resources/graph")) {
        return Promise.resolve({ ok: true, json: async () => RESOURCES_PAYLOAD });
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    const { container } = render(<App />);
    expect(await screen.findByText("demo-session")).toBeInTheDocument();

    const canvas = container.querySelector("canvas");
    expect(canvas).not.toBeNull();
    canvas.getBoundingClientRect = () => ({
      x: 0, y: 0, top: 0, left: 0, bottom: 460, right: 1400, width: 1400, height: 460, toJSON: () => ({}),
    });

    // Hover worker-2 segment (row 1, spanning roughly x=796..1372, y=234..434)
    fireEvent.mouseMove(canvas, { clientX: 1000, clientY: 300 });

    await waitFor(() => {
      const detail = screen.getByText("Timeline detail").closest("aside");
      expect(within(detail).getByText("worker-2")).toBeInTheDocument();
    });

    // MouseLeave: hover clears, detail falls back to selected task (worker-1)
    fireEvent.mouseLeave(canvas);

    await waitFor(() => {
      const detail = screen.getByText("Timeline detail").closest("aside");
      expect(within(detail).getByText("worker-1")).toBeInTheDocument();
      expect(within(detail).queryByText("RUNNING")).not.toBeInTheDocument();
    });
  });

  it("canvas click selects the hovered task and updates the inspector", async () => {
    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") {
        return Promise.resolve({ ok: true, json: async () => SESSION_PAYLOAD });
      }
      if (String(path).startsWith("/api/v1/resources/graph")) {
        return Promise.resolve({ ok: true, json: async () => RESOURCES_PAYLOAD });
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    const { container } = render(<App />);
    expect(await screen.findByText("demo-session")).toBeInTheDocument();

    const canvas = container.querySelector("canvas");
    expect(canvas).not.toBeNull();
    canvas.getBoundingClientRect = () => ({
      x: 0, y: 0, top: 0, left: 0, bottom: 460, right: 1400, width: 1400, height: 460, toJSON: () => ({}),
    });

    // Hover worker-2 segment, then click to select it
    fireEvent.mouseMove(canvas, { clientX: 1000, clientY: 300 });
    fireEvent.click(canvas);

    await waitFor(() => {
      const inspector = screen.getByText("Inspector").closest("section");
      expect(inspector).not.toBeNull();
      // inspector should now display worker-2's details
      expect(within(inspector).getByText("worker-2")).toBeInTheDocument();
      expect(within(inspector).getByText("CANCELLED")).toBeInTheDocument();
    });
  });

  it("Cancelled preset activates Cancellation tab for cancellation_cascade insights", async () => {
    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") {
        return Promise.resolve({ ok: true, json: async () => CANCELLATION_CASCADE_PAYLOAD });
      }
      if (String(path).startsWith("/api/v1/resources/graph")) {
        return Promise.resolve({ ok: true, json: async () => [] });
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    render(<App />);
    expect(await screen.findByText("cascade-session")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Cancelled" }));

    await waitFor(() => {
      const workspace = screen.getByText("Focus workspace").closest("section");
      expect(workspace).not.toBeNull();
      expect(within(workspace).getByRole("tab", { name: "Cancellation" })).toHaveClass("active");
      expect(within(workspace).getByText("Cancellation focus")).toBeInTheDocument();
      expect(within(workspace).getByText("parent_task")).toBeInTheDocument();
      expect(within(workspace).getByText("2 task(s)")).toBeInTheDocument();
    });
  });

  it("clicking a task in the cancellation drilldown navigates the inspector to that task", async () => {
    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") {
        return Promise.resolve({ ok: true, json: async () => SESSION_PAYLOAD });
      }
      if (String(path).startsWith("/api/v1/resources/graph")) {
        return Promise.resolve({ ok: true, json: async () => RESOURCES_PAYLOAD });
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    render(<App />);
    expect(await screen.findByText("demo-session")).toBeInTheDocument();

    // Open the cancellation drilldown via the insight button
    fireEvent.click(
      screen.getByRole("button", {
        name: /Task worker-1 triggered cancellation of 1 sibling task: worker-2/i,
      }),
    );

    await waitFor(() => {
      const workspace = screen.getByText("Focus workspace").closest("section");
      expect(within(workspace).getByRole("tab", { name: "Cancellation" })).toHaveClass("active");
    });

    // Click the source task button (worker-1) inside the cancellation panel
    const workspace = screen.getByText("Focus workspace").closest("section");
    const sourceBtn = within(workspace).getAllByRole("button", { name: /worker-1/i })[0];
    fireEvent.click(sourceBtn);

    await waitFor(() => {
      const inspector = screen.getByText("Inspector").closest("section");
      expect(inspector).not.toBeNull();
      expect(within(inspector).getByText("worker-1")).toBeInTheDocument();
      expect(within(inspector).getByText("BLOCKED")).toBeInTheDocument();
    });
  });

  it("teaching mode toggle shows and hides explanation fields on insight cards", async () => {
    const TEACHING_PAYLOAD = {
      session: { session_name: "teach-session", task_count: 1, event_count: 0 },
      tasks: [{ task_id: 1, name: "worker-1", state: "BLOCKED", resource_roles: [], parent_task_id: null, children: [], exception: null, metadata: {} }],
      segments: [{ task_id: 1, task_name: "worker-1", state: "BLOCKED", start_ts_ns: 0, end_ts_ns: 1_000_000 }],
      insights: [
        {
          kind: "queue_backpressure",
          severity: "warning",
          message: "Queue queue:jobs is backing up with 1 waiting task",
          resource_id: "queue:jobs",
          explanation: {
            what: "Multiple tasks are waiting on the same queue.",
            how: "Add more consumer workers or increase queue capacity.",
          },
        },
      ],
    };

    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") return Promise.resolve({ ok: true, json: async () => TEACHING_PAYLOAD });
      if (String(path).startsWith("/api/v1/resources/graph")) return Promise.resolve({ ok: true, json: async () => [] });
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    render(<App />);
    expect(await screen.findByText("teach-session")).toBeInTheDocument();

    // explanation fields not visible before teaching mode is on
    expect(screen.queryByText(/Multiple tasks are waiting on the same queue/)).not.toBeInTheDocument();

    // enable teaching mode
    fireEvent.click(screen.getByRole("button", { name: /enable teaching mode/i }));

    await waitFor(() => {
      expect(screen.getByText(/Multiple tasks are waiting on the same queue/)).toBeInTheDocument();
      expect(screen.getByText(/Add more consumer workers or increase queue capacity/)).toBeInTheDocument();
    });

    // disable teaching mode
    fireEvent.click(screen.getByRole("button", { name: /disable teaching mode/i }));

    await waitFor(() => {
      expect(screen.queryByText(/Multiple tasks are waiting on the same queue/)).not.toBeInTheDocument();
    });
  });

  it("request/job panel shows label rows and clicking narrows task list", async () => {
    const LABELED_PAYLOAD = {
      session: { session_name: "labeled-session", task_count: 4, event_count: 0 },
      tasks: [
        { task_id: 1, name: "handle-users-1", state: "DONE",    resource_roles: [], parent_task_id: null, children: [], exception: null, metadata: { request_label: "GET /users" } },
        { task_id: 2, name: "handle-users-2", state: "BLOCKED", resource_roles: [], parent_task_id: null, children: [], exception: null, metadata: { request_label: "GET /users" } },
        { task_id: 3, name: "handle-orders",  state: "RUNNING", resource_roles: [], parent_task_id: null, children: [], exception: null, metadata: { request_label: "GET /orders" } },
        { task_id: 4, name: "bg-job",         state: "DONE",    resource_roles: [], parent_task_id: null, children: [], exception: null, metadata: { job_label: "job-bg" } },
      ],
      segments: [
        { task_id: 1, task_name: "handle-users-1", state: "DONE",    start_ts_ns: 0, end_ts_ns: 1_000_000 },
        { task_id: 2, task_name: "handle-users-2", state: "BLOCKED", start_ts_ns: 0, end_ts_ns: 2_000_000 },
        { task_id: 3, task_name: "handle-orders",  state: "RUNNING", start_ts_ns: 0, end_ts_ns: 3_000_000 },
        { task_id: 4, task_name: "bg-job",         state: "DONE",    start_ts_ns: 0, end_ts_ns: 1_000_000 },
      ],
      insights: [],
    };

    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") return Promise.resolve({ ok: true, json: async () => LABELED_PAYLOAD });
      if (String(path).startsWith("/api/v1/resources/graph")) return Promise.resolve({ ok: true, json: async () => [] });
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    render(<App />);
    expect(await screen.findByText("labeled-session")).toBeInTheDocument();

    // Panel heading present
    const panel = screen.getByRole("heading", { name: /requests & jobs/i }).closest("section");
    expect(panel).not.toBeNull();

    // Both request labels shown with task counts
    expect(within(panel).getByText("GET /users")).toBeInTheDocument();
    expect(within(panel).getByText("GET /orders")).toBeInTheDocument();
    // job label shown
    expect(within(panel).getByText("job-bg")).toBeInTheDocument();

    // Clicking "GET /users" filters task list to 2 tasks
    fireEvent.click(within(panel).getByRole("button", { name: /GET \/users/i }));
    await waitFor(() => {
      const taskSection = screen.getByRole("heading", { name: "Tasks" }).closest("section");
      expect(within(taskSection).getByRole("button", { name: /handle-users-1/i })).toBeInTheDocument();
      expect(within(taskSection).getByRole("button", { name: /handle-users-2/i })).toBeInTheDocument();
      expect(within(taskSection).queryByRole("button", { name: /handle-orders/i })).not.toBeInTheDocument();
    });
  });

  it("timeline has Task / Request / Job view mode toggle buttons", async () => {
    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") {
        return Promise.resolve({ ok: true, json: async () => SESSION_PAYLOAD });
      }
      if (String(path).startsWith("/api/v1/resources/graph")) {
        return Promise.resolve({ ok: true, json: async () => RESOURCES_PAYLOAD });
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    render(<App />);
    expect(await screen.findByText("demo-session")).toBeInTheDocument();

    const timelineSection = screen.getByRole("heading", { name: "Timeline" }).closest("section");
    expect(within(timelineSection).getByRole("button", { name: /task view/i })).toBeInTheDocument();
    expect(within(timelineSection).getByRole("button", { name: /request view/i })).toBeInTheDocument();
    expect(within(timelineSection).getByRole("button", { name: /job view/i })).toBeInTheDocument();

    // Clicking Request view and Job view should not throw
    fireEvent.click(within(timelineSection).getByRole("button", { name: /request view/i }));
    fireEvent.click(within(timelineSection).getByRole("button", { name: /job view/i }));
    fireEvent.click(within(timelineSection).getByRole("button", { name: /task view/i }));
  });

  it("shows a slow-client warning banner when SSE sends an error frame", async () => {
    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") {
        return Promise.resolve({ ok: true, json: async () => SESSION_PAYLOAD });
      }
      if (String(path).startsWith("/api/v1/resources/graph")) {
        return Promise.resolve({ ok: true, json: async () => RESOURCES_PAYLOAD });
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    render(<App />);
    expect(await screen.findByText("demo-session")).toBeInTheDocument();

    act(() => {
      MockEventSource.instances[0].onmessage?.({
        data: JSON.stringify({ type: "error", code: "slow_client" }),
      });
    });

    await waitFor(() => {
      expect(screen.getAllByText(/connection slow/i).length).toBeGreaterThan(0);
      expect(screen.getByText(/connection too slow/i)).toBeInTheDocument();
    });
  });
});

describe("groupTasksByLabel", () => {
  const tasks = [
    { task_id: 1, state: "DONE", metadata: { request_label: "GET /foo", job_label: "job-a" } },
    { task_id: 2, state: "RUNNING", metadata: { request_label: "GET /foo", job_label: "job-a" } },
    { task_id: 3, state: "FAILED", metadata: { request_label: "POST /bar", job_label: "job-b" } },
    { task_id: 4, state: "DONE", metadata: {} },
  ];
  const segments = [
    { task_id: 1, start_ts_ns: 0, end_ts_ns: 100 },
    { task_id: 2, start_ts_ns: 50, end_ts_ns: 200 },
    { task_id: 3, start_ts_ns: 10, end_ts_ns: 90 },
  ];

  it("groups tasks by request_label, skipping tasks without a label", () => {
    const groups = groupTasksByLabel(tasks, segments, "request_label");
    expect(groups).toHaveLength(2);
    const foo = groups.find((g) => g.label === "GET /foo");
    expect(foo.taskIds).toEqual([1, 2]);
    expect(foo.start_ts_ns).toBe(0);
    expect(foo.end_ts_ns).toBe(200);
    expect(foo.state).toBe("RUNNING");
  });

  it("picks dominant state: FAILED > RUNNING > DONE", () => {
    const mixed = [
      { task_id: 3, state: "FAILED", metadata: { job_label: "j" } },
      { task_id: 1, state: "DONE", metadata: { job_label: "j" } },
    ];
    const [group] = groupTasksByLabel(mixed, segments, "job_label");
    expect(group.state).toBe("FAILED");
  });

  it("groups tasks by job_label", () => {
    const groups = groupTasksByLabel(tasks, segments, "job_label");
    const a = groups.find((g) => g.label === "job-a");
    expect(a.taskIds).toHaveLength(2);
  });
});

// ---------------------------------------------------------------------------
// U11 — isCancellationInsight / insightMeta cover new insight kinds
// ---------------------------------------------------------------------------

import { isCancellationInsight, insightMeta } from "./utils";

// ---------------------------------------------------------------------------
// U15 — "Export Minimized" link in hero
// ---------------------------------------------------------------------------

describe("Export Minimized link", () => {
  beforeEach(() => {
    global.EventSource = MockEventSource;
    MockEventSource.instances = [];
  });

  it("renders an Export Minimized download link when session is present", async () => {
    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") {
        return Promise.resolve({ ok: true, json: async () => SESSION_PAYLOAD });
      }
      if (String(path).startsWith("/api/v1/resources/graph")) {
        return Promise.resolve({ ok: true, json: async () => RESOURCES_PAYLOAD });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    });
    render(<App />);
    const link = await screen.findByText(/export minimized/i);
    expect(link.getAttribute("href")).toContain("format=minimized");
  });

  it("scopes Export Minimized to the selected insight kind", async () => {
    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") {
        return Promise.resolve({ ok: true, json: async () => SESSION_PAYLOAD });
      }
      if (String(path).startsWith("/api/v1/resources/graph")) {
        return Promise.resolve({ ok: true, json: async () => RESOURCES_PAYLOAD });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    });

    render(<App />);

    const insightButton = await screen.findByRole("button", {
      name: /queue queue:jobs is backing up/i,
    });
    fireEvent.click(insightButton);

    const link = await screen.findByText(/export minimized/i);
    expect(link.getAttribute("href")).toContain("format=minimized");
    expect(link.getAttribute("href")).toContain("kind=queue_backpressure");
  });
});

describe("Capture compare", () => {
  beforeEach(() => {
    global.EventSource = MockEventSource;
    MockEventSource.instances = [];
  });

  it("compares two uploaded captures without restarting the UI session", async () => {
    const compareResponse = {
      baseline: { session_name: "fixture-a" },
      candidate: { session_name: "fixture-b" },
      counts: {
        baseline_tasks: 2,
        candidate_tasks: 3,
        baseline_insights: 1,
        candidate_insights: 2,
      },
      state_changes: [
        {
          name: "worker-1",
          baseline_state: "DONE",
          candidate_state: "BLOCKED",
        },
      ],
    };

    global.fetch = vi.fn((path, options) => {
      if (path === "/api/v1/session") {
        return Promise.resolve({ ok: true, json: async () => SESSION_PAYLOAD });
      }
      if (String(path).startsWith("/api/v1/resources/graph")) {
        return Promise.resolve({ ok: true, json: async () => RESOURCES_PAYLOAD });
      }
      if (path === "/api/v1/replay/compare") {
        expect(options?.method).toBe("POST");
        return Promise.resolve({ ok: true, json: async () => compareResponse });
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    if (!File.prototype.text) {
      Object.defineProperty(File.prototype, "text", {
        configurable: true,
        value() {
          return Promise.resolve("{}");
        },
      });
    }

    render(<App />);
    expect(await screen.findByText("demo-session")).toBeInTheDocument();

    const baselineInput = screen.getByLabelText("Baseline capture");
    const candidateInput = screen.getByLabelText("Candidate capture");
    const baselineFile = new File(["{}"], "baseline.json", { type: "application/json" });
    const candidateFile = new File(["{}"], "candidate.json", { type: "application/json" });

    fireEvent.change(baselineInput, { target: { files: [baselineFile] } });
    fireEvent.change(candidateInput, { target: { files: [candidateFile] } });
    fireEvent.click(screen.getByRole("button", { name: /compare captures/i }));

    const comparePanel = screen.getByText("Browser").closest("section");
    expect(comparePanel).not.toBeNull();
    await within(comparePanel).findByText("fixture-a");
    expect(within(comparePanel).getByText("fixture-b")).toBeInTheDocument();
    expect(within(comparePanel).getByText("Tasks")).toBeInTheDocument();
    expect(within(comparePanel).getByText("2 -> 3")).toBeInTheDocument();
    expect(within(comparePanel).getByText("Insights")).toBeInTheDocument();
    expect(within(comparePanel).getByText("1 -> 2")).toBeInTheDocument();
    expect(
      within(comparePanel).getByText("worker-1 (DONE -> BLOCKED)"),
    ).toBeInTheDocument();
  });
});

describe("isCancellationInsight — new kinds", () => {
  it("returns true for timeout_taskgroup_cascade", () => {
    expect(isCancellationInsight({ kind: "timeout_taskgroup_cascade" })).toBe(true);
  });

  it("returns false for deadlock (not a cancellation)", () => {
    expect(isCancellationInsight({ kind: "deadlock" })).toBe(false);
  });
});

describe("insightMeta — deadlock cycle string", () => {
  it("returns cycle string for deadlock insight", () => {
    const item = {
      kind: "deadlock",
      cycle_task_names: ["alpha", "beta"],
    };
    const meta = insightMeta(item);
    expect(meta).toContain("alpha");
    expect(meta).toContain("beta");
  });

  it("returns group_task_name for timeout_taskgroup_cascade", () => {
    const item = {
      kind: "timeout_taskgroup_cascade",
      group_task_name: "parent",
      timeout_seconds: 5,
    };
    const meta = insightMeta(item);
    expect(meta).toContain("parent");
  });
});

// ---------------------------------------------------------------------------
// U17 — CancellationFocus shows cancelled_task_ids for timeout_taskgroup_cascade
// ---------------------------------------------------------------------------

const TG_CASCADE_PAYLOAD = {
  ...SESSION_PAYLOAD,
  tasks: [
    { task_id: 10, name: "tg-parent", state: "CANCELLED", children: [11, 12], parent_task_id: null, metadata: {} },
    { task_id: 11, name: "tg-child-a", state: "CANCELLED", children: [], parent_task_id: 10, metadata: {} },
    { task_id: 12, name: "tg-child-b", state: "CANCELLED", children: [], parent_task_id: 10, metadata: {} },
  ],
  segments: [],
  insights: [
    {
      kind: "timeout_taskgroup_cascade",
      severity: "error",
      message: "TaskGroup on 'tg-parent' cancelled 2 tasks after 3.00s timeout",
      task_id: 10,
      group_task_id: 10,
      group_task_name: "tg-parent",
      timeout_seconds: 3.0,
      cancellation_origin: "timeout_cm",
      cancelled_task_ids: [11, 12],
      cancelled_task_names: ["tg-child-a", "tg-child-b"],
      explanation: { what: "...", how: "..." },
    },
  ],
};

describe("CancellationFocus — timeout_taskgroup_cascade", () => {
  it("shows cancelled children in the drilldown when timeout_taskgroup_cascade is selected", async () => {
    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") {
        return Promise.resolve({ ok: true, json: async () => TG_CASCADE_PAYLOAD });
      }
      if (String(path).startsWith("/api/v1/resources/graph")) {
        return Promise.resolve({ ok: true, json: async () => [] });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    });
    render(<App />);
    // Wait for session to load, then click the insight message
    await screen.findByText(/TaskGroup on 'tg-parent'/i);
    fireEvent.click(screen.getByText(/TaskGroup on 'tg-parent'/i));
    await waitFor(() => {
      const workspace = screen.getByText("Focus workspace").closest("section");
      expect(within(workspace).getByRole("tab", { name: "Cancellation" })).toHaveClass("active");
      // Both cancelled children should appear as buttons in the drilldown
      expect(within(workspace).getByRole("button", { name: /tg-child-a/i })).toBeInTheDocument();
      expect(within(workspace).getByRole("button", { name: /tg-child-b/i })).toBeInTheDocument();
    });
  });
});

// ---------------------------------------------------------------------------
// U18 — DeadlockFocus panel
// ---------------------------------------------------------------------------

const DEADLOCK_PAYLOAD = {
  ...SESSION_PAYLOAD,
  tasks: [
    { task_id: 20, name: "alpha", state: "BLOCKED", children: [], parent_task_id: null, metadata: {} },
    { task_id: 21, name: "beta", state: "BLOCKED", children: [], parent_task_id: null, metadata: {} },
  ],
  segments: [],
  insights: [
    {
      kind: "deadlock",
      severity: "error",
      task_id: 20,
      cycle_task_ids: [20, 21],
      cycle_task_names: ["alpha", "beta"],
      message: "Deadlock: alpha → beta → alpha",
      explanation: { what: "...", how: "..." },
    },
  ],
};

describe("DeadlockFocus panel", () => {
  it("opens the Deadlock tab when a deadlock insight is selected", async () => {
    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") {
        return Promise.resolve({ ok: true, json: async () => DEADLOCK_PAYLOAD });
      }
      if (String(path).startsWith("/api/v1/resources/graph")) {
        return Promise.resolve({ ok: true, json: async () => [] });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    });
    render(<App />);
    await screen.findByText(/Deadlock: alpha/i);
    fireEvent.click(screen.getByText(/Deadlock: alpha/i));
    await waitFor(() => {
      const workspace = screen.getByText("Focus workspace").closest("section");
      // Deadlock tab should be present and active
      expect(within(workspace).getByRole("tab", { name: /Deadlock/i })).toHaveClass("active");
      // Cycle tasks should be shown (cycle string + individual buttons)
      expect(within(workspace).getAllByText(/alpha/i).length).toBeGreaterThan(0);
      expect(within(workspace).getAllByText(/beta/i).length).toBeGreaterThan(0);
    });
  });
});
