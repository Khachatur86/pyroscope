import React, { useEffect, useMemo, useRef, useState } from "react";

import { STATE_COLORS, formatDuration, timelineGeometry } from "./utils";

export function Timeline({ tasks, segments, selectedTaskId, onSelectTask, taskResourceRole, onTimeWindowChange }) {
  const canvasRef = useRef(null);
  const [hoveredSegment, setHoveredSegment] = useState(null);
  const [viewRange, setViewRange] = useState({ start: 0, end: 1 });
  const [scrubStart, setScrubStart] = useState(0);
  const [scrubEnd, setScrubEnd] = useState(100);

  const minTs = segments.length ? Math.min(...segments.map((s) => s.start_ts_ns)) : 0;
  const maxTs = segments.length ? Math.max(...segments.map((s) => s.end_ts_ns)) : 0;
  const span = Math.max(1, maxTs - minTs);

  function handleScrubStart(event) {
    const val = Math.min(Number(event.target.value), scrubEnd - 1);
    setScrubStart(val);
    if (val === 0 && scrubEnd === 100) {
      onTimeWindowChange(null);
    } else {
      onTimeWindowChange({ start: minTs + (val / 100) * span, end: minTs + (scrubEnd / 100) * span });
    }
  }

  function handleScrubEnd(event) {
    const val = Math.max(Number(event.target.value), scrubStart + 1);
    setScrubEnd(val);
    if (scrubStart === 0 && val === 100) {
      onTimeWindowChange(null);
    } else {
      onTimeWindowChange({ start: minTs + (scrubStart / 100) * span, end: minTs + (val / 100) * span });
    }
  }

  function handleClearScrub() {
    setScrubStart(0);
    setScrubEnd(100);
    onTimeWindowChange(null);
  }

  const scrubActive = scrubStart > 0 || scrubEnd < 100;
  const geometry = useMemo(
    () => timelineGeometry(tasks, segments, 1400, 460, viewRange.start, viewRange.end),
    [segments, tasks, viewRange],
  );

  const zoomLevel = Math.round(1 / (viewRange.end - viewRange.start));

  function handleZoomIn() {
    setViewRange(({ start, end }) => {
      const center = (start + end) / 2;
      const halfRange = (end - start) / 4;
      return { start: Math.max(0, center - halfRange), end: Math.min(1, center + halfRange) };
    });
  }

  function handleZoomOut() {
    setViewRange(({ start, end }) => {
      const span = end - start;
      const center = (start + end) / 2;
      const newHalf = span;
      const newStart = Math.max(0, center - newHalf);
      const newEnd = Math.min(1, center + newHalf);
      return { start: newStart, end: newEnd };
    });
  }

  function handleResetZoom() {
    setViewRange({ start: 0, end: 1 });
  }

  function handleWheel(event) {
    event.preventDefault();
    const canvas = canvasRef.current;
    if (!canvas) {
      return;
    }
    const rect = canvas.getBoundingClientRect();
    const mouseX = ((event.clientX - rect.left) / rect.width) * canvas.width;
    const { labelWidth } = geometry;
    const usableWidth = canvas.width - labelWidth - 28;
    if (mouseX < labelWidth || mouseX > labelWidth + usableWidth) {
      return;
    }
    const pointerFrac = (mouseX - labelWidth) / usableWidth;
    setViewRange(({ start, end }) => {
      const span = end - start;
      const dataFrac = start + pointerFrac * span;
      const factor = event.deltaY > 0 ? 1.5 : 0.667;
      const newSpan = Math.min(1, Math.max(0.01, span * factor));
      const newStart = Math.max(0, Math.min(1 - newSpan, dataFrac - pointerFrac * newSpan));
      return { start: newStart, end: newStart + newSpan };
    });
  }

  const selectedTaskSegments = useMemo(
    () => segments.filter((segment) => segment.task_id === selectedTaskId),
    [segments, selectedTaskId],
  );
  const detailSegment =
    hoveredSegment ??
    selectedTaskSegments[selectedTaskSegments.length - 1] ??
    segments[segments.length - 1] ??
    null;
  const detailTask = useMemo(() => {
    if (!detailSegment) {
      return null;
    }
    return tasks.find((task) => task.task_id === detailSegment.task_id) ?? null;
  }, [detailSegment, tasks]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) {
      return;
    }
    const context = canvas.getContext("2d");
    const width = canvas.width;
    const height = canvas.height;
    context.clearRect(0, 0, width, height);
    context.fillStyle = "#0d1117";
    context.fillRect(0, 0, width, height);

    if (!segments.length) {
      context.fillStyle = "#dbe4ee";
      context.font = "14px IBM Plex Mono, monospace";
      context.fillText("No timeline data yet.", 24, 36);
      return;
    }

    const { labelWidth, rowHeight, bounds } = geometry;

    context.font = "12px IBM Plex Mono, monospace";
    context.textBaseline = "middle";

    tasks.forEach((task, index) => {
      const y = 18 + index * rowHeight;
      context.fillStyle =
        task.task_id === selectedTaskId ? "rgba(93, 175, 255, 0.14)" : "rgba(255, 255, 255, 0.03)";
      context.fillRect(0, y, width, rowHeight - 4);
      context.fillStyle = "#dbe4ee";
      context.fillText(task.name, 18, y + (rowHeight - 4) / 2);
    });

    bounds.forEach(({ segment, x, y, width: segmentWidth, height: segmentHeight }) => {
      context.fillStyle = STATE_COLORS[segment.state] || "#6bb9ff";
      context.fillRect(x, y, segmentWidth, segmentHeight);
      if (segment.task_id === selectedTaskId) {
        context.strokeStyle = "#f8fafc";
        context.lineWidth = 2;
        context.strokeRect(x, y, segmentWidth, segmentHeight);
      }
      if (
        hoveredSegment &&
        hoveredSegment.task_id === segment.task_id &&
        hoveredSegment.start_ts_ns === segment.start_ts_ns &&
        hoveredSegment.end_ts_ns === segment.end_ts_ns
      ) {
        context.strokeStyle = "#dbe4ee";
        context.lineWidth = 2;
        context.strokeRect(x, y, segmentWidth, segmentHeight);
      }
    });
  }, [geometry, hoveredSegment, segments, selectedTaskId, tasks]);

  function handlePointerMove(event) {
    const canvas = canvasRef.current;
    if (!canvas) {
      return;
    }
    const rect = canvas.getBoundingClientRect();
    const x = ((event.clientX - rect.left) / rect.width) * canvas.width;
    const y = ((event.clientY - rect.top) / rect.height) * canvas.height;
    const hit = geometry.bounds.find(
      (bound) =>
        x >= bound.x &&
        x <= bound.x + bound.width &&
        y >= bound.y &&
        y <= bound.y + bound.height,
    );
    setHoveredSegment(hit?.segment ?? null);
  }

  return (
    <section className="panel timeline-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Runtime view</p>
          <h2>Timeline</h2>
        </div>
        <div className="timeline-zoom-controls">
          <span className="zoom-level">{zoomLevel}×</span>
          <button className="preset-chip" type="button" onClick={handleZoomIn} aria-label="Zoom in">
            +
          </button>
          <button className="preset-chip" type="button" onClick={handleZoomOut} aria-label="Zoom out">
            −
          </button>
          <button className="preset-chip" type="button" onClick={handleResetZoom} aria-label="Reset zoom">
            Reset
          </button>
        </div>
      </div>
      <div className="timeline-layout">
        <canvas
          ref={canvasRef}
          className="timeline-canvas"
          width={1400}
          height={460}
          onClick={() => onSelectTask((hoveredSegment ?? detailSegment)?.task_id ?? selectedTaskId)}
          onMouseLeave={() => setHoveredSegment(null)}
          onMouseMove={handlePointerMove}
          onWheel={handleWheel}
        />
        <div className="timeline-scrubber">
          <label>
            <span>Window start</span>
            <input
              aria-label="Window start"
              type="range"
              min="0"
              max="100"
              value={scrubStart}
              onChange={handleScrubStart}
            />
          </label>
          <label>
            <span>Window end</span>
            <input
              aria-label="Window end"
              type="range"
              min="0"
              max="100"
              value={scrubEnd}
              onChange={handleScrubEnd}
            />
          </label>
          {scrubActive ? (
            <button className="preset-chip" type="button" onClick={handleClearScrub}>
              Clear time filter
            </button>
          ) : null}
        </div>
        <aside className="timeline-detail">
          <p className="eyebrow">Timeline detail</p>
          {detailSegment ? (
            <>
              <h3>{detailSegment.task_name}</h3>
              <div className="key-grid">
                <div>State</div>
                <div>{detailSegment.state}</div>
                <div>Duration</div>
                <div>{formatDuration(detailSegment.end_ts_ns - detailSegment.start_ts_ns)}</div>
                <div>Reason</div>
                <div>{detailSegment.reason ?? "n/a"}</div>
                <div>Resource</div>
                <div>{detailSegment.resource_id ?? "n/a"}</div>
                <div>Resource role</div>
                <div>{detailTask ? taskResourceRole(detailTask) ?? "n/a" : "n/a"}</div>
              </div>
              <div className="resource-block">
                <h3>Task timeline states</h3>
                <div className="reason-list">
                  {selectedTaskSegments.length ? (
                    selectedTaskSegments.map((segment, index) => (
                      <div key={`${segment.task_id}-${segment.start_ts_ns}-${index}`} className="reason-chip">
                        {segment.state} · {formatDuration(segment.end_ts_ns - segment.start_ts_ns)}
                      </div>
                    ))
                  ) : (
                    <div className="muted">Select a task to inspect its state intervals.</div>
                  )}
                </div>
              </div>
            </>
          ) : (
            <div className="empty">Hover a segment to inspect timing and wait metadata.</div>
          )}
        </aside>
      </div>
    </section>
  );
}
