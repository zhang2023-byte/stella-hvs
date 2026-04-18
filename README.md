# High-Velocity Star Literature Workflow

This workspace collects monthly DeepXiv/arXiv literature notes for high-velocity star research.

Default flow:

- Search with DeepXiv.
- Split by arXiv category.
- Deduplicate by arXiv ID.
- Classify titles with local rules.
- Fetch DeepXiv brief only for selected papers.

## Setup

```bash
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

One month:

```bash
conda run -n stella-env python scripts/fetch_high_velocity_lit.py \
  --start-year 2026 \
  --start-month 3 \
  --end-year 2026 \
  --end-month 3 \
  --max-results 20
```

More commands and options: [docs/usage.md](docs/usage.md)

## Key Docs

- Title triage rules and LLM review: [docs/title-triage.md](docs/title-triage.md)
- Outputs and logs: [docs/outputs.md](docs/outputs.md)

## Layout

```text
scripts/fetch_high_velocity_lit.py   Main CLI
scripts/run_2025_2026.sh             Convenience batch runner
docs/                                Detailed docs
notes/                               Generated Markdown notes
src/high_velocity_lit/               Pipeline implementation
```
