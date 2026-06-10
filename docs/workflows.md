# Workflows

This is the human-readable guide to what you can ask Stella's agent to do. Each
workflow has a machine-readable contract in
[../workflows/stella_workflows.yaml](../workflows/stella_workflows.yaml); the
agent uses that YAML to route requests and this page is for people.

You normally just ask in natural language. The agent identifies the workflow,
fills in defaults, and asks only for details that change the result, trigger
real network/API calls, or risk modifying the wrong generated data.

JSON is the source of truth throughout. Markdown, indexes, HTML, and the object
catalog are generated views; fix the source JSON or renderer if a view is wrong.

## Pipeline overview

```text
monthly_literature_fetch  ->  catalog_assessment  ->  literature_asset_archive
   ->  catalog_review  ->  catalog_table_extraction  ->  hvs_candidate_extraction
   ->  object_catalog_merge  ->  hvs_dynamics_calculate  ->  hvs_catalog_html_build
   ->  hvs_catalog_pages_prepare
```

`ads_metadata_repair` and `index_or_markdown_regeneration` are maintenance
workflows used as needed. `catalog_review` and `hvs_candidate_extraction` have
batch variants for processing many papers, one fresh worker per paper.

The `hvs_benchmark_*` family (sample → variant extraction → review build →
gold finalize → score) maintains an expert-adjudicated benchmark for the
`hvs_candidate_extraction` stage; see `skills/hvs-benchmark/SKILL.md`.

## monthly_literature_fetch

Fetch and triage a month (or range) of HVS literature.

- Ask: "Fetch high-velocity-star literature from 2026-03."
- Clarifies: start month/date, whether real DeepXiv/arXiv network search is
  allowed, whether LLM review should be enabled.
- Produces: monthly JSON, Markdown, and title-triage JSON under
  `notes/YYYY/YYYY-MM/`, plus rebuilt notes indexes.
- Risk: network (needs explicit permission for real fetching).

## catalog_assessment

Annotate monthly records with an observational-data assessment.

- Ask: "Add catalog assessments for 2026-03."
- Clarifies: target month/range/paper set, whether DeepXiv/LLM calls are allowed.
- Produces: updated monthly JSON plus regenerated Markdown and indexes.
- Risk: network / LLM.

## literature_asset_archive

Archive public paper assets (HTML, PDF, source, ADS metadata) locally.

- Ask: "Archive local assets for data-related papers from 2024-01 to 2026-04."
- Clarifies: month range or explicit arXiv IDs, whether public downloads are
  allowed.
- Produces: `literature/<arxiv_id>/audit.json` and archived assets per paper.
- Risk: network / download.

## ads_metadata_repair

Fill paper-level bibcodes via the ADS API.

- Ask: "Repair ADS metadata for 2402.10714."
- Clarifies: specific arXiv IDs or all archived papers, whether ADS API calls are
  allowed.
- Produces: `ads_metadata.json`, updated `audit.json`, and `paper.bibcode` in
  candidate JSON when present.
- Risk: network / API. Bibcodes are never constructed by hand and ADS pages are
  never scraped.

## catalog_review

Inventory a paper's structured data assets (internal tables and described
external resources). It does not decide HVS relevance and does not download
external resources.

- Ask: "Review structured data assets for 2402.10714."
- Clarifies: arXiv ID, whether to continue if archive assets are missing.
- Produces: `literature/<arxiv_id>/catalog_review.json` plus the rebuilt catalog
  workflow index.
- Risk: generated data.

## catalog_review_batch

Run `catalog_review` over several papers, dispatching one fresh worker per paper
and rebuilding the index once at the end.

- Ask: "Review structured data assets for 2402.10714, 2603.00001, and 2604.21646."
- Clarifies: the arXiv ID list, archive-asset failure policy.

## catalog_table_extraction

Convert reviewed internal LaTeX tables into ECSV. It adds no scientific
semantics and does no HVS filtering.

- Ask: "Extract reviewed internal tables for 2402.10714."
- Clarifies: arXiv ID or all reviewed papers, whether to overwrite existing
  outputs.
- Produces: `catalog_extraction.json`, `catalog_sources/`, and `catalog_tables/`
  ECSV files.
- Risk: generated data.

## hvs_candidate_extraction

Extract paper-level Galactic-unbound / HVS candidates. Inclusion is text-driven:
the paper must explicitly treat an object as possibly unbound before tables are
used for quantities.

- Ask: "Extract paper-level HVS candidates for 2402.10714."
- Clarifies: arXiv ID, whether to create missing review/extraction inputs first.
- Produces: `literature_hvs_candidates.json` (or a documented `no_candidates`
  result) plus the rebuilt HVS candidates index.
- Risk: scientific judgment.

## hvs_candidate_extraction_batch

Run `hvs_candidate_extraction` over several papers, one fresh worker per paper,
rebuilding the index once at the end when requested.

- Ask: "Extract HVS candidates for 2402.10714, 2603.00001, and 2604.21646."
- Clarifies: the arXiv ID list, whether to create missing inputs first.

## object_catalog_merge

Merge paper-level candidates into the object-level catalog, with an evidence
graph and default SIMBAD / Gaia DR3 enrichment.

- Ask: "Rebuild the object-level HVS catalog."
- Clarifies: rebuild all objects or update one paper; the arXiv ID/path when
  updating one.
- Produces: `catalog/candidates/<object_id>.json` plus the catalog index. Use
  `--enrichment-mode off --external-merge-mode off` for a pure offline merge.
- Risk: network / API + generated data.

## hvs_dynamics_calculate

Compute object-level Galactocentric total velocities and unbound probabilities
from cached external enrichment, writing only the `dynamics` field.

- Ask: "Calculate HVS dynamics for the object catalog."
- Clarifies: whether public Gaia DR3 queries are allowed (only with
  `--refresh-external`), all objects or one `object_id` when ambiguous.
- Produces: the `dynamics` field inside each object JSON. Rerun after every
  `object_catalog_merge`, which rebuilds object JSON and clears dynamics.
- Risk: generated data (no network by default).

## hvs_catalog_html_build

Build the local HTML display pages from the object catalog.

- Ask: "Build the HVS catalog HTML demo."
- Clarifies: whether this means a local build or a deployment outside this repo.
- Produces: `catalog/html/live/` and `catalog/html/static/index.html`.
- Risk: generated view (no network).

## hvs_catalog_pages_prepare

Copy the generated static HTML snapshot into the committed GitHub Pages publish
directory.

- Ask: "Prepare the GitHub Pages site."
- Clarifies: deployment target if it is not GitHub Pages.
- Produces: `site/`, including `site/index.html`, `catalog-data.js`, CSS, JS,
  image assets, and `.nojekyll`.
- Risk: generated view deployment artifact (no network locally; deployment
  happens after pushing to GitHub).

## index_or_markdown_regeneration

Rebuild generated indexes and Markdown from JSON.

- Ask: "Regenerate literature Markdown and indexes from JSON."
- Clarifies: which view family (monthly notes, catalog index, HVS index, or all).
- Produces: regenerated Markdown and index files.
- Risk: generated view (no network).

## hvs_benchmark_sample

Select a frozen, stratified benchmark paper sample for the extraction
benchmark (year bucket × extraction status × candidate-count bucket).

- Ask: "Create a benchmark sample of 10 papers."
- Clarifies: sample size, whether an existing frozen manifest may be replaced.
- Produces: `benchmark/manifest/benchmark_manifest.json` (committed).
- Risk: generated data (no network).

## hvs_benchmark_variant_extraction

Run one independent candidate extraction for one benchmark paper, writing into
a variant directory instead of `literature/`. Workers follow the same
extraction skill but must not read the production extraction, other variants,
or any gold/adjudication data (contamination rule).

- Ask: "Extract benchmark variant rerun-fable5-202606 for 2402.10714."
- Clarifies: arXiv ID and variant id.
- Produces: `benchmark/variants/<variant_id>/<arxiv_id>/literature_hvs_candidates.json`.
- Risk: scientific judgment.

## hvs_benchmark_variant_extraction_batch

Run `hvs_benchmark_variant_extraction` over the manifest papers, one fresh
worker per paper, then report the manifest × variants completion matrix.

- Ask: "Collect benchmark variant rerun-fable5-202606 for all manifest papers."
- Clarifies: variant id (register it first when missing).

## hvs_benchmark_review_build

Align variant extractions per paper (embedding source-ref evidence excerpts),
build the local expert review site, and start the verdict-persisting review
server.

- Ask: "Build the benchmark review site; I'll review as expert wz."
- Clarifies: expert id.
- Produces: `benchmark/alignment/`, `benchmark/review/` (generated), and
  expert verdicts in `benchmark/adjudication/` (committed, written only via
  the review server).
- Risk: generated view; localhost server only.

## hvs_benchmark_gold_finalize

Apply expert verdicts to assemble per-paper gold v7 records, gate on verdict
completeness, and validate gold with the standard candidate validator.

- Ask: "Finalize benchmark gold for all adjudicated papers."
- Clarifies: one paper or all; whether partial runs are allowed.
- Produces: `benchmark/gold/<arxiv_id>/literature_hvs_candidates.json` and
  `gold_provenance.json` (committed).
- Risk: scientific judgment (no network).

## hvs_benchmark_score

Score variants against gold: detection precision/recall/F1 with bootstrap
confidence intervals, paper-status agreement, and field-level accuracy under
strict and loose numeric tolerances.

- Ask: "Score the benchmark variants."
- Clarifies: which variants (default: all registered).
- Produces: `benchmark/reports/benchmark_report.json` and `.md` (generated).
- Risk: generated view (no network).
