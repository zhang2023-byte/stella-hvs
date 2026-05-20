# Stella Agent Notes

This file is for future agents working in the `stella-workspace` repository.

## Current Repository Scope

The repository currently supports this workflow:

- Fetch high-velocity-star literature by month.
- Run title-based relevance triage.
- Write normalized literature records into `notes/`.
- Add `catalog_assessment` to existing monthly JSON records.
- Review structured data assets in archived paper sources and write `catalog_review.json`.
- Faithfully extract reviewed internal LaTeX tables into ECSV and write `catalog_extraction.json`.
- Extract paper-level HVS/unbound candidates from the paper text, `catalog_review.json`, `catalog_extraction.json`, and ECSV tables, then write `literature_hvs_candidates.json`.
- Merge paper-level HVS candidates into object-level JSON under `catalog/`.
- Generate Markdown from JSON.

## Project Vision

Stella's long-term goal is to build a traceable, reproducible, and continuously updated object-level data and knowledge system for high-velocity-star research.

Read the root `TODO.md` when you need the long-term direction, implementation roadmap, or future extension goals.

## Core Principles

JSON is the source of truth. Markdown is only a reading view generated from JSON and must stay consistent with it.

Default outputs:

```text
notes/YYYY/YYYY-MM/YYYY-MM.json   Monthly normalized records
notes/YYYY/YYYY-MM/YYYY-MM.md     Monthly reading notes
notes/literature_notes_index.json                  Global index
notes/literature_notes_index.md                    Yearly view
literature/<arxiv_id>/catalog_review.json   Paper-level structured data asset review source of truth
literature/<arxiv_id>/catalog_extraction.json   Paper-level internal table extraction source of truth
literature/<arxiv_id>/literature_hvs_candidates.json   Paper-level HVS/unbound candidate extraction source of truth
literature/<arxiv_id>/catalog_sources/<internal_table_id>/excerpt.tex   Original LaTeX table excerpt
literature/<arxiv_id>/catalog_sources/<internal_table_id>/latexml.html   LaTeXML conversion view
literature/<arxiv_id>/catalog_tables/<internal_table_id>.ecsv   Faithful ECSV table
literature/literature_hvs_index.json        Global HVS candidates index
literature/literature_hvs_index.md          HVS candidates reading view
catalog/<object_id>.json                    Object-level HVS candidate merge result
catalog/hvs_candidates_index.json           Object-level HVS candidates global index
catalog/hvs_candidates_index.md             Object-level HVS candidates reading view
literature/literature_catalog_index.json      Data asset workflow global index
literature/literature_catalog_index.md        Data asset workflow reading view
```

Do not manually edit generated Markdown. If generated output is wrong, fix the JSON construction logic or the Markdown rendering logic, then regenerate.

Git should store the toolchain, documentation, tests, and skills that generate these data products. JSON, Markdown, PDFs, source archives, HTML, and other generated data under `notes/`, `literature/`, `catalog/`, and `logs/` are ignored by default. Do not force-add them with `git add -f` unless the user explicitly asks for that.

## Literature Workflow

The common command only needs `--from`:

```bash
conda run -n stella-env python scripts/fetch_high_velocity_lit.py --from 2026-03
```

Defaults should balance recall and quota usage:

- `--source deepxiv`
- If DeepXiv hits quota limits, token/API failures, or other search errors, the remaining searches in that run automatically fall back to arXiv.
- `--llm-review False`
- Do not fetch `DeepXiv brief`.
- `--max-results 20`
- `--deepxiv-llm-review-max-candidates 20`
- `--categories astro-ph.GA,astro-ph.SR,astro-ph.IM`
- `--search-mode hybrid`

Multiple categories mean OR: a paper enters the candidate pool if it belongs to any of `astro-ph.GA`, `astro-ph.SR`, or `astro-ph.IM`. DeepXiv searches each query/category pair and deduplicates the merged results. arXiv queries should push the category OR condition directly into the API query instead of fetching category-free results and filtering only locally.

When using `--source deepxiv --llm-review True`, DeepXiv still searches each query/category pair and deduplicates results, but only the top 20 `no-clear-title-evidence` candidates by DeepXiv score are sent to the LLM by default. The remaining candidates should stay in the title triage JSON and be marked skipped.

Default title triage has two buckets:

- `rule-related`: the title clearly matches high-velocity-star relevance rules and enters the final monthly note directly.
- `no-clear-title-evidence`: title evidence is unclear and, by default, only enters the title triage JSON.

When `--llm-review True` is enabled:

- Only `no-clear-title-evidence` papers are sent to the LLM.
- `rule-related` results are unchanged.

LLM classification or review input should include:

- Title.
- Search-returned abstract.
- Categories.

Do not send only the title unless the user explicitly asks for that.

To add `catalog_assessment` to existing months, use:

```bash
conda run -n stella-env python scripts/annotate_catalog_data.py --on 2026-03
```

The assessment should use the abstract. If older `brief` fields exist, they may also be considered. Refresh the corresponding Markdown and rebuild indexes after completion.

For structured data asset review, use the in-repository `hvs-catalog-review` skill. Before review or extraction, always check `literature/<arxiv_id>/audit.json`. If ADS API metadata, arXiv source, PDF, or other archived assets were not fetched successfully, report the specific paper and failure reason to the user; do not silently proceed and leave downstream fields empty indefinitely. When ADS API metadata or the paper-level bibcode is missing, prefer:

```bash
conda run -n stella-env python scripts/repair_ads_metadata.py --arxiv-id 2402.10714
```

That script only fills `audit.json` and `literature_hvs_candidates.json` `paper.bibcode`; do not use it to modify `candidate_origin.citation.bibcode` for candidates cited from other literature. The ADS API is the source of truth for this paper-level bibcode. If the API fails, keep the field empty and report the failure. Do not construct arXiv-style bibcodes or substitute non-ADS sources. Do not scrape ADS HTML pages.

At this stage, do not decide whether assets are high-velocity-star catalogs. Only inventory `internal_tables` and `external_resources` found in the paper. Internal tables use `columns[]` to record visible column meanings. External resources only record the paper's overall description of each resource. The review stage does not download external resources; the extraction stage also does not download, parse, or convert external resources.

Helper inventory:

```bash
conda run -n stella-env python scripts/inventory_catalog_candidates.py --arxiv-id 2402.10714
```

Rebuild the data asset workflow index:

```bash
conda run -n stella-env python scripts/build_catalog_index.py
```

Rebuild the HVS candidates global index:

```bash
conda run -n stella-env python scripts/build_hvs_candidates_index.py
```

Do not manually edit `literature/literature_catalog_index.json`, `literature/literature_catalog_index.md`, `literature/literature_hvs_index.json`, or `literature/literature_hvs_index.md`. If the output is wrong, fix the corresponding source JSON or index rendering logic, then regenerate.

For reviewed data asset extraction, use the in-repository `hvs-catalog-extraction` skill:

```bash
conda run -n stella-env python scripts/extract_catalog_tables.py --arxiv-id 2402.10714
```

Extraction only processes `latex_table` entries under `internal_tables`. LaTeX conversion order is LaTeXML, Pandoc, then the in-project fallback parser. Table assets are written as ECSV. `catalog_extraction.json` keeps only the single current `run` that generated the current internal table extraction assets; it does not accumulate run history. The extraction stage does not add scientific semantics, perform HVS filtering, force a unified schema, or process external resources. Full reruns can use `--jobs Auto` to choose parallelism by paper count. For more than 100 papers, the script tries higher concurrency; `--jobs N` can also be specified directly.

For paper-level HVS/unbound candidate extraction, use the in-repository `hvs-candidates-extraction` skill. Included objects must be anchored in paper text evidence: the paper must explicitly discuss, list, or evaluate the object as a possible HVS, unbound, escaping, hyper-runaway, or equivalent candidate from the Milky Way/Galactic potential. Ordinary runaways, cluster escapers, local-GC-unbound objects that the paper states are still bound to the Galaxy, and objects already judged bound by the paper do not enter `candidates[]`. Fixed velocity thresholds may only support checking; they cannot be the sole inclusion criterion.

Extraction order must be text-driven: first read the paper text to identify candidate identity, unbound evidence, and `candidate_origin`; then use `catalog_review.json`, `catalog_extraction.json`, and ECSV to extract quantities. Core quantities should prefer `catalog_tables/*.ecsv`, and `literature_hvs_candidates.json` must record the ECSV file, physical line number, machine column name, column header, and raw cell text precisely. Quantity records must preserve `raw_value`, cleaned `value`, per-value `source_refs`, and field-level direct-producer `method_refs`. `value`, `error`, `lower_error`, and `upper_error` must not retain LaTeX residue.

Candidate identity, method chains, field definitions, references, and missingness notes must be supported by paper line numbers. Candidate identifiers are standardized under `identifiers`: `record_id` uses Stella internal IDs such as `<arxiv_id>:cand-001`; `paper_candidate_id` is the paper's preferred display name; `gaia_source_id` is empty or a strict machine identifier such as `Gaia DR3/EDR3/DR2 ...`; `all[]` contains every name, number, and Gaia source ID appearing in the paper with per-item `source_refs`. `record_id` does not enter `all[]`.

`method_chain[]` uses local paper IDs such as `step-01`, `step-02`, controlled `step_type`, and `depends_on[]` for direct upstream dependencies. `method_refs` should reference only the direct step that produced the quantity; the complete lineage is recovered recursively from `depends_on[]`. Do not use candidate-level `method_chain_refs`. Candidates cited from other work must also record the text citation line and the `.bib`/`.bbl` entry. Papers with no candidates still need an empty result file with `extraction.status=no_candidates`.

Validation:

```bash
conda run -n stella-env python scripts/validate_hvs_candidates.py --arxiv-id 2402.10714
```

Validation plus automatic index rebuild:

```bash
conda run -n stella-env python scripts/validate_hvs_candidates.py --arxiv-id 2402.10714 --rebuild-index
```

For object-level HVS candidate merging, use the in-repository `hvs-candidates-merge` skill.

Rebuild from scratch:

```bash
conda run -n stella-env python scripts/merge_hvs_candidate_catalog.py rebuild --literature-dir literature --catalog-dir catalog
```

Merge a new paper-level candidate file into the existing catalog:

```bash
conda run -n stella-env python scripts/merge_hvs_candidate_catalog.py update --arxiv-id 2604.21646 --literature-dir literature --catalog-dir catalog
```

Merge rules: first prefer identical non-empty `gaia_source_id`; when either side lacks a Gaia source ID, use RA/Dec and merge only if the angular separation is `<5 arcsec`. If both sides have different Gaia source IDs but coordinates are within `<5 arcsec`, do not merge and write a warning. If both sides have the same Gaia source ID but coordinates are not close, still merge and write a warning. Do not manually modify generated files under `catalog/`. If a warning exposes a source data error, fix the corresponding `literature_hvs_candidates.json` and rerun the merge.

## Engineering Rules

- Test environment: `conda run -n stella-env python -m unittest discover tests`
- Do not make real DeepXiv calls unless the user explicitly asks for new data fetching.
- JSON must preserve provenance: search source, query, category, score, and `run_id`.
- When quota limits are hit, already completed months still need JSON, Markdown, and partial summaries saved.
- Do not restore unrelated changes and do not revert user changes.
- If dependencies or environment steps change, update the environment file and relevant docs.

## Change Checklist

When output structure changes, update:

- `src/high_velocity_lit/records.py`
- `src/high_velocity_lit/markdown.py`
- `docs/outputs.md`
- Relevant tests

When CLI arguments or defaults change, update:

- `scripts/fetch_high_velocity_lit.py`
- Any newly added or changed `scripts/*.py`
- `docs/usage.md`
- `README.md`
- CLI tests

When dependencies or environment setup change, update:

- `environment.yml`
- `docs/setup.md`
- `README.md`

When adding scientific capabilities, design machine-readable JSON first, then consider Markdown or other display layers.
