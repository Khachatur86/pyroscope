import React from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

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
      expect(within(inspector).getByText("parent_task")).toBeInTheDocument();
      expect(screen.getByText("Cancel source")).toBeInTheDocument();
      expect(within(inspector).getByText("queue_get")).toBeInTheDocument();
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
      expect(within(inspector).getByText("parent_task")).toBeInTheDocument();
      expect(within(inspector).getByText("queue_get")).toBeInTheDocument();
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
});
