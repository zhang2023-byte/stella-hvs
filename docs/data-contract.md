# Stella Data and Version Contract

This document owns artifact paths, mutability, privacy, lifecycle, and version
boundaries. Commands belong to the workflow catalogs and exact fields belong to
Pydantic models. Current versions and lifecycle states come only from
[`src/stella/schema_registry.py`](../src/stella/schema_registry.py);
[`versions.md`](versions.md) is its generated view.

## 1. Data roles

- **Canonical record:** maintained source for downstream products. Only its
  owning operation or an explicitly approved editing workflow may update it.
- **Derived product:** reproducibly rebuilt from canonical records or archived
  inputs. Fix the builder or upstream source, not the generated file.
- **Reading view:** human-facing Markdown or HTML, never scientific authority.
- **Private artifact:** data that must remain outside this public workspace and
  public Git history.
- **Historical artifact:** immutable evidence retained for old releases or
  scientific targets; current writers never modify it.

JSON is an interchange format, not permission for manual editing.

## 2. Current data flow

```text
monthly literature record
  -> archived paper assets and provenance
  -> catalog_assessment.json
  -> catalog_review.json
  -> catalog_extraction.json and ECSV tables
  -> literature_hvs_contributions.json
  -> contribution index and object timelines
  -> optional dynamics from an explicit input selection
  -> pages/contributions/
```

The benchmark is isolated:

```text
paper PDF -> private annotator draft -> expert-approved private Gold JSON
private Gold hashes -> public, value-free, immutable selection
archived paper inputs -> ignored immutable benchmark run
finalized run + selected Gold hashes -> public aggregate scorecard + private details
```

Gold annotation and production extraction may not share contexts or data paths.
See [`../benchmark/AGENTS.md`](../benchmark/AGENTS.md) and
[`../benchmark/GUIDELINE.md`](../benchmark/GUIDELINE.md).

## 3. Literature, contributions, and derived views

| Path | Role | Mutation rule |
|---|---|---|
| `notes/YYYY/YYYY-MM/YYYY-MM.json` | Canonical monthly literature record | Written by the literature workflow; reading views are regenerated |
| `literature/<paper_id>/assets/` and `arxiv.pdf` | Archived paper input | Written by archive operations; ignored by default |
| `literature/<paper_id>/audit.json` | Asset/provenance audit | Written by archive and metadata operations |
| `literature/<paper_id>/catalog_assessment.json` | Canonical data-asset assessment | Validated operation output |
| `literature/<paper_id>/catalog_review.json` | Canonical reviewed extraction plan | Validated operation output |
| `literature/<paper_id>/catalog_extraction.json` and `<table>.ecsv` | Table extraction record and faithful tables | Deterministically regenerated from archived sources and review |
| `literature/<paper_id>/literature_hvs_contributions.json` | Canonical `literature_hvs_contributions` v1 paper/object record | Written by `literature.extract_contributions`; replacement requires `supersede` authority |
| `literature/hvs_contributions_index.json` | Derived contribution index | Rebuilt by `literature.build_contribution_index` |
| `literature/hvs_contribution_catalog/` | Derived object timelines | Rebuilt by `literature.build_object_timelines`; never asserts one global boundness state |
| `literature/hvs_dynamics_input_selection.json` | Explicit human-approved dynamics input snapshot | Must hash and justify every selected scientific input |
| `literature/hvs_dynamics_results/` | Derived dynamics results | Rebuilt only from a valid input selection and canonical contributions |
| `pages/contributions/` | Generated contribution site | Rebuilt by `web.build_contribution_site`; committable deployment view |

`literature_hvs_candidates`, candidate catalog schemas, and the frozen
candidate site under `pages/` are read-only historical surfaces. Current
operations do not regenerate or reinterpret them.

## 4. Contribution evidence and identity

The canonical unit is one current-paper/object contribution. Production
evidence points into the frozen current-paper TeX/source graph and, where
available, exact converted ECSV cells. Gold uses PDF locators. The evidence
representations differ, but the scientific target is shared and remains
paper-local.

Identifiers are paper-visible unordered sets. External aliases, preferred-name
selection, and model-completed Gaia prefixes are derived concerns and do not
enter the canonical contribution. A transient production `range_groups`
submission may be deterministically expanded, but canonical production and Gold
store only ordinary one-object contributions.

## 5. Benchmark artifacts

| Path | Role | Mutation rule |
|---|---|---|
| `benchmark/campaigns/<id>/manifest/` | Public campaign, sample, assignment, and historical hash records | Immutable after the owning builder freezes them |
| `$STELLA_GOLD_WORK_DIR/<paper_id>/draft_<expert>.json` | Private work state | Never scoring input; removed or retained only by the approved workflow |
| `$STELLA_GOLD_DIR/<paper_id>/annotation_<expert>.json` | Canonical private contribution Gold | First write follows validation and paper-level approval; a selected contribution revision additionally needs `supersede`, retained migration audit, base-selection, and exact-current-SHA pins |
| `<private-gold-repo>/legacy-v6/` | Preserved original-V6 Gold | Written only by the explicit transactional supersede path; never an active fallback |
| `<private-gold-repo>/contribution-history/objects/<sha256>.json` | Exact prior contribution JSON bytes | Private tracked, content-addressed, write-once preservation used only to resolve an immutable contribution selection by the same SHA |
| `<private-gold-repo>/contribution-history/receipts/<sha256>.json` | Minimal private revision provenance | Private tracked, content-addressed operational metadata; not Gold, not selected, and not a versioned artifact contract |
| `$STELLA_GOLD_WORK_DIR/<paper_id>/locks/` | Transient contribution-revision lock | Must be inside the private repository and verified by `git check-ignore`; removed after the transaction |
| `benchmark/gold_selections/<selection_id>.json` | Public, value-free contribution Gold selection | Named, hash-pinned, and write-once |
| `runs/benchmark/<run_id>/` | Ignored current benchmark audit root | Freezes the request, appends attempts/events, and finalizes one-way |
| `runs/benchmark/<run_id>/scoring/scored_run.json` | Value-free scored-run aggregate | Written once after private hash verification |
| `benchmark/scorecards/<run_id>.json` | Public layered contribution scorecard | Written once; aggregates and hashes only |
| `$STELLA_GOLD_DIR/../scoring-details/` | Private item-level comparisons | External only; never commit |

The unified `benchmark` workflow owns prepare, method freeze, execution, resume,
finalize, scoring, and scorecard emission. The `gold_annotation` workflow owns
queue, PDF draft, validation, save, and public selection. Their operations and
authority gates are declared in `workflows/operations.yaml` and
`workflows/stella_workflows.yaml`.

An immutable contribution selection resolves its declared paper, expert,
filename, and SHA from the active canonical path while those bytes still
match. After a controlled revision it may resolve only the same SHA from the
private content-addressed contribution history. History and receipts sit
outside the active Gold root, remain trackable preservation state, are not
scanned while preparing a selection or legacy inventory, and never authorize a
different annotation. Revision preserves the complete existing `legacy-v6`
paper directory byte-for-byte, locks and checks the base SHA twice, atomically
replaces the canonical file with file and directory fsync, and restores the
exact historical bytes if any post-replacement step fails. Revision enumerates
the retained paper audit before history or canonical writes and never cleans it
after replacement.

Historical candidate-era campaign runs, debug containers, releases, pricing
snapshots, supplements, scorecards, and scratch inventories under
`benchmark/campaigns/` remain readable and immutable. They are not current
execution routes, Gold fallbacks, or contribution score baselines.

## 6. Local state and Git

`runs/`, `logs/`, raw paper assets, private Gold, migration work, and private
scoring details are local or external evidence and must not enter public Git.
Cross-session plans are temporary, stay untracked, and are deleted at delivery.

| Category | Default Git behavior |
|---|---|
| Source, schemas, workflows, tests, and allowlisted permanent documentation | Commit |
| Validated paper-level canonical records permitted by repository policy | May commit |
| Campaign manifests and public scorecards | Commit only after the owning workflow writes them |
| `pages/` | Committable generated deployment snapshot |
| `runs/`, `logs/`, raw assets, temporary plans | Ignore or leave untracked |
| Expert Gold and private details | External repository only |

Never use force-add to cross these boundaries without an explicit policy change.

## 7. Three version axes

Stella has three independent identifiers:

1. **Stella release:** human-facing SemVer.
2. **Artifact schema:** a positive integer scoped to one artifact name.
3. **Benchmark campaign ID:** a frozen cohort and evaluation contract.

Models, prompts, providers, runtimes, rules, and context packers are identified
by Git state, component hashes, and method fingerprints rather than another
manual version sequence.

### Stella release

- PATCH: fixes, tests, documentation, performance work, and internal refactors
  that do not change a persisted contract or required user behavior.
- MINOR: new capability, workflow, artifact, schema, or pre-1.0 breaking
  behavior.
- MAJOR: incompatible public API, CLI, workflow, or persistence behavior after
  1.0.

Release history belongs in [`../CHANGELOG.md`](../CHANGELOG.md).

### Artifact schema

Increment an Artifact schema when fields, types, requiredness, units, ranges,
defaults, enumerations, containers, identity, or scientific meaning change.
Documentation, rendering, error text, prompt wording, and provenance-only
changes do not increment it.

Every `N -> N+1` transition must:

1. register the new model and retain required old readers;
2. make the normal writer emit N+1 only;
3. route readers through the registry;
4. provide an explicit, idempotent, atomic migration and value-free audit;
5. validate before and after migration;
6. test unknown versions, dry runs, repeats, and partial failure; and
7. regenerate contract views and [`versions.md`](versions.md).

### Benchmark campaign

A new cohort or split requires a new campaign. A changed scientific target may
reuse a cohort only with explicit approval and separate schemas, Gold
selections, method fingerprints, and scorecards. Within one target, changed
Gold protocol, scored fields, matching/aggregation semantics, contamination
controls, release rules, or evidence rules require a new target version or
campaign. Changed implementation produces a new immutable run ID. For one
frozen target, a frozen campaign accepts no new formal runs after one-way
closure.

## 8. Corrections and update triggers

Never overwrite a published scorecard. A result-neutral implementation repair
uses new scorer provenance; a result-changing defect invalidates or supersedes
the old record. Changed scoring semantics require a new target or campaign.

Update the owning surface only:

- workflow behavior or authority -> workflow/operation catalogs;
- artifact path, privacy, lifecycle, or version boundary -> this document;
- CLI usage -> [`guide.md`](guide.md);
- durable design decision -> [`decisions.md`](decisions.md);
- release history -> [`../CHANGELOG.md`](../CHANGELOG.md);
- benchmark status ->
  [`../benchmark/benchmark_implementation.md`](../benchmark/benchmark_implementation.md);
- scoring semantics -> [`../benchmark/SCORE_SPEC.md`](../benchmark/SCORE_SPEC.md).
