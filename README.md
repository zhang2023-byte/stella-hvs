# High-Velocity Star Literature Workflow

This workspace collects monthly DeepXiv/arXiv literature notes for high-velocity star research.

Default behavior:

- Search with DeepXiv.
- Split searches by arXiv category.
- Deduplicate by arXiv ID.
- Classify titles with fast local rules.
- Fetch DeepXiv brief only for selected papers.

## Setup

Run inside the project conda environment:

```bash
conda activate stella-env
```

Keep project secrets in `.env`. This file is ignored by Git.

```bash
cp scripts/env.example .env
```

Required:

```env
DEEPXIV_TOKEN=
```

Optional, only needed when using LLM review:

```env
LLM_API_KEY=
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
```

## Run

Run the default 2025 to 2026-to-date job:

```bash
bash scripts/run_2025_2026.sh
```

Run one month:

```bash
conda run -n stella-env python scripts/fetch_high_velocity_lit.py \
  --start-year 2026 \
  --start-month 3 \
  --end-year 2026 \
  --end-month 3 \
  --max-results 20
```

Run without fetching DeepXiv brief:

```bash
conda run -n stella-env python scripts/fetch_high_velocity_lit.py \
  --start-year 2026 \
  --start-month 3 \
  --end-year 2026 \
  --end-month 3 \
  --max-results 20 \
  --no-brief
```

## Title Triage

Default classifier is `rules`.

Direct matches are accepted immediately. These include titles with explicit terms such as:

```text
hypervelocity star
high-velocity star
runaway star
unbound star
escaping/ejected star
stellar escaper
walkaway star
```

Weak matches are also accepted by default, but marked as `rule-weak` in the note. These cover mechanism or proxy topics such as stellar ejection, bow shocks, Galactic-center ejection language, stellar collisions/disruptions, cluster escapers, and unusual stellar kinematics.

To ask the LLM to review weak matches before keeping them:

```bash
conda run -n stella-env python scripts/fetch_high_velocity_lit.py \
  --classifier rules \
  --llm-review-weak
```

To use full LLM title classification:

```bash
conda run -n stella-env python scripts/fetch_high_velocity_lit.py \
  --classifier llm
```

## Useful Options

```text
--source deepxiv|arxiv       Search backend. Default: deepxiv.
--classifier rules|llm|none  Title classifier. Default: rules.
--llm-review-weak            Send weak rule matches to the LLM.
--max-results N              Results per query/category.
--categories A,B,C           arXiv categories. Default: astro-ph.GA,astro-ph.SR,astro-ph.IM.
--min-score X                Optional DeepXiv score floor.
--no-brief                   Skip DeepXiv brief calls.
--token TOKEN                Override DEEPXIV_TOKEN.
```

## Outputs

```text
notes/index.md      Monthly index
notes/YYYY-MM.md    Monthly literature note
logs/               Ignored local run logs
```

Each monthly note includes selected papers, arXiv/PDF links, matched queries/categories, title-triage labels, DeepXiv brief, abstract, and query summary.

## Project Layout

```text
scripts/fetch_high_velocity_lit.py   Main CLI
scripts/run_2025_2026.sh             Convenience batch runner
scripts/env.example                  Example environment file
src/high_velocity_lit/               Pipeline implementation
notes/                               Generated Markdown notes
```
