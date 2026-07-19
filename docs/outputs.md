# Artifact and Data Ownership

This page is the human-readable map of Stella artifacts: where they live, who
owns them, whether they are canonical or derived, and whether they may enter
Git. It is not a workflow command reference and it does not duplicate complete
schema field definitions.

Use [`workflows/stella_workflows.yaml`](../workflows/stella_workflows.yaml) and
the selected file under
[`workflows/definitions/`](../workflows/definitions/) for execution. Use the
Pydantic models, validators, and generated schema references for exact field
shape. Current versions and lifecycle states come from
[`src/stella/schema_registry.py`](../src/stella/schema_registry.py) and the
generated [`docs/versions.md`](versions.md).

## Ownership Terms

- **Canonical record**: the maintained source for downstream Stella products.
  Update it only through its owning workflow, schema, or validated editing
  process.
- **Derived product**: machine-readable data rebuilt from canonical records or
  archived inputs. Fix the upstream source or builder rather than patching it.
- **Reading view**: Markdown or HTML generated for people. Never treat it as a
  data source.
- **Private artifact**: data that must remain outside the public workspace.

JSON is the preferred machine-readable interchange format, but not every JSON
file is canonical or hand-editable. Indexes, object catalogs, scorecards, and
many manifests are derived products with an owning builder.

## Main Data Flow

```text
monthly literature JSON
  -> archived paper assets and audit metadata
  -> catalog_review.json
  -> catalog_extraction.json and ECSV tables
  -> literature_hvs_candidates.json
  -> object-level catalog/candidates/*.json
  -> embedded dynamics
  -> local web catalog
  -> committable Pages snapshot
```

The benchmark is an isolated branch of this flow:

```text
paper PDF -> expert-led gold in external private repository
paper-local literature inputs -> isolated AI run archive
sealed AI run + selected private gold -> public scorecard + private details/report
paired FULL/CORE dev scorecards + private details -> private aggregate ablation summary
```

Gold annotation and AI extraction must never share an execution context or data
path. The full protocol is in
[`benchmark/GUIDELINE.md`](../benchmark/GUIDELINE.md).

## Literature and Paper-Level Artifacts

| Path | Role | Owner and edit policy |
|---|---|---|
| `notes/YYYY/YYYY-MM/YYYY-MM.json` | Canonical normalized monthly literature record | Written by literature fetch/assessment workflows; regenerate Markdown from it |
| `notes/YYYY/YYYY-MM/YYYY-MM.title-triage.json` | Derived triage and review record | Written by literature fetch; do not promote it to paper evidence |
| `notes/00_literature_notes_index.json` | Derived global literature index | Rebuild from monthly JSON |
| `notes/**/*.md` | Reading views | Regenerate; never hand-edit |
| `literature/<arxiv_id>/arxiv.pdf`, `arxiv_abs.html`, `arxiv_source/` | Archived paper inputs | Written by the asset archive workflow; raw assets are local and ignored |
| `literature/<arxiv_id>/audit.json` | Asset and provenance audit | Written by archive/metadata workflows |
| `literature/<arxiv_id>/ads_metadata.json` | Full ADS API response for the paper | Written only by ADS metadata workflows; do not synthesize ADS bibcodes |
| `literature/<arxiv_id>/catalog_review.json` | Canonical paper-level structured-data review | Schema-backed, agent-filled record; validate before downstream use |
| `literature/<arxiv_id>/catalog_extraction.json` | Canonical record of the current internal-table extraction | Written by the table extraction workflow from review and archived source |
| `literature/<arxiv_id>/catalog_sources/` | Derived excerpts and conversion diagnostics | Rebuild from reviewed table definitions and archived source |
| `literature/<arxiv_id>/catalog_tables/*.ecsv` | Faithful derived table products | Re-extract rather than adding scientific interpretation by hand |
| `literature/<arxiv_id>/literature_hvs_candidates.json` | Canonical paper-level HVS candidate extraction | Schema-backed scientific record with paper-grounded provenance; validate before indexing |
| `literature/01_literature_catalog_index.{json,md}` | Derived review/extraction index and reading view | Rebuild from paper-level review/extraction JSON |
| `literature/02_literature_hvs_index.{json,md}` | Derived HVS extraction index and reading view | Rebuild from paper-level candidate JSON |

The three structured paper records intentionally serve different questions:

- `catalog_review.json` inventories structured assets described by the paper.
- `catalog_extraction.json` records faithful conversion of reviewed internal
  tables.
- `literature_hvs_candidates.json` records paper-supported Galactic-unbound/HVS
  candidates and scientific provenance.

Review and table extraction do not decide HVS inclusion. ECSV files locate
values but do not replace paper-text evidence.

## Object Catalog and Web Artifacts

| Path | Role | Owner and edit policy |
|---|---|---|
| `catalog/candidates/<object_id>.json` | Derived object-level merge product | Rebuild or update from paper-level candidate JSON; never hand-edit |
| `catalog/candidates/<object_id>.json` `dynamics` | Derived dynamical reassessment embedded in the object | Written by the dynamics workflow; rerun after any object-catalog merge |
| `catalog/03_hvs_candidates_index.{json,md}` | Derived object index and reading view | Rebuild with the object merge |
| `catalog/web/live/` | Local generated view over catalog data | Rebuild with the web workflow |
| `catalog/web/static/` | Local generated snapshot | Rebuild from the current object catalog |
| `pages/` | Committable deployment snapshot | Prepare from `catalog/web/static/`; catalog JSON remains upstream truth |

Object JSON deliberately compacts paper-level candidate records. Full
`raw_value`, source locations, evidence, and detailed provenance remain in
`literature_hvs_candidates.json`; object-level products preserve only the data
needed for merging, comparison, enrichment, dynamics, and display.

The default object merge may query public SIMBAD and Gaia DR3 services. Those
results enrich or support grouping but never overwrite the paper-level source
record. Use the `object_catalog_merge` workflow for the current network and
review policy.

## Benchmark Artifacts

Use `<campaign_id>` as resolved by the schema registry rather than copying the
current campaign literal into new documentation or code.

| Path | Visibility and lifecycle | Owner and edit policy |
|---|---|---|
| `benchmark/campaigns/<campaign_id>/manifest/sampling_manifest.json` | Public committed campaign input | Deterministically generated by campaign preparation |
| `benchmark/campaigns/<campaign_id>/manifest/campaign_manifest.json` | Public committed formal campaign contract | Generated and frozen by campaign preparation |
| `benchmark/campaigns/<campaign_id>/manifest/gold_manifest.json` | Public committed hashes/metadata only | Refreshed from private gold only with explicit authority; existing paper hashes are append-only |
| `$STELLA_GOLD_DIR/<arxiv_id>/annotation_<annotator>.yaml` | External private expert source | Written only by the expert-led annotation workflow |
| `$STELLA_GOLD_DIR/<arxiv_id>/annotation_<annotator>.json` | External private validated twin | Generated from expert YAML; never copy into this workspace |
| `benchmark/campaigns/<campaign_id>/runs/<run_id>/` | Local ignored AI run archive, including per-paper extraction, full context manifest, roster-only context manifest, report, reviewer challenge record, shared-roster copy, and request/response attempts | Written by the selected extraction workflow; sealed run-manifest v4 requires the paper-first roster context for B/C and records decoupled CORE (`full_core`/`core_prov`) and enrichment (`full_enrichment`) delivery status and hashes, with enrichment validity never demoting a valid core; never read gold or mutate sealed runs |
| `benchmark/campaigns/<campaign_id>/runs/_shared_rosters/<shared_key>/` | Local ignored surface-neutral roster cache; new runs use Method B/Core, historical Method C/FULL entries remain readable | Keyed by method, paper, extractor/reviewer model and provider, prompt/rules, roster-context manifest/content hashes, and code version. Bundle v3 compares a producer roster with an independently discovered reviewer roster; exact matches seal directly and mismatches get one bounded same-reviewer reconciliation before seal-or-fail. Each consuming run receives its own bundle/attempt copy |
| `benchmark/campaigns/<campaign_id>/runs/<run_id>/<arxiv_id>/attempts/*transport-error.json` | Local ignored redacted provider-failure evidence | Stores bounded structured category/status/retry/request-id/body-excerpt/stage/call evidence; never stores credentials and never changes retry eligibility of an old report |
| `logs/benchmark-dev-console/<campaign_id>/<run_id>/events.jsonl` | Local ignored append-only observability trace | Written only when trace output is requested; exact event metadata points to content-addressed blobs and does not replace the formal run archive |
| `logs/benchmark-dev-console/<campaign_id>/<run_id>/blobs/<sha256>.json.gz` | Local ignored request/response/tool payload store | Canonical JSON compressed and deduplicated by SHA-256; requests exclude API key and base URL |
| `logs/benchmark-dev-console/<campaign_id>/<run_id>/{controller.json,runner.log}` | Local ignored console process state and stdio | Owned by the local dev console; operational recovery evidence only |
| `logs/benchmark-dev-console/<campaign_id>/_groups/<group_id>/{group.json,events.jsonl}` | Local ignored experiment-group queue and event state | Owns multi-run scheduling, stop/resume state, and restart reconciliation; a single run is represented as a one-experiment group |
| `logs/benchmark-dev-console/<campaign_id>/_groups/<group_id>/evaluation/` | Local ignored dev-console evaluation state and evaluation-labelled aggregate scorecards | Owns local audit/seal/score orchestration and browser-safe aggregate cards; each evaluation is append-only and private item details are excluded |
| `$STELLA_GOLD_DIR/../scoring-details/dev-console/<group_id>/` | External private dev-console scoring details | Written only by explicit local evaluation; never returned by the console API and never overwrites `$STELLA_GOLD_DIR/../report/` |
| `benchmark/campaigns/<campaign_id>/releases/<run_id>.json` | Persistent public release metadata for a released test run | Written by run finalization |
| `benchmark/campaigns/<campaign_id>/scoring/<run_label>/scorecard.json` | Public committed counts and rates | Written once by the formal scorer for an eligible sealed run; use a new label and optional `supersedes` relation instead of overwriting |
| `$STELLA_GOLD_DIR/../scoring-details/<run_label>/details.json` | External private scoring detail | May contain gold values and notes; never commit here |
| `$STELLA_GOLD_DIR/../report/` | External private HTML report | Generated from public scorecards plus private details; never commit here |
| `$STELLA_GOLD_DIR/../ablation/core-surface-dev-v1/<method>/summary.json` | External private aggregate diagnostic | Compares paired FULL/CORE dev runs; contains only aggregate quality, delivery, token/call, CI, and decision fields; never commit here |

Benchmark definitions own commands, prerequisites, retry rules, release gates,
and validators. [`benchmark/README.md`](../benchmark/README.md) explains the
toolchain, while [`docs/benchmark-plan.md`](benchmark-plan.md) and
[`docs/benchmark-l2-spec.md`](benchmark-l2-spec.md) own campaign and scoring
methodology.

## Logs and Temporary State

`logs/` contains local run logs, partial summaries, and JSONL event streams. It
is operational evidence, not a canonical scientific dataset, and is ignored by
Git. Temporary helpers and scratch outputs belong under `/tmp` or an ignored
scratch location and should be removed when the task finishes.

Formal run archives and generated catalog products may be long-lived local
artifacts even though they are not source-controlled. Preserve or publish them
through an explicit data-release process rather than force-adding them to the
toolchain repository.

## Git and Repository Boundaries

| Category | Default repository treatment |
|---|---|
| Source, schemas, scripts, workflows, tests, skills, and documentation | Committed |
| `literature/*/catalog_review.json`, `catalog_extraction.json`, and `literature_hvs_candidates.json` | Explicitly eligible for tracking; all other paper assets remain ignored |
| `notes/`, raw `literature/` assets, `catalog/`, and `logs/` | Ignored by default |
| Campaign manifests, public release metadata, and public scorecards | Committed when produced by their owning workflow |
| Campaign `runs/` | Ignored local archives |
| `pages/` | Committed generated deployment snapshot |
| Expert gold, private scoring details, and private reports | External private repository only |

Do not use `git add -f` to bypass these boundaries unless the user explicitly
requests a deliberate repository-policy change.

## Schema and Version References

Exact fields and enums come from code and generated references, not this page:

- [`skills/hvs-catalog-review/references/schema.md`](../skills/hvs-catalog-review/references/schema.md)
- [`skills/hvs-catalog-extraction/references/schema.md`](../skills/hvs-catalog-extraction/references/schema.md)
- [`skills/hvs-candidates-extraction/references/schema.md`](../skills/hvs-candidates-extraction/references/schema.md)
- [`src/stella/lit/schema_models.py`](../src/stella/lit/schema_models.py)
- [`src/stella/schema_registry.py`](../src/stella/schema_registry.py)
- generated [`docs/versions.md`](versions.md)
- [`docs/versioning-policy.md`](versioning-policy.md)

When fields change, update models/templates/validators and regenerate schema
references. Update this page only when artifact paths, ownership, lifecycle,
privacy, source/derived status, or cross-workflow data flow changes.
