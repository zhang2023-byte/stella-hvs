# Usage

Run the default 2025 to 2026-to-date job:

```bash
bash scripts/run_2025_2026.sh
```

Run one month:

```bash
conda run -n stella-env python scripts/fetch_high_velocity_lit.py \
  --from 2026-03 \
  --to 2026-03 \
  --max-results 20
```

Run without fetching DeepXiv brief:

```bash
conda run -n stella-env python scripts/fetch_high_velocity_lit.py \
  --from 2026-03 \
  --to 2026-03 \
  --max-results 20 \
  --brief False
```

Useful options:

```text
--source deepxiv|arxiv       Search backend. Default: deepxiv.
--classifier rules|llm       Title classifier. Default: rules.
--from DATE                  Start: YYYY-MM-DD, YYYY-MM, or YYYY.
--to DATE                    End: YYYY-MM-DD, YYYY-MM, YYYY, or none. Default: today.
--brief True|False           Fetch DeepXiv brief. Default: True.
--llm-review True|False      With rules, send weak matches to the LLM. Default: False.
--max-results N              Results per query/category.
--categories A,B,C           arXiv categories. Default: astro-ph.GA,astro-ph.SR,astro-ph.IM.
--min-score X                Optional DeepXiv score floor.
--token TOKEN                Override DEEPXIV_TOKEN.
```

Date parsing:

```text
--from 2026-03-15  starts on 2026-03-15
--from 2026-03     starts on 2026-03-01
--from 2026        starts on 2026-01-01
--to 2026-03-15    ends on 2026-03-15
--to 2026-03       ends on 2026-03-31
--to 2026          ends on 2026-12-31
--to none          ends today
```

Future dates are clamped to today. Invalid date formats fail fast.

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
