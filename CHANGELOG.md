# Stella Changelog

The current version comes from `src/stella/schema_registry.py`. This file
records only user-visible behavior, compatibility changes, and validation
results. Git preserves the complete implementation history.

## 0.6.0 — 2026-07-19

- Method B now uses deterministic paper-first roster context: sorted TeX
  followed by declared ECSV inputs. Generated catalog JSON and bibliography are
  excluded only from the roster stage.
- Producer and reviewer independently discover the complete roster. A mismatch
  permits one same-reviewer reconciliation attempt, then the run seals or fails
  closed.
- An ECSV display label maps to a machine column only when there is one exact
  match.
- Each extractor and reviewer route freezes its exact provider,
  structured-output mode, and request overrides before run creation. The
  current DeepSeek and BigModel routes use forced typed `tool_submission`;
  thinking is disabled for the DeepSeek route.
- Missing, wrong, multiple, malformed, or schema-invalid tool calls enter only
  bounded correction. A run never changes provider, model, or mode midway.
- `benchmark.roster_bundle` advanced to version 3 and
  `benchmark.run_manifest` to version 4. Historical runs are not migrated.

Validation result: the first V4 post-engineering development run did not
establish an end-to-end improvement. Compared with the pre-engineering
baseline, valid delivery fell from 7/10 to 6/10, L1 micro F1 fell from 0.189 to
0.120, and strict L2 end-to-end delivery fell from 0.299 to 0.201. See
[`benchmark/README.md`](benchmark/README.md) for the current conclusion and next
gate.

## 0.5.1 — 2026-07-19

- Batch generation returns only ordered `record_id` anchors and candidate
  fields. After count, order, and anchor checks, code restores the complete
  identifier payload from the sealed roster.
- Initial fill, validator repair, and final-review repair use the same path.
- An exhausted batch retains rejection summaries and a non-empty failure
  reason.
- Historical responses, reports, manifests, seals, and scorecards remain
  immutable. Future experiments use a new run ID.

Offline replay showed that this general repair removed sealed-identifier
mismatches from parseable 1902 and 2401 responses, but it did not resolve the
scientific candidate boundary.

## 0.5.0 — 2026-07-18

- Method B with `core_prov` became the only active direct benchmark path.
- Method C and FULL enrichment became explicit legacy opt-ins. Dev Console
  history is read-only.
- Run-manifest version 3 separated CORE and enrichment delivery and checked
  component hashes before reading outputs.
- Roster-bundle version 2 added the reviewer provider to cache identity.
- V3 baseline and hardened-B public scorecards were preserved. The incomplete
  hardened-C run remained unsealed and unscored.

This release did not claim that the roster-review architecture had passed
scientific validation. The test split remained locked.

## Earlier versions

Migration and experiment details before 0.5.0 remain available in Git history,
the schema registry, historical artifacts, and scorecards. Stella no longer
maintains one Markdown file per release.
