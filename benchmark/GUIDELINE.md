# Expert Annotation Guideline

Status: draft for calibration (Phase 3 starts with 2-3 jointly annotated
papers; this document is revised before formal annotation begins).
Record the git short hash of the version you used in every annotation's
`guideline_version` field (quoted — all-digit hashes parse as numbers).

## 1. What this benchmark measures

We compare expert manual extraction against AI extraction of hypervelocity
star (HVS) candidates from the literature. Your annotations become the gold
standard, scored on four layers:

- **L1 — candidate set**: which objects the paper treats as HVS candidates
  (precision/recall after identity matching; false positives on
  no-candidate papers).
- **L2 — values**: normalized quantity values, units, and limit semantics.
- **L3 — evidence**: whether extracted values point at genuine support in
  the paper.
- **L4 — method facts**: closed questions about the analysis (potential
  model, solar parameters, etc.) and a checklist of analysis stages.

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
`record_id`, one identifier, and candidate-level evidence. When there are
more than 15 candidates, record full quantities (L2) only for the **union**
of:

- (a) the first 15 rows of the paper's main candidate table, and
- (b) every candidate individually discussed in the running text (named and
  given at least one sentence of its own discussion, not just a table row).

There is no priority between (a) and (b); a star in both sets is one entry.
(b) has no cap — individually discussed stars are the paper's scientific
focus and are never truncated. If the paper has no candidate table, (b)
alone applies. State the truncation in `notes`; scoring respects it.

## 4. Identity fields (L1)

Per candidate:

- `record_id`: your stable id within this paper, usually the main name.
- `names`: every identifier the paper makes visible for the object (survey
  designations, Gaia ids, common names). These drive identity matching —
  more aliases, better matching.
- `gaia_source_id`: strict form `Gaia DR2 123...` / `Gaia EDR3 123...` /
  `Gaia DR3 123...`, with the data release exactly as the paper states it.
  Leave empty if the paper gives none. Never look the id up in external
  databases — paper-visible only.
- coordinates and motion — a matching aid of last resort, not a scored
  claim. They are only needed when the paper gives no usable name or Gaia
  id (e.g. anonymous table rows); otherwise leave everything null/empty:
  - `ra_raw`/`dec_raw`: paste the coordinate **exactly as printed**, e.g.
    `"12h34m03.0s"`, `"12:34:03.0"`, `"188.512 deg"`. The upgrade script
    converts mechanically — never convert by hand. Colon- or h-separated
    RA is read as hours; plain numbers as degrees.
  - or `ra_deg`/`dec_deg` directly when the paper already prints decimal
    degrees. Give the raw or the decimal form, not both.
  - `pm_ra_masyr`/`pm_dec_masyr` (Gaia convention: mu_alpha* includes
    cos dec) and `epoch_year` (e.g. 2016.0): fill when reported.

## 5. Quantities (L2) and evidence (L3)

Record the scored fields the paper reports per candidate, prioritizing:
radial velocity, distance, total velocity, Galactic rest-frame velocity,
escape velocity, bound/unbound probability. Field names are dotted paths
from the controlled list (the upgrade script rejects typos), e.g.
`observed_phase_space.radial_velocity`,
`derived_kinematics.total_velocity`,
`bound_assessment.unbound_probability`.

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
- Use the paper's value and unit. **Never recompute or convert** when the
  conversion needs a model or external input (no km/s ↔ mas/yr, no distance
  from a parallax prior) unless the paper itself prints the converted number.
  **Exception — standard lossless transforms** (log10 distance ↔ distance,
  distance modulus ↔ distance, plain parallax ↔ distance): you may convert,
  but record the printed form in `notes` and mind the error transform (a
  symmetric error in log space is asymmetric in linear space).
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

## 6. Method facts (L4a)

Closed questions about the paper's kinematic analysis. Answer with
`status: reported` plus the value, or `status: not_reported` after actually
checking — `not_reported` is a positive finding, not a skip. Required for
`candidates_found` papers; optional for `no_candidates` papers (recommended
when the paper performs kinematic analysis anyway).

| name | question |
|---|---|
| `potential_name` | Which Galactic potential model does the paper adopt (e.g. MWPotential2014, McMillan17)? |
| `R0` | Adopted Sun-Galactic-center distance |
| `z0` | Adopted solar height above the plane |
| `v_circ_sun` | Adopted circular velocity at the Sun |
| `solar_motion_u`/`_v`/`_w` | Adopted solar peculiar motion components |
| `escape_velocity_definition` | How is escape defined (to infinity, to a radius, potential zero-point)? |
| `other` | Any further assumption you find load-bearing (may repeat) |

The solar-motion facts are **peculiar** components (relative to the LSR);
`v_circ_sun` is the separate circular speed. When the paper reports only a
single combined solar velocity that already includes the circular term
(e.g. `(U,V,W)=(11.1, 245, 7.25)` where V=245 is circular+peculiar), set
`solar_motion_v` and `v_circ_sun` to `not_reported` and record the combined
value as an `other` fact (notes tag e.g. `combined_solar_v`). U and W are
unaffected — the LSR contributes only to V.

The named facts are scored against the AI's structured step parameters;
`other` rows are documented but not scored in v1. Two recurring `other`
facts we recommend recording when the paper states them, with a fixed tag
in `notes` so they can be grouped later:

```yaml
- name: other
  status: reported
  value: "spectrophotometric"
  notes: "distance_method"
- name: other
  status: reported
  value: "LAMOST DR8 pipeline RV"
  notes: "rv_source"
```

Typical time: about 5 minutes per paper — these usually sit in one
"Methods" paragraph or a footnote.

## 7. Step-type checklist (L4b)

Tick every analysis stage the paper actually performs. Presence only —
order, granularity, and dependencies are not scored. Vocabulary (identical
to the extraction schema):

| step type | tick when the paper... |
|---|---|
| `input_catalog` | starts from a survey/catalog (Gaia, LAMOST, SDSS...) |
| `sample_selection` | applies selection cuts to define its sample |
| `cross_match` | matches objects across catalogs |
| `quality_filter` | applies astrometric/photometric quality criteria |
| `astrometric_calibration` | corrects or re-calibrates astrometry (e.g. parallax zero-point) |
| `distance_estimation` | derives or adopts distances |
| `radial_velocity_measurement` | measures or adopts radial velocities |
| `stellar_parameter_inference` | infers Teff/logg/mass etc. |
| `photometric_or_sed_modeling` | fits photometry or SEDs |
| `velocity_calculation` | computes space velocities |
| `solar_position_and_motion` | adopts solar position/motion parameters |
| `galactic_potential_model` | adopts a Galactic potential |
| `escape_or_bound_assessment` | compares against escape speed / computes bound probability |
| `orbit_integration` | integrates orbits (backward or forward) |
| `origin_assessment` | localizes ejection/origin site (Galactic center, disk, LMC...) |
| `candidate_classification` | classifies objects into candidate classes |
| `follow_up_validation` | uses new follow-up observations to validate |
| `reported_value_adoption` | adopts key values directly from cited literature |
| `other` | does a load-bearing stage not listed above (explain in `notes`) |

## 8. Mechanics

1. Copy `benchmark/templates/gold_annotation_template.yaml` to
   `benchmark/gold/<arxiv_id>/annotation_<you>.yaml`
   (the filled example `gold_annotation_example.yaml` shows every feature).
2. Read the PDF and fill the template.
3. Run
   `python scripts/upgrade_gold_annotation.py benchmark/gold/<arxiv_id>/annotation_<you>.yaml`
   — it validates all controlled vocabularies, points at the offending
   line, cross-checks the paper's manifest role, and writes the gold JSON
   next to your YAML.
4. Commit both files. Never hand-edit the generated JSON; fix the YAML and
   re-run.

Budget guidance (calibrate in Phase 3): no-candidate papers ~15-30 min;
candidate papers ~45-90 min depending on table size. If a paper takes far
longer, stop and flag it in `notes` — that is a finding about annotation
cost, not a failure.
