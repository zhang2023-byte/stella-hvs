# Benchmark live node monitor

## Goal

Keep the compact paper-level result monitor while restoring the useful part of
the earlier workflow graph: a live, clickable view of which stage is running and
what kind of work is happening inside it.

## Data boundary

The monitor reads only the existing bounded `structural-events.jsonl` view
returned by the paper-detail endpoint. It does not load raw response deltas,
reconstruct model replies, or expose hidden reasoning. The open paper detail is
refreshed every three seconds, matching the run-summary polling interval.

## Interaction

Method B and Method C have separate stage maps. Completed stages are green,
failed stages are red, queued stages are neutral, and the current stage uses a
small pulse and animated connector. Selecting a node opens its description,
call totals, and compact step record.

Repeated work is represented as step segments rather than an event dump. A
consecutive run of the same semantic step becomes `step name × N`; a change of
step starts a new segment, so later non-consecutive occurrences remain in their
original execution position. This applies to model calls, tools, validation,
repair, retry, and system steps. Paired completion events update the originating
step status and do not create duplicate rows.

## Compatibility

Historical runs with sparse structural events still receive a useful graph from
their canonical paper status and failing stage. Existing report errors,
validator root-cause groups, warnings, transport evidence, and retry rules stay
unchanged. Reduced-motion browser preferences disable the live animations.

## Verification

Component tests cover Method C stage status and the distinction between
consecutive and non-consecutive repetitions. Run-page integration tests confirm
that the graph appears only after opening a paper. Production build output is
regenerated and the live regression group is used for a read-only visual check.
