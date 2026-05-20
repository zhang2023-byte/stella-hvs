# High-Velocity-Star Literature Workflow

This repository currently provides:

- Monthly fetching of high-velocity-star literature.
- Rule-based title triage, with optional LLM review for papers whose titles have no clear evidence.
- Monthly title triage records under `notes/`.
- Normalized monthly literature records under `notes/`.
- `catalog_assessment` annotations for papers that may contain observational data assets.
- Local archival of data-related papers from `notes/` into `literature/`.
- Structured data asset review for archived paper sources, plus a data asset workflow index.
- Faithful extraction of reviewed internal LaTeX tables into ECSV with extraction provenance.
- Paper-level HVS/unbound candidate extraction from paper text and ECSV with per-value provenance.
- Object-level merging of paper-level HVS candidates into `catalog/` JSON with source mappings.
- Markdown generation from JSON.

## Environment Setup

```bash
conda env create -f environment.yml
conda activate stella-env
cp env.example .env
```

LaTeX table extraction works best with LaTeXML installed:

```bash
brew install latexml
```

If you use `--source deepxiv`, or run DeepXiv-enhanced `catalog_assessment`, set `DEEPXIV_TOKEN` in `.env`.

See [docs/setup.md](docs/setup.md) for details.

## Common Commands

Basic run:

```bash
conda run -n stella-env python scripts/fetch_high_velocity_lit.py \
  --from 2026-03
```

By default, candidate search uses DeepXiv and covers `astro-ph.GA`, `astro-ph.SR`, and `astro-ph.IM`. If DeepXiv hits quota limits, token/API failures, or other search errors, the remaining searches in that run automatically fall back to the arXiv API.

Run with LLM review:

```bash
conda run -n stella-env python scripts/fetch_high_velocity_lit.py \
  --from 2026-03 \
  --llm-review True
```

Add data-related assessments to existing months:

```bash
conda run -n stella-env python scripts/annotate_catalog_data.py \
  --on 2026-03
```

This workflow fetches a DeepXiv brief for each paper to be assessed, reads the final paragraph of the introduction plus each section title and first paragraph, and sends the combined context to the LLM to judge whether the paper is a high-velocity-star data paper.

Archive local assets for papers already judged data-related:

```bash
conda run -n stella-env python scripts/pull_literature_assets.py \
  --from 2024-01 \
  --to 2026-04
```

Repair ADS metadata and paper-level HVS candidate bibcodes for archived papers:

```bash
conda run -n stella-env python scripts/repair_ads_metadata.py
```

Force-refresh all archived ADS API metadata JSON:

```bash
conda run -n stella-env python scripts/repair_ads_metadata.py --force True
```

The script reads `ADS_API_TOKEN` from `.env`, queries the ADS API by arXiv ID, and saves the full API response as `ads_metadata.json`. It no longer scrapes ADS HTML pages. If the API fails or finds no record, the field remains empty and the command reports the reason. It does not construct arXiv-style bibcodes.

Initialize a structured data asset review template for one paper:

```bash
conda run -n stella-env python scripts/init_catalog_review.py \
  --arxiv-id 2402.10714
```

The template is generated from Pydantic schemas. Agents should only fill paper-semantic blanks, then use the in-repository `hvs-catalog-review` skill with the paper text to complete `literature/<arxiv_id>/catalog_review.json`. This stage inventories paper data assets as `internal_tables` and `external_resources`; it does not decide whether they are HVS catalogs. Internal tables use `internal_tables[].columns` for column meanings. External resources only keep the paper's descriptions and are not converted, parsed, or downloaded.

Validate after completion:

```bash
conda run -n stella-env python scripts/validate_catalog_review.py \
  --arxiv-id 2402.10714 \
  --require-complete
```

Extract reviewed internal tables:

```bash
conda run -n stella-env python scripts/extract_catalog_tables.py \
  --arxiv-id 2402.10714
```

Extraction writes `literature/<arxiv_id>/catalog_extraction.json`, `catalog_sources/<id>/...`, and `catalog_tables/<id>.ecsv`. LaTeX tables use LaTeXML first, then Pandoc, then the in-project fallback parser. External resources are not processed during extraction; they remain paper-declared resource descriptions in `catalog_review.json`. `catalog_extraction.json` keeps only the single current run and does not accumulate run history. ECSV preserves the paper's internal table structure and does not imply a unified object schema.

Full reruns can use `--all-reviewed --jobs Auto`, which chooses parallelism by paper count. For more than 100 papers, the default tries 12 jobs. You can also set `--jobs N` directly. The extraction script validates `catalog_extraction.json` with Pydantic before writing; standalone validation is also available:

```bash
conda run -n stella-env python scripts/validate_catalog_extraction.py \
  --arxiv-id 2402.10714 \
  --require-reviewed
```

Extract HVS/unbound candidates from one paper with the in-repository `hvs-candidates-extraction` skill. First generate the schema template:

```bash
conda run -n stella-env python scripts/init_hvs_candidates.py \
  --arxiv-id 2402.10714
```

Then the agent fills `literature/<arxiv_id>/literature_hvs_candidates.json`. This stage uses `stella.literature_hvs_candidates.v6` and is bounded by paper-text evidence: include only objects the paper treats as possibly unbound from the Milky Way/Galactic potential or as escaping/HVS candidates. Ordinary runaways, cluster escapers, local-GC-unbound objects still described as Galactic-bound, and objects the paper judges bound do not enter `candidates[]`.

Extraction should first read the text to establish candidate identity, unbound evidence, and `candidate_origin`; then use `catalog_review.json`, `catalog_extraction.json`, and ECSV for quantities. `core` and `extra[]` parameters must keep `raw_value`, cleaned `value`, per-value `source_refs`, and direct-producer `method_refs`. Candidate identifiers live under `identifiers`: `record_id` is the Stella internal `<arxiv_id>:cand-001` ID, `paper_candidate_id` is the paper's preferred display name, `gaia_source_id` is empty or a strict `Gaia DR3/EDR3/DR2 ...` machine identifier, and `all[]` stores every name and number appearing in the paper with `source_refs`. `method_chain[]` uses local `step-01`, `step-02` IDs, controlled `step_type`, and direct `depends_on[]` dependencies. Cited candidates must include text citation lines and `.bib`/`.bbl` entries.

RA/Dec are coordinate-specific records: `value` and `raw_value` store only one coordinate component, `coordinate_format` stores the notation, coordinate `unit` stores only real units such as `deg` or `hourangle`, and frame/epoch live inside the RA/Dec `reference_frame` and `epoch` objects. If the paper text, table header, and skill reference cannot determine frame/epoch, write `unknown` and preserve the evidence instead of guessing.

```bash
conda run -n stella-env python scripts/validate_hvs_candidates.py \
  --arxiv-id 2402.10714 \
  --require-complete
```

The validator checks JSON structure and provenance consistency; it does not replace scientific judgment by the agent.

Merge paper-level HVS candidates into the object-level catalog with the in-repository `hvs-candidates-merge` skill.

Rebuild from scratch:

```bash
conda run -n stella-env python scripts/merge_hvs_candidate_catalog.py rebuild \
  --literature-dir literature \
  --catalog-dir catalog
```

Merge one new paper-level candidate file into an existing `catalog/`:

```bash
conda run -n stella-env python scripts/merge_hvs_candidate_catalog.py update \
  --arxiv-id 2604.21646 \
  --literature-dir literature \
  --catalog-dir catalog
```

Merging uses Gaia source ID as the strong key. If either side lacks a Gaia source ID, RA/Dec must match within `<5 arcsec`. Different Gaia IDs with very close coordinates, or identical Gaia IDs with non-close coordinates, produce warnings that should be reviewed in `catalog/hvs_candidates_index.md`.

Build the object-level HVS catalog HTML demo:

```bash
conda run -n stella-env python scripts/build_hvs_catalog_html.py \
  --catalog-dir catalog \
  --html-dir html
```

Outputs include `html/live/` and `html/static/index.html`. The live version requires an HTTP server launched from the repository root and reads `catalog/` in real time. The static version is a single-file snapshot with the current `catalog/` embedded for quick demos.

Clean old catalog workflow products while preserving the original paper archive:

```bash
conda run -n stella-env python scripts/cleanup_catalog_workflow_outputs.py --dry-run True
```

Rebuild the catalog workflow index:

```bash
conda run -n stella-env python scripts/build_catalog_index.py
```

The index uses `catalog_review.json` as the entry point and, when `catalog_extraction.json` exists, also reports internal table extraction status, ECSV success/failure counts, and excerpt-file success/failure counts. Review status and extraction status are displayed separately; `partial` is not reused across stages.

Regenerate Markdown from JSON:

```bash
conda run -n stella-env python scripts/render_lit_notes.py
```

See [docs/usage.md](docs/usage.md) for more options.

## Documentation

- Environment: [docs/setup.md](docs/setup.md)
- Usage: [docs/usage.md](docs/usage.md)
- Outputs: [docs/outputs.md](docs/outputs.md)
- Title triage rules: [docs/title-triage.md](docs/title-triage.md)
- Repository agent constraints: [AGENTS.md](AGENTS.md)

## Directory Map

```text
scripts/fetch_high_velocity_lit.py   Main monthly literature fetcher
scripts/annotate_catalog_data.py     Add catalog_assessment to monthly JSON
scripts/pull_literature_assets.py    Archive local assets for data-related papers
scripts/repair_ads_metadata.py       Fill paper-level bibcodes via the ADS API
scripts/inventory_catalog_candidates.py   List data asset review candidates for one paper
scripts/init_catalog_review.py       Generate catalog_review.json templates from code schemas
scripts/extract_catalog_tables.py    Extract internal LaTeX tables from catalog_review.json into ECSV
scripts/validate_catalog_review.py    Validate catalog_review.json structure and source refs
scripts/validate_catalog_extraction.py Validate catalog_extraction.json structure and extraction products
scripts/init_hvs_candidates.py        Generate literature_hvs_candidates.json templates from code schemas
scripts/validate_hvs_candidates.py    Validate literature_hvs_candidates.json structure and provenance
scripts/merge_hvs_candidate_catalog.py Merge object-level HVS candidates catalog
scripts/build_hvs_catalog_html.py     Build object-level HVS catalog HTML demo pages
scripts/generate_schema_docs.py       Generate skill schema reference docs from Pydantic schemas
scripts/cleanup_catalog_workflow_outputs.py   Clean old catalog review/extraction products
scripts/build_catalog_index.py        Rebuild the data asset workflow index from review/extraction JSON
scripts/render_lit_notes.py           Regenerate Markdown from JSON
docs/                                Documentation
literature/                          Local literature archive, ignored by Git by default
notes/                               Monthly title triage JSON, monthly JSON, monthly Markdown, yearly index
catalog/                             Object-level HVS candidates catalog, generated product
src/high_velocity_lit/               Core implementation
tests/                               Tests
```
