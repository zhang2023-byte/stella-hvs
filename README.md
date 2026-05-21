# High-Velocity-Star Literature Workflow

Stella builds a traceable, reproducible, object-level data workflow for
high-velocity-star research. The repository currently supports literature
fetching, title triage, data-asset review, internal table extraction,
paper-level HVS candidate extraction, object-level candidate merging, and
generated Markdown/HTML views.

Most day-to-day use is natural-language driven through an agent. The agent
should route requests through `workflows/stella_workflows.yaml`, using
`docs/human-workflows.md` for human prompt examples and `docs/agent-workflows.md`
for execution rules.

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

If you use DeepXiv, ADS repair, or LLM-backed review, configure the relevant
tokens in `.env`. See [docs/setup.md](docs/setup.md).

## Common Agent Requests

Humans can usually ask in natural language:

```text
Fetch high-velocity-star literature from 2026-03.
Add catalog assessments for 2026-03.
Archive local assets for 2402.10714.
Review structured data assets for 2402.10714.
Extract reviewed internal tables for 2402.10714.
Extract paper-level HVS candidates for 2402.10714.
Rebuild the object-level HVS catalog.
Build the HVS catalog HTML demo.
Regenerate generated Markdown and indexes.
```

When details are missing, agents should ask only for high-impact ambiguity such
as target month/arXiv ID, whether network/API calls are allowed, or whether a
catalog merge should rebuild everything or update one paper.

## Common CLI Commands

Direct CLI use remains available:

```bash
conda run -n stella-env python scripts/fetch_high_velocity_lit.py --from 2026-03
conda run -n stella-env python scripts/annotate_catalog_data.py --on 2026-03
conda run -n stella-env python scripts/pull_literature_assets.py --arxiv-id 2402.10714
conda run -n stella-env python scripts/repair_ads_metadata.py --arxiv-id 2402.10714
conda run -n stella-env python scripts/init_catalog_review.py --arxiv-id 2402.10714
conda run -n stella-env python scripts/validate_catalog_review.py --arxiv-id 2402.10714 --require-complete
conda run -n stella-env python scripts/extract_catalog_tables.py --arxiv-id 2402.10714
conda run -n stella-env python scripts/validate_catalog_extraction.py --arxiv-id 2402.10714 --require-reviewed
conda run -n stella-env python scripts/init_hvs_candidates.py --arxiv-id 2402.10714
conda run -n stella-env python scripts/validate_hvs_candidates.py --arxiv-id 2402.10714 --require-complete
conda run -n stella-env python scripts/merge_hvs_candidate_catalog.py rebuild --literature-dir literature --catalog-dir catalog
conda run -n stella-env python scripts/build_hvs_catalog_html.py --catalog-dir catalog --html-dir html
conda run -n stella-env python scripts/render_lit_notes.py
```

See [docs/usage.md](docs/usage.md) for full CLI options and failure behavior.

## Source of Truth

JSON is canonical. Markdown, HTML, indexes, and object-level catalog files are
generated products or reading views. If generated output is wrong, fix the JSON
construction logic or renderer and regenerate.

Important outputs are documented in [docs/outputs.md](docs/outputs.md):

```text
notes/YYYY/YYYY-MM/YYYY-MM.json
notes/YYYY/YYYY-MM/YYYY-MM.title-triage.json
literature/<arxiv_id>/catalog_review.json
literature/<arxiv_id>/catalog_extraction.json
literature/<arxiv_id>/literature_hvs_candidates.json
catalog/<object_id>.json
html/live/
html/static/index.html
```

Generated data under `notes/`, `literature/`, `catalog/`, `html/`, and `logs/`
is ignored by Git by default. Do not force-add it unless that is explicitly
requested.

## Documentation

- Human workflow prompts: [docs/human-workflows.md](docs/human-workflows.md)
- Agent workflow rules: [docs/agent-workflows.md](docs/agent-workflows.md)
- Machine-readable workflow manifest: [workflows/stella_workflows.yaml](workflows/stella_workflows.yaml)
- Environment: [docs/setup.md](docs/setup.md)
- Usage: [docs/usage.md](docs/usage.md)
- Outputs: [docs/outputs.md](docs/outputs.md)
- Title triage rules: [docs/title-triage.md](docs/title-triage.md)
- Long-term vision: [docs/vision.md](docs/vision.md)
- Repository agent constraints: [AGENTS.md](AGENTS.md)

## Directory Map

```text
workflows/stella_workflows.yaml       Agent workflow routing contract
docs/                                 Documentation and workflow guides
skills/                               In-repository agent skills
scripts/fetch_high_velocity_lit.py    Main monthly literature fetcher
scripts/annotate_catalog_data.py      Add catalog_assessment to monthly JSON
scripts/pull_literature_assets.py     Archive local assets for papers
scripts/repair_ads_metadata.py        Fill paper-level bibcodes via ADS API
scripts/init_catalog_review.py        Generate catalog_review.json templates
scripts/extract_catalog_tables.py     Extract reviewed LaTeX tables into ECSV
scripts/init_hvs_candidates.py         Generate literature_hvs_candidates templates
scripts/merge_hvs_candidate_catalog.py Merge object-level HVS candidates catalog
scripts/build_hvs_catalog_html.py      Build object-level HVS catalog HTML demo
src/high_velocity_lit/                Core implementation
tests/                                Tests
notes/                                Generated monthly records and views
literature/                           Generated local literature archive
catalog/                              Generated object-level HVS catalog
html/                                 Generated local HTML display layer
logs/                                 Local run logs
```
