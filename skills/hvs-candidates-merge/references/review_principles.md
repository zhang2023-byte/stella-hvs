# HVS Candidates Merge Review Principles

## Matching Policy

- Gaia source ID is the strongest match key. Candidates with the same non-empty
  normalized `gaia_source_id` are merged into the same object.
- If one side or both sides have no Gaia source ID, compare RA/Dec with
  `astropy.coordinates.SkyCoord`. A separation strictly `< 5 arcsec` means the
  candidates are treated as the same object.
- If two records have different non-empty Gaia source IDs, do not merge them
  even when their RA/Dec are closer than 5 arcsec. Emit and review a warning.
- If two records have the same Gaia source ID but their RA/Dec separation is
  not `< 5 arcsec`, merge them by Gaia ID but emit and review a warning.
- If an object group ends up with more than one non-empty Gaia source ID through
  a coordinate bridge, treat it as a high-priority warning.

## Warning Review

For `different_gaia_near_coordinates`:

- Check both paper-level JSON files.
- Confirm whether one Gaia ID was transcribed incorrectly.
- Confirm whether RA/Dec values were parsed from the correct row and component.
- Leave the object split unless the source JSON is corrected and a rerun merges
  them under the normal rules.

For `same_gaia_far_coordinates`:

- Confirm the Gaia ID in both sources.
- Check RA/Dec units, sexagesimal format, epoch/frame notes, and table rows.
- If the Gaia IDs are correct, keep the merge and leave the warning as a review
  marker unless the coordinate source data can be corrected.

For `coordinate_parse_failed`:

- Check `core.observed_phase_space.ra` and `.dec` in the paper-level source.
- Fix invalid coordinate text or units in `literature_hvs_candidates.json`, not
  in generated `catalog/` output.

## Output Audit Checklist

- Every object file has `schema_version:
  stella.hvs_candidate_catalog.object.v1`.
- `sources[]` entries trace back to a source paper through:
  `source`, `paper`, `source_json_path`, `record_id`,
  `paper_candidate_id`, and `gaia_source_id`.
- `method_chain[]` is grouped by `source`; local `step-XX` IDs remain local to
  that source.
- `candidates[]` is grouped by `source` and only keeps the requested
  `identifiers` and simplified `core`.
- `method_chain` and `candidates.core` do not contain `source_refs`.
- Quantity records in object-level `core` only keep `value`, non-empty error
  fields, `unit`, and `method_refs`.
- File names prefer Gaia source ID slugs. Objects without Gaia source IDs use
  the earliest source's `paper_candidate_id`, ordered by `paper.month`, arXiv
  ID, and `record_id`.

## Generated Output Boundary

Treat `catalog/` as generated output. Do not manually patch object JSON or the
Markdown index. Correct bad merges by fixing the source
`literature_hvs_candidates.json` or the merge implementation, then rerun:

```bash
conda run -n stella-env python scripts/merge_hvs_candidate_catalog.py rebuild \
  --literature-dir literature \
  --catalog-dir catalog
```
