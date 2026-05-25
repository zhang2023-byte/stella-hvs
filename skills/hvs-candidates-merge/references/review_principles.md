# HVS Candidates Merge Review Principles

## Matching Policy

- Literature Gaia source ID is the strongest match key. Candidates with the
  same non-empty normalized `gaia_source_id` are merged into the same object.
  `Gaia EDR3` and `Gaia DR3` records with the same numeric source ID share a
  DR3-family match key; `Gaia DR2` remains a separate family.
- Default `--external-merge-mode auto` can also merge by same external Gaia DR3
  source ID, same SIMBAD object, or same strong alias when those signals do not
  conflict with literature Gaia IDs.
- Strong alias matches require `<5 arcsec` when both records have coordinates.
  If either side lacks coordinates, alias-only merges are allowed but emit
  `alias_only_merge_no_coordinate_check`.
- Coordinate-only matches require separation strictly `<5 arcsec`, no
  Gaia/SIMBAD identity conflict, and a unique coordinate neighbor in auto mode.
- `--external-merge-mode review` records potential external/alias merges without
  applying them. `--external-merge-mode off` keeps the old Gaia/coordinate-only
  policy.

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

For `same_alias_far_coordinates`, `same_alias_literature_gaia_conflict`,
`external_gaia_literature_gaia_conflict`, or `simbad_literature_gaia_conflict`:

- Treat the merge as blocked unless the source paper-level identifiers are
  corrected.
- Check `merge.evidence[]` to see which provider or alias produced the blocked
  edge.
- Do not patch generated object JSON by hand.

## Output Audit Checklist

- Every object file has `schema_version:
  stella.hvs_candidate_catalog.object.v5`.
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
- `merge.evidence[]` records applied, blocked, and review-only identity edges.
- File names prefer normalized Gaia release-family slugs. Objects without Gaia
  source IDs use strong paper candidate IDs, then coordinate slugs, then stable
  source record slugs. Strong paper ID slugs preserve ASCII `+` and `-`; weak
  paper IDs such as bare numbers are not used directly as filenames.

## Generated Output Boundary

Treat `catalog/` as generated output. Do not manually patch object JSON or the
Markdown index. Correct bad merges by fixing the source
`literature_hvs_candidates.json` or the merge implementation, then rerun:

```bash
conda run -n stella-env python scripts/merge_hvs_candidate_catalog.py rebuild \
  --literature-dir literature \
  --catalog-dir catalog \
  --enrichment-mode auto \
  --external-merge-mode auto
```
