---
name: hvs-catalog-review
description: "Review archived Stella papers to build an article data-asset inventory: internal LaTeX tables with columns, plus external resources described from the paper text. This stage does not decide whether assets are high-velocity-star catalogs and does not download external resources."
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
   meanings in `columns[]`. For every external resource, record only a
   per-resource description grounded in the paper text; do not infer or analyze
   remote-file structure or schema.
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

## Fidelity Rules

- **Do not invent URLs.** Every value in `external_resources[].url` must be
  copied verbatim from the paper source (tex, bib, or ancillary files). If the
  paper mentions a resource but does not give a concrete URL, leave `url` as an
  empty string. Never "fill in" a missing URL with what "ought to be" the
  address (e.g. turning "available at the CDS" into `https://cds.u-strasbg.fr/`).
- **Do not record generic database acknowledgements as external resources.**
  A sentence like "This research has made use of the SIMBAD database" in the
  Acknowledgements section is not a structured data asset; omit it.

## Schema Reference

Read `references/schema.md` before writing `catalog_review.json`. Use
`schema_version: "stella.article_data_assets.review.v1"`.

The top-level sections are:

- `paper`: paper identity, month, note source, and links.
- `source`: archived source locations and source availability.
- `review`: review status, timestamp, reviewer, and summary.
- `internal_tables`: structured tables visible in the paper source, including
  source refs, full-paper role, and visible column meanings.
- `external_resources`: paper-described resources, URLs, local paths, evidence,
  and comments.

Allowed `review.status` values are `reviewed`, `partial`, `needs_review`, and
`source_missing`.
