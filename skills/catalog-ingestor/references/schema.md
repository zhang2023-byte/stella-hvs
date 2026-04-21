# Catalog Ingestion Schema

This skill uses three machine-readable files under `literature/<arxiv_id>/catalog_ingest/`.

## `manifest.json`

Purpose:
- enumerate extracted candidate tables
- record their provenance
- record which ones look like true catalogs versus supporting tables

Important fields:
- `verification_summary`: effective paper-level verification status from the paper record
- `catalog_candidates[*].catalog_id`: stable identifier for one extracted table
- `catalog_candidates[*].catalog_role_hint`: bootstrap hint such as `candidate_catalog`, `schema_definition`, or `schema_or_supporting`
- `catalog_candidates[*].schema_field_count`: when a schema-definition table is recognized, how many real catalog fields it describes
- `catalog_candidates[*].selected_for_ingest`: set during agent review when the table should become part of Stella's data layer

## `field_definitions.json`

Purpose:
- capture what each source column means in the paper's own language

Important fields:
- `source_column`: the best available source name from the extracted CSV or source header
- `record_header` / `csv_header`: raw provenance for the field name
- `units_hint`: unit string extracted from the source table when available
- `definition`: short meaning in the paper's own context
- `semantic_type`: compact category like `object_id`, `coordinate`, `astrometry`, `radial_velocity`, `chemistry`, `classification`, `orbit_result`, `quality_flag`, `provenance`
- `standardized_name`: proposed Stella-side normalized name
- `object_identifier`: whether this field can identify or join stellar objects

## `column_mapping.json`

Purpose:
- capture how source columns should map into Stella's normalized ontology / data model

Important fields:
- `standardized_name`: target normalized column name
- `semantic_group`: broader bucket for downstream ingestion
- `unit`: target unit expectation
- `transform`: any conversion or normalization needed before ingest
- `confidence`: `high|medium|low|pending`

## Practical Rule

When in doubt:

- write paper-specific meaning into `field_definitions.json`
- reserve cross-paper normalization decisions for `column_mapping.json`

If a table is recognized as `schema_definition`, the bootstrapper may already expand
its row labels into drafted field entries and first-pass column mappings. Review those
drafts, but do not throw them away and retype them in chat.

That split helps Stella preserve provenance without blocking ingestion on full ontology design.
