# Human Workflows

Stella is usually driven through natural-language requests to an agent, not by
humans typing every command. This document describes useful human requests, what
an agent should clarify, and the precise prompt it should internally execute.

Default clarification policy: ask only when the missing detail changes the
result, causes real network/API usage, or risks modifying the wrong generated
data. Otherwise use workflow defaults and report the assumption.

## Monthly Literature Fetch

Recommended human request:

```text
Fetch high-velocity-star literature from 2026-03.
```

Common vague request:

```text
Update recent HVS papers.
```

Clarify when missing:

- Start month or date.
- Whether real DeepXiv/arXiv network search is allowed.
- Whether LLM review should be enabled.

Precise agent prompt:

```text
Run the monthly_literature_fetch workflow for FROM=<YYYY-MM or date> and optional TO=<YYYY-MM or date>. Use default source=deepxiv, categories=astro-ph.GA,astro-ph.SR,astro-ph.IM, max_results=20, llm_review=False unless explicitly requested. Do not make real DeepXiv calls unless the user explicitly allows new data fetching. Save monthly JSON/Markdown and rebuild indexes as the workflow requires. Report partial results and resume command if quota or API failures occur.
```

## Catalog Assessment

Recommended human request:

```text
Add catalog assessments for 2026-03.
```

Common vague request:

```text
Figure out which papers have useful data.
```

Clarify when missing:

- Target month, month range, or paper set.
- Whether DeepXiv-enhanced assessment and LLM calls are allowed.

Precise agent prompt:

```text
Run catalog_assessment for MONTHS=<YYYY-MM list or range>. Use existing monthly JSON as input. Use title, abstract, DeepXiv brief when available, and paper context gathered by the CLI. Refresh generated Markdown and indexes after completion. Report any missing token/API failures explicitly.
```

## Literature Asset Archive

Recommended human request:

```text
Archive local assets for data-related papers from 2024-01 to 2026-04.
```

Common vague request:

```text
Download the papers we need.
```

Clarify when missing:

- Month range or explicit arXiv IDs.
- Whether public network downloads are allowed.

Precise agent prompt:

```text
Run literature_asset_archive for TARGET=<month range, month list, or arXiv ID list>. Archive only papers selected by catalog_assessment unless explicit arXiv IDs are supplied. Save audit.json for every paper, preserve fetch failures, and do not treat missing assets as success.
```

## ADS Metadata Repair

Recommended human request:

```text
Repair ADS metadata for 2402.10714.
```

Common vague request:

```text
Fix missing bibcodes.
```

Clarify when missing:

- Specific arXiv IDs, or whether all archived papers should be scanned.
- Whether ADS API network calls are allowed.

Precise agent prompt:

```text
Run ads_metadata_repair for TARGET=<arXiv IDs or all archived papers>. Query only the ADS API, save full ads_metadata.json responses, update audit.json, and fill only paper.bibcode in literature_hvs_candidates.json when present. Do not construct ADS bibcodes manually and do not scrape ADS HTML.
```

## Catalog Review

Recommended human request:

```text
Review structured data assets for 2402.10714.
```

Common vague request:

```text
Look at this paper's tables and data.
```

Clarify when missing:

- arXiv ID.
- Whether to continue if audit.json reports missing source/PDF/ADS metadata.

Precise agent prompt:

```text
Use the hvs-catalog-review skill for ARXIV_ID=<id>. First inspect audit.json and archived source assets. Generate or refresh the schema-backed catalog_review.json template. Inventory internal LaTeX tables and paper-described external resources only; do not decide HVS relevance and do not download external resources. Validate with --require-complete and rebuild the catalog workflow index.
```

## Catalog Review Batch

Recommended human request:

```text
Review structured data assets for 2402.10714, 2603.00001, and 2604.21646.
```

Common vague request:

```text
Review all archived data papers.
```

Clarify when missing:

- The explicit arXiv ID list or the source from which to derive it.
- Whether to continue for papers whose audit.json reports missing source, PDF,
  or ADS metadata.

Precise agent prompt:

```text
Run catalog_review_batch for ARXIV_IDS=<id list>. The parent agent should resolve the queue, dispatch one fresh subagent per arXiv ID using the single-paper catalog_review workflow, never reuse a worker for a second paper, and avoid reading multiple papers deeply in the parent context. Use adaptive concurrency based on the current agent tool's exposed limit or runtime probe; if worker creation hits a concurrency, quota, or rate-limit error, keep the discovered cap and continue as workers finish. Each worker returns arxiv_id, status, outputs, validator_result, warnings, blockers, and next_action. After all workers complete, rebuild the catalog workflow index once.
```

## Catalog Table Extraction

Recommended human request:

```text
Extract reviewed internal tables for 2402.10714.
```

Common vague request:

```text
Convert the paper tables.
```

Clarify when missing:

- arXiv ID or whether all reviewed papers should be processed.
- Whether overwrite is intended.

Precise agent prompt:

```text
Run catalog_table_extraction for ARXIV_ID=<id> or all reviewed papers, using the hvs-catalog-extraction skill. Process only latex_table entries from catalog_review.json. Write catalog_extraction.json, catalog_sources, and catalog_tables ECSV. Do not add scientific semantics, do not perform HVS filtering, and do not process external resources. Validate extraction output.
```

## HVS Candidate Extraction

Recommended human request:

```text
Extract paper-level HVS candidates for 2402.10714.
```

Common vague request:

```text
Check whether this paper has HVS candidates.
```

Clarify when missing:

- arXiv ID.
- Whether required review/extraction files should be created first if missing.

Precise agent prompt:

```text
Run hvs_candidate_extraction for ARXIV_ID=<id>, using the hvs-candidates-extraction skill. Confirm audit.json, ADS metadata, catalog_review.json, catalog_extraction.json, and relevant ECSV files exist. Read paper text first to establish candidate inclusion and candidate_origin. Use tables only after text evidence justifies inclusion. Write literature_hvs_candidates.json with source_refs and method_refs, or status=no_candidates with empty candidates. Validate with --require-complete and rebuild the HVS candidates index when requested.
```

## HVS Candidate Extraction Batch

Recommended human request:

```text
Extract HVS candidates for 2402.10714, 2603.00001, and 2604.21646.
```

Common vague request:

```text
Check all reviewed papers for HVS candidates.
```

Clarify when missing:

- The explicit arXiv ID list or the source from which to derive it.
- Whether missing catalog reviews or table extractions should be created first.

Precise agent prompt:

```text
Run hvs_candidate_extraction_batch for ARXIV_IDS=<id list>. The parent agent should resolve the queue, dispatch one fresh subagent per arXiv ID using the single-paper hvs_candidate_extraction workflow, never reuse a worker for a second paper, and avoid reading multiple papers deeply in the parent context. Use adaptive concurrency based on the current agent tool's exposed limit or runtime probe; if worker creation hits a concurrency, quota, or rate-limit error, keep the discovered cap and continue as workers finish. Each worker returns arxiv_id, status, outputs, validator_result, warnings, blockers, and next_action. After all workers complete, rebuild the HVS candidates index once when requested.
```

## Object Catalog Merge

Recommended human request:

```text
Rebuild the object-level HVS catalog.
```

Common vague request:

```text
Update catalog.
```

Clarify when missing:

- Rebuild all objects or update one paper.
- If updating one paper, the arXiv ID or path.

Precise agent prompt:

```text
Run object_catalog_merge, using the hvs-candidates-merge skill. For rebuild, merge all valid literature_hvs_candidates.json files into catalog/. For update, merge only ARXIV_ID=<id> or PATH=<file>. Validate inputs first, preserve merge evidence and warnings, run default public SIMBAD/Gaia DR3 enrichment plus external-assisted merge unless enrichment_mode=off or external_merge_mode=off, and do not manually edit generated catalog files.
```

## HVS Dynamics Calculate

Recommended human request:

```text
Calculate HVS dynamics for the object catalog.
```

Common vague request:

```text
Recompute unbound probabilities.
```

Clarify when missing:

- Whether public Gaia DR3 network queries are allowed, only when the user
  requests `--refresh-external`.
- Whether to process all objects or one `object_id` when the request is scoped
  ambiguously.

Precise agent prompt:

```text
Run hvs_dynamics_calculate for CATALOG_DIR=<catalog, unless overridden>, using the hvs_dynamics_calculate skill. Reuse official Gaia DR3 raw rows cached under external_enrichment by default, apply gaiadr3-zeropoint correction, use literature RV when available, and otherwise ignore SIMBAD RV and compute the Boubert-style missing-RV lower-limit case. Then compute Galactocentric total velocity and unbound probability with the same default 10000 MCMC posterior samples used for graveyard classification. Write results into each object JSON dynamics field only when write=True, and report skipped reasons, lower-limit results, and graveyard count. Query Gaia DR3 only when --refresh-external is explicitly requested.
```

## HVS Catalog HTML Build

Recommended human request:

```text
Build the HVS catalog HTML demo.
```

Common vague request:

```text
Refresh the website.
```

Clarify when missing:

- Whether this means local HTML build only, or a deployment outside this repo.

Precise agent prompt:

```text
Run hvs_catalog_html_build using catalog/ as source and catalog/html/ as output. Build live and static pages from generated object-level catalog JSON. Do not treat HTML as source of truth. Verify that expected catalog/html/live and catalog/html/static outputs exist.
```

## Index or Markdown Regeneration

Recommended human request:

```text
Regenerate literature Markdown and indexes from JSON.
```

Common vague request:

```text
Refresh generated views.
```

Clarify when missing:

- Which view family: monthly notes, catalog workflow index, HVS candidate index,
  or all generated views.

Precise agent prompt:

```text
Run index_or_markdown_regeneration for TARGET=<monthly notes, catalog index, HVS index, or all>. Treat JSON as source of truth. Do not manually edit generated Markdown or index JSON; fix source JSON or rendering logic if generated output is wrong.
```
