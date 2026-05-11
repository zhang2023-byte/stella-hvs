---
name: hvs-catalog-extraction
description: Extract reviewed Stella article data assets after catalog_review.json exists. This stage faithfully preserves internal LaTeX table excerpts, downloads reviewed external resources, converts table-like assets to ECSV, and saves non-table resources as raw files without adding scientific/HVS semantics.
---

# Article Data Asset Extraction

Use this skill after `literature/<arxiv_id>/catalog_review.json` has been written
by the data-asset review workflow.

This is a preservation and conversion workflow. It may write:

```text
literature/<arxiv_id>/catalog_extraction.json
literature/<arxiv_id>/catalog_sources/<internal_table_id>/excerpt.tex
literature/<arxiv_id>/catalog_sources/<internal_table_id>/latexml.html
literature/<arxiv_id>/catalog_sources/<internal_table_id>/pandoc.html
literature/<arxiv_id>/catalog_sources/<external_resource_id>/download-001.*
literature/<arxiv_id>/catalog_tables/<table_id>.ecsv
```

Do not edit generated ECSV or raw downloads by hand. If conversion is wrong,
improve or rerun the extractor.

## Workflow

1. Confirm `catalog_review.json` exists and uses
   `stella.article_data_assets.review.v1`.
2. Run extraction:

   ```bash
   conda run -n stella-env python scripts/extract_catalog_tables.py --arxiv-id <arxiv_id>
   ```

   Use `--internal-table-id <id>` for one LaTeX table and
   `--external-resource-id <id>` for one external resource.
3. Inspect `catalog_extraction.json`:
   - `run`
   - `files[]`
   - `tables[]`
   - `external_resources[].resolver_attempts`
   - `external_resources[].locator_attempts`
   - `external_resources[].download_attempts`
   - `external_resources[].stopped_reason`
4. For internal LaTeX tables, confirm `excerpt.tex` exists even if table
   conversion failed.
5. For external resources, confirm every reviewed resource is represented as a
   saved raw file when download succeeds, even if it is not table-like.

## Boundaries

- This stage does not decide whether anything is high-velocity-star data.
- This stage does not fill scientific meanings or normalized object schemas.
- Table-like assets are converted to ECSV.
- Non-table resources such as ReadMe, HTML landing pages, JSON metadata, or
  unsupported files are saved as raw artifacts and recorded in `files[]`.
- External downloads are limited to `external_resources[]` listed by review and
  direct links found by deterministic provider resolvers or the bounded Agent
  locator.
- Do not use search engines, browser automation, login flows, or recursive
  crawling.

## Output Schema

Use `schema_version: "stella.article_data_assets.extraction.v1"`.

`catalog_extraction.json` contains:

- `paper`: arXiv ID, title, month.
- `review`: source review path and review status.
- `run`: the single current extraction run, including options, summary, and
  status. Do not append historical runs.
- `files`: source excerpts and raw downloaded files, with hashes, size, paths,
  parse attempts, and stopped reasons.
- `tables`: ECSV outputs for assets that parsed as tables, with observed
  columns, row/column counts, conversion attempts, warnings, and source hash.
- `external_resources`: per-resource resolver, locator, download, output, and
  stopped-reason records.

Validate after edits:

```bash
python -m json.tool literature/<arxiv_id>/catalog_extraction.json >/dev/null
conda run -n stella-env python -m unittest tests.test_catalog_extraction
```
