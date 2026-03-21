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
  ],
};

const RESOURCES_PAYLOAD = [
  { resource_id: "sleep", task_ids: [1] },
  { resource_id: "queue:jobs", task_ids: [1, 2] },
];

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

    fireEvent.click(screen.getAllByRole("button", { name: /worker-2/i })[1]);

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
      expect(screen.getByText("Drilldown")).toBeInTheDocument();
      expect(screen.getByText("Related tasks")).toBeInTheDocument();
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
});
