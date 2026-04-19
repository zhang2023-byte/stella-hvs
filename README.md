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
scripts/render_lit_notes.py          Regenerate Markdown from note JSON
scripts/run_2025_2026.sh             Convenience batch runner
docs/                                Detailed docs
notes/                               Canonical JSON and generated Markdown notes
src/high_velocity_lit/               Pipeline implementation
```
