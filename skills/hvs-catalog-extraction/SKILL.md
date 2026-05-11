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

Validate after edits:

```bash
python -m json.tool literature/<arxiv_id>/catalog_extraction.json >/dev/null
conda run -n stella-env python -m unittest tests.test_catalog_extraction
```
