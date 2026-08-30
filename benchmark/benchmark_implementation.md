# Benchmark Implementation Status

This page records only current implementation state, decision-relevant
evidence, open risks, and the next gate. Scoring semantics belong in
[`SCORE_SPEC.md`](SCORE_SPEC.md), Gold review in
[`GUIDELINE.md`](GUIDELINE.md), lifecycle values in
`src/stella/schema_registry.py`, and executable procedures in the workflow and
operation catalogs.

## Current state

Stella 0.11.2 exposes the contribution-first benchmark through the unified
`benchmark` and `gold_annotation` workflows. `hvs-extraction-v6` remains the
active `evaluation_ready` campaign and supplies the fixed 50-paper order and
10/40 split. Candidate-era artifacts and scorecards are read-only history;
contribution evaluation uses its own schema, Gold selection, run provenance,
and scorecard.

The three explicit profiles preserve that split: `dev10` is development,
`test40` is held-out evaluation, and separately authorized `full50` is a
complete-cohort regression profile. Selection publication accepts an exact
paper-to-expert map so mixed-expert cohorts never rely on filename inference.

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

All 50 original-V6 papers now have expert-approved contribution Gold v2 in the
private repository, committed as `35d8377`. The older dev selections target v1
and no v2 split selection has yet been published, so formal scoring remains
closed until the new selections bind the active hashes.
There is no trusted current contribution performance result yet.

The completed re-review preserved the batch authority boundary: Batch sessions
never stage, commit, push, or publish selections. A separate integration owner
performed the cohort audit and created one selective private commit.

## Decision-relevant evidence

- The current quantity-v2 rules, schemas, compatibility readers, and scoring
  target checks are preserved in Git commit `191d1ac`.
- At that boundary, the complete offline suite passed 833 tests, generated
  schema/rule views had zero drift, and both v1 schemas remained unchanged.
- The integrated 50-paper audit found one current-schema active JSON per paper,
  valid canaries, lint-clean content, exact retained-draft semantic agreement,
  complete PDF coverage, and retained ignored migration audit material.
- The first contribution dev10 attempt does not establish model quality: its
  first run had an HTTP 401 transport failure, while later diagnostics exposed
  stage/canonical validation and partial-delivery defects.
- Candidate-era V6 scores measure a different scientific target and are not a
  baseline for contribution-first L1 or L2.

## Open risks

- Rule changes can improve apparent alignment by changing both extractor and
  Gold. Paper-level expert review must therefore remain independent and
  PDF-grounded.
- A formal score is meaningful only when the run freezes the quantity-v2 rules
  and extraction schema, reaches one-way finalization, and binds a new
  same-split Gold-v2 selection in exact campaign order.
- Contribution selections are active-only. Any future Gold revision requires a
  new named selection before scoring; older selections are not runtime
  fallbacks.

## Next gate

1. Publish new write-once Gold-v2 selections for `dev10`, `test40`, and the
   complete `full50` regression profile using the explicit expert map.
2. Keep benchmark execution, one-way finalization, formal scoring, and any
   scorecard publication behind their separate authorities.
