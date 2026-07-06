# Schema v0.2 Notes

Changelog for the v0.1 → v0.2 extraction-schema revision, plus the live
parking lot of deferred schema issues ("Still deferred" below is the only
forward-looking section; everything else is a compressed record).

**Status (2026-07-06): v0.2 landed, in two same-day batches.** The first
batch (morning) repaired the defects listed under "Landed in v0.2"; the
second batch (midday, after the gold8 `ai_only` triage) aligned the
extraction surface field-for-field with the gold guideline — see "Landed in
v0.2, second batch" below. No document was ever produced between the
batches, so `stella.literature_hvs_candidates.v0.2` has exactly one meaning:
the union of both. The user lifted the post-freeze
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

## Landed in v0.2, second batch (2026-07-06, after the gold8 ai_only triage)

Expert decisions from the triage, motivated by the plan to re-extract
method A (skill agent) and run a third B/C dev round on a surface that is
field-for-field aligned with the gold guideline — same schema for all three
methods, no scorer projections:

- **`bound_assessment` reduced to the two probability slots**
  (`bound_probability`, `unbound_probability`). Record whichever
  probability the paper reports; an escape probability **is** an unbound
  probability (escape ≡ unbound), so P_esc records under
  `unbound_probability`. The dropped fields — `escape_velocity`,
  `escape_velocity_ratio`, `escape_margin`, `bound_status_metric` — were
  rarely comparable across papers and diluted the scored vocabulary; no
  gold annotation ever used them. The scored vocabulary shrinks from 23 to
  19 fields (GUIDELINE §5, docs/benchmark-l2-spec.md amendment v0.2.1). AI
  values on the dropped fields in archived v0.1 runs simply leave the
  scored surface, exactly like `total_velocity`.
- **Plain-spelling `unit` contract**: the semantic validator rejects LaTeX
  markup (braces, `$`, backslashes, commands) in quantity `unit` fields —
  `mas yr^{-1}` must be written `mas yr^-1`; the typeset form stays in
  `raw_value`/source refs. Complementary scorer-side change:
  `normalize_unit` (synonym table v2) strips the same residue so archived
  v0.1 runs score correctly without re-extraction. Found via gold8
  unit_mismatch rows that were pure markup differences.
- **Gold-side unit discipline reaffirmed**: the 1807.00427 gold annotation
  had converted printed pc distances to kpc "for consistency" — reverted to
  the printed pc values, and GUIDELINE §6 now names pc↔kpc scale shifts
  explicitly in the never-convert examples.
- **Method A run provenance contract**: agent-harness reruns are archived
  like B/C runs under `benchmark/runs/<run_id>/` with a `run_config.json`
  that must record the **harness** (name/version of the coding-agent
  runtime) and **model**. `scripts/init_agent_run.py` scaffolds the config;
  the scorer copies `harness` into `run_source` and the report displays it.
  Per-paper `extraction.tooling` mirrors the same facts
  (`agent_runtime = "<harness>/<version>"`, `model_id`).
- **Version mechanics**: the legacy reader family gains
  `LegacyBoundAssessment` (restores the four dropped fields for v0.1
  documents) alongside `LegacyDerivedKinematics.total_velocity`. Pipelines
  bumped again: B 0.6.0 (prompt template v0.6.0), C 0.3.0. The batch was
  briefly minted as "v0.3" with a `benchmark-freeze-v3` tag; since the
  first-batch v0.2 never had documents, the user folded it back into v0.2
  and the `benchmark-freeze-v2` tag was re-pointed to the final v0.2
  commit (the interim tags anchored no runs).

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
  drive whether a later revision opens this up (cf. the "no schema
  teardown" redline in docs/benchmark-plan.md).

(The pre-v0.2 gold/AI alignment findings and the Phase 3/4 projection plan
that used to be archived here are fully implemented in
`stella.benchmark.scoring` and specified in docs/benchmark-l2-spec.md R2;
see git history of this file for the original text.)
