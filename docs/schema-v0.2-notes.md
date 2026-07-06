# Schema v0.2 Notes

Parking lot for schema issues identified after the `benchmark-freeze-v1`
window closed, or triaged out of v0.1 during the pre-freeze scan.

**Superseded:** v0.2 was replaced by v0.3 later the same day, before any
extraction instantiated it — see [schema-v0.3-notes.md](schema-v0.3-notes.md).
No document anywhere carries the v0.2 version string.

**Status (2026-07-06): v0.2 landed.** The user lifted the post-freeze
redline at the pre-formal-runs point — the dev iteration on gold8 was
closed and no formal run existed yet, so the whole formal campaign runs on
the repaired surface instead of baking known v0.1 defects into the paper's
headline numbers. Scope discipline for the batch: **clear design defects
only, no prompt fine-tuning** (overfitting guard). The v0.1 corpus under
`literature/` and the archived v0.1 runs are validated historical data:
readers accept them through a legacy model (`schema_models.py`), nothing is
re-extracted, and the scorer's projection keeps scoring archived v0.1 runs.

## Landed in v0.2 (2026-07-06)

- **`derived_kinematics.total_velocity` removed** (decided with the L2 spec
  approval): an early-schema artifact that in practice always held the
  Galactic rest-frame speed. Whole speeds keep exactly one slot,
  `galactic_rest_frame_velocity`. The scorer's unconditional projection
  (docs/benchmark-l2-spec.md R2) now applies only when scoring archived
  v0.1 runs.
- **Inline `thebibliography` accepted as bibliography evidence** (Phase 2
  pilot finding, paper 2101.10878): the v0.1 validator required
  `candidate_origin.citation.bibliography_refs` to point at `.bib`/`.bbl`
  files, but A&A-style papers embed `\begin{thebibliography}` inside the
  main `.tex` and ship no `.bbl` — a `cited_from_literature` candidate
  could not validate no matter how correct the extraction (the pilot
  plateaued at 20 errors on an otherwise clean document). v0.2 accepts
  `.tex` line ranges whose resolved text contains `\bibitem` entries; the
  bibkey/author/title support checks run on that text unchanged.
- **`input_catalog` allowed as direct producer for catalog-adopted values**
  (gold8 dev-run finding): the v0.1 direct-producer vocabulary demanded
  producer-family step_types for `stellar_parameters` / `abundances` /
  `quality_flags` quantities, but papers routinely adopt RUWE, Teff, [Fe/H]
  etc. straight from the input catalog's columns without performing any
  inference step. Method B plateaued at 7 and 15 such errors on papers
  1804.10179 and 1807.00427 (temperature 0, 3 repair rounds), uniformly
  across models; method C burned reviewer tokens fixing the same thing.
  `stellar_parameter` and `quality` categories now allow `input_catalog`.
- **Version mechanics**: `LITERATURE_HVS_CANDIDATES_SCHEMA_VERSION` is
  v0.2; index/catalog builders dispatch through
  `validate_literature_hvs_document` (v0.1 documents validate against
  `LegacyLiteratureHvsCandidatesRecord`); the semantic validator accepts
  only current-version output. The 18 legacy files that already failed
  strict validation before v0.2 (empty bibcode, pre-vocabulary step_type
  strings) fail identically after it — no regression, no repair (they
  predate the frozen vocabulary and are skipped by builders as before).
- Extraction pipelines bumped: B `stella-benchmark-extraction` 0.5.0
  (prompt template v0.5.0 via the regenerated schema reference), C
  `stella-agentic-extraction` 0.2.0. The unit-synonym comparison problem
  from the pre-freeze scan is owned by the L2 scorer's versioned synonym
  table (docs/benchmark-l2-spec.md R4) — resolved without a schema change.

## Still deferred (need design decisions or evidence; not "clear defects")

Triaged out of v0.1 (2026-06-11 corpus scan, 898 candidates) and kept out
of v0.2 deliberately:

- `galactic_longitude` / `galactic_latitude` (82 uses each in `extra[]`):
  papers report l/b directly. Needs the same frame/epoch design discussion
  as the RA/Dec CoordinateQuantityRecord; l/b is usually derivable from
  RA/Dec.
- `total_proper_motion` (82+7 uses in `extra[]`): mechanically derivable
  from pmRA/pmDec; a typed slot would mostly duplicate information.
- `catalog_source` (165 uses in `extra[]`): "which input catalog this row
  came from" overlaps with `source_refs` + `input_catalog` method lineage;
  needs a design decision rather than a new field.
- `tangential_only` flags (154 uses in `extra[]`): the Boubert-style
  missing-RV convention. Expressible as `limit_kind: "lower_limit"` on the
  whole-speed slot; the legacy extra[] flags can be normalized during
  post-benchmark re-extraction.
- Provenance category for `galactocentric_radius` (added in v0.1): the
  direct-producer classifier currently leaves it unconstrained; decide
  whether it should require `velocity_calculation`-family lineage.
- `EBV` in `extra[]` (165 uses): not a schema gap — `photometry[]` already
  has `extinction`/`reddening` measurement types. An extraction convention
  error in legacy files; fix via post-benchmark re-extraction.
- Controlled unit vocabulary: scoring-side synonyms cover the benchmark;
  constraining the extraction `unit` strings is a bigger contract change.
- Legacy limit/range raw values (~20 quantities): files migrated from v7
  keep limits only in `raw_value` with empty `value`; normalize during
  post-benchmark re-extraction.
- Identity matcher tier B (deferred by design, not schema): a
  proper-motion-aware fallback tolerance (`5" + |mu| x dt_max`) for pairs
  with proper motion but no usable epoch. The gold8 scorecards' matching
  sensitivity block shows the coordinate tier is rarely load-bearing;
  revisit if the test-set papers change that.
- **No machine-explicit "printed form" on distance/velocity quantities**
  (template trial, 1907.11725): papers print plain linear values,
  `log10(D/kpc)`, or distance moduli; the printed form lives in free-text
  `unit`. Both gold and AI transcribe the same printed number, so L2 lines
  up without conversion; a typed `form` enum would make it
  machine-explicit. Revisit with benchmark evidence.
- **Single-slot quantity fields force "pick one" on multi-method
  estimates** (S5-HVS1-style papers): a multi-valued redesign is a SHAPE
  change pulling in method-tagged estimates, set-vs-set L2 scoring, and a
  value-boundary rule. The benchmark now measures the pick-one loss
  directly (`gold_note_present` mismatch triage, R8) — let that evidence
  drive whether a later revision opens this up (cf. the B2 "no schema
  teardown" line).

## Historical record

The sections below preserve the original findings and the Phase 3/4
alignment plan that produced the scorer-owned projection; they are
superseded by the implementations above but kept for provenance.

### Expert-gold / AI alignment before Phase 4 scoring (2026-06-26)

During Phase 3 calibration, the expert gold contract was narrowed without
changing the frozen AI extraction schema, skill, or validator:

- expert gold no longer records the subjective `galactic_bound_claim` enum;
  candidate inclusion and its PDF evidence are the L1 target, while numeric
  boundness remains in `bound_assessment.*` quantities;
- expert gold no longer scores `derived_kinematics.total_velocity`; the only
  scored whole-speed field is
  `derived_kinematics.galactic_rest_frame_velocity` for a speed whose Galactic
  or Galactocentric rest frame is stated in the table header, caption, or text.

Scorer-owned projection rules delivered with Phase 4 (all implemented and
fixture-covered in `stella.benchmark.scoring`):

1. AI-only `inclusion_assessment.galactic_bound_claim` is ignored in L1
   scoring; it creates no false positive or negative.
2. AI whole speeds are compared on the gold scoring surface through the
   unconditional, flagged `total_velocity` fallback
   (docs/benchmark-l2-spec.md R2).
3. Historical v0.1 runs are scored through that projection without
   rewriting the archives.
