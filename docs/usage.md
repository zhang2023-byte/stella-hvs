# Usage

Run the default 2025 to 2026-to-date job:

```bash
bash scripts/run_2025_2026.sh
```

Minimal run:

```bash
conda run -n stella-env python scripts/fetch_high_velocity_lit.py \
  --from 2026-03
```

Only `--from` is required. With the command above, the script starts on
2026-03-01 and runs through today, because `--to` defaults to today.

Run exactly one month:

```bash
conda run -n stella-env python scripts/fetch_high_velocity_lit.py \
  --from 2026-03 \
  --to 2026-03
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
--max-results N              Results per query/category. Default: 20.
--categories A,B,C           arXiv categories. Default: astro-ph.GA.
--min-score X                Optional DeepXiv score floor. Default: disabled.
--progress True|False        Show terminal progress bars. Default: True.
--token TOKEN                Override DEEPXIV_TOKEN.
--notes-dir PATH             Canonical JSON and Markdown output directory. Default: notes.
--logs-dir PATH              Local run logs. Default: logs.
```

Defaults:

```text
--to                today; future dates are also clamped to today
--source            deepxiv
--classifier        rules
--llm-review        False
--brief             True
--max-results       20 per query/category
--categories        astro-ph.GA
--min-score         disabled
--search-mode       hybrid
--progress          True; shown when a terminal is available, including under conda run
--sleep             0.2 seconds between search calls
--brief-sleep       0.2 seconds between brief calls
--llm-base-url      LLM_BASE_URL/OPENAI_BASE_URL/DEEPXIV_AGENT_BASE_URL, else https://api.openai.com/v1
--llm-model         LLM_MODEL/OPENAI_MODEL/DEEPXIV_AGENT_MODEL, else gpt-4o-mini
--llm-batch-size    25
--notes-dir         notes
--logs-dir          logs
```

At the start of a terminal run, the script prints the resolved parameter set,
including defaults. It writes to the terminal when available so `conda run`
still shows the status output. Secret values are never printed; tokens and API
keys are shown only as `configured` or `not configured`.

The default search is intentionally modest because high-velocity star papers are
a relatively small field and DeepXiv quota appears to scale with returned
records. It searches five representative query phrases in `astro-ph.GA`, for a
default maximum of 100 returned records per full month. Increase `--max-results`,
add `--extra-query`, or pass more `--categories` only when doing a broader
recall pass.

`--classifier llm` uses pure LLM classification. `--llm-review True` only has
an effect with `--classifier rules`; it sends weak rule matches to the LLM and
requires a configured LLM API key. LLM review/classification uses the title,
abstract returned by DeepXiv/arXiv search, and categories.

With the default rules classifier, `--brief True` fetches DeepXiv brief only for
strong/direct matches (`rule-direct`). Weak matches (`rule-weak*`) stay in the
monthly note but use only metadata already returned by DeepXiv search, such as
title, abstract, score, categories, and matched queries.

Monthly results are split into strong/direct and weak sections with a divider
between them. The note's `Search Abstract` section is the abstract returned by
DeepXiv search; it does not mean an extra `brief` request was made.

JSON is the source of truth. Each run writes monthly records and generated
Markdown into the same monthly note folder:

```text
notes/index.json
notes/index.md
notes/YYYY-MM/YYYY-MM.json
notes/YYYY-MM/YYYY-MM.md
```

The exact date range is stored inside each monthly JSON record as
`date_from`/`date_to`. Markdown files are generated from those JSON records and
should be treated as reading views.

To regenerate Markdown from existing JSON without calling DeepXiv:

```bash
conda run -n stella-env python scripts/render_lit_notes.py
```

Or regenerate one month:

```bash
conda run -n stella-env python scripts/render_lit_notes.py --month 2026-03
```

Catalog-data assessment uses an LLM to decide whether papers in existing note
JSON likely contain real observational high-velocity-star data or catalog/sample
tables. It uses each paper's abstract and DeepXiv brief when available, then
updates the JSON and refreshes the sibling Markdown file. It requires the same
LLM API environment variables as weak-match LLM review.

Assess one monthly note:

```bash
conda run -n stella-env python scripts/annotate_catalog_data.py --on 2026-03
```

Assess a range:

```bash
conda run -n stella-env python scripts/annotate_catalog_data.py \
  --from 2025-01 \
  --to 2025-06
```

When `--to` is omitted, `--from` runs from that date/month/year through today.
For example, `--from 2025-01` selects all note months from January 2025 through
the current month.

Assess several non-contiguous months:

```bash
conda run -n stella-env python scripts/annotate_catalog_data.py \
  --on 2025-01,2025-03,2026-02
```

`--on` accepts either one `YYYY-MM` value or one comma-separated list of
`YYYY-MM` values. Do not repeat `--on`, and do not use brackets.

Existing `catalog_assessment` fields are skipped unless `--force True` is set.

Per-paper catalog verification runs a deeper three-stage workflow on a selected
paper:

1. Use DeepXiv progressively (`head`, selected sections, optional raw fallback)
   to decide whether the paper appears to contain object-level catalog data.
2. Download the arXiv PDF and try to confirm the signal from the PDF text. When
   direct PDF text extraction is weak, Stella records that limitation and may
   continue with a source fallback if DeepXiv already gave a strong signal.
3. Download arXiv source safely, extract tables and data-like files, and store
   any external catalog path (for example VizieR/CDS) mentioned in the source.

Verify one paper:

```bash
conda run -n stella-env python scripts/verify_literature_catalog.py \
  --arxiv-id 2405.04750
```

Randomly sample a few papers from `notes/index.md`:

```bash
conda run -n stella-env python scripts/verify_literature_catalog.py \
  --sample-index-md 3 \
  --seed 7
```

Useful options:

```text
--arxiv-id ID[,ID...]       One arXiv ID or a comma-separated list.
--sample-index-md N         Randomly sample N papers from notes/index.md.
--seed N                    Seed for reproducible sampling.
--output-dir PATH           Output root. Default: literature.
--force                     Recompute even when literature/<id>/record.json exists.
--token TOKEN               Override DEEPXIV_TOKEN.
--max-sections N            Max DeepXiv sections before raw fallback. Default: 4.
```

If DeepXiv returns a daily limit error, completed months are kept. The script
writes a partial summary to `logs/partial_<run_id>.json`, appends it to
`logs/runs.jsonl` with `status: partial`, prints the resume command, and exits
without a Python traceback. Resume from the reported failed month after quota
recovers.

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
high-velocity stars
runaway stars
unbound stars
escaping stars
```

Broader category recall example:

```bash
conda run -n stella-env python scripts/fetch_high_velocity_lit.py \
  --from 2026-03 \
  --to 2026-03 \
  --categories astro-ph.GA,astro-ph.SR,astro-ph.IM
```
