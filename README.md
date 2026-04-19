# High-Velocity Star Literature Workflow

This workspace collects monthly DeepXiv/arXiv literature records for high-velocity star research.

Default flow:

- Search with DeepXiv.
- Split by arXiv category.
- Deduplicate by arXiv ID.
- Classify titles with local rules.
- Save canonical JSON, then generate Markdown notes from that JSON.

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

Minimal run:

```bash
conda run -n stella-env python scripts/fetch_high_velocity_lit.py \
  --from 2026-03
```

More commands, defaults, and date rules: [docs/usage.md](docs/usage.md)

## Key Docs

- Title triage rules and LLM review: [docs/title-triage.md](docs/title-triage.md)
- Outputs and logs: [docs/outputs.md](docs/outputs.md)
- Agent context for future work: [AGENTS.md](AGENTS.md)

## Layout

```text
scripts/fetch_high_velocity_lit.py   Main CLI
scripts/run_2025_2026.sh             Convenience batch runner
data/literature/                     Canonical JSON outputs
docs/                                Detailed docs
notes/                               Markdown generated from JSON
src/high_velocity_lit/               Pipeline implementation
```
