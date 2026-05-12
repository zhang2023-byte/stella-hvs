---
name: hvs-catalog-extraction
description: Extract reviewed Stella internal LaTeX tables after catalog_review.json exists. This stage preserves table excerpts and converts internal table-like assets to ECSV without handling external resources or adding scientific/HVS semantics.
---

# Article Data Asset Extraction

Use this skill after `literature/<arxiv_id>/catalog_review.json` has been written
by the data-asset review workflow.

This is a preservation and conversion workflow for internal LaTeX tables. It may write:

```text
literature/<arxiv_id>/catalog_extraction.json
literature/<arxiv_id>/catalog_sources/<internal_table_id>/excerpt.tex
literature/<arxiv_id>/catalog_sources/<internal_table_id>/latexml.html
literature/<arxiv_id>/catalog_sources/<internal_table_id>/pandoc.html
literature/<arxiv_id>/catalog_tables/<table_id>.ecsv
```

Do not edit generated ECSV or excerpts by hand. If conversion is wrong, improve
or rerun the extractor.

## Workflow

1. Confirm `catalog_review.json` exists and uses
   `stella.article_data_assets.review.v1`.
2. Run extraction:

   ```bash
   conda run -n stella-env python scripts/extract_catalog_tables.py --arxiv-id <arxiv_id>
   ```

   Use `--internal-table-id <id>` for one LaTeX table.
3. Inspect `catalog_extraction.json`:
   - `run`
   - `files[]`
   - `tables[]`
4. For internal LaTeX tables, confirm `excerpt.tex` exists even if table
   conversion failed.

## Boundaries

- This stage does not decide whether anything is high-velocity-star data.
- This stage does not fill scientific meanings or normalized object schemas.
- Internal LaTeX tables are converted to ECSV.
- External resources listed in `catalog_review.json` are not downloaded,
  resolved, parsed, converted, or represented in `catalog_extraction.json`.

## Output Schema

Use `schema_version: "stella.article_data_assets.extraction.v2"`.

`catalog_extraction.json` contains:

- `paper`: arXiv ID, title, month.
- `review`: source review path and review status.
- `run`: the single current extraction run, including options, summary, and
  status. Do not append historical runs.
- `files`: source excerpts, with hashes, paths, and errors.
- `tables`: ECSV outputs for internal tables that parsed, with observed
  columns, row/column counts, conversion attempts, warnings, and source hash.
  Converter stdout/stderr content is not embedded in JSON; keep only artifact
  paths such as `latexml.stdout.txt` and `latexml.stderr.txt`.

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
  "run": {
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
  },
  "files": [
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
  ],
  "tables": [
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
      "conversion_attempts": [
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
        },
        {
          "method": "pandoc",
          "status": "failed",
          "command": ["pandoc", "..."],
          "error": "...",
          "artifacts": {}
        },
        {
          "method": "internal",
          "status": "failed",
          "command": [],
          "error": "",
          "artifacts": {}
        }
      ],
      "source_sha256": "abc123..."
    }
  ]
}
```

### Field notes

- `run.status`: one of `success`, `partial`, `failed`, `skipped`.
- `files[].status`: one of `written`, `skipped_existing`, `would_write`, `failed`, `deferred`.
- `tables[].status`: one of `success`, `would_write`, `skipped_existing`, `failed`, `deferred`.
- `tables[].columns[]` uses machine-observed fields (`original_header`, `unit_text`, `data_type`, `null_values`), not the human-assessed `meaning`/`confidence` from the review schema.
- `tables[].conversion_attempts[]` records the ordered fallback chain (LaTeXML → Pandoc → internal parser). Only the first successful attempt is the source of the final ECSV; later attempts may show `failed`.
- When `internal_table.kind` is not `latex_table`, both `files[]` and `tables[]` receive a minimal deferred record with `status: "deferred"` and an `error` explaining the skip.

Validate after edits:

```bash
python -m json.tool literature/<arxiv_id>/catalog_extraction.json >/dev/null
conda run -n stella-env python -m unittest tests.test_catalog_extraction
```
