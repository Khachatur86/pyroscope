# Tasks

## Next Up

- Stabilize the event/session contract from the current MVP shape into a clearer replay-safe schema with explicit compatibility rules and fixture coverage for forward/backward reads.
- Deepen cancellation analysis so timeout, sibling-failure, parent-task, external, and mixed-cause cascades produce more precise summaries instead of relying on mostly heuristic grouping.
- Expand timeline interaction coverage beyond the current hover smoke path with tests for selection changes, filtered views, and resource/cancellation drilldown coordination.
- Add a search-first task query flow to the API/UI so large captures can be narrowed by task name, exception text, request label, or job label without manual filter combinations.
- Add richer headless compare output for changed states, hot tasks, request labels, and job labels so regression review is useful without opening the UI.

## In Progress

- Move the internal event model toward a more stable contract for replay, exports, and UI consumers.
- Improve cancellation analysis beyond the current TaskGroup and grouped-cascade heuristics.

## Soon

- Add explicit session metadata support for captured script path, module name, command line, and Python version so saved captures carry more debugging context.
- Introduce replay contract tests for cross-session schema drift, including missing optional fields and future additive metadata.
- Add stack-aware error summaries to headless `summary` and `compare` output so failed captures expose the top exception context immediately.
- Add task-detail API coverage for request/job label filtering plus `q` search behavior on mixed captures.
- Improve resource graph drilldown to distinguish owners, waiters, and cancelled waiters instead of only listing task ids per resource.

## Later

- Add a lightweight "teaching mode" that overlays common asyncio patterns and explains why a queue, lock, semaphore, or gather shape looks suspicious.
- Add timeline zoom and windowing for longer captures so the canvas remains usable when sessions have thousands of segments.
- Add capture diff fixtures for service-style workloads with multiple request labels and overlapping jobs.
- Support optional session tags or run notes on saved captures for local incident comparison workflows.
- Add richer export formats for downstream analysis, such as flattened task JSONL and resource-wait summaries.

## Bugs / Technical Debt

- Runtime instrumentation is useful but still partial relative to full `asyncio` behavior, especially around less common primitives and edge-case scheduling paths.
- The UI currently fetches the full snapshot eagerly; larger captures will eventually need incremental loading and stronger server-side pagination usage.
- Built frontend assets are committed into `src/pyroscope/web_dist`, which is practical today but creates churn and review noise.
- The current test matrix splits Python and frontend flows cleanly, but there is still no end-to-end check that exercises packaged static assets through the local server.
- Headless summaries and UI drilldowns share concepts but not a single presentation contract yet, which raises the risk of subtle output drift.

## Future Ideas

- Add request-centric and job-centric dashboards that collapse task noise into higher-level local service flows.
- Add watch mode for replay comparison so a saved baseline can be contrasted automatically against a newly captured run.
- Add fixture minimization tooling that trims large captures into the smallest reproducible regression artifact.
- Add optional OpenTelemetry-style span export for cross-tool inspection while keeping the local session model as the source of truth.
- Add a "why is this task blocked?" explainer that walks parent links, blocking reason, resource ownership, and cancellation history in one pane.
