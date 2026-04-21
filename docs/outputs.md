# Outputs

JSON is canonical. Markdown is generated from JSON and should stay fully
corresponding to it.

Canonical data:

```text
notes/index.json                  Collection index rebuilt from monthly JSON
notes/YYYY/YYYY-MM/YYYY-MM.json   Monthly canonical record
literature/<arxiv_id>/record.json Per-paper verification evidence record
literature/<arxiv_id>/catalog_ingest/manifest.json           Catalog-ingestion manifest scaffold
literature/<arxiv_id>/catalog_ingest/field_definitions.json  Per-field semantic-definition scaffold
literature/<arxiv_id>/catalog_ingest/column_mapping.json     Stella normalization scaffold
```

Generated notes:

```text
notes/index.md                   Yearly collection view generated from index JSON
notes/YYYY/YYYY-MM/YYYY-MM.md    Monthly literature note generated from JSON
literature/<arxiv_id>/summary.md Human-readable verification summary generated from record JSON
```

Local logs:

```text
logs/arxiv_metadata_<timestamp>.json
logs/runs.jsonl
logs/run_<timestamp>.log
```

`logs/` is ignored by Git.

Each monthly JSON record includes:

- date range and run ID
- resolved search/classifier/brief config, including the actual month-level categories and queries used
- per-query/category search log
- local month-window filtering stats, including out-of-window and missing-date drops
- best-effort arXiv metadata backfill stats for DeepXiv results that arrived without a publication date
- selected papers with arXiv/PDF links and provenance
- matched queries and categories
- title-triage label, confidence, and reason
- direct/weak triage level
- search-returned abstract
- DeepXiv brief content and fetched/skipped status
- optional `catalog_assessment` fields for observational catalog/sample checks
- optional `catalog_verification` summary fields for paper-level DeepXiv/PDF/source verification
- optional `agent_adjudication` inside `literature/<arxiv_id>/record.json` when an Agent overrides the automated paper-level verdict, including the repo-local `skill_path` and `skill_version` used for that adjudication
- optional `catalog_ingest/` JSON scaffolds under `literature/<arxiv_id>/` for catalog-level ingestion work after verification; when a `Label / Unit / Description` table describes a full machine-readable catalog, the manifest marks it as `schema_definition` and the bootstrapper drafts per-field definitions and column mappings from it
- direct/weak rule counts

Monthly Markdown notes are rendered from those fields. They list direct matches
before weak matches and use a divider between the two sections. When present,
catalog assessments and paper-level verification summaries are rendered beside
each paper and summarized near the top of the note.

The current collection index is rebuilt from monthly JSON and grouped by year.
`notes/index.md` emphasizes yearly counts, recent literature, data-related
literature identified through `catalog_assessment`, and paper-level verification
counts.
`notes/index.json` also carries a flat `papers` list so downstream scripts can
sample or filter papers without parsing Markdown. Those flat paper entries now
also carry optional `catalog_verification` summaries and collection-level counts
for how many papers have been verified and how many were confirmed to contain a
catalog. When `catalog_verification.decision_source = agent`, that flat summary
reflects the effective agent override rather than the automated DeepXiv/PDF/source
heuristic alone.

Main log event types:

```text
start
query
arxiv_metadata
classify
brief
month_done
finish
```
