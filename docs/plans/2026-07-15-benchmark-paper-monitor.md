# Benchmark Paper Monitor Implementation Plan

> **Execution note:** implement in the existing worktree and preserve unrelated
> local edits.

**Goal:** Make future Dev Console runs non-streaming and replace the live model
trace UI with a paper status/error monitor.

**Architecture:** Keep runner artifacts and structural traces as the backend
source of truth. Poll a compact run summary for overview state, and fetch one
paper report on demand for stage/error detail. Do not load response deltas or
model blobs in the run page.

---

### Task 1: Lock the transport contract

- Update Python tests to expect non-streaming requests and runner commands.
- Change Dev Console request defaults and setup payloads to non-streaming.
- Update the workflow definition to describe whole-response transport.

### Task 2: Add paper diagnostics APIs

- Add tests for report-derived error summaries and paper detail.
- Extend run summaries with compact per-paper diagnostics.
- Add a read-only paper detail route backed by `report.json` and structural
  events, with existing path validation and no gold access.

### Task 3: Replace the run trace UI

- Add a RunPage test covering OK/failed rows, error summary, and drill-down.
- Render a paper monitor table and detail panel using summary polling.
- Remove transcript reconstruction, workflow graph rendering, and response-blob
  hydration from the run page.
- Remove the unused graph dependency and obsolete components/hooks.

### Task 4: Verify and rebuild

- Run focused Python and React tests, then the relevant full suites.
- Build the React production bundle under the committed asset path.
- Open the local console on a disposable port and visually verify the paper
  overview and failure detail using existing runs.
