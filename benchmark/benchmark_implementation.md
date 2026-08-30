# Benchmark Implementation Status

This page records only current implementation state, decision-relevant
evidence, open risks, and the next gate. Scoring semantics belong in
[`SCORE_SPEC.md`](SCORE_SPEC.md), Gold review in
[`GUIDELINE.md`](GUIDELINE.md), lifecycle values in
`src/stella/schema_registry.py`, and executable procedures in the workflow and
operation catalogs.

## Current state

Stella 0.11.0 exposes the contribution-first benchmark through the unified
`benchmark` and `gold_annotation` workflows. `hvs-extraction-v6` remains the
active `evaluation_ready` campaign and supplies the fixed 50-paper order and
10/40 split. Candidate-era artifacts and scorecards are read-only history;
contribution evaluation uses its own schema, Gold selection, run provenance,
and scorecard.

Benchmark extraction now freezes one profile-independent execution policy:
ten paper workers, up to fifty quantity-candidate workers per paper, and an
exact workspace-shared 400 RPM rolling provider limit with 429-driven
downshift. Quantity failures are isolated and resume at candidate granularity;
deterministic roster order and successful candidate bytes are preserved.

The current contribution contract is `literature_hvs_contributions` v2 with
grouped multivalue quantities; v1 remains readable history. The approved rule
profile now requires an explicit
Galactic-unbound anchor, classifies contributions from the current paper's
sample-entry path, preserves paper-local identifiers, and uses concise
scientific exclusions. Narrow peer review has been removed. Unambiguous stable
integer ranges use a transient `range_groups` submission that program code
expands into ordinary one-object contributions; neither canonical production
nor Gold persists the group.

The named `contribution-dev-primary-v2` selection binds the expert-approved,
re-reviewed dev10 Gold under the corrected rules and is the default for new
dev10 scoring. The 40-paper complement currently has only its frozen legacy V6
annotations: contribution migration has not started and no contribution test40
selection exists. Its migration is now approved as four disjoint ten-paper
batches under the original-50 exception. There is no trusted current
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

1. Run four disjoint ten-paper test40 migration sessions. For every paper,
   isolate clean PDF-only preannotation from a separate reconciliation that
   reads only that draft and the frozen legacy annotation.
2. Retain paper-scoped migration work, report title-bearing differences to the
   expert, and save only paper-level approved drafts. Distinct paper paths may
   save concurrently, but batch sessions do not stage, commit, push, or publish
   a selection.
3. After all four batches, one integration owner audits the exact 40-paper
   path set, validates every canonical and legacy archive, and owns the private
   commit and separate value-free contribution test40 selection.
4. Any contribution test40 run or score remains behind new, explicit network,
   LLM, private-Gold, scoring, and publication gates.
