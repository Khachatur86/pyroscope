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
      affected_task_ids: [2],
      affected_task_names: ["worker-2"],
      reason: "parent_task",
    },
  ],
};

const RESOURCES_PAYLOAD = [
  { resource_id: "sleep", task_ids: [1] },
  { resource_id: "queue:jobs", task_ids: [1, 2] },
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
      if (path === "/api/v1/resources/graph") {
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
    });

    const tasksSection = screen.getByRole("heading", { name: "Tasks" }).closest("section");
    expect(tasksSection).not.toBeNull();
    fireEvent.click(within(tasksSection).getByRole("button", { name: /worker-2/i }));

    await waitFor(() => {
      const inspector = screen.getByText("Inspector").closest("section");
      expect(inspector).not.toBeNull();
      expect(screen.getByText("boom")).toBeInTheDocument();
      expect(screen.getByText("queue:jobs · 2 task(s)")).toBeInTheDocument();
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
      if (path === "/api/v1/resources/graph") {
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

  it("drives cancellation and blocked drilldowns from filter presets", async () => {
    global.fetch = vi.fn((path) => {
      if (path === "/api/v1/session") {
        return Promise.resolve({
          ok: true,
          json: async () => SESSION_PAYLOAD,
        });
      }
      if (path === "/api/v1/resources/graph") {
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
      expect(within(workspace).getByText("queue_get · 1")).toBeInTheDocument();
      expect(within(workspace).getByRole("button", { name: /worker-1/i })).toBeInTheDocument();
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
      if (path === "/api/v1/resources/graph") {
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
      if (path === "/api/v1/resources/graph") {
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
      if (path === "/api/v1/resources/graph") {
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
      expect(within(tasksSection).queryByRole("button", { name: /worker-2/i })).not.toBeInTheDocument();

      const inspector = screen.getByText("Inspector").closest("section");
      expect(inspector).not.toBeNull();
      expect(within(inspector).getByText("worker-1")).toBeInTheDocument();
      expect(within(inspector).getByText("BLOCKED")).toBeInTheDocument();
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
      if (path === "/api/v1/resources/graph") {
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
      if (path === "/api/v1/resources/graph") {
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
      if (path === "/api/v1/resources/graph") {
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
      if (path === "/api/v1/resources/graph") {
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
      if (path === "/api/v1/resources/graph") {
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
      if (path === "/api/v1/resources/graph") {
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
});
