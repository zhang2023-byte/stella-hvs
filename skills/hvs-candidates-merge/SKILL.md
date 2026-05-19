---
name: hvs-candidates-merge
description: Merge Stella paper-level HVS candidates into object-level catalog JSON. Use when the user asks to merge HVS candidates, rebuild catalog/, update catalog/ with a new literature_hvs_candidates.json, review merge warnings, or audit object-level candidate grouping.
---

# HVS Candidates Merge

Use this skill after paper-level files exist:

```text
literature/<arxiv_id>/literature_hvs_candidates.json
```

The object-level outputs live in:

```text
catalog/<object_id>.json
catalog/hvs_candidates_index.json
catalog/hvs_candidates_index.md
```

This stage merges candidates across papers. It does not re-extract candidates
from paper text and does not edit paper-level `literature_hvs_candidates.json`
unless merge review finds a source-data problem that the user asks to fix.

## Workflow

1. Confirm this is the Stella repository by checking for `AGENTS.md`,
   `scripts/merge_hvs_candidate_catalog.py`, and `src/high_velocity_lit/`.
2. Inspect inputs:
   - For a full rebuild, scan `literature/*/literature_hvs_candidates.json`.
   - For an update, inspect the requested `--arxiv-id` or explicit JSON path
     and the current `catalog/` directory if it exists.
3. Choose the mode:
   - Use `rebuild` when catalog output is missing, stale, or the user asks to
     regenerate from scratch.
   - Use `update` when the user only wants to merge one newly created or
     revised paper-level candidate JSON into an existing catalog.
4. Prefer a dry run first when reviewing matching behavior:

   ```bash
   conda run -n stella-env python scripts/merge_hvs_candidate_catalog.py rebuild \
     --literature-dir literature \
     --catalog-dir catalog \
     --dry-run True
   ```

   ```bash
   conda run -n stella-env python scripts/merge_hvs_candidate_catalog.py update \
     --arxiv-id <arxiv_id> \
     --literature-dir literature \
     --catalog-dir catalog \
     --dry-run True
   ```

5. Run the selected command without `--dry-run True` after the plan looks
   reasonable:

   ```bash
   conda run -n stella-env python scripts/merge_hvs_candidate_catalog.py rebuild \
     --literature-dir literature \
     --catalog-dir catalog
   ```

   ```bash
   conda run -n stella-env python scripts/merge_hvs_candidate_catalog.py update \
     --arxiv-id <arxiv_id> \
     --literature-dir literature \
     --catalog-dir catalog
   ```

   Use an explicit path when the file is outside the default layout:

   ```bash
   conda run -n stella-env python scripts/merge_hvs_candidate_catalog.py update \
     --path literature/<arxiv_id>/literature_hvs_candidates.json \
     --literature-dir literature \
     --catalog-dir catalog
   ```

6. Review the command summary, then open `catalog/hvs_candidates_index.md`.
   Check `Warnings`, object counts, and source counts before considering the
   merge complete.

## Review Rules

Read `references/review_principles.md` when the merge reports warnings, when
object grouping looks surprising, or when the user asks to audit the merged
catalog. The reference defines the Gaia and coordinate matching policy, warning
interpretation, and generated-output boundaries.

## Boundaries

- Do not hand-edit generated files under `catalog/`.
- If an object merge is wrong because a source candidate has a bad Gaia ID,
  RA/Dec, or identifier, fix the corresponding
  `literature/<arxiv_id>/literature_hvs_candidates.json` and rerun the merge.
- Do not call DeepXiv or re-fetch literature for this workflow.
- Do not force-add generated `catalog/`, `literature/`, or `notes/` files to
  Git unless the user explicitly asks.
