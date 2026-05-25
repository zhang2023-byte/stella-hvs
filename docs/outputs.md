# Outputs

This is the data contract reference. For workflow entry points, use
`workflows/stella_workflows.yaml`, `docs/human-workflows.md`, and
`docs/agent-workflows.md`.

JSON is the canonical output. Markdown is a reading view generated from JSON.

## Canonical Data

```text
literature/<arxiv_id>/    Local literature asset directory
literature/<arxiv_id>/catalog_review.json   Paper-level structured data asset review source of truth
literature/<arxiv_id>/catalog_extraction.json   Paper-level internal table extraction source of truth
literature/<arxiv_id>/literature_hvs_candidates.json   Paper-level HVS/unbound candidate extraction source of truth
literature/01_literature_catalog_index.json       Global data asset workflow index rebuilt from catalog_review.json and catalog_extraction.json
catalog/candidates/<object_id>.json                       Object-level HVS candidate merge result
catalog/03_hvs_candidates_index.json              Object-level HVS candidate catalog index
notes/00_literature_notes_index.json              Global index rebuilt from monthly JSON
notes/YYYY/YYYY-MM/YYYY-MM.json                Monthly normalized records
notes/YYYY/YYYY-MM/YYYY-MM.title-triage.json   Monthly title triage and review records
```

## Generated Files

```text
literature/<arxiv_id>/audit.json   Per-paper asset fetch audit record
literature/<arxiv_id>/arxiv_abs.html
literature/<arxiv_id>/arxiv.pdf
literature/<arxiv_id>/arxiv_source*
literature/<arxiv_id>/arxiv_source/...
literature/<arxiv_id>/ads_metadata.json
literature/<arxiv_id>/catalog_sources/<internal_table_id>/excerpt.tex
literature/<arxiv_id>/catalog_sources/<internal_table_id>/latexml.html
literature/<arxiv_id>/catalog_sources/<internal_table_id>/latexml.stderr.txt
literature/<arxiv_id>/catalog_sources/<internal_table_id>/pandoc.html
literature/<arxiv_id>/catalog_sources/<internal_table_id>/pandoc.stderr.txt
literature/<arxiv_id>/catalog_tables/<internal_table_id>.ecsv
literature/01_literature_catalog_index.md        Data asset workflow view generated from 01_literature_catalog_index.json
catalog/03_hvs_candidates_index.md               Object-level HVS catalog view generated from catalog/03_hvs_candidates_index.json
catalog/html/live/index.html                          Object-level HVS catalog display page that reads catalog/ live
catalog/html/static/index.html                        Single-file HTML demo with the current catalog/ snapshot embedded
notes/00_literature_notes_index.md               Yearly view generated from 00_literature_notes_index.json
notes/YYYY/YYYY-MM/YYYY-MM.md                 Monthly note generated from monthly JSON
```

Table extraction uses:

```text
literature/<arxiv_id>/catalog_sources/   Original LaTeX excerpts and conversion artifacts; stdout/stderr are stored as files, and extraction JSON records only paths
literature/<arxiv_id>/catalog_tables/    Faithful ECSV tables
```

## Local Logs

```text
logs/arxiv_metadata_<timestamp>.json
logs/partial_<timestamp>.json
logs/runs.jsonl
logs/run_<timestamp>.log
```

`logs/` is not committed to Git. `literature/` is also ignored by default. `catalog/` is an object-level catalog generated from paper-level JSON and is ignored by default as well.

## Monthly JSON

Monthly JSON includes:

- Time range and `run_id`.
- Effective search parameters.
- Search logs for each query/category.
- Month filtering statistics.
- arXiv metadata backfill statistics.
- Final high-velocity-star relevance decisions and papers written to the monthly note.
- Matched query and category.
- Abstract returned by search.
- Optional `catalog_assessment`.
- Optional `catalog_assessment_context.deepxiv_brief`.

## Title Triage JSON

Title triage JSON includes:

- Rule-related papers: `rule_related_papers`.
- Papers with no clear title evidence: `no_clear_title_evidence_papers`.
- When `--llm-review True` is enabled, the latter also includes `review`.
- Monthly search logs and filtering statistics.

## Monthly Markdown

Monthly Markdown is organized as follows:

- It lists only papers finally included in the monthly note.
- It no longer displays direct/weak relevance tiers.
- The header keeps counts for rule triage, LLM review, and final inclusion.
- If `catalog_assessment` exists, it is displayed next to the corresponding paper.

## `catalog_assessment_context`

`catalog_assessment_context` includes:

- `deepxiv_brief.source`
- `deepxiv_brief.fetched`
- `deepxiv_brief.error`
- `deepxiv_brief.tldr`
- `deepxiv_brief.keywords`
- `deepxiv_brief.citations`
- `deepxiv_brief.fetched_at`

Section excerpts are not persisted here. The final introduction paragraph and first paragraphs of sections are only temporary context during `catalog_assessment`.

## `literature/` Audit Records

Each audit record includes:

- `arxiv_id`
- `title`
- `month`
- `source_note_json`
- `folder_name`
- `run_at`
- `ads_metadata`: only the `local_path` for the full ADS API metadata JSON
- `ads_api`
- `arxiv_abs`
- `arxiv_pdf`
- `arxiv_source`

Each asset status records:

- `url`
- `success`
- `status_code`
- `content_type`
- `final_url`
- `local_path`
- `size_bytes`
- `error`

Asset downloads only allow public HTTP(S) and stream up to size limits. If a safety boundary or size limit blocks a download, the asset record stores the corresponding error. Source archive extraction rejects absolute paths, `..`, and writes outside the extraction directory.

`arxiv_source` additionally records:

- `extracted`
- `extract_dir`
- `extract_error`
- `extract_skipped_existing`
- `source_unavailable_on_arxiv`
- `source_unavailable_reason`

## `catalog_review.json`

`catalog_review.json` is the structured data asset inventory produced by an agent after reviewing the paper text. It does not mean table extraction is complete, and it does not decide whether the assets are high-velocity-star catalogs. The file structure is generated from Pydantic schemas and `scripts/init_catalog_review.py`; agents only fill paper-semantic fields.

- `paper`: arXiv ID, title, month, monthly JSON path, abs/pdf links.
- `source`: paper directory, `audit.json`, source directory, main TeX, source availability.
- `review`: data asset review status, time, reviewer, and summary.
- `internal_tables`: structured LaTeX tables inside the paper, including their role in context and visible `columns[]` definitions.
- `external_resources`: external or local resources declared or cited by the paper, with paper descriptions, links, paths, evidence, and notes.

This stage stores only LaTeX snippets, links, paths, evidence, internal-table `columns[]` descriptions, and external-resource descriptions from the paper. It does not convert LaTeX to ECSV, download external resources, analyze remote resource internals, or perform HVS filtering. `external_resources[].local_path` only means an already archived local resource. After completion, run `scripts/validate_catalog_review.py --require-complete` to validate structure, enums, paths, source line refs, and remaining template blanks.

## `catalog_extraction.json`

`catalog_extraction.json` is the source of truth for preserving and converting internal LaTeX tables. Its input is the `internal_tables` list from `catalog_review.json`.

- `paper`: arXiv ID, title, month.
- `review`: source `catalog_review.json` path, schema, and review status.
- `run`: one current extraction run with parameters, success/failure statistics, and status; run history is not accumulated.
- `files`: original TeX excerpts, checksums, save status, and errors.
- `tables`: ECSV paths, captions, labels, row/column counts, parse status, converter/parser attempts, warnings, and observed column records.

ECSV uses stable names such as `col_001` and `col_002` and preserves paper table data as faithfully as possible. Extraction does not record manual scientific semantics or a normalized object schema; HVS object recognition and normalization happen later. The file is generated by `scripts/extract_catalog_tables.py` and validated with Pydantic before writing. Final checks can include `scripts/validate_catalog_extraction.py --require-reviewed` to prevent downstream processing from a `needs_review` template.

## `literature_hvs_candidates.json`

`literature_hvs_candidates.json` is the source of truth for HVS/unbound candidates in one paper that may be unbound from the Milky Way/Galactic potential or escaping from it. Extraction is driven by the paper text. `catalog_review.json`, `catalog_extraction.json`, and generated ECSV files are only used to locate tables and quantities. The skeleton is generated from Pydantic schemas by `scripts/init_hvs_candidates.py`; agents fill candidates, method chains, quantities, and provenance.

- `paper`: arXiv ID, bibcode from `ads_metadata.json` referenced by `audit.json`, title, month, monthly JSON path, abs/pdf links.
- `inputs`: paper directory, review/extraction JSON, and ECSV paths used for this extraction.
- `extraction`: candidate extraction status, time, actor, and summary.
- `method_chain`: paper-level atomic method DAG, including survey inputs, sample selection, quality filtering, distance estimation, RV measurement, velocity calculation, potential model, orbit integration, bound probability, or escape assessment. IDs use local `step-01`, `step-02` order, `step_type` uses the controlled vocabulary, and `depends_on[]` lists only direct upstream steps.
- `candidates`: text-evidence-anchored Galactic-unbound HVS/unbound candidates. Each candidate includes `identifiers`, `inclusion_assessment`, `candidate_origin`, observed 6D phase space, derived kinematics, bound assessment, typed photometry/spectroscopy/stellar/abundance/orbit/origin groups, and `extra[]` only for values that do not fit typed groups.
- `candidate_groups_considered`: reviewed but excluded candidate groups, tables, or object sets, especially for `no_candidates` results.

Candidate identifiers are standardized under `identifiers`: `record_id` is the Stella internal ID in the form `<arxiv_id>:cand-001` and does not enter `identifiers.all[]`; `paper_candidate_id` is the paper's preferred display name; `gaia_source_id` is empty or a strict `Gaia DR3/EDR3/DR2 ...` machine-match identifier; `all[]` records all names, numbers, and Gaia source IDs that actually appear in the paper, each with `source_refs`. Non-empty `paper_candidate_id` and `gaia_source_id` must also appear in `all[]`.

Candidate inclusion must come from the paper text itself: the paper must explicitly discuss, list, or evaluate the object as a possible HVS, unbound, escaping, hyper-runaway, or equivalent candidate from the Milky Way/Galactic potential. Ordinary runaways, cluster escapers, local-GC-unbound objects described as still bound to the Galaxy, and objects already judged bound by the paper do not enter `candidates[]`. A fixed velocity threshold can only be a sanity check, not the sole inclusion reason.

`inclusion_assessment` records non-exclusive `paper_labels[]`, the mutually exclusive `galactic_bound_claim`, `inclusion_basis`, and agent `extraction_confidence` (`high`, `medium`, or `low`) with a required reason. It is not a physical probability field.

`candidate_origin.origin_type` distinguishes `introduced_by_this_paper` from `cited_from_literature`. "Introduced" means this paper first presents the object as a possible Galactic-unbound/HVS candidate. Known objects that are reanalyzed by the paper are marked `cited_from_literature`, with `paper_reassesses_unbound_status=true` when the paper reassesses the status. Cited candidates must include text citation lines in `citation_context_refs` and `.bib`/`.bbl` entries in `bibliography_refs`; non-empty citation metadata fields must be supported by those bibliography lines.

Every `core`, typed-group, and `extra[]` quantity must include `raw_value`, cleaned `value`, per-value source provenance, and field-level direct-producer `method_refs`. `raw_value` must stay consistent with the ECSV cell or source-text value for traceability. `value`, `error`, `lower_error`, and `upper_error` are machine-readable and cannot keep LaTeX commands, braces, `$`, `_`, `^`, or `+/-`. Numeric core and typed quantitative machine fields should be single plain numbers; ranges, limits, units, footnotes, and explanatory text stay in `raw_value` or `description`. Bound/unbound probabilities live under `core.bound_assessment` as unitless 0-1 values. Origin/model probabilities, p-values, and likelihood ratios live under `astrophysical_origin.hypothesis_metrics[]`.

RA/Dec may preserve decimal-degree or sexagesimal values from the paper, but `coordinate_format` must state the notation. Frame and epoch belong in the internal `reference_frame` and `epoch` objects under the RA/Dec record, and `unit` stores only the real coordinate unit. ECSV references need exact file path, physical line number, machine column name, column header, and raw cell text. If one cell contains both RA and Dec, the source ref `raw_value` keeps the full cell, the quantity-level `raw_value` keeps only the current component, and `component_raw_value` connects them. Text sources need exact TeX/text paths and line ranges. `method_refs` reference the direct `method_chain[]` `step-XX` ID in the same file; full lineage is recovered recursively from `depends_on[]`.

## Object-Level `catalog/`

`catalog/` is the object-level HVS candidates catalog merged from all paper-level `literature_hvs_candidates.json` files. It is generated by `scripts/merge_hvs_candidate_catalog.py` and should not be manually modified.

Each `catalog/candidates/<object_id>.json` uses `schema_version: stella.hvs_candidate_catalog.object.v5` and contains:

- `object_id`: stable object ID used as the filename. Gaia IDs use a normalized Gaia release-family slug; EDR3 and DR3 source IDs with the same numeric source ID use `Gaia_DR3_<source_id>`. Non-Gaia objects use a strong paper candidate ID when available, preserving ASCII `+` and `-`, otherwise a J2000-style coordinate slug, otherwise a source record slug.
- `canonical_identifier`: object-level preferred identifier and its source short ID.
- `sources[]`: each paper-level candidate source, including `source`, original `paper` field, source JSON path, `record_id`, `paper_candidate_id`, and `gaia_source_id`.
- `method_chain[]`: source-grouped paper-level method chains, preserving local `step-XX` IDs and removing `source_refs`.
- `candidates[]`: source-grouped compact candidate records with `identifiers`, `candidate_context`, compact `core`, and compact typed quantity groups: `photometry`, `spectroscopy`, `stellar_parameters`, `abundances`, `quality_flags`, `orbit`, `astrophysical_origin`, and `extra`.
- `external_enrichment`: post-merge official SIMBAD and Gaia DR3 data, provider statuses, raw non-empty query columns, selected highlights, identifier/coordinate verification, value comparisons, and enrichment warnings.
- `merge.evidence[]`: machine-readable edges used or considered for object grouping, including evidence type, source, decision, matched value, record refs, and coordinate separation when available.
- `merge.warnings[]`: Gaia/coordinate conflicts, coordinate parse failures, and other issues needing review.

Object-level candidate quantities keep only `value`, non-empty uncertainty fields, `unit`, `method_refs`, and small typed semantic fields such as photometric band, abundance element, quality-flag name, or hypothesis metric type. They do not keep `raw_value`, `source_refs`, `description`, `kind`, coordinate frame/epoch, or coordinate format. `candidate_context` keeps compact inclusion/origin metadata and compact citation metadata when present. Full provenance remains in the paper-level `literature_hvs_candidates.json`.

`external_enrichment` is generated by the default `--enrichment-mode auto` merge behavior. It queries public SIMBAD and Gaia DR3 TAP services through `astroquery`, and it can be disabled with `--enrichment-mode off` or made strict with `--enrichment-mode required`. Enrichment values do not overwrite paper-level quantities. With default `--external-merge-mode auto`, high-confidence external Gaia/SIMBAD identity evidence can also appear in `merge.evidence[]` and affect grouping; use `--external-merge-mode off` for the old Gaia/coordinate-only behavior or `review` to list potential external/alias merges without applying them.

Merge rules:

- Same normalized literature Gaia source ID: merge. `Gaia EDR3 <source_id>` and `Gaia DR3 <source_id>` are the same DR3-family match key, while DR2 remains separate.
- Same external Gaia DR3 source ID or same SIMBAD object: merge only when literature Gaia IDs do not conflict.
- Same strong alias: merge when both records lack coordinates or their RA/Dec separation is `<5 arcsec`; alias-only merges without coordinate sanity checks write warnings.
- Coordinate-only matches require `<5 arcsec`, no Gaia/SIMBAD identity conflict, and a unique coordinate neighbor in auto mode. Different Gaia IDs or far coordinates become warnings instead of forced merges.
- Other official values such as parallax, proper motion, RV, photometry, and stellar parameters are sanity checks in `external_enrichment.verification.value_comparisons`; they do not drive grouping.

`catalog/03_hvs_candidates_index.json` summarizes object count, source count, merge warnings, process warnings, potential review merges, enrichment statuses, enrichment warnings, skipped inputs, and each object link. `catalog/03_hvs_candidates_index.md` is the generated reading view. For strict rebuilds, run `scripts/merge_hvs_candidate_catalog.py ... --fail-on-skipped` so malformed paper-level inputs fail the command instead of only appearing in `skipped[]`; add `--enrichment-mode required` when SIMBAD/Gaia enrichment failures should also fail the command.

## `catalog/html/` Display Pages

`catalog/html/` is the web display layer for the object-level HVS catalog, generated by `scripts/build_hvs_catalog_html.py`. The source of truth remains `catalog/candidates/*.json`.

- `catalog/html/live/`: under a local HTTP server, reads `catalog/03_hvs_candidates_index.json` and each `catalog/candidates/<object_id>.json` live. Refreshing the page reflects catalog updates.
- `catalog/html/static/index.html`: a single-file snapshot with catalog data, CSS, JS, and local visual assets embedded at build time. It has no CDN or remote image dependency and is suitable for quick demos.

The home page shows Stella's vision, object-level statistics, and the HVS object index. The index lists identifier, bibcode, RA, Dec, plx, pmRA, pmDec, RV, total velocity, unbound probability, and the detail entry. Multi-source objects are shown as source-specific rows so values from different papers are not overwritten. Detail pages show source cards, method chain DAGs, candidate core fields, and the full object-level JSON. Clicking a quantity highlights its direct `method_refs`, recursive upstream steps, and dependency edges.

## Index Files

`notes/00_literature_notes_index.json` stores:

- Statistics grouped by year.
- A flat `papers` list of all papers.

`notes/00_literature_notes_index.md` emphasizes:

- Paper counts by year.
- Recent papers.
- Papers judged data-related by `catalog_assessment`.

`literature/01_literature_catalog_index.json` stores:

- A summary of papers with `catalog_review.json`.
- Review status, status notes, internal table count, and external resource count.
- Whether `catalog_extraction.json` exists, current internal-table extraction status, and table/excerpt success/failure counts.
- Yearly review, data asset, and extraction statistics.

`literature/01_literature_catalog_index.md` emphasizes:

- Review and extraction status for each reviewed or pending paper.
- Data asset counts, including internal tables and external resources.
- Internal table and excerpt extraction progress.
- Links to per-paper `catalog_review.json` and `catalog_extraction.json`.

`01_literature_catalog_index` keeps review status and extraction status as independent axes:

- review `reviewed`: data asset review is complete in the available paper/source context.
- review `partial`: data asset review is incomplete, or candidate coverage has unresolved issues.
- review `needs_review`: data asset review is not complete.
- review `source_missing`: source-based review is impossible; if source metadata also says source is available, Markdown marks the inconsistency with `(!)`.
- extraction `success`: the current extraction run has no table or file failures.
- extraction `partial`: the current extraction produced at least one table or file but also has failures.
- extraction `failed`: the current extraction or manifest read failed.
- extraction `not_started`: review found internal tables but there is no `catalog_extraction.json`.
- extraction `not_applicable`: review found no internal tables; extraction is not needed even if external resources exist.

`catalog/03_hvs_candidates_index.json` stores:

- Total object-level HVS candidates, total sources, warning count, process warning count, and potential merge count.
- Enrichment status counts and enrichment warning count.
- Each object's canonical identifier, object JSON path, source count, Gaia source IDs, paper candidate IDs, evidence count, and enrichment status.
- Merge warnings, potential review merges, enrichment warnings, and skipped input files.

`catalog/03_hvs_candidates_index.md` emphasizes:

- Each object's JSON link and source count.
- Object-level Gaia/paper identifiers.
- Merge warnings, potential merges, and enrichment warnings that need manual review.

## Main Log Events

```text
start
query
arxiv_metadata
classify
month_done
partial_finish
finish
```
