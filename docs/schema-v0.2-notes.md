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

## Found during Phase 2 pilot runs (2026-06-12)

- **Inline `thebibliography` defeats citation provenance** (found on pilot
  paper 2101.10878): the frozen validator requires
  `candidate_origin.citation.bibliography_refs` to point at `.bib`/`.bbl`
  files, but A&A-style papers often embed `\begin{thebibliography}` inside
  the main `.tex` (2101.10878 ships no `.bbl` at all). For such papers a
  `cited_from_literature` candidate **cannot validate**, no matter how
  correct the extraction — the pilot pipeline plateaued at 20 errors (10
  candidates x 2 citation rules) with an otherwise clean document. v0.2
  should accept paper-text bibliography references (e.g. line ranges inside
  a `thebibliography` environment) as bibliography evidence. Until then
  this is a *systematic, documented* failure mode of the frozen surface:
  benchmark papers with inline bibliographies will lose citation-provenance
  points uniformly across all models, and error analysis must report it as
  a validator limitation, not a model failure.

## Found during Phase 1 review — template trial fill (2026-06-14)

- **No machine-explicit "printed form" on distance/velocity quantities**
  (found trial-filling 1907.11725, S5-HVS1): papers report distance as a plain
  linear value, `log10(D/kpc)`, or a distance modulus (RV occasionally as
  redshift). A quantity carries only `value` + free-text `unit`, with no field
  stating which printed form it is. The benchmark does **not** convert: the
  frozen AI side keeps the printed form (SKILL: "preserve the paper value and
  unit text", with the raw cell in `raw_value`), and the gold GUIDELINE matches
  it — `value: "0.936"`, `unit: "log(D/kpc)"`, original string in the evidence
  `quote`. Because gold and AI read the same printed number, their `value`s
  line up without any conversion; only unit-string synonyms (and, if ever
  needed, cross-form comparison) fall to the Phase 4 scoring normalizer. The
  gold lint also treats units containing `log`/`dex`/`mag` as legitimate
  transformed forms (not "unusual"). A typed log-distance / distance-modulus
  slot, or a `form` enum on the quantity, would make the form machine-explicit
  instead of living in free-text `unit`; revisit in v0.2. Many HVS papers
  report distances this way.

- **Single-slot quantity fields force "pick one" on multi-method estimates**
  (raised from the log-distance discussion, 2026-06-14): each scored quantity
  (`ObservedPhaseSpace.distance`, `DerivedKinematics.*velocity`, …) is a single
  `QuantityRecord | None`, but papers routinely report several values for one
  quantity of one star — S5-HVS1's distance (Model P / Model SP / GC-assumption)
  and velocity (V_GSR / V_GSR,GC / Model P / Model SP / ejection). The current
  GUIDELINE rule keeps the value with the fewest model assumptions and puts the
  rest into notes, so the alternatives are lost to free text. Asymmetry to note:
  the gold side's `quantities` is already a list and does not reject repeated
  fields, but the frozen AI side is single-valued — so multi-valued gold would
  not align for L2 scoring. A v0.2 redesign could let a quantity hold multiple
  method-tagged estimates, but this is a SHAPE change, not a patch, and pulls in
  three things: (a) a controlled method/condition tag per value (likely coupled
  to `method_chain`); (b) L2 becomes set-vs-set matching (precision/recall,
  alignment) instead of value-vs-value; (c) a boundary rule for which values
  count (headline / alternative / sensitivity / cited). Decide with evidence:
  the benchmark already measures the "pick-one + rest-in-notes" loss (how common
  multi-value is, how much is dropped, how much experts and AI disagree on which
  to pick) — let that drive whether and how v0.2 opens this up, rather than
  recomputing the schema on intuition (cf. the B2 "no schema teardown" line).

## Found during gold8 dev runs (2026-07-06)

- **Direct-producer step_type vocabularies plateau under repair** (run
  `gold8-b-01-deepseek-v4-pro`, papers 1804.10179 and 1807.00427): the frozen
  validator requires `quality_flags` / `abundances` / `stellar_parameters`
  quantities to cite direct producers from specific step_type families. At
  temperature 0 with 3 repair rounds, method B plateaued at 7 and 15 such
  errors respectively — the model keeps citing the input-catalog or
  sample-selection step that *reported* the value instead of a
  producer-family step. Method C's reviewer-repair loop resolved the same
  errors at extra token cost. Treat this as a frozen-surface known
  limitation in error analysis (uniform across models, like the
  inline-thebibliography case); consider relaxing or clarifying the
  direct-producer vocabulary in v0.2.

## Expert-gold / AI alignment before Phase 4 scoring (2026-06-26)

During Phase 3 calibration, the expert gold contract was narrowed without
changing the frozen AI extraction schema, skill, or validator:

- expert gold no longer records the subjective `galactic_bound_claim` enum;
  candidate inclusion and its PDF evidence are the L1 target, while numeric
  boundness remains in `bound_assessment.*` quantities;
- expert gold no longer scores `derived_kinematics.total_velocity`; the only
  scored whole-speed field is
  `derived_kinematics.galactic_rest_frame_velocity` for a speed whose Galactic
  or Galactocentric rest frame is stated in the table header, caption, or text.

Before Phase 4 scoring, add an explicit AI-to-gold projection and tests:

1. Ignore AI-only `inclusion_assessment.galactic_bound_claim` when scoring L1;
   it must not create a false positive or false negative.
2. Map AI-extracted V_GSR, V_GC, V_3D, and v_rf values with an explicit or
   inherited Galactic rest-frame definition to
   `derived_kinematics.galactic_rest_frame_velocity` on the gold scoring
   surface. Do not map a speed stated in a non-Galactic frame.
3. Specify how historical AI runs using `derived_kinematics.total_velocity`
   are projected, without rewriting the archived runs; cover this with scorer
   fixtures so a field-name mismatch cannot create an artificial L2 error.

At the next permitted AI schema/skill revision, align the extraction prompt and
template with this field mapping. Until then, preserve the frozen AI artifacts
and treat the projection as scorer-owned compatibility logic.

Decided with the L2 spec approval (2026-07-06): **v0.2 removes
`derived_kinematics.total_velocity` from the AI extraction schema** — the
field was an early-schema artifact and in practice always held the Galactic
rest-frame speed. Whole speeds keep exactly one slot,
`galactic_rest_frame_velocity`. The scorer's unconditional projection
(docs/benchmark-l2-spec.md R2) then applies only when scoring archived v0.1
runs.
