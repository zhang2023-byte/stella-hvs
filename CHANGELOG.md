# Stella Changelog

The current version comes from `src/stella/schema_registry.py`. This file
records only user-visible behavior, compatibility changes, and validation
results. Git preserves the complete implementation history.

## Unreleased

- V6 became the only writable benchmark campaign while preserving V5's exact
  50-paper order, 10/40 split, sampling weights, public gold hashes, and expert
  assignment mapping. V1-V5 remain readable and immutable.
- Formal scorecards advanced to version 7 and now present L0 delivery and
  format validity, operational usage and estimated CNY cost, L1 identity, and
  L2 fields without a composite score. Run summaries/manifests advanced to
  versions 2/6 and seal normalized usage and L0 raw counts.
- Immutable TokenDance pricing snapshots and offline Decimal cost calculation
  were added. Missing route coverage fails preflight; incomplete usage is
  reported as partial or unavailable rather than zero.
- Terminal V6 extraction runs now automatically persist an immutable
  snapshot-bound `run_cost.json`. A deterministic generator recalculates and
  stores costs for the frozen set of 21 completed end-to-end legacy dev10 runs
  without modifying any read-only campaign.
- The first screenshot-backed snapshot records eight flat-priced current or
  comparison routes with provider-specific cache rates. MiniMax M3's two
  context tiers are retained as deferred metadata and cannot be used for cost
  calculation from aggregate usage.
- The transient development evaluator and its CLI were retired. Targeted runs
  now stop at the sealed run summary and manifest.
- The private static benchmark HTML renderer was retired. Formal scoring now
  stops at immutable public scorecards and private per-item details, which
  remain the read-only data boundary for future presentation layers.

## 0.7.0 — 2026-07-26

- The staged roster-plus-core-field engine became the canonical
  `hvs_candidate_extraction` workflow, and V5 became the only writable
  benchmark campaign.
- `literature_hvs_candidates` version 3 is core-first. Roster candidates remain
  available to L1 after field-stage failure; full fields and method-chain data
  moved to immutable optional supplements.
- V5 run config version 4 and run manifest version 5 freeze separate model
  roles, request policy, paper order, component hashes, delivery layers, and
  resource totals before scoring.
- `coding_agent_baseline` is the maintained independent comparison path.
- The pre-promotion experiments were preserved as a read-only hash-inventoried
  legacy campaign. The old direct writers and development console were retired.
- Formal evaluation is documented in `benchmark/SCORE_SPEC.md` as L1 and L2
  only. Supporting evidence remains mandatory but is not scored.
- Multiple experts can retain independent annotation twins for one paper. New
  formal scores require an immutable, public, value-free profile that selects
  one authorized expert per paper and records only paths and hashes.
- Public write-once assignment profiles now separate primary scoring roles and
  additional parallel annotations from private draft state. Expert queues list
  new, resumable, and completed work without reading gold content.

Validation result: the latest pre-promotion dev10 delivered 6/10 papers, with
L1 precision/recall/F1 of 0.941/0.681/0.790 and L2 coverage of 0.122. This does
not meet the stable-development gate; V5 remains test-not-ready.

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
