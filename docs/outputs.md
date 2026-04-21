# Outputs

JSON is canonical. Markdown is generated from JSON and should stay fully
corresponding to it.

Canonical data:

```text
notes/index.json                  Collection index rebuilt from monthly JSON
notes/YYYY/YYYY-MM/YYYY-MM.json   Monthly canonical record
```

Generated notes:

```text
notes/index.md                   Yearly collection view generated from index JSON
notes/YYYY/YYYY-MM/YYYY-MM.md    Monthly literature note generated from JSON
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
- direct/weak rule counts

Monthly Markdown notes are rendered from those fields. They list direct matches
before weak matches and use a divider between the two sections. When present,
catalog assessments are rendered beside each paper and summarized near the top
of the note.

The current collection index is rebuilt from monthly JSON and grouped by year.
`notes/index.md` currently emphasizes yearly counts plus data-related literature
identified through `catalog_assessment`.
`notes/index.json` also carries a flat `papers` list so downstream scripts can
sample or filter papers without parsing Markdown.

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
