# High-Velocity Star Literature Workflow

This workspace collects monthly DeepXiv/arXiv literature records for high-velocity star research.

Default flow:

- Search with DeepXiv.
- Split by arXiv category.
- Deduplicate by arXiv ID.
- Classify titles with local rules.
- Save canonical JSON under `notes/`, then generate Markdown notes from that JSON.

## Setup

```bash
conda env create -f environment.yml
conda activate stella-env
cp scripts/env.example .env
```

Fill `DEEPXIV_TOKEN` in `.env`.

Details: [docs/setup.md](docs/setup.md)

## Run

Default batch:

```bash
bash scripts/run_2025_2026.sh
```

Minimal run:

```bash
conda run -n stella-env python scripts/fetch_high_velocity_lit.py \
  --from 2026-03
```

Catalog verification for one paper or a sampled set from `notes/index.json`:

```bash
conda run -n stella-env python scripts/verify_literature_catalog.py \
  --arxiv-id 2405.04750

conda run -n stella-env python scripts/verify_literature_catalog.py \
  --sample-index 3 \
  --seed 7

conda run -n stella-env python scripts/verify_literature_catalog.py \
  --take-index 10 \
  --only-unverified

conda run -n stella-env python scripts/apply_agent_catalog_adjudication.py \
  --arxiv-id 2401.02017 \
  --has-catalog true \
  --internal-delivery format_only \
  --external-delivery full \
  --location-class mixed \
  --primary-host china-vo \
  --confidence high \
  --evidence "The paper states that the catalog is available on China-VO." \
  --reasoning-notes "The full machine-readable catalog is externally hosted; the internal appendix is only guidance."

conda run -n stella-env python scripts/init_catalog_ingestion.py \
  --arxiv-id 2401.02017
```

More commands, defaults, and date rules: [docs/usage.md](docs/usage.md)

## Key Docs

- Title triage rules and LLM review: [docs/title-triage.md](docs/title-triage.md)
- Outputs and logs: [docs/outputs.md](docs/outputs.md)
- Agent context for future work: [AGENTS.md](AGENTS.md)

## Layout

```text
scripts/fetch_high_velocity_lit.py   Main CLI
scripts/annotate_catalog_data.py     Add observational catalog assessments to note JSON
scripts/verify_literature_catalog.py Verify one paper's catalog content across DeepXiv, PDF, and source
scripts/apply_agent_catalog_adjudication.py Persist agent overrides for ambiguous per-paper catalog judgments
scripts/init_catalog_ingestion.py   Bootstrap machine-readable catalog-ingestion scaffolds for a verified paper
scripts/render_lit_notes.py          Regenerate Markdown from note JSON
scripts/run_2025_2026.sh             Convenience batch runner
docs/                                Detailed docs
literature/                          Per-paper catalog verification records and extracted source artifacts
skills/                              Repo-local reusable agent skills
notes/                               Canonical JSON under YYYY/YYYY-MM/ plus generated Markdown and collection index
src/high_velocity_lit/               Pipeline implementation
```
