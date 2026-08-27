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

The named `contribution-dev-primary-v1` selection exists, but the migrated dev10
Gold is being re-reviewed against the corrected rules before another formal
evaluation. The 40-paper complement remains closed. There is no trusted current
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

- The migrated dev10 Gold was created while the roster rules were incomplete;
  it may contain inclusion, type, identity, exclusion, or range-expansion
  errors.
- Rule changes can improve apparent alignment by changing both extractor and
  Gold. Paper-level expert review must therefore remain independent and
  PDF-grounded.
- Group/table conclusions and compressed identifiers are scientifically valid
  only when every resulting object is individually identifiable and all members
  share the approved Galactic-unbound basis.
- Provider authentication and transport must pass a separate network gate
  before a new real run can be interpreted scientifically.

## Next gate

1. Finish this documentation/schema consistency audit and commit the formal
   repository changes while keeping the cross-session plan untracked.
2. Run a zero-write dev10 Gold preflight. Do not read or modify private Gold
   until the user separately grants `gold_private` authority.
3. Re-review each dev10 paper from its PDF, obtain paper-level expert approval,
   preserve the legacy hashes, and create a new immutable Gold selection.
4. Only after separate network, LLM, private-Gold, scoring, and publication
   grants, run and score a new dev10 extraction.
5. Migrate and review the 40-paper complement only after dev10 rules and Gold
   are stable.
