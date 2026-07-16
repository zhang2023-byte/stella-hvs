# ADR 0007: V3 campaign provenance and append-only evaluation

- Status: Accepted
- Date: 2026-07-16

## Context

The corrected B/C development evaluation exposed an infrastructure problem
separate from scientific model behavior: a run could be sealed or scored after
validator, normalization, matching, unit, or scorer code had drifted from the
hashes recorded when the run was created. Published scorecards also needed an
explicit immutable evaluation identity.

The next architecture work will later separate the formal CORE product from
FULL enrichment and add a bounded pre-seal roster review. Those behavior
changes must not be mixed into the pre-change baseline.

## Decision

1. `hvs-extraction-v3` is the only active, writable campaign. V1 and V2 remain
   readable history and reject new formal run creation.
2. V3 inherits the exact V2 50-paper order and fixed 10 dev / 40 test split. It
   is not resampled.
3. A formal run records hashes for every component that can affect its sealed
   product, including validator, task surface, representation normalizer,
   scorer, identity matching, unit table, prompt, skill, context packer, and
   rule profiles. Seal and scoring compare those hashes with current code and
   fail closed before reading paper outputs or private gold when they differ.
4. Gold manifests are append-only: a new paper may be added, but an existing
   paper may not be removed or acquire a different recorded hash.
5. Public scorecards are append-only by evaluation label. A correction creates
   a new label and may record `supersedes`; it never overwrites the old file.
6. The first V3 B CORE and C CORE runs are pre-change baselines. Roster-review
   behavior, CORE/FULL isolation, and later architecture changes wait until
   those baselines and their provenance are frozen.

## Consequences

- Stella advances to 0.4.0 with current schemas `benchmark.run_config` v3,
  `benchmark.run_manifest` v2, `benchmark.roster_bundle` v2, and
  `benchmark.scorecard` v4. Older registered versions remain readable but are
  not emitted by normal writers.
- `literature_hvs_candidates` stays at v2; no candidate field, scientific
  eligibility rule, value, unit, or evidence behavior changes in this phase.
- The V3 public sampling and campaign manifests can be prepared without private
  gold. Initializing the real V3 gold snapshot and running/scoring baselines are
  separate authorization checkpoints.
