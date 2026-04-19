# Outputs

JSON is canonical. Markdown is generated from JSON and should stay fully
corresponding to it.

Canonical data:

```text
data/literature/index.json             Collection index for completed months
data/literature/monthly/YYYY-MM.json   Monthly canonical record
data/literature/papers.jsonl           Flat paper stream for machine readers
```

Generated notes:

```text
notes/index.md      Monthly index
notes/YYYY-MM.md    Monthly literature note
```

Local logs:

```text
logs/runs.jsonl
logs/run_<timestamp>.log
```

`logs/` is ignored by Git.

Each monthly JSON record includes:

- date range and run ID
- resolved search/classifier/brief config
- per-query/category search log
- selected papers with arXiv/PDF links and provenance
- matched queries and categories
- title-triage label, confidence, and reason
- direct/weak triage level
- search-returned abstract
- DeepXiv brief content and fetched/skipped status
- direct/weak rule counts

Monthly Markdown notes are rendered from those fields. They list direct matches
before weak matches and use a divider between the two sections.

Main log event types:

```text
start
query
classify
brief
month_done
finish
```
