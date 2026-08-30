# Stella Changelog

The current version comes from `src/stella/schema_registry.py`. This file
records only user-visible behavior, compatibility changes, and validation
results. Git preserves the complete implementation history.

## 0.11.0

- Versioned the current contribution and contribution-Gold contracts to v2
  while keeping v1 readable. The structured scope now has eighteen quantities:
  Galactocentric tangential velocity is unstructured, current/reference-state
  frame boundaries are explicit, Galactocentric radius is three-dimensional,
  and conditions cannot admit otherwise ineligible values.

## 0.10.1

Repair release for the 0.10 architecture refactor, from the Codex acceptance
review:

- Unified benchmark execution across dev10 and full50 at ten concurrent papers
  with up to fifty concurrent quantity candidates per paper. All workers share
  an exact 400 RPM rolling limiter, adapt downward on provider 429 responses,
  honor longer `Retry-After` delays, preserve deterministic roster order, and
  resume only retryable failed candidates without rewriting successful ones.

- Simplified contribution benchmark reporting to three quality layers: L0
  delivery, L1 contribution-object identification, and L2 quantity
  completeness/accuracy. Removed the separate delivery output and lettered
  sublayers; contribution type and paper-boundness claim agreement remain
  diagnostics. New scorecards and private scoring details use v2 while
  immutable v1 artifacts remain readable. V2 now has one strict generated
  schema, separates missing from schema-invalid documents, exposes value-free
  summary/evidence presence diagnostics, and binds exact input, score-spec,
  target-schema, and scorer hashes.

- Tightened contribution eligibility to explicit paper-supported Galactic
  unbound or escaping claims (including paper-defined applied criteria); an
  HVS or hypervelocity label qualifies only when the paper explicitly defines
  that class as Galactic-unbound and applies it to the object or identifiable
  group. Labels alone and model-chosen probability thresholds are not proxies.
- Classified `candidates_found` and `follow_up` by the current paper's
  sample-entry path, while keeping substantive follow-up contributions even
  when boundness is rejected or not reassessed.
- Restored deterministic compressed-identifier expansion as a transient,
  strictly validated roster helper. Canonical contribution and Gold identity
  schemas remain unchanged, and non-enumerable remainders become one reviewed
  exclusion.
- Reorganized the unchanged nineteen-quantity scientific scope into focused
  coordinate, velocity, probability, uncertainty, group-value, evidence,
  authority, preference, and provenance rules.

- Activated the frozen original V6 50-paper sample as the contribution
  benchmark cohort. Dev10 uses a named, immutable, JSON-only contribution Gold
  selection; full50 remains closed until the other 40 annotations are migrated.
  Candidate-era scores remain a separate target and are never compared as the
  same metric.
- Replaced the single global contribution Gold selection path with named
  write-once profiles under `benchmark/gold_selections/`, so dev10 and full50
  can bind independent exact annotation hashes.
- Added a fail-closed correction branch to the existing contribution Gold save
  operation. It binds the exact active SHA under an ignored paper lock,
  requires the migration audit to remain retained, requires the active
  canonical to match private Git `HEAD`, atomically replaces or restores from
  a transient ignored rollback backup, and leaves `legacy-v6` untouched.
  Private Git is the only durable revision history; contribution selections
  resolve active canonical bytes only, and dev10 defaults to the
  expert-approved `contribution-dev-primary-v2`.

- Completed the acceptance follow-up: existing benchmark runs are selectable
  by `run_id`; dev10 resolves before execution; resume performs a real
  per-paper retry; benchmark extraction stays inside the single outer run;
  partial status, finalization, selected-Gold hashes, and write-once scoring
  are enforced end to end.
- Added the loopback-only interactive Gold form CLI, request-carried expert
  approval, write-once private JSON annotations, and correct per-paper hashes
  in the immutable value-free selection.
- Existing assessment, review, and extraction artifacts now pass their full
  Pydantic contracts rather than JSON parsing alone; candidate-era schemas,
  catalogs, and sites are explicitly read-only legacy products.
- The two workflow catalogs are mechanically truthful: every callable,
  validator, model, contract path, and test path resolves (enforced by
  `tests/test_operation_catalog_integrity.py`), and the runtime validates
  each operation result against its declared output model and runs the
  declared validators - no declaration is decorative.
- All three workflows execute real maintained implementations behind
  injected fakes: literature discovery/assessment/review/extraction run
  their library implementations, the gold form writes one JSON annotation
  per paper and expert (no YAML twin), and the benchmark lifecycle
  (prepare/freeze/execute/resume/finalize/score) runs end to end with one
  run id.
- One fresh worker process owns each paper's ordered operation chain;
  run state is persisted (active/partial/complete/failed/network_failed);
  transport failures classify as resumable `network_failed` while
  scientific failures stay terminal.
- Production provider transport is a maintained gateway client built from
  the frozen method; transcript replay is explicit test injection through
  a session file, never a scientific request field.
- Contribution dynamics write `literature/hvs_dynamics_results/` as
  declared and never mutate contribution object JSON; the legacy candidate
  calculator is read-only and candidate schema views shrink to the
  persisted v1 boundary.
- Restored the maintained library tests deleted by the refactor (101
  tests across ADS repair, catalog assessment/review/extraction,
  literature assets, LLM batching, schema templates, and the extraction
  internals) and replaced every false-green expectation.

## 0.10.0

- Rebuilt Stella as a contribution-first, workflow-led system: four business
  packages (`benchmark`, `dyn`, `lit`, `web`), a unified `python -m stella`
  CLI, and exactly three public product workflows (`literature_pipeline`,
  `gold_annotation`, `benchmark`) resolved from two YAML catalogs.
- Moved contribution extraction into `src/stella/lit/extraction/`, made
  `lit` independent of `benchmark`/`dyn`/`web`, and centralized scientific
  rules under `contracts/` with generated structural schema views.
- Removed the retired execution surfaces: `src/stella/hvs_extraction/`,
  `src/stella/hvs_contribution_extraction/`, `scripts/`, `skills/`, and
  `workflows/definitions/`. Historical V6 artifacts stay readable through
  read-only adapters; no retired writer survives.
- Introduced explicit, fail-closed authority gates (`--execute` never grants
  network/LLM/Gold/scoring/supersede/publication), frozen append-only run
  directories with per-paper worker isolation, bounded adaptive concurrency,
  resumable runs, and one-way finalize.
- Rebuilt contribution gold annotation as PDF-only, annotator-isolated, one
  JSON per paper and expert, with a value-free public selection and separate
  L0/operations/L1/L2 scoring without composite or pass/fail results.
- No real workflow, model call, gold access, or benchmark run was executed
  during this refactor; acceptance is offline with fake transports.

## 0.9.0

- Added the parallel, pre-campaign contribution-first HVS contract
  (`literature_hvs_contributions` v1): paper-object contribution records with
  candidates_found/follow_up typing, a five-value paper-reported
  `paper_boundness.status`, mandatory notes and evidence, and grouped
  multivalue measurements over the same 19 fields with explicit
  `paper_preferred` and scalar `source` provenance.
- Added the `hvs_contribution_extraction` local runner (preflight by default,
  explicit authority for real calls), immutable non-formal runs under the
  ignored `runs/hvs-contribution-extraction` root, timeline catalogs and web
  views, a one-time AI-assisted migration workflow for the original 50 gold
  papers with independent PDF-only preannotation, legacy-note reconciliation,
  paper-level expert approval, and cleanup of temporary work artifacts, a
  pre-campaign layered scorer, and explicit dynamics input
  selection that fingerprints every consumed field and fails closed when
  missing or stale. Contribution runs are confined to their fixed ignored
  root, gold keeps required nullable preferences, and identity matching vetoes
  conflicting Gaia ids while using only unambiguous coordinate facets.
- V6 public manifests, runs, scorecards, rules, and the active campaign remain
  historical and unchanged. Private working gold may be overwritten only after
  a clean pre-migration commit or tag; contribution scores require a distinct
  future campaign and unseen evaluation gold.

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
- Cost formula 1.1 prices time-tiered routes from each physical request's
  timezone-aware start time, reports peak/off-peak subtotals, and fails closed
  when request timing is unavailable instead of silently applying peak rates.
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
