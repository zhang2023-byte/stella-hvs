# B-core Primary and Legacy Boundary Design

## Goal

Establish one clean, auditable Stella 0.5.0 starting point before further
Method B debugging: B with `core_prov` is the only actively created direct
benchmark method, while Method C and FULL remain readable legacy interfaces
without being selectable by accident.

## Decision boundary

- New formal and regression experiments created through the dev console use
  Method B with `core_prov` only.
- Direct Method B/C CLIs retain legacy implementation paths, but Method C and
  FULL require explicit legacy opt-in flags. These flags exist for historical
  reproduction and deliberate future extension; agents must not use them
  without a new decision and explicit LLM authority.
- Existing Method C runs stay readable. The incomplete
  `v3-dev-hardened-c-core-r1` run remains an unsealed local diagnostic and is
  not resumed, sealed, scored, or published.
- FULL remains a readable generation surface and private diagnostic-analysis
  input. It is not a formal product and is removed from active GUI creation.
- Method A is unchanged and remains governed by its isolated harness plan.

## Data and provenance handling

- Preserve the raw Kimi export under ignored `notes/` rather than leaving it
  at the repository root, where it would block formal clean-worktree checks.
- Restore the already-produced public hardened-B scorecard from ignored local
  backup to its canonical campaign scoring path. Verify its hash/provenance
  against the sealed run before deleting the redundant backup.
- Do not copy private gold values, scoring details, or run request/response
  payloads into tracked files. Documentation may record only aggregate public
  scorecard results and delivery status.
- Preserve every run directory. Repository cleanup never deletes or rewrites a
  sealed run, and never mutates the paused Method C run.

## Contract hardening

The cleanup also closes mechanical audit gaps already identified in the
pre-seal roster contract:

- reviewer provider/route becomes part of the roster cache identity and review
  provenance;
- a `revise` verdict requires at least one recorded challenge;
- roster `record_id` values must be contiguous and ordered;
- mechanical-normalization findings report the canonical nested quantity path;
- current run-manifest documentation says v3, not v2.

These changes do not alter the campaign, gold judgments, scored vocabulary, or
artifact schema. New runs receive new component hashes and cold caches; old
run artifacts remain readable.

## User and UI behavior

The dev console continues to inspect historical B/C and FULL runs, but new
experiment cards expose only B-core. Paused or failed Method C runs are
read-only and cannot be resumed or retried through the console. Backend checks
enforce the same policy so an old browser bundle or crafted request cannot
bypass it.

## Release and verification

Stella 0.5.0 is not tagged or pushed yet, so this cleanup remains inside that
unreleased minor-version boundary. Release notes document the run-manifest v3
change, B-core default, legacy opt-ins, and the no-migration rule for immutable
historical runs. Completion requires targeted Python and frontend tests, the
full Python suite, frontend tests/build, generated rule/schema checks, data
hash verification, contamination tests, and a clean selective commit. The
40-paper test split remains sealed.
