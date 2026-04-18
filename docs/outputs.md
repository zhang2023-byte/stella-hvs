# Outputs

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

Each monthly note includes:

- date range and run ID
- search source and categories
- selected papers with arXiv/PDF links
- matched queries and categories
- title-triage label, confidence, and reason
- direct/weak rule counts
- DeepXiv brief and arXiv abstract when available
- per-query/category search summary

Main log event types:

```text
start
query
classify
brief
month_done
finish
```
