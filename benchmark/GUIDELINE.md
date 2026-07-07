# Expert Annotation Guideline

Status: protocol v2 (2026-07-05) — expert-led annotation with a PDF-only
scribe; gold files live in the external private gold repository
(`STELLA_GOLD_DIR`). Calibration-era annotations were made under the earlier
pure-manual revision of this document.
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

## 2. Expert-led annotation with a PDF-only scribe

Every sampled paper in `benchmark/manifest/sampling_manifest.json` is annotated
from the paper PDF (`literature/<arxiv_id>/arxiv.pdf`) like a referee. The PDF
is the only evidence input for gold — for the expert and for the scribe alike.

The protocol (`expert_led_scribe.v1`) has three steps:

1. **Expert judgment first.** Read the PDF independently and settle every
   scientific question before any agent is involved: whether the paper has
   candidates under Section 3, which objects they are, why they qualify, and
   where the supporting data lives (which tables, which sections).
2. **Scribe transcription.** A scribe agent may then fill the annotation
   draft, transcribing the values and evidence locators the expert
   identified. The scribe reads only the same PDF. It must not open extracted
   JSON, TeX sources, ECSV files, archived AI runs, or any other pipeline
   artifact, and it must not add, remove, or reinterpret candidates on its
   own.
3. **Expert verification.** Check every transcribed value, unit, and evidence
   locator against the PDF before saving. Judgment-type choices — which of
   several estimates to record (Section 5), quantity-field mapping,
   limit/range semantics, probability normalization — are made or confirmed
   by the expert, never left to the scribe.

Record the scribe in the optional `annotation_process` block (protocol,
scribe agent runtime, model). Fully hand-filled annotations remain valid:
omit the block or use protocol `manual_pdf_only.v1`.

Never open extracted JSON, TeX sources, ECSV files, archived AI runs, or any
other pipeline artifact while annotating gold. If the PDF and the LaTeX/ECSV
pipeline view disagree, record the discrepancy in `notes` as a finding (it
measures our ingestion layer) instead of silently following either side.

### Scribe session boundaries

The gold repository and this toolchain workspace are deliberately separate;
the scribe bridges them in **one direction only**. Route scribe requests
through the optional scribe stage of `benchmark_gold_annotation_form` in
`workflows/stella_workflows.yaml`. The rules:

- **Where it runs.** The scribe is a fresh coding-agent session opened in
  this public workspace (the PDF lives here) with `STELLA_GOLD_DIR` set.
  Writing the draft outward into the private gold repository is the
  sanctioned direction. The "gold never enters this workspace" rule governs
  the reverse: no gold content may be copied into, or committed to,
  workspace files.
- **Read surface.** `literature/<arxiv_id>/arxiv.pdf` for its single
  assigned paper, this guideline, and `benchmark/templates/`. Nothing else
  under that paper's `literature/<arxiv_id>/` — the TeX, ECSV, and
  `literature_hvs_candidates.json` sit right next to the PDF and are the
  easiest contamination mistake. Inside the gold repository it may read only
  its own paper's directory (`$STELLA_GOLD_DIR/<arxiv_id>/`): the existing
  draft, and the existing annotation when the expert is amending previously
  saved gold. It must not list or read any other paper's gold files, and
  never AI pipeline artifacts (extracted JSON, TeX, ECSV, archived runs
  under `benchmark/runs/`, scorecards under `benchmark/scoring/`, report
  pages).
- **Write surface.** Only `$STELLA_GOLD_DIR/<arxiv_id>/draft_<you>.json`
  (form path) or the working `annotation_<you>.yaml` (CLI fallback path).
  The scribe never runs `scripts/upgrade_gold_annotation.py` and never
  produces the final JSON twin; validation and final save are the expert's
  acts.
- **No judgment, no guessing.** The scribe transcribes what the expert
  identified. If the instructions leave a judgment open (which estimate,
  field mapping, limit semantics, candidate in/out), it stops and asks the
  expert instead of deciding.
- **Single use.** One scribe session per paper, retired after the
  transcription is delivered. Its context necessarily carries gold content,
  so it must never be reused for extraction runs, scoring, report building,
  or toolchain development. Conversely, a session that has read AI
  extraction output for a paper must never scribe that paper.

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

A re-assessment that ends in a bound verdict does not create a candidate
either: the "do include re-assessed candidates" rule applies only when the
paper's own final treatment still leaves the object possibly unbound.
For reassessment papers that conclude most historical candidates are bound,
annotate only the objects the paper itself still singles out as possibly
unbound. Appearing in a table of previously claimed candidates, or having a
tabulated bound/unbound probability, is not sufficient by itself
(clarified 2026-07-06 after the first dev scoring round; this codifies how
the calibration annotations were judged).

For papers with **no** candidates under this definition, set
`status: no_candidates`, leave `candidates` empty, and briefly note in
`notes` which object groups you considered and why they fall outside the
definition (e.g. "Table 1 runaways: bound, paper never questions Galactic
boundness").

**Large candidate tables**: the candidate list (L1) must be complete — every
object the paper treats as a candidate gets an entry with at least
one paper-visible identifier or Gaia source id, and candidate-level evidence.
Record full quantities (L2) for every candidate; the scribe protocol makes
transcription cheap, so there is no row cap. (An earlier revision capped full
L2 at the first 15 table rows; no formal annotation ever triggered that rule,
so scoring has no truncation handling.) If a table is so large that even
scribed transcription is impractical, stop and flag the paper in `notes` for
adjudication instead of silently truncating.

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

Record **every** scored field the paper reports per candidate — gold is
exhaustive over the quantity vocabulary below, and the scorer treats an
absent gold field as an assertion that the paper does not report it (an AI
value there is scored as a presumed hallucination). Give verification
priority to the four key fields: radial velocity, distance, Galactic
rest-frame velocity, bound/unbound probability — but
"priority" governs the expert's checking effort, never permission to skip
recording the rest. Field names are dotted paths
from the controlled list (the upgrade script rejects typos), e.g.
`observed_phase_space.radial_velocity`,
`derived_kinematics.galactic_rest_frame_velocity`,
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
- `derived_kinematics.galactic_rest_frame_velocity`

The third group is bound/unbound assessment — exactly two probability
slots (schema v0.2):

- `bound_assessment.bound_probability`
- `bound_assessment.unbound_probability`

Record whichever probability the paper actually reports. A paper's
**escape probability counts as an unbound probability** (escape ≡ unbound):
record P_esc under `bound_assessment.unbound_probability`. Other boundness
statistics — escape velocity, escape-velocity ratios, escape margins, ΔE,
ad-hoc bound-status metrics — are **not** recorded in gold: they are rarely
comparable across papers and are outside the scored vocabulary.

Do not fill photometry, spectroscopy, abundances, stellar parameters, quality
flags, or survey-specific columns in expert gold. Those may be useful catalog
enrichments elsewhere, but they are not part of this benchmark's HVS-candidate
accuracy target.

Coordinate fields follow the same "copy, do not convert" rule as other
quantities. Fill `observed_phase_space.ra` or `observed_phase_space.dec` when
the paper prints a coordinate component you can copy directly: decimal degrees
or sexagesimal forms such as `12:34:02.88` / `+56:46:51.6`. Do not convert
sexagesimal coordinates by hand; keep the printed value in `value` and use the
paper's unit/header form in `unit` when available (for example `deg`, `hms`, or
`dms`). If coordinates are the only usable identity evidence, also mention that
in `notes` for adjudication.

Field disambiguation and multiple estimates:

- A speed used for Galactic boundness that the paper gives as V_GSR, V_3D,
  v_rf, or a velocity in the Galactic/Galactocentric rest frame →
  `derived_kinematics.galactic_rest_frame_velocity`. The relevant reference
  frame may be in the table header, caption, or surrounding text. Do not
  record a generic `total_velocity` in expert gold; a total speed stated in a
  non-Galactic frame is outside this benchmark's HVS-boundness target.
- When the paper gives several values for the same quantity of one star
  (with vs without a Galactic-Centre-origin assumption, different distance
  models, ejection vs current velocity), record the one carrying the
  **fewest extra model assumptions** and put the rest in `notes`.

Value rules (mirror the extraction schema semantics):

- `value` is a single plain number as printed, e.g. `742`, `-12.3`,
  `1.3e5`. No units, operators, ranges, or footnote markers inside it. The
  only exception is `observed_phase_space.ra` / `observed_phase_space.dec`,
  where sexagesimal coordinate strings may be copied verbatim.
- Use the paper's value and unit **exactly as printed — never recompute or
  convert**, even for "easy" transforms (pc↔kpc scale shifts, log10 distance,
  distance modulus, parallax↔distance, km/s↔mas/yr). A distance printed as
  `334.7 +/- 185.5 pc` stays in pc — do not restate it in kpc "for
  consistency" with other papers. The AI side also preserves the printed
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

Gold annotations live in the external private gold repository, outside this
workspace. Set `STELLA_GOLD_DIR` (in `.env` or the shell) to that repository's
`gold/` directory before starting; the tools below refuse to run without it.

Recommended path:

1. Open the PDF in your editor or PDF viewer:
   `literature/<arxiv_id>/arxiv.pdf`.
2. Read the paper and settle the expert judgments of Section 2 step 1.
3. (Optional scribe step) Open a **fresh** coding-agent session in this
   workspace and ask it to run the scribe stage of
   `benchmark_gold_annotation_form` for the paper, telling it which objects
   are candidates and where the supporting data lives (tables, sections). The
   scribe obeys the session boundaries of Section 2 and writes the draft checkpoint
   `$STELLA_GOLD_DIR/<arxiv_id>/draft_<you>.json` in the form's envelope:

   ```json
   {
     "draft_schema": "stella.benchmark_gold_form_draft.v0.1",
     "saved_at": "<UTC ISO timestamp>",
     "payload": { ...same structure as the annotation YAML... }
   }
   ```

   The `payload` mapping mirrors `benchmark/templates/gold_annotation_template.yaml`
   field-for-field (top-level metadata, `candidates[]`, `quantities[]`,
   `evidence[]`); drafts are unvalidated checkpoints, so partially filled
   payloads are fine. Retire the scribe session once the draft is delivered.

   A ready-to-paste scribe briefing (fill the angle brackets):

   > Run the optional scribe stage of `benchmark_gold_annotation_form`
   > (`workflows/stella_workflows.yaml`) for paper `<arxiv_id>`, annotator
   > `<annotator>`. You are a PDF-only scribe under
   > `benchmark/GUIDELINE.md` §2: read ONLY
   > `literature/<arxiv_id>/arxiv.pdf`, the guideline,
   > `benchmark/templates/`, and this paper's own files under
   > `$STELLA_GOLD_DIR/<arxiv_id>/`. Do not open TeX, ECSV, extracted JSON,
   > archived runs, scoring outputs, or any other paper's files. I have
   > already decided the candidate list and which printed values to record;
   > transcribe exactly what I dictate — verbatim printed values and units,
   > no conversion, no recomputation, no adding, removing, or
   > reinterpreting candidates. If a value I point at is ambiguous in the
   > PDF, stop and ask instead of guessing. Write only
   > `$STELLA_GOLD_DIR/<arxiv_id>/draft_<annotator>.json` in the
   > `stella.benchmark_gold_form_draft.v0.1` envelope. My decisions:
   > `<candidates, tables and rows to transcribe, chosen estimates,
   > no-candidate groups for notes>`.

4. Start the local annotation form:

   ```bash
   conda run -n stella-env python scripts/serve_gold_annotation.py \
     --arxiv-id <arxiv_id> \
     --annotator <you>
   ```

5. Load the draft (or fill from scratch) and verify every value against the
   PDF. **Save Draft** keeps interruption-safe checkpoints without schema
   validation.
6. Use **Validate** before final save. **Save** writes
   `$STELLA_GOLD_DIR/<arxiv_id>/annotation_<you>.yaml` and generates the JSON
   twin (with its leak-audit canary) from the same validated payload.
7. Commit the final YAML/JSON files in the private gold repository, then
   refresh the integrity manifest in this workspace:
   `conda run -n stella-env python scripts/update_gold_manifest.py`.
   Never hand-edit the generated JSON; fix the YAML in the form or by hand
   and re-run validation.

CLI fallback:

1. Copy `benchmark/templates/gold_annotation_template.yaml` to
   `$STELLA_GOLD_DIR/<arxiv_id>/annotation_<you>.yaml`
   (the filled example `gold_annotation_example.yaml` shows every feature).
2. Read the PDF and fill the YAML (scribe transcription optional, as above).
3. Run
   `python scripts/upgrade_gold_annotation.py $STELLA_GOLD_DIR/<arxiv_id>/annotation_<you>.yaml`
   - it validates all controlled vocabularies, points at the offending
   line, cross-checks that the paper is sampled in the manifest, and writes
   the gold JSON next to your YAML.

Budget guidance (calibrate in Phase 3): no-candidate papers ~15-30 min;
candidate papers ~45-90 min depending on table size. If a paper takes far
longer, stop and flag it in `notes` — that is a finding about annotation
cost, not a failure.
