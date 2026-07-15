# Benchmark Dev Console Paper Monitor Design

**Date:** 2026-07-15

## Goal

Turn the Dev Console run view into a paper-level monitor. New console runs use
whole-response LLM transport. The UI shows whether each paper is queued,
running, successful, or failed; failed papers expose the failing stage and a
concise error, with a drill-down backed by the existing per-paper report.

## Decisions

- New Dev Console requests default to `stream_responses: false`, and the setup
  UI no longer exposes a streaming switch. Ordinary benchmark CLIs keep their
  explicit `--stream-responses` option for compatibility.
- The run page polls the run summary. It does not subscribe to response deltas,
  reconstruct model transcripts, render workflow graphs, or hydrate response
  blobs.
- `RunSummary` owns a compact `paper_diagnostics` map. Completed papers are
  derived from canonical `report.json` files; active paper/stage state is
  augmented from the compact structural-event index when available.
- A paper-detail API returns the report plus structural events for that paper.
  It never returns private gold or scoring details.
- Existing run archives remain usable. Runs without a structural index still
  expose status and failure detail from their reports.

## Error presentation

The overview shows the report status as the error type, the inferred failing
stage, and a short message. The detail panel shows the ordered stage log,
validator errors, warnings, and the full recorded run error. No model reasoning
or token-by-token response is displayed.

## Compatibility and safety

The compatibility field remains in persisted requests, but the controller
normalizes it to `false`. The benchmark campaign, dev split, runner scripts,
and anti-contamination boundaries are unchanged. Broad historical resume is
not part of this monitor: manual group resume is limited to a paused group, and
historical repair is handled only by the separately validated external-failure
retry contract.
