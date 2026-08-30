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

All 50 original-V6 papers now have expert-approved contribution Gold v1 in the
private repository. The named `contribution-dev-primary-v2` selection still
targets v1 and matches the current dev10 annotations; no contribution test40
selection exists. The quantity-v2 boundary therefore closes both splits to new
formal scoring until their active annotations are PDF-re-reviewed, revised to
Gold v2, and bound to new selections. There is no trusted current contribution
performance result yet.

## Decision-relevant evidence

- The current quantity-v2 rules, schemas, compatibility readers, and scoring
  target checks are preserved in Git commit `191d1ac`.
- At that boundary, the complete offline suite passed 833 tests, generated
  schema/rule views had zero drift, and both v1 schemas remained unchanged.
- A read-only 50-paper preflight found one valid active JSON per paper, exact
  private-HEAD byte agreement, complete PDF coverage, and retained migration
  audit material; all active annotations are still Gold v1.
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

1. Run five disjoint ten-paper read-only review sessions: dev10 plus the four
   campaign-ordered test40 groups. Use fresh one-paper workers with at most
   three concurrent workers per parent session.
2. Review every structured value against the current PDF and quantity-v2 rules,
   consolidate one title-bearing batch report, and stop for expert decisions
   before any canonical write.
3. After batch approval, each parent uses the controlled revision transaction
   only on its assigned papers. Batch sessions never stage, commit, push, or
   publish a selection.
4. After all five batches, one new integration session verifies all 50 Gold-v2
   canonicals, audits the exact changed path set, and creates one selective
   private commit covering the complete cohort. Separate value-free dev10 and
   test40 selections, benchmark execution, scoring, and push remain separately
   authorized gates.
