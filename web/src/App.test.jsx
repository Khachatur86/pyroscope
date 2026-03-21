import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

class MockEventSource {
  constructor(url) {
    this.url = url;
    this.onmessage = null;
    this.onerror = null;
  }

  close() {}
}

describe("App", () => {
  beforeEach(() => {
    global.EventSource = MockEventSource;
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

    render(<App />);

    expect(await screen.findByText("demo-session")).toBeInTheDocument();
    expect(
      screen.getByText("Queue queue:jobs is backing up with 2 waiting tasks: worker-1, worker-2"),
    ).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("9.0 ms")).toBeInTheDocument();

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
    });

    fireEvent.click(screen.getByRole("button", { name: /Queue queue:jobs is backing up/i }));

    await waitFor(() => {
      const resourceFocus = screen.getByText("Resource focus").closest("section");
      expect(resourceFocus).not.toBeNull();
      expect(within(resourceFocus).getByRole("heading", { name: "Drilldown" })).toBeInTheDocument();
      expect(within(resourceFocus).getByText("Contention summary")).toBeInTheDocument();
      expect(within(resourceFocus).getByText("Queue Backpressure")).toBeInTheDocument();
      expect(within(resourceFocus).getByText("queue_get · 2")).toBeInTheDocument();
      expect(within(resourceFocus).getByText("Related tasks")).toBeInTheDocument();
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
      const cancellationFocus = screen.getByText("Cancellation focus").closest("section");
      expect(cancellationFocus).not.toBeNull();
      expect(within(cancellationFocus).getByText("parent_task")).toBeInTheDocument();
      expect(within(cancellationFocus).getByRole("button", { name: /worker-1/i })).toBeInTheDocument();
      expect(within(cancellationFocus).getByRole("button", { name: /worker-2/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Blocked main" }));

    await waitFor(() => {
      expect(screen.getByText("Showing 1 of 2")).toBeInTheDocument();
      const resourceFocus = screen.getByText("Resource focus").closest("section");
      expect(resourceFocus).not.toBeNull();
      expect(within(resourceFocus).getByText("Queue Backpressure")).toBeInTheDocument();
      expect(within(resourceFocus).getByText("queue_get · 1")).toBeInTheDocument();
      expect(within(resourceFocus).getByRole("button", { name: /worker-1/i })).toBeInTheDocument();
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
      const errorFocus = screen.getByText("Error focus").closest("section");
      expect(errorFocus).not.toBeNull();
      expect(within(errorFocus).getByText("yes")).toBeInTheDocument();
      expect(within(errorFocus).getByRole("button", { name: /root-main/i })).toBeInTheDocument();
      expect(within(errorFocus).getByText("RuntimeError")).toBeInTheDocument();
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
      expect(screen.getByText("Cancellation focus")).toBeInTheDocument();
      expect(screen.getByText("Source task")).toBeInTheDocument();
      expect(screen.getByText("Affected tasks")).toBeInTheDocument();
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
      const errorFocus = screen.getByText("Error focus").closest("section");
      expect(errorFocus).not.toBeNull();
      expect(within(errorFocus).getByText("Failed task")).toBeInTheDocument();
      expect(within(errorFocus).getByText("yes")).toBeInTheDocument();
      expect(within(errorFocus).getByRole("button", { name: /root-main/i })).toBeInTheDocument();

      const inspector = screen.getByText("Inspector").closest("section");
      expect(inspector).not.toBeNull();
      expect(within(inspector).getByText("root-main")).toBeInTheDocument();
      expect(within(inspector).getByText("FAILED")).toBeInTheDocument();
    });
  });
});
