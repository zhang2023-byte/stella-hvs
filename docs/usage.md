# Usage

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

Useful options:

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

Default queries:

```text
hypervelocity stars
hypervelocity star
high velocity stars
high-velocity stars
runaway stars
OB runaway stars
unbound stars
escaping stars
```
