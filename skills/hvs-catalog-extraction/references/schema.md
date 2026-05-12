# `catalog_extraction.json` Schema

Use `schema_version: "stella.article_data_assets.extraction.v2"`.

`catalog_extraction.json` is the fact source for preserving and converting
reviewed internal LaTeX tables. It does not add scientific HVS semantics and
does not represent external resources.

## Top Level

```json
{
  "schema_version": "stella.article_data_assets.extraction.v2",
  "generated_at": "2024-02-15T10:30:00",
  "paper": {
    "arxiv_id": "2402.10714",
    "title": "",
    "month": "2024-02"
  },
  "review": {
    "path": "literature/2402.10714/catalog_review.json",
    "schema_version": "stella.article_data_assets.review.v1",
    "review_status": "reviewed"
  },
  "run": {},
  "files": [],
  "tables": []
}
```

Top-level sections:

- `paper`: arXiv ID, title, month.
- `review`: source review path and review status.
- `run`: the single current extraction run. Do not append historical runs.
- `files`: source excerpts, with hashes, paths, and errors.
- `tables`: ECSV outputs for internal tables that parsed.

## Run

```json
{
  "run_id": "catalog-extraction-20240215103000",
  "started_at": "2024-02-15T10:30:00",
  "tool": "scripts/extract_catalog_tables.py",
  "options": {
    "arxiv_id": "2402.10714",
    "internal_table_id": null,
    "dry_run": false,
    "overwrite": false
  },
  "summary": {
    "internal_table_count": 2,
    "work_count": 2,
    "table_count": 2,
    "success_count": 1,
    "failed_count": 0,
    "deferred_count": 0,
    "file_count": 2,
    "file_success_count": 2,
    "file_failed_count": 0
  },
  "status": "partial"
}
```

Allowed `run.status` values:

- `success`
- `partial`
- `failed`
- `skipped`

## Files

```json
{
  "id": "table-1",
  "internal_table_id": "table-1",
  "kind": "latex_table",
  "status": "written",
  "source_ref": {
    "path": "literature/2402.10714/arxiv_source/main.tex",
    "start_line": 120,
    "end_line": 180,
    "caption": "",
    "label": "tab:sample"
  },
  "source_path": "literature/2402.10714/arxiv_source/main.tex",
  "excerpt_path": "literature/2402.10714/catalog_sources/table-1/excerpt.tex",
  "sha256": "abc123...",
  "line_count": 61,
  "error": ""
}
```

Allowed `files[].status` values:

- `written`
- `skipped_existing`
- `would_write`
- `failed`
- `deferred`

## Tables

```json
{
  "id": "table-1",
  "internal_table_id": "table-1",
  "status": "success",
  "ecsv_path": "literature/2402.10714/catalog_tables/table-1.ecsv",
  "caption": "",
  "label": "tab:sample",
  "row_count": 42,
  "column_count": 8,
  "environment": "deluxetable",
  "header_rows": [["Name", "RA", "Dec", "..."]],
  "columns": [
    {
      "name": "col_001",
      "original_header": "Name",
      "unit_text": "",
      "data_type": "string",
      "null_values": ["", "..."]
    }
  ],
  "warnings": [],
  "error": "",
  "extraction_method": "latexml",
  "conversion_attempts": [],
  "source_sha256": "abc123..."
}
```

Allowed `tables[].status` values:

- `success`
- `would_write`
- `skipped_existing`
- `failed`
- `deferred`

`tables[].columns[]` uses machine-observed fields (`original_header`,
`unit_text`, `data_type`, `null_values`), not the human-assessed
`meaning`/`confidence` from the review schema.

## Conversion Attempts

```json
{
  "method": "latexml",
  "status": "success",
  "command": ["latexmlc", "..."],
  "error": "",
  "artifacts": {
    "wrapped_tex": "literature/2402.10714/catalog_sources/table-1/wrapped.tex",
    "html": "literature/2402.10714/catalog_sources/table-1/latexml.html",
    "stdout": "literature/2402.10714/catalog_sources/table-1/latexml.stdout.txt",
    "stderr": "literature/2402.10714/catalog_sources/table-1/latexml.stderr.txt"
  }
}
```

Rules:

- `tables[].conversion_attempts[]` records the ordered fallback chain:
  LaTeXML, Pandoc, then the internal parser.
- Only the first successful attempt is the source of the final ECSV; later
  attempts may show `failed`.
- Converter stdout/stderr content is not embedded in JSON. Keep only artifact
  paths such as `latexml.stdout.txt` and `latexml.stderr.txt`.
- When `internal_table.kind` is not `latex_table`, both `files[]` and `tables[]`
  receive a minimal deferred record with `status: "deferred"` and an `error`
  explaining the skip.
