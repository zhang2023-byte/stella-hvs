---
name: catalog-ingestor
version: 0.2.0
description: Use when the goal is no longer just deciding whether a paper has a catalog, but actually organizing that catalog into machine-readable Stella ingestion artifacts. Especially useful after paper-level catalog verification is done and you need manifest files, per-field meanings, column mappings, and a reproducible bridge from extracted tables into the high-velocity-star knowledge base.
---

# Catalog Ingestor

Use this skill after a paper has already passed catalog verification and the task shifts from literature triage to catalog ingestion.

This skill is for questions like:

- which extracted tables in `literature/<arxiv_id>/source/catalog_tables/` are the real ingest targets
- what each field in a catalog means
- which columns are object identifiers, astrometry, radial velocities, chemistry, or provenance
- how a paper-specific catalog should be mapped into Stella's future object-level knowledge layer

The repository boundary is:

- scripts and code should bootstrap stable JSON scaffolds from existing verification artifacts
- the agent should decide which tables are meaningful catalogs and fill in semantic field definitions and mappings

## Start Here

1. Confirm the paper has already been verified.
Read:
   - `literature/<arxiv_id>/record.json`
   - `literature/<arxiv_id>/summary.md`

2. Bootstrap the ingestion bundle:

```bash
conda run -n stella-env python scripts/init_catalog_ingestion.py --arxiv-id <id>
```

This creates:

- `literature/<arxiv_id>/catalog_ingest/manifest.json`
- `literature/<arxiv_id>/catalog_ingest/field_definitions.json`
- `literature/<arxiv_id>/catalog_ingest/column_mapping.json`

3. Inspect the paper evidence needed to interpret the tables:
   - `literature/<arxiv_id>/source/catalog_tables/*.csv`
   - `literature/<arxiv_id>/source/extracted/*`
   - `literature/<arxiv_id>/deepxiv/raw.md`

4. Decide which tables are real ingest targets.
Do not ingest every extracted table blindly. Distinguish:
   - true catalog tables
   - schema-definition tables that describe the full machine-readable catalog
   - schema/format tables that are only explanatory
   - selection-criteria or QC tables
   - small supporting tables that are not the main catalog

5. Fill semantics into the JSON scaffolds rather than prose notes.

The bootstrap step can now auto-expand a `Label / Unit / Description` schema-definition
table into drafted `field_definitions.json` and `column_mapping.json` entries. Treat
those drafted entries as a starting point: verify them against the paper and then refine
them when needed.

For the exact artifact meanings, read [references/schema.md](references/schema.md).

## Required Output

The ingestion bundle should end up expressing three things:

1. `manifest.json`
Which tables exist, which ones are the likely ingest targets, and what the current ingestion status is.

2. `field_definitions.json`
For each source field, record what it means in the paper's own terms.

3. `column_mapping.json`
For each source field, record how it should map into Stella's normalized ontology layer.

## Judging Table Value

Prefer ingesting tables that contain:

- object identifiers such as Gaia source IDs
- positions or coordinates
- proper motions or parallaxes
- radial velocities
- chemistry, stellar parameters, or orbit-integration outputs tied to actual objects

Be cautious with tables that are only:

- catalog format descriptions
- selection criteria
- quality-control thresholds
- summary counts

## Working Rule

- `field_definitions.json` answers: "What does this source column mean?"
- `column_mapping.json` answers: "Where should this source column land in Stella?"

If a field meaning is uncertain, mark it as pending or unclear in JSON instead of guessing.

## Persistence Rule

Do not store the important interpretation only in markdown or chat.
Update the ingestion JSON files directly so the work can survive across agent sessions.
