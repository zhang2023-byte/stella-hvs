---
name: hvs_dynamics_calculate
description: Calculate object-level HVS Galactocentric dynamics, Gaia DR3 zero-point-corrected astrometry, total velocity, unbound probability, and graveyard flags for Stella catalog objects.
---

# HVS Dynamics Calculate

Use this skill after the object catalog exists:

```text
catalog/candidates/<object_id>.json
```

This workflow writes a generated `dynamics` field into each object JSON. It
does not edit paper-level `literature_hvs_candidates.json` and does not decide
whether an object belongs in the catalog.

## Workflow

1. Confirm `catalog/candidates/` exists and that the object JSON files contain
   `external_enrichment.providers.gaia_dr3.raw_columns` from a prior enriched
   merge. Public Gaia DR3 astroquery calls are needed only when the user
   explicitly asks to refresh external data.
2. Prefer a dry run for first review:

   ```bash
   conda run -n stella-env python scripts/calculate_hvs_dynamics.py \
     --catalog-dir catalog \
     --samples 10000 \
     --dry-run True
   ```

3. Run the calculation when the target set is correct:

   ```bash
   conda run -n stella-env python scripts/calculate_hvs_dynamics.py \
     --catalog-dir catalog \
     --samples 10000 \
     --write True
   ```

   Limit to one object when debugging:

   ```bash
   conda run -n stella-env python scripts/calculate_hvs_dynamics.py \
     --catalog-dir catalog \
     --object-id Gaia_DR3_123456789 \
     --samples 10000 \
     --write True
   ```

   Force fresh Gaia DR3 queries only when explicitly requested:

   ```bash
   conda run -n stella-env python scripts/calculate_hvs_dynamics.py \
     --catalog-dir catalog \
     --samples 10000 \
     --refresh-external \
     --write True
   ```

4. Review the JSON summary. Check skipped reasons, `graveyard_count`,
   `lower_limit_count`, and per-object warnings.

## Calculation Rules

- Gaia astrometry comes only from official Gaia DR3 raw rows cached at
  `external_enrichment.providers.gaia_dr3.raw_columns`. Prefer the object's
  DR3-family Gaia source ID when present; otherwise a matched cached
  `external_enrichment.providers.gaia_dr3.source_id` is acceptable because it
  came from the prior official Gaia DR3 enrichment. DR2-only objects without a
  matched DR3 cache are skipped.
- Parallax zero-point correction uses `zero_point.zpt` from
  `gaiadr3-zeropoint`; missing required raw Gaia columns or failed correction
  yields `zero point correction not available`.
- Continue only when `corrected_parallax / parallax_error > 5`; otherwise
  write `parallax uncertainty too large` plus an astrometry audit payload with
  the raw parallax, zero point, corrected parallax, parallax error, and corrected
  parallax-over-error.
- RV priority is literature first, choosing the literature RV with the smallest
  numeric error. If no literature RV exists, ignore SIMBAD RV and use the
  Boubert et al. missing-RV minimum Galactocentric rest-frame velocity
  convention, marking the result as a lower limit.
- The same MCMC posterior sample set, default exactly 10000 samples, drives
  velocity summaries, escape comparisons, Beta probabilities, raw MC fractions,
  and `graveyard`.
- `graveyard=true` means the 10000 posterior samples contain zero unbound
  realizations.
- Bound probability follows Boubert et al. 2018:
  `P_bound ~ Beta(N_bound + 1/2, N - N_bound + 1/2)`.

## Boundaries

- Do not hand-edit generated `dynamics` fields. Rerun the CLI.
- Rerunning `merge_hvs_candidate_catalog.py` rebuilds object JSON and resets
  `dynamics`; rerun this workflow after a merge rebuild or update.
- Default calculation mode performs no network calls. Use `--refresh-external`
  only with explicit permission for Gaia DR3 refresh queries.
- Do not call DeepXiv, ADS, LLMs, or literature download tools.
- Do not force-add generated `catalog/` outputs unless explicitly requested.
