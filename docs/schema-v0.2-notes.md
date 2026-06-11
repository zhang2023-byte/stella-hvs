# Schema v0.2 Notes

Parking lot for schema issues identified after the `benchmark-freeze-v1`
window closed, or triaged out of v0.1 during the pre-freeze scan. Do not
change the frozen v0.1 schema, skill text, or validator for these; collect
them here and batch them into v0.2 after the benchmark.

## Triaged out of v0.1 (2026-06-11 corpus scan, 898 candidates)

- `galactic_longitude` / `galactic_latitude` (82 uses each in `extra[]`):
  papers report l/b directly. Deferred because Galactic coordinates would
  need the same frame/epoch design discussion as the RA/Dec
  CoordinateQuantityRecord, and l/b is usually derivable from RA/Dec.
- `total_proper_motion` (82+7 uses in `extra[]`): mechanically derivable
  from pmRA/pmDec; a typed slot would mostly duplicate information.
- `catalog_source` (165 uses in `extra[]`): "which input catalog this row
  came from" overlaps with `source_refs` + `input_catalog` method lineage;
  needs a design decision rather than a new field.
- `tangential_only` flags (154 uses in `extra[]`): the Boubert-style
  missing-RV convention. Going forward this is expressible as
  `limit_kind: "lower_limit"` on total velocity; the legacy extra[] flags
  can be normalized during post-benchmark re-extraction.
- Provenance category for `galactocentric_radius` (added in v0.1): the
  direct-producer classifier currently leaves it unconstrained; decide
  whether it should require `velocity_calculation`-family lineage.
- `EBV` in `extra[]` (165 uses): not a schema gap — `photometry[]` already
  has `extinction`/`reddening` measurement types. This is an extraction
  convention error in legacy files; fix via re-extraction, and the
  benchmark GUIDELINE should call it out.
- Unit synonym normalization (`km/s` vs `km s^-1` vs `km s-1`, `mas/yr` vs
  `mas yr^-1`): not a schema change; build the synonym table in the
  benchmark scoring normalizer (Phase 4) and consider a controlled unit
  vocabulary for v0.2.
- Legacy limit/range raw values (~20 quantities): files migrated from v7
  keep limits only in `raw_value` with empty `value`; normalize to the
  structured limit fields during re-extraction.
- Identity matcher tier B (deferred by design, not schema): a
  proper-motion-aware fallback tolerance (`5" + |mu| x dt_max`) for pairs
  with proper motion but no usable epoch. Decide after the calibration
  phase shows how many pairs actually reach the coordinate tier; tiers A
  (propagate to J2016, 2") and C (fixed 5", faststars SIMBAD precedent)
  are implemented in `stella.benchmark.identity`.
