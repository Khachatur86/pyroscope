import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
      parent_task_id: null,
      children: [2],
      exception: null,
    },
    {
      task_id: 2,
      name: "worker-2",
      state: "RUNNING",
      parent_task_id: 1,
      children: [],
      exception: "boom",
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
      kind: "long_block",
      severity: "warning",
      message: "worker-1 has been blocked on sleep",
    },
  ],
};

const RESOURCES_PAYLOAD = [
  { task_id: 1, resource_id: "sleep", action: "await" },
  { task_id: 2, resource_id: "queue:jobs", action: "put" },
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
    expect(screen.getByText("worker-1 has been blocked on sleep")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("9.0 ms")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /worker-2/i }));

    await waitFor(() => {
      expect(screen.getByText("boom")).toBeInTheDocument();
      expect(screen.getByText("queue:jobs · put")).toBeInTheDocument();
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
