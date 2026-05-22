# Usage

This is the low-level CLI reference. For day-to-day natural-language use, start
with `docs/human-workflows.md`; agents should route those requests through
`workflows/stella_workflows.yaml` and `docs/agent-workflows.md`.

## 1. Fetch Literature

Basic run:

```bash
conda run -n stella-env python scripts/fetch_high_velocity_lit.py \
  --from 2026-03
```

One month only:

```bash
conda run -n stella-env python scripts/fetch_high_velocity_lit.py \
  --from 2026-03 \
  --to 2026-03
```

### Common Arguments

```text
--source deepxiv|arxiv       Search backend, default deepxiv; DeepXiv failures fall back to arXiv
--from DATE                  Start date, accepts YYYY-MM-DD, YYYY-MM, or YYYY
--to DATE                    End date, default today
--llm-review True|False      Whether the LLM reviews no-clear-title-evidence papers, default False
--max-results N              Result limit per arXiv query or DeepXiv query/category, default 20
--deepxiv-llm-review-max-candidates N
                             Max no-clear-title-evidence candidates sent to the LLM in DeepXiv mode, default 20
--categories A,B,C           arXiv categories, default astro-ph.GA,astro-ph.SR,astro-ph.IM
--min-score X                DeepXiv score floor, disabled by default
--progress True|False        Show progress bars, default True
--token TOKEN                Override DEEPXIV_TOKEN
--notes-dir PATH             Output directory, default notes
--logs-dir PATH              Log directory, default logs
```

### Defaults

```text
--to                today
--source            deepxiv
--llm-review        False
--max-results       20
--categories        astro-ph.GA,astro-ph.SR,astro-ph.IM
--min-score         disabled
--search-mode       hybrid
--progress          True
--sleep             0.2
--llm-base-url      https://api.openai.com/v1 by default
--llm-model         gpt-4o-mini by default
--llm-batch-size    25
--deepxiv-llm-review-max-candidates 20
--notes-dir         notes
--logs-dir          logs
```

### Notes

- The script prints the effective parameters at startup.
- Secrets are not printed in clear text.
- After deduplication, the script runs rule-based title triage and writes `YYYY-MM.title-triage.json`.
- With `--llm-review True`, only no-clear-title-evidence papers are reviewed by the LLM.
- With `--source deepxiv --llm-review True`, `no-clear-title-evidence` candidates are sorted by DeepXiv score and only the top `--deepxiv-llm-review-max-candidates` are sent to the LLM. The rest stay in `title-triage.json` with `review.status=skipped`.
- The final monthly note includes rule-related papers and papers confirmed relevant by LLM review.
- `fetch_high_velocity_lit.py` no longer calls `DeepXiv brief`.
- Candidate search uses `DeepXiv` by default. If DeepXiv hits quota limits, token/API failures, or other search errors, the remaining searches in that run automatically fall back to the `arXiv API`.
- arXiv candidate search pushes multiple `--categories` into the query as an OR expression, for example `(cat:astro-ph.GA OR cat:astro-ph.SR OR cat:astro-ph.IM)`. DeepXiv searches categories separately and deduplicates the merged results.

## 2. Add Data-Related Assessments

Add `catalog_assessment` to one month:

```bash
conda run -n stella-env python scripts/annotate_catalog_data.py --on 2026-03
```

Add assessments for a range:

```bash
conda run -n stella-env python scripts/annotate_catalog_data.py \
  --from 2025-01 \
  --to 2025-06
```

Add assessments for non-contiguous months:

```bash
conda run -n stella-env python scripts/annotate_catalog_data.py \
  --on 2025-01,2025-03,2026-02
```

### Common Arguments

```text
--on MONTH[,MONTH...]       One or more YYYY-MM months
--from DATE                 Start month or date
--to DATE                   End month or date
--notes-dir PATH            Notes root, default notes
--llm-api-key KEY           Override LLM_API_KEY
--llm-base-url URL          Override LLM_BASE_URL
--llm-model MODEL           Override LLM_MODEL
--llm-batch-size N          LLM batch size, default 25
--render True|False         Refresh Markdown and indexes, default True
--dry-run True|False        Show intended changes only
```

### Notes

- `catalog_assessment` first obtains a `DeepXiv brief` through the local `deepxiv` CLI.
- It also reads the final paragraph of the introduction plus each section title and first paragraph.
- The LLM receives `title + abstract + DeepXiv brief + final introduction paragraph + section titles and first paragraphs + categories`.
- Only `catalog_assessment_context.deepxiv_brief` is written back to monthly JSON; section excerpts are temporary context for the current judgment.
- Rerunning `annotate_catalog_data.py` recomputes existing `catalog_assessment` values.

## 3. Regenerate Markdown

Regenerate all monthly Markdown:

```bash
conda run -n stella-env python scripts/render_lit_notes.py
```

Regenerate one month:

```bash
conda run -n stella-env python scripts/render_lit_notes.py --month 2026-03
```

Rebuild the yearly index:

```bash
conda run -n stella-env python scripts/render_lit_notes.py --index-only
```

## 4. Pull Local Literature Assets

Pull local assets for data-related papers in a range:

```bash
conda run -n stella-env python scripts/pull_literature_assets.py \
  --from 2024-01 \
  --to 2026-04
```

Pull only selected months:

```bash
conda run -n stella-env python scripts/pull_literature_assets.py \
  --on 2025-07,2025-11
```

Pull only selected papers:

```bash
conda run -n stella-env python scripts/pull_literature_assets.py \
  --arxiv-id 2402.10714,2507.07558
```

### Common Arguments

```text
--on MONTH[,MONTH...]       One or more YYYY-MM months
--from DATE                 Start month or date
--to DATE                   End month or date
--arxiv-id ID[,ID...]       Specific arXiv IDs
--notes-dir PATH            Notes root, default notes
--literature-dir PATH       Literature archive root, default literature
--timeout N                 Per-request timeout in seconds, default 60
--ads-token TOKEN           Override ADS_API_TOKEN / ADS_TOKEN
--dry-run True|False        Parse the selection without downloading, default False
```

### Notes

- Only papers in `notes/` with `catalog_assessment.has_observational_catalog == true` are processed.
- Each paper is written to `literature/<arxiv_id>/`.
- By default, the workflow tries to save the arXiv abs page HTML, arXiv PDF, arXiv source when the response looks like a source package, extracted `arxiv_source/`, and NASA ADS API metadata JSON for paper-level ADS bibcodes.
- Each paper gets an `audit.json` with success/failure status for every asset.
- Downloads allow only public HTTP(S), reject localhost/private/special addresses, and stream PDF/source downloads with size limits.
- Source extraction rejects absolute paths, `..`, and archive members that would write outside the extraction directory.

## 5. Repair ADS Metadata and Paper-Level Bibcodes

If an archive lacks `ads_metadata.json`, or `audit.json` lacks `ads_metadata.local_path`, scan all archived papers and retry the ADS API:

```bash
conda run -n stella-env python scripts/repair_ads_metadata.py
```

Check only, without writing files:

```bash
conda run -n stella-env python scripts/repair_ads_metadata.py \
  --dry-run True
```

Repair selected papers:

```bash
conda run -n stella-env python scripts/repair_ads_metadata.py \
  --arxiv-id 2402.10714,2507.07558
```

Force-refresh ADS API metadata JSON for all archived papers:

```bash
conda run -n stella-env python scripts/repair_ads_metadata.py \
  --force True
```

The script updates `audit.json` `ads_api` and `ads_metadata`. `ads_metadata` records only the `local_path` of the complete ADS API metadata JSON. If `literature_hvs_candidates.json` exists, the script only fills `paper.bibcode`. It does not modify `candidate_origin.citation.bibcode`, because those fields describe candidates cited from other literature. The script reads `ADS_API_TOKEN` or `ADS_TOKEN` from `.env`, queries ADS with `identifier:<arxiv_id>`, and saves the full response to `literature/<arxiv_id>/ads_metadata.json`. If the token is missing, the request fails, or no result is found, the relevant bibcode remains empty and the command reports the reason. The script does not construct arXiv-style bibcodes.

## 6. Review Structured Data Assets

For a paper already archived under `literature/<arxiv_id>/`, first generate the standard review template:

```bash
conda run -n stella-env python scripts/init_catalog_review.py \
  --arxiv-id 2402.10714
```

`init_catalog_review.py` uses the inventory logic and Pydantic schema to generate a fixed-field `catalog_review.json` skeleton. Then use the in-repository `hvs-catalog-review` skill with the full paper text to fill only paper-semantic fields:

```text
literature/<arxiv_id>/catalog_review.json
```

This stage inventories structured data assets already present in the paper. It does not decide whether an asset is an HVS catalog. Output is split into `internal_tables` and `external_resources`; internal tables need paper-context roles and `columns[]` meanings, while external resources keep only overall descriptions, links, paths, evidence, and notes from the paper. Remote resource internals are not analyzed and remote resources are not downloaded.

Validate structure and source refs after review:

```bash
conda run -n stella-env python scripts/validate_catalog_review.py \
  --arxiv-id 2402.10714 \
  --require-complete
```

Rebuild the global catalog workflow index:

```bash
conda run -n stella-env python scripts/build_catalog_index.py
```

Outputs:

```text
literature/literature_catalog_index.json
literature/literature_catalog_index.md
```

The index uses `literature/*/catalog_review.json` as its entry point. If `catalog_extraction.json` exists in the same directory, it also summarizes current internal table extraction status, ECSV table success/failure counts, and excerpt-file success/failure counts. `literature_catalog_index.md` displays review and extraction status separately.

Review status:

- `reviewed`: data asset review is complete in the available paper/source context.
- `partial`: data asset review is incomplete or candidate coverage has unresolved issues.
- `needs_review`: data asset review is not complete.
- `source_missing`: source-based review is impossible; if source metadata simultaneously says source is available, the index marks the inconsistency with `(!)`.

Extraction status:

- `success`: the current extraction run has no table or file failures.
- `partial`: the current extraction produced at least one table or file but also has failures.
- `failed`: the current extraction or manifest read failed.
- `not_started`: review found internal tables but there is no `catalog_extraction.json`.
- `not_applicable`: review found no internal tables; extraction is unnecessary even if external resources exist.

## 7. Extract Reviewed Internal Tables

Install LaTeXML when possible:

```bash
brew install latexml
```

The extraction script tries LaTeXML, Pandoc, and then the in-project fallback parser. Only `internal_tables` from `catalog_review.json` enter extraction. `external_resources` remain in the review record.

Extract all reviewed internal tables for one paper:

```bash
conda run -n stella-env python scripts/extract_catalog_tables.py \
  --arxiv-id 2402.10714
```

Extract one candidate table:

```bash
conda run -n stella-env python scripts/extract_catalog_tables.py \
  --arxiv-id 2402.10714 \
  --internal-table-id table-tab-72dr3
```

Extract all reviewed papers that have internal tables:

```bash
conda run -n stella-env python scripts/extract_catalog_tables.py \
  --all-reviewed
```

### Common Arguments

```text
--arxiv-id ID              Extract one paper
--all-reviewed             Extract all reviewed papers with internal tables
--internal-table-id ID     Extract only one internal_tables[].id; requires --arxiv-id
--jobs Auto|N              Parallel paper worker count for --all-reviewed, default 1
--literature-dir PATH      Literature archive root, default literature
--dry-run True|False       Parse and report without writing, default False
--overwrite True|False     Overwrite existing excerpt.tex and ECSV, default False
```

### Notes

- LaTeX tables write `catalog_sources/<internal_table_id>/excerpt.tex`, converter HTML/log artifacts, and `catalog_tables/<internal_table_id>.ecsv`.
- Failed LaTeX parsing still preserves `excerpt.tex` for later review.
- External resources are not parsed, downloaded, located, converted, or written during extraction. If needed, use only the resource descriptions and evidence in `catalog_review.json`.
- Clean old catalog workflow products with:

```bash
conda run -n stella-env python scripts/cleanup_catalog_workflow_outputs.py --dry-run True
```

- Full reruns can use `--jobs Auto`, which chooses 1/2/4/8/12 workers by paper count. `--jobs N` can also be specified directly.
- Each paper writes `catalog_extraction.json` with the single current `run`, excerpt files, conversion attempts, success/failure state, ECSV paths, and observed headers/units. Converter stdout/stderr stays in artifact files; JSON stores only paths.
- ECSV uses stable names such as `col_001` and `col_002`, preserving the paper table as faithfully as possible. This does not mean a unified object schema is complete.
- `catalog_extraction.json` is validated with Pydantic before writing; standalone validation is:

```bash
conda run -n stella-env python scripts/validate_catalog_extraction.py \
  --arxiv-id 2402.10714 \
  --require-reviewed
```

## 8. Extract Paper-Level HVS Candidates

After `catalog_review.json` and `catalog_extraction.json` are complete, use the in-repository `hvs-candidates-extraction` skill. First generate the fixed-field template:

```bash
conda run -n stella-env python scripts/init_hvs_candidates.py \
  --arxiv-id 2402.10714
```

Then fill it from the paper text, review/extraction sources, and ECSV:

```text
literature/<arxiv_id>/literature_hvs_candidates.json
```

This stage extracts only objects in a single paper that are anchored by text evidence as possible HVS/unbound/escaping/hyper-runaway candidates from the Milky Way/Galactic potential. Ordinary runaways, cluster escapers, local-GC-unbound objects still described as Galactic-bound, and objects already judged bound by the paper do not enter `candidates[]`. Fixed velocity thresholds are only checks, not standalone inclusion criteria.

Extraction must be text-driven: first read the paper text to determine candidate identity, Galactic-unbound evidence, and `candidate_origin`; then use `catalog_review.json`, `catalog_extraction.json`, and `catalog_tables/*.ecsv` to locate values. Review/extraction JSON is a table map, not inclusion evidence.

Validate after completion:

```bash
conda run -n stella-env python scripts/validate_hvs_candidates.py \
  --arxiv-id 2402.10714 \
  --require-complete
```

Repeated warnings across many candidates are grouped by default in CLI output.
Use `--verbose-warnings` when you need the original per-field warning list.

Validate a specific file directly:

```bash
conda run -n stella-env python scripts/validate_hvs_candidates.py \
  --path literature/2402.10714/literature_hvs_candidates.json \
  --require-complete
```

Validate and rebuild the global index:

```bash
conda run -n stella-env python scripts/validate_hvs_candidates.py \
  --arxiv-id 2402.10714 \
  --require-complete \
  --rebuild-index
```

Rebuild the global index without validation:

```bash
conda run -n stella-env python scripts/build_hvs_candidates_index.py
```

### Notes

- `literature_hvs_candidates.json` uses `schema_version: stella.literature_hvs_candidates.v6`.
- Templates, validators, and skill schema references come from the same Pydantic models. Do not add fields outside the template manually.
- Every paper should have a result file. If no candidate meets the boundary, write `extraction.status=no_candidates` and empty `candidates[]`.
- Candidate identifiers live under `identifiers`: `record_id` is the Stella internal `<arxiv_id>:cand-001` ID, `paper_candidate_id` is the paper's preferred display name, `gaia_source_id` is empty or a strict `Gaia DR3/EDR3/DR2 ...` machine identifier, and `all[]` contains every name, number, and Gaia source ID appearing in the paper with `source_refs`. `record_id` does not enter `all[]`.
- `method_chain[]` is a paper-level atomic method DAG. IDs use local `step-01`, `step-02` order, `step_type` uses the controlled vocabulary, and `depends_on[]` lists only direct upstream steps.
- Every `core` and `extra[]` parameter references exactly one direct-producing `method_chain` step through field-level `method_refs`; full lineage is recovered recursively through `depends_on[]`. Candidate-level `method_chain_refs` is no longer used.
- `candidate_origin.origin_type` distinguishes `introduced_by_this_paper` from `cited_from_literature`. "Introduced" means the paper first presents the object as a possible Galactic-unbound/HVS candidate. Known objects reanalyzed by the paper are `cited_from_literature`, with `paper_reassesses_unbound_status=true` when the paper reassesses status. Cited candidates must give both text citation lines and `.bib`/`.bbl` entries in `candidate_origin.citation.source_refs`.
- `core.observed_phase_space` standard slots are RA, Dec, distance/parallax, pmRA, pmDec, and RV. Galactocentric coordinates, velocities, escape-speed comparisons, and bound/unbound probabilities go under derived/probabilities.
- RA/Dec use coordinate-specific records: `raw_value` and `value` store only one coordinate component; `coordinate_format` stores the notation; coordinate unit stores only real units such as `deg` or `hourangle`; frame and epoch live inside the RA/Dec `reference_frame` and `epoch` objects. If paper text, table header, and `hvs-candidates-extraction/references/coordinate_frames.md` cannot determine frame/epoch, write `unknown` with source refs and `inference_basis=not_in_reference` or `not_reported`; the validator treats this as documented uncertainty rather than warning noise.
- `extra[]` stores photometry, stellar parameters, quality flags, neighboring-source checks, orbit quantities, and paper-specific metrics outside the core.
- Every `core` and `extra[]` parameter must include `raw_value`, cleaned `value`, `source_refs`, and `method_refs`. ECSV sources need `path`, `line`, `column`, `column_header`, and `raw_value`, and the parameter `raw_value`, source ref `raw_value`, and real ECSV cell must agree. If one ECSV cell contains both RA and Dec, source ref `raw_value` keeps the full cell, quantity-level `raw_value` keeps only the current component, and `component_raw_value` connects them. ECSV paths must use `kind: ecsv_cell`; ordinary text refs must not point to `.ecsv`.
- `value`, `error`, `lower_error`, and `upper_error` cannot keep LaTeX commands, braces, `$`, `_`, `^`, or `+/-`; mechanical uncertainty expressions should be split into error fields. Numeric core fields and quantitative `extra[]` machine fields must be single plain numbers. Ranges, limits, units, footnotes, and explanatory text stay in `raw_value` or `description`; when no single value exists, leave `value` empty. Core probability fields normalize `value` to a unitless 0-1 fraction and leave `unit` empty; paper percent values remain in `raw_value` and provenance refs. RA/Dec may keep original decimal-degree or sexagesimal values, but must not mix `J2000.0`, `J2016`, `ICRS`, or similar context into `value`, `raw_value`, `unit`, or `description`.
- Text sources need `path`, `start_line`, and `end_line`, and must point to substantive paper/source lines rather than page markers, blank/comment lines, isolated LaTeX structure lines, or preamble settings. Candidate inclusion, candidate origin, and `no_candidates` exclusion evidence must cite paper text; metadata JSON, ECSV cells, and `.bib`/`.bbl` entries are not scientific evidence. Bibliography refs are only valid inside `candidate_origin.citation.source_refs` alongside the paper text citation line.
- The validator checks JSON structure and provenance consistency; it does not replace the agent's scientific judgment.
- Fixed direct-producer `method_refs` conventions: position/parallax/proper motion/catalog photometry reference `input_catalog` or `astrometric_calibration`; RV references `radial_velocity_measurement` or direct catalog `input_catalog`; distance references `distance_estimation`; velocity and Galactocentric coordinates reference `velocity_calculation`; escape speed, bound probability, and escape margin reference `escape_or_bound_assessment`; orbit quantities reference `orbit_integration`; origin quantities reference `origin_assessment`; stellar parameters reference `stellar_parameter_inference` or `photometric_or_sed_modeling`; values reported without method detail reference `reported_value_adoption`.

Older `literature_hvs_candidates.json` versions are no longer a long-term compatibility target. When backfilling or redoing work, regenerate under the current v6 schema and `hvs-candidates-extraction` skill.

When schema fields change, update Pydantic models first, then run:

```bash
conda run -n stella-env python scripts/generate_schema_docs.py
```

Global index files are `literature/literature_hvs_index.json` and `literature/literature_hvs_index.md`, generated by scanning all `literature/<arxiv_id>/literature_hvs_candidates.json` files with `scripts/build_hvs_candidates_index.py`. Do not edit index files manually; if output is wrong, fix candidates JSON or index rendering logic and regenerate.

## 9. Merge Object-Level HVS Candidate Catalog

After paper-level `literature_hvs_candidates.json` files are complete, use the in-repository `hvs-candidates-merge` skill to generate the object catalog:

```text
catalog/<object_id>.json
catalog/hvs_candidates_index.json
catalog/hvs_candidates_index.md
```

Rebuild the full object-level catalog:

```bash
conda run -n stella-env python scripts/merge_hvs_candidate_catalog.py rebuild \
  --literature-dir literature \
  --catalog-dir catalog
```

Merge one new paper-level candidate into an existing `catalog/`:

```bash
conda run -n stella-env python scripts/merge_hvs_candidate_catalog.py update \
  --arxiv-id 2604.21646 \
  --literature-dir literature \
  --catalog-dir catalog
```

Or specify a file directly:

```bash
conda run -n stella-env python scripts/merge_hvs_candidate_catalog.py update \
  --path literature/2604.21646/literature_hvs_candidates.json \
  --literature-dir literature \
  --catalog-dir catalog
```

Both modes support `--dry-run True`, which prints generated writes/deletes without modifying `catalog/`.

### Merge and Review Principles

- Inputs are validated against the current `LiteratureHvsCandidatesRecord` schema first. Invalid files enter index `skipped[]` and do not participate in merging.
- Gaia source ID is the strong match key; identical non-empty `gaia_source_id` values merge.
- If either side lacks a Gaia source ID, RA/Dec angular separation must be strictly `<5 arcsec` to merge.
- If both sides have different Gaia source IDs, do not merge; if coordinates are `<5 arcsec`, write a warning.
- If both sides have the same Gaia source ID but coordinates are not `<5 arcsec`, still merge and write a warning.
- Object-level JSON `sources[]` stores short source IDs, original `paper` fields, source JSON paths, and paper-level candidate IDs.
- `method_chain[]` and `candidates[]` are grouped by `source` and do not keep `source_refs`; full provenance still lives in the paper-level JSON.
- Do not manually modify `catalog/`. If warnings expose errors, fix the corresponding `literature_hvs_candidates.json` and rerun the merge.

After running, inspect the command summary and then:

```text
catalog/hvs_candidates_index.md
```

Focus on `Warnings`, object count, source count, and each object's JSON link.

## 10. Build HVS Catalog HTML Pages

After object-level `catalog/` exists, build the HTML demo:

```bash
conda run -n stella-env python scripts/build_hvs_catalog_html.py \
  --catalog-dir catalog \
  --html-dir html
```

Outputs:

```text
html/live/index.html              Entry page that reads catalog/ live
html/live/assets/...              Local CSS, JS, and visual assets shared by live/static
html/static/index.html            Single-file demo with the current catalog/ snapshot embedded
```

The live version needs an HTTP server started from the repository root, for example:

```bash
python -m http.server 8765 --bind 127.0.0.1
```

Then open:

```text
http://127.0.0.1:8765/html/live/
```

The static version does not read JSON live. It is a build-time `catalog/` snapshot and can be opened directly as `html/static/index.html` or copied to static hosting for demos. The source of truth remains `catalog/*.json`; the web page is only a display layer.

## 11. Date Syntax

```text
--from 2026-03-15  starts from 2026-03-15
--from 2026-03     starts from 2026-03-01
--from 2026        starts from 2026-01-01
--to 2026-03-15    ends at 2026-03-15
--to 2026-03       ends at 2026-03-31
--to 2026          ends at 2026-12-31
--to none          ends today
```

Future dates are automatically clipped to today. Invalid date formats fail immediately.

## 12. Additional Notes

When DeepXiv returns a quota error:

- Completed months are still saved.
- The script writes `logs/partial_<run_id>.json`.
- It appends the result to `logs/runs.jsonl`.
- It prints the resume command and exits.

Default search terms:

```text
hypervelocity stars
high-velocity stars
high radial velocity stars
runaway stars
unbound stars
escaping stars
```
