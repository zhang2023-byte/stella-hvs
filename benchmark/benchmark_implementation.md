# Benchmark Implementation Status

This page records only current implementation state, decision-relevant
evidence, open risks, and the next gate. Scoring semantics belong in
[`SCORE_SPEC.md`](SCORE_SPEC.md), Gold review in
[`GUIDELINE.md`](GUIDELINE.md), lifecycle values in
`src/stella/schema_registry.py`, and executable procedures in the workflow and
operation catalogs.

## Current state

Stella 0.10.1 exposes the contribution-first benchmark through the unified
`benchmark` and `gold_annotation` workflows. `hvs-extraction-v6` remains the
active `evaluation_ready` campaign and supplies the fixed 50-paper order and
10/40 split. Candidate-era artifacts and scorecards are read-only history;
contribution evaluation uses its own schema, Gold selection, run provenance,
and scorecard.

The contribution contract is `literature_hvs_contributions` v1 with grouped
multivalue quantities. The approved rule profile now requires an explicit
Galactic-unbound anchor, classifies contributions from the current paper's
sample-entry path, preserves paper-local identifiers, and uses concise
scientific exclusions. Narrow peer review has been removed. Unambiguous stable
integer ranges use a transient `range_groups` submission that program code
expands into ordinary one-object contributions; neither canonical production
nor Gold persists the group.

The named `contribution-dev-primary-v2` selection binds the expert-approved,
re-reviewed dev10 Gold under the corrected rules and is the default for new
dev10 scoring. The 40-paper complement remains closed. There is no trusted current
contribution performance result yet.

## Decision-relevant evidence

- The rules and range implementation are preserved in Git commit `62ce3d9`.
- At that boundary, the complete test suite passed 760 tests with one skip, and
  generated schema/rule views had zero drift.
- The first contribution dev10 attempt does not establish model quality: its
  first run had an HTTP 401 transport failure, while later diagnostics exposed
  stage/canonical validation and partial-delivery defects.
- Candidate-era V6 scores measure a different scientific target and are not a
  baseline for contribution-first L1 or L2.

## Open risks

- Rule changes can improve apparent alignment by changing both extractor and
  Gold. Paper-level expert review must therefore remain independent and
  PDF-grounded.
- A formal score is meaningful only when the selected dev10 run froze the
  corrected rules and method, reached one-way finalization, and binds
  `contribution-dev-primary-v2` in the exact campaign order.
- Contribution selections are active-only. Any future Gold revision requires a
  new named selection before scoring; older selections are not runtime
  fallbacks.

## Next gate

1. Finish the active-only selection and Git-backed revision implementation
   checks while keeping the cross-session plan untracked.
2. Run a zero-write scoring preflight for the selected new-rules dev10 run and
   `contribution-dev-primary-v2`.
3. Only after a separate scoring grant, write the private item-level details
   and public layered scorecard.
4. Diagnose delivery, roster, boundness, and quantity layers separately.
5. Keep the 40-paper complement closed until dev10 evaluation is stable and a
   separate migration/review authorization is granted.
