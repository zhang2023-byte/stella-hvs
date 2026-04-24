---
name: hvs-catalog-review
description: Review archived high-velocity-star papers in Stella to identify object-level catalog tables and data resources from local TeX/source files, then write literature/<arxiv_id>/catalog_review.json. Use when asked to inspect catalog tables, source TeX, machine-readable files, or external catalog resources for a paper.
---

# HVS Catalog Review

Use this skill inside Stella after paper assets have been archived under `literature/<arxiv_id>/`.

This is a review workflow, not a table-extraction workflow. Do not convert LaTeX to CSV, parse FITS, or download external tables in this stage. The output is a machine-readable judgment record: `literature/<arxiv_id>/catalog_review.json`.

## Workflow

1. Inspect the paper archive:
   - `literature/<arxiv_id>/audit.json`
   - `literature/<arxiv_id>/arxiv_source/`
   - the related monthly JSON referenced by `audit.source_note_json`
2. Run the local inventory helper:

   ```bash
   conda run -n stella-env python scripts/inventory_catalog_candidates.py --arxiv-id <arxiv_id>
   ```

   Treat inventory output as a reading map only. It is not a decision.
3. Read the main `.tex` file, relevant `\input`/`\include` files, table surroundings, abstract/conclusion, and any data-availability or acknowledgements text.
4. Decide which candidates are true high-velocity-star object catalogs. Include only tables or resources that list, describe, or point to object-level stellar data: object names/IDs, coordinates, astrometry, radial velocities, spectra, abundances, orbit quantities, candidate flags, or follow-up measurements.
5. Write `catalog_review.json` with included, external, rejected, and uncertain candidates. Keep evidence short but specific.
6. Rebuild the global index:

   ```bash
   conda run -n stella-env python scripts/build_catalog_index.py
   ```

## Review Boundaries

Include:

- New or compiled high-velocity, hypervelocity, runaway, escaping, unbound, high-speed, or ejected star candidate/object tables.
- Single-object tables when they provide object-level measurements for a target high-velocity star.
- External or local machine-readable resources that are explicitly the paper's object catalog or table data.

Reject:

- General survey descriptions without a paper-specific object catalog.
- Simulation-only tables, model grids, population summaries, observing logs, or figures without object-level catalog values.
- Non-stellar high-velocity objects unless the paper clearly connects them to stellar object catalogs.

If uncertain, keep the candidate out of `catalog_candidates` and put it in `rejected_candidates` with `decision: "uncertain"` and a comment explaining what would resolve it.

## Output Schema

Use `schema_version: "stella.hvs_catalog.review.v1"`.

```json
{
  "schema_version": "stella.hvs_catalog.review.v1",
  "paper": {
    "arxiv_id": "2402.10714",
    "title": "",
    "month": "2024-02",
    "source_note_json": "notes/2024/2024-02/2024-02.json",
    "links": {
      "abs": "",
      "pdf": ""
    }
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
  "catalog_candidates": [
    {
      "id": "table-1",
      "kind": "latex_table",
      "catalog_role": "new_catalog",
      "object_scope": "multiple_objects",
      "data_products": ["source_ids", "coordinates", "astrometry"],
      "source_refs": [
        {
          "path": "literature/2402.10714/arxiv_source/main.tex",
          "start_line": 10,
          "end_line": 40,
          "caption": "",
          "label": ""
        }
      ],
      "latex_excerpt": "",
      "columns": [
        {"name": "Gaia DR3 source_id", "meaning": "stellar source identifier"}
      ],
      "meaning": "",
      "evidence": "",
      "confidence": 0.0,
      "comments": ""
    }
  ],
  "external_resources": [
    {
      "id": "resource-1",
      "kind": "external_url",
      "url": "",
      "local_path": "",
      "meaning": "",
      "evidence": "",
      "comments": ""
    }
  ],
  "rejected_candidates": [
    {
      "id": "rejected-1",
      "kind": "latex_table",
      "source_ref": {
        "path": "",
        "start_line": 0,
        "end_line": 0,
        "caption": "",
        "label": ""
      },
      "decision": "rejected",
      "reason": ""
    }
  ]
}
```

Allowed `review.status` values: `reviewed`, `partial`, `needs_review`, `source_missing`.

Suggested `catalog_role` values: `new_catalog`, `compiled_catalog`, `followup_observations`, `uses_existing_catalog`, `unclear`.

Suggested `object_scope` values: `single_object`, `multiple_objects`, `none`, `unclear`.
