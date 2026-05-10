---
name: hvs-catalog-extraction
description: Extract reviewed high-velocity-star catalog tables in Stella after catalog_review.json exists. Use LaTeXML/Pandoc/project fallback tools for internal LaTeX tables and bounded local/URL/ADS handling for external catalog sources, then manually review catalog_extraction.json with per-column physical meanings, usage notes, join keys, caveats, and provenance.
---

# HVS Catalog Extraction

Use this skill inside Stella after `literature/<arxiv_id>/catalog_review.json`
has been written by the `hvs-catalog-review` workflow.

This is the extraction-and-meaning workflow. It may write:

```text
literature/<arxiv_id>/catalog_extraction.json
literature/<arxiv_id>/catalog_sources/<internal_table_id>/excerpt.tex
literature/<arxiv_id>/catalog_sources/<internal_table_id>/latexml.html
literature/<arxiv_id>/catalog_sources/<internal_table_id>/pandoc.html
literature/<arxiv_id>/catalog_sources/<external_source_id>/download-001.*
literature/<arxiv_id>/catalog_tables/<internal_table_id>.csv
literature/<arxiv_id>/catalog_tables/<external_source_id>.csv
```

Do not edit generated CSV by hand. If table conversion is wrong, improve or rerun
the extraction command. Do edit `catalog_extraction.json` to fill semantic fields.

## Workflow

1. Confirm prerequisites:
   - `catalog_review.json` exists and has reviewed `internal_tables`.
   - `external_catalog_sources` entries are ready for local machine-readable file
     parsing, explicit URL fetch, or bounded ADS Agent location. TeX evidence
     belongs in `source_refs`, not `local_path`.
   - `latexmlc` is available; if not, continue but note fallback behavior.
2. Run extraction:

   ```bash
   conda run -n stella-env python scripts/extract_catalog_tables.py --arxiv-id <arxiv_id>
   ```

   Use `--internal-table-id <id>` for one LaTeX table, `--external-source-id <id>` for one
   external catalog source, `--dry-run True` before risky bulk runs, and `--overwrite True`
   only when regenerating stale conversion artifacts.
   `--fetch-external Auto` enables network for one paper and disables it for
   `--all-reviewed`; local files are still parsed.
   For full reruns, use `--jobs Auto` to parallelize by paper when external pages
   or Agent locator calls dominate runtime. Auto scales up to 12 workers for
   100+ papers by default. Use `--jobs N` when the user asks for an exact
   concurrency level, or `--jobs 1` when debugging a single failure or avoiding
   concurrent API calls.
   The CLI default `--provider-resolver On` first uses deterministic resolvers
   for known external providers: ADS abstract pages are entrypoints to data
   products/catalog records, CDS/VizieR pages are resolved through catalog IDs,
   Zenodo records through the records API, and NADC/China-VO resource pages
   through `file_upload/download` links. The CLI default `--agent-locator Always`
   uses the bounded Agent locator only after provider resolvers fail to produce
   a parseable machine-readable candidate, or for non-provider HTML landing pages.
   The Agent sees extracted page/link context, treats webpage text as untrusted,
   returns only candidate IDs, and the script still validates URL safety, file
   size, type, and table parsing. Use `--agent-locator Off` when the run must
   avoid LLM calls entirely.
   External downloads are bounded by `--max-external-bytes` and only allow public
   HTTP(S) URLs. Supported machine-readable suffixes are `.csv/.tsv/.txt/.dat/.tbl/.mrt/.ecsv/.fits/.fit/.fits.gz/.vot/.votable/.xml`.
3. Inspect `catalog_extraction.json`:
   - `tables[].status`
   - `tables[].extraction_method`
   - `tables[].conversion_attempts`
   - `tables[].warnings`
   - `external_catalog_sources[].resolver_attempts`
   - `external_catalog_sources[].locator_attempts`
   - `external_catalog_sources[].download_attempts`
   - `agent_locator_context.json` / `agent_locator_response.json` when an Agent
     locator attempt was used
   - `external_catalog_sources[].stopped_reason`
   - row/column counts against the source table
4. If conversion failed:
   - Read `conversion_attempts[].stderr_tail`.
   - Inspect saved `latexml.html`, `pandoc.html`, and `excerpt.tex`; the excerpt
     should be present even when parsing failed.
   - If the table is commented out, malformed, or not actually a data table, record
     that in `tables[].error` or `usage.caveats`.
5. For external-resource failures:
   - Treat `network_disabled`, `agent_locator_disabled`, `agent_no_download_candidates`,
     `blocked_url`, `download_too_large`, `ambiguous_placeholder_url`,
     `unsupported_content_type`, `parse_failed`, `ads_no_data_product_links`,
     `ads_catalog_record_unresolved`, `cds_catalog_not_published`,
     `cds_no_machine_readable_tables`, `zenodo_no_matching_files`,
     `nadc_no_download_files`, and `provider_resolver_disabled`
     as bounded outcomes, not invitations to search the web.
   - Do not use search engines, recursive crawling, login flows, or unrelated
     archives unless the user explicitly starts a new task for that resource.
6. For each successfully extracted table, manually fill table usage:
   - `usage.row_entity`
   - `usage.relation_to_paper`
   - `usage.primary_identifier_columns`
   - `usage.join_keys`
   - `usage.recommended_use`
   - `usage.caveats`
   - `usage.semantic_status`
   - `usage.confidence`
7. For every column in every successful table, manually fill:
   - `physical_quantity`
   - `meaning`
   - `data_type` if the automatic guess is wrong
   - `null_values`
   - `source_of_definition`
   - `notes`
   - `semantic_status`
   - `confidence`
8. Preserve provenance. For each semantic claim, cite concise evidence in
   `source_of_definition`, such as caption, table note, table footnote, or a nearby
   paragraph where the table is referenced.
9. Validate JSON and run tests:

   ```bash
   python -m json.tool literature/<arxiv_id>/catalog_extraction.json >/dev/null
   conda run -n stella-env python -m unittest tests.test_catalog_extraction
   ```

## Reading Context for Meanings

Use the table itself, not just the column header.

- Read `catalog_review.json` for `meaning`, `evidence`, `data_products`, and
  `source_refs`.
- Read `catalog_sources/<internal_table_id>/excerpt.tex`.
- For external catalog sources, read `external_catalog_sources[].meaning/evidence`,
  `external_catalog_sources[].source_refs`, `catalog_sources/<external_source_id>/download-*.{csv,txt,fits,vot,xml}`,
  and `sources[].parse_attempts`.
- Read several paragraphs before and after the source line range.
- Search the TeX source for the table label, e.g. `rg "Tab_72dr3|ref\\{Tab_72dr3\\}"`.
- Read caption, `tablefoot`, `tablecomments`, appendix notes, data availability,
  and any section explaining derived quantities.

If a column meaning is uncertain, do not invent it. Set:

```json
"semantic_status": "needs_agent_review",
"confidence": 0.4
```

and explain the ambiguity in `notes`.

## Semantic Conventions

- `row_entity`: usually `stellar object`, `candidate star`, `observation`, or
  `derived orbit/origin result`.
- `physical_quantity`: short normalized phrase, e.g. `Gaia DR3 source identifier`,
  `radial velocity`, `proper motion in right ascension`, `tangential velocity`.
- `meaning`: one complete sentence explaining what the column stores.
- `join_keys`: use paper-visible identifiers only, such as Gaia DR3 source ID,
  object name, or survey ID.
- `recommended_use`: explain whether the table is a main object catalog,
  supporting quality-control table, follow-up measurements table, or derived
  kinematics/origin table.
- `caveats`: record embedded uncertainties, approximate values, selection flags,
  footnotes, missing radial velocities, or values that require later splitting.

## Boundaries

- This stage still preserves the paper's table structure. Do not map to a global
  Stella object schema unless the user explicitly asks for normalization.
- External catalog sources are handled only within strict boundaries: local file,
  explicit URL, deterministic known-provider resolvers, or bounded Agent locator
  fallback. ADS abstract HTML is an entrypoint only; allowed structured hops are
  limited to ADS catalog/data-product, CDS/VizieR, Zenodo, and NADC/China-VO. No
  broad web search, browser automation, login, or recursive crawling.
- Reviewed semantic fields may be preserved on rerun only when source hash and
  column identity still match. If headers or source content changed, review the
  meanings again instead of carrying them forward.
- Markdown is not the fact source. Update JSON first; regenerate views only when
  a renderer exists for this stage.
