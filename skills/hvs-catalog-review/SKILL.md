---
name: hvs-catalog-review
description: Review archived Stella papers to build a complete article data-asset inventory: internal LaTeX tables and external resources, with paper-context roles and data-unit meanings. This stage does not decide whether assets are high-velocity-star catalogs and does not download external resources.
---

# Article Data Asset Review

Use this skill after paper assets have been archived under `literature/<arxiv_id>/`.

This is a data-asset review workflow, not an HVS catalog filtering workflow and
not an extraction workflow. Do not convert LaTeX to ECSV, parse FITS, or download
external resources in this stage. The output is:

```text
literature/<arxiv_id>/catalog_review.json
```

## Workflow

1. Inspect:
   - `literature/<arxiv_id>/audit.json`
   - `literature/<arxiv_id>/arxiv_source/`
   - the monthly JSON referenced by `audit.source_note_json`
2. Run the inventory helper:

   ```bash
   conda run -n stella-env python scripts/inventory_catalog_candidates.py --arxiv-id <arxiv_id>
   ```

   Treat inventory output as a reading map only.
3. Read the main `.tex`, relevant `\input`/`\include` files, table surroundings,
   abstract/conclusion, appendix, acknowledgements, and data-availability text.
4. Record all structured data assets visible in the paper:
   - `internal_tables`: LaTeX tables in the paper source.
   - `external_resources`: external or local resources mentioned by the paper.
5. For every internal table, record its full-paper role and visible column
   meanings in `columns[]`. For external resources, record only
   declared/expected data units visible in the paper; do not claim the remote
   file was verified.
6. Rebuild the workflow index:

   ```bash
   conda run -n stella-env python scripts/build_catalog_index.py
   ```

## Review Boundaries

Include all structured data assets, not only high-velocity-star object catalogs:

- object/candidate tables
- observation logs
- sample summaries
- model/fit parameter tables
- follow-up measurement tables
- data-availability resources
- local or external machine-readable files
- ReadMe or metadata resources referenced by the paper

If an inventory candidate is not a structured data asset, simply omit it. The
review should not decide whether an asset is HVS data; later workflows handle
HVS extraction and normalization.

## Output Schema

Use `schema_version: "stella.article_data_assets.review.v1"`.

```json
{
  "schema_version": "stella.article_data_assets.review.v1",
  "paper": {
    "arxiv_id": "2402.10714",
    "title": "",
    "month": "2024-02",
    "source_note_json": "notes/2024/2024-02/2024-02.json",
    "links": {"abs": "", "pdf": ""}
  },
  "source": {
    "paper_dir": "literature/2402.10714",
    "audit_path": "literature/2402.10714/audit.json",
    "source_dir": "literature/2402.10714/arxiv_source",
    "tex_root": "literature/2402.10714/arxiv_source/main.tex",
    "source_available": true
  },
  "review": {
    "status": "reviewed",
    "reviewed_at": "YYYY-MM-DDTHH:MM:SS",
    "reviewer": "agent",
    "summary": ""
  },
  "internal_tables": [
    {
      "id": "table-1",
      "kind": "latex_table",
      "asset_type": "object_measurement_table",
      "role_in_paper": "",
      "source_refs": [
        {
          "path": "literature/2402.10714/arxiv_source/main.tex",
          "start_line": 10,
          "end_line": 40,
          "caption": "",
          "label": ""
        }
      ],
      "columns": [
        {
          "name": "",
          "meaning": "",
          "unit_text": "",
          "source_of_definition": "",
          "confidence": 0.0
        }
      ],
      "evidence": "",
      "comments": ""
    }
  ],
  "external_resources": [
    {
      "id": "resource-1",
      "kind": "external_url",
      "url": "",
      "local_path": "",
      "role_in_paper": "",
      "source_refs": [
        {
          "path": "",
          "start_line": 0,
          "end_line": 0,
          "context": ""
        }
      ],
      "declared_data_units": [
        {
          "name": "",
          "meaning": "",
          "unit_text": "",
          "source_of_definition": "",
          "confidence": 0.0
        }
      ],
      "evidence": "",
      "comments": ""
    }
  ]
}
```

Allowed `review.status` values: `reviewed`, `partial`, `needs_review`,
`source_missing`.

Suggested `asset_type` values: `object_measurement_table`, `observation_log`,
`sample_summary`, `model_parameter_table`, `fit_result_table`,
`external_machine_readable_table`, `readme_or_metadata`,
`data_availability_resource`, `other_structured_data`.

For `external_resources`, use `local_path` only when it points to an already
archived local resource. Remote resources are downloaded only by
`hvs-catalog-extraction`.
