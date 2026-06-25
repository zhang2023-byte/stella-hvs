# Expert Annotation Guideline

Status: draft for calibration (Phase 3 starts with 2-3 jointly annotated
papers; this document is revised before formal annotation begins).
Record the git short hash of the version you used in every annotation's
`guideline_version` field (quoted — all-digit hashes parse as numbers).

## 1. What this benchmark measures

We compare expert manual extraction against AI extraction of hypervelocity
star (HVS) candidates from the literature. Your annotations become the gold
standard, scored on three layers:

- **L1 — candidate set**: which objects the paper treats as HVS candidates
  (precision/recall after identity matching; false positives on
  no-candidate papers).
- **L2 — values**: normalized quantity values, units, and limit semantics.
- **L3 — evidence**: whether extracted values point at genuine support in
  the paper.

You annotate what the **paper claims**, not what is astrophysically true.
If the paper says a star is unbound and you disagree scientifically, record
the paper's claim (your disagreement can go in `notes`).

## 2. The two workflows

Your role for each paper is fixed in
`benchmark/manifest/sampling_manifest.json`. Never swap roles.

**Blind** (12 papers, 5 of them annotated by both experts): read the paper
PDF (`literature/<arxiv_id>/arxiv.pdf`) like a referee and fill the
annotation template from scratch.

- Do not open extracted JSON, TeX sources, ECSV files, or the review
  workbench for these papers. The PDF is the only input.
- For double-annotated (overlap) papers: do not discuss the paper with the
  other annotator until both annotations are committed. Disagreements are
  adjudicated afterwards and feed Cohen's kappa.

**Verification** (35 papers): review AI-prefilled extractions in the review
workbench, which shows each AI assertion next to the PDF location it claims
to come from. Confirm, reject, or correct each assertion, and add anything
the AI missed — recall matters: skim the PDF for candidates and quantities
the AI did not extract, do not only audit what is shown.

**Evidence policy (both workflows): the PDF is normative.** The AI pipeline
reads LaTeX sources and tables converted from them; you read the compiled
PDF. If the PDF disagrees with what the AI quotes from TeX/ECSV, the PDF
wins — record the discrepancy in `notes` as a finding (it measures our
ingestion layer) instead of silently following either side.

## 3. What counts as a candidate (L1)

Include an object when **the paper treats it as possibly unbound from the
Milky Way** — as an HVS candidate, hyper-runaway, escaping or unbound star,
or a high-velocity star whose Galactic boundness the paper genuinely
questions.

Do **not** include:

- objects mentioned with "high velocity" or a generic velocity cutoff when
  the paper never questions their boundness;
- ordinary runaway stars, unless the paper also treats them as possibly
  unbound from the Galaxy;
- objects for which *you* would make an unbound claim but the paper does
  not — never make a bound/unbound decision the paper does not make;
- objects from other papers that this paper merely cites in passing. But
  **do** include cited candidates that this paper re-assesses (new data,
  new distances, revised kinematics): mark them
  `origin_type: cited_from_literature`.

Re-assessment means this paper **recomputes or questions the object's
Galactic boundness** — a new distance, revised kinematics, or a fresh
bound/unbound verdict. Merely confirming a radial velocity, or adding
chemistry, while citing another paper's "hypervelocity" label, is
cite-in-passing — not a candidate here.

For papers with **no** candidates under this definition, set
`status: no_candidates`, leave `candidates` empty, and briefly note in
`notes` which object groups you considered and why they fall outside the
definition (e.g. "Table 1 runaways: bound, paper never questions Galactic
boundness").

**Large candidate tables**: the candidate list (L1) must be complete — every
object the paper treats as a candidate gets an entry with at least
one paper-visible identifier or Gaia source id, and candidate-level evidence.
When there are more than 15 candidates, record full quantities (L2) only for
the **union** of:

- (a) the first 15 rows of the paper's main candidate table, and
- (b) every candidate individually discussed in the running text (named and
  given at least one sentence of its own discussion, not just a table row).

There is no priority between (a) and (b); a star in both sets is one entry.
(b) has no cap — individually discussed stars are the paper's scientific
focus and are never truncated. If the paper has no candidate table, (b)
alone applies. State the truncation in `notes`; scoring respects it.

## 4. Identity fields (L1)

Per candidate:

- `paper_candidate_id`: the paper's main display id for this object, usually
  the table row label or name used in the text (e.g. `S5-HVS1`, `HVS 7`,
  `J1234+5678`). Leave it empty when the paper's only visible identifier is a
  Gaia source id; put that value in `gaia_source_id` instead.
- `gaia_source_id`: strict form `Gaia DR2 123...` / `Gaia EDR3 123...` /
  `Gaia DR3 123...`, with the data release exactly as the paper states it.
  Leave empty if the paper gives none. Never look the id up in external
  databases — paper-visible only.
- `aliases`: other paper-visible identifiers, excluding values already written
  in `paper_candidate_id` or `gaia_source_id`. Leave it empty when there are no
  additional aliases. These aliases help identity matching, but they should not
  duplicate the main id or Gaia id.

At least one of `paper_candidate_id`, `gaia_source_id`, or `aliases` must be
filled. Do not invent a local id just to make the form look complete.

Do not put coordinates, proper motions, velocities, distances, or probabilities
at candidate top level. They are physical quantities and belong in
`quantities[]` using the vocabulary below. Coordinates and proper motions are
usually optional matching aids; fill them when the paper gives no usable name
or Gaia id, or when the value is directly relevant to the paper's HVS claim.

## 5. Quantities (L2) and evidence (L3)

Record the scored fields the paper reports per candidate, prioritizing:
radial velocity, distance, total velocity, Galactic rest-frame velocity,
escape velocity, bound/unbound probability. Field names are dotted paths
from the controlled list (the upgrade script rejects typos), e.g.
`observed_phase_space.radial_velocity`,
`derived_kinematics.total_velocity`,
`bound_assessment.unbound_probability`.

### Quantity vocabulary

Use only these `field` values in `quantities[]`. The first group is observed
phase-space information:

- `observed_phase_space.ra`
- `observed_phase_space.dec`
- `observed_phase_space.distance`
- `observed_phase_space.parallax`
- `observed_phase_space.proper_motion_ra`
- `observed_phase_space.proper_motion_dec`
- `observed_phase_space.radial_velocity`

The second group is derived kinematics:

- `derived_kinematics.galactocentric_x`
- `derived_kinematics.galactocentric_y`
- `derived_kinematics.galactocentric_z`
- `derived_kinematics.galactocentric_radius`
- `derived_kinematics.galactocentric_vx`
- `derived_kinematics.galactocentric_vy`
- `derived_kinematics.galactocentric_vz`
- `derived_kinematics.tangential_velocity`
- `derived_kinematics.galactocentric_tangential_velocity`
- `derived_kinematics.total_velocity`
- `derived_kinematics.galactic_rest_frame_velocity`

The third group is bound/unbound assessment:

- `bound_assessment.escape_velocity`
- `bound_assessment.escape_velocity_ratio`
- `bound_assessment.escape_margin`
- `bound_assessment.bound_probability`
- `bound_assessment.unbound_probability`
- `bound_assessment.bound_status_metric`

Do not fill photometry, spectroscopy, abundances, stellar parameters, quality
flags, or survey-specific columns in expert gold. Those may be useful catalog
enrichments elsewhere, but they are not part of this benchmark's HVS-candidate
accuracy target.

Coordinate fields follow the same "copy, do not convert" rule as other
quantities. Fill `observed_phase_space.ra` or `observed_phase_space.dec` only
when the paper prints a numeric coordinate component you can copy directly
(for example decimal degrees). If the paper only prints sexagesimal coordinates,
do not convert them by hand; rely on `paper_candidate_id`, `gaia_source_id`, or
`aliases` for identity, and mention coordinate-only identity problems in
`notes` for adjudication.

Field disambiguation and multiple estimates:

- A velocity the paper calls V_GSR, V_3D, or "velocity in the Galactic
  (rest) frame" → `derived_kinematics.galactic_rest_frame_velocity`. Reserve
  `derived_kinematics.total_velocity` for a plain "total"/"space velocity"
  stated without naming a frame.
- When the paper gives several values for the same quantity of one star
  (with vs without a Galactic-Centre-origin assumption, different distance
  models, ejection vs current velocity), record the one carrying the
  **fewest extra model assumptions** and put the rest in `notes`.

Value rules (mirror the extraction schema semantics):

- `value` is a single plain number as printed, e.g. `742`, `-12.3`,
  `1.3e5`. No units, operators, ranges, or footnote markers inside it.
- Use the paper's value and unit **exactly as printed — never recompute or
  convert**, even for "easy" transforms (log10 distance, distance modulus,
  parallax↔distance, km/s↔mas/yr). The AI side also preserves the printed
  value and unit text, so converting on the gold side would only misalign the
  two. E.g. a distance printed as `log10(D/kpc)=0.936` → `value: "0.936"`,
  `unit: "log(D/kpc)"`; a distance modulus → `unit: "mag"`. `unit` is free
  text: put the paper's form there and keep the full printed string in the
  evidence `quote`. (Probabilities are the one normalization — see below.)
- Uncertainties: symmetric into `error`; asymmetric into
  `lower_error`/`upper_error` (e.g. `743^{+15}_{-12}` → value `743`,
  lower_error `12`, upper_error `15`).
- One-sided limits (`v_tot > 500 km/s`): `limit_kind: lower_limit` (or
  `upper_limit`), bound number in `value`.
- Closed ranges (`500-700 km/s`): `limit_kind: range`, `value` empty,
  bounds in `range_lower`/`range_upper`.
- Bound/unbound probabilities: normalize to a 0-1 fraction with empty
  unit (paper's `99.995%` → value `0.99995`). Origin-comparison metrics
  (p_MW vs p_LMC, likelihood ratios) are *not* bound probabilities — skip
  them or put a remark in `notes`.
- Reddening/extinction, photometry, abundances, stellar parameters are not
  scored quantity fields; do not spend time on them.

Evidence (L3): every quantity and every candidate needs at least one
PDF locator — precise enough that another person finds it in under ~30
seconds, e.g. `"Table 2, row J1234+5678, col v_GC"` or `"Sec 4.1, second
paragraph"`. A short verbatim `quote` is encouraged for text claims; for
uncertainty forms, quote the printed form (e.g. `"743^{+15}_{-12}"`).

If a value is genuinely absent, do not invent it — absence of a field is
itself information ("paper does not report" vs "annotator missed" is
exactly what the benchmark separates).

## 6. Method diagnostics are not gold-scored

Do not fill structured method facts or a step-type checklist in the gold
annotation. The AI extraction still produces a schema-validated
`method_chain[]`, including `parameters[]` and field-level `method_refs`,
but those records are **unscored diagnostics** in this benchmark version.
Review pages may show them to help inspect model behavior; they are not
expert-validated gold truth and do not enter scoring.

If a method detail is necessary to explain an L1-L3 judgment, put it in
free-text `notes` near the affected candidate or quantity. Examples:
"distance uses the no-Galactic-center-origin case" or "paper's bound
probability assumes the McMillan potential." Do not spend time transcribing
solar parameters, potential names, or method stages unless they directly
clarify a scored candidate or quantity.

## 7. Mechanics

Recommended path:

1. Open the PDF in your editor or PDF viewer:
   `literature/<arxiv_id>/arxiv.pdf`.
2. Start the local annotation form:

   ```bash
   conda run -n stella-env python scripts/serve_gold_annotation.py \
     --arxiv-id <arxiv_id> \
     --annotator <you>
   ```

3. Fill the form from the PDF. Use **Save Draft** for interruption-safe
   checkpoints; it writes `benchmark/gold/<arxiv_id>/draft_<you>.json`
   without schema validation. When reopening the form, load that draft or start
   fresh.
4. Use **Validate** before final save. **Save** writes
   `benchmark/gold/<arxiv_id>/annotation_<you>.yaml` and generates the JSON
   twin from the same validated payload.
5. Commit the final YAML/JSON files. Never hand-edit the generated JSON; fix the YAML in the
   form or by hand and re-run validation.

CLI fallback:

1. Copy `benchmark/templates/gold_annotation_template.yaml` to
   `benchmark/gold/<arxiv_id>/annotation_<you>.yaml`
   (the filled example `gold_annotation_example.yaml` shows every feature).
2. Read the PDF and fill the YAML.
3. Run
   `python scripts/upgrade_gold_annotation.py benchmark/gold/<arxiv_id>/annotation_<you>.yaml`
   - it validates all controlled vocabularies, points at the offending
   line, cross-checks the paper's manifest role, and writes the gold JSON
   next to your YAML.

Budget guidance (calibrate in Phase 3): no-candidate papers ~15-30 min;
candidate papers ~45-90 min depending on table size. If a paper takes far
longer, stop and flag it in `notes` — that is a finding about annotation
cost, not a failure.
