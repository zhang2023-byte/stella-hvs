# Expert Annotation Guideline

Status: protocol v2 (2026-07-12) — expert-led annotation with an optional
PDF-only scribe. Gold files live in the external private gold repository
(`STELLA_GOLD_DIR`). Calibration-era annotations made under the earlier
pure-manual revision remain valid. This public workspace also contains source
and AI artifacts; the permitted evidence surface for gold is only the paper
PDF and this guideline.

Record the git short hash of this file in every annotation's
`guideline_version` field (quoted — all-digit hashes parse as numbers).

## 1. What we measure, and the one rule that governs everything

Gold captures three layers for comparing AI extraction with manual extraction:

- **L1 — candidate set**: which objects the paper treats as HVS candidates
  (precision/recall after identity matching; false positives count on
  no-candidate papers).
- **L2 — values**: normalized quantity values, units, and limit semantics.
- **L3 — evidence**: whether extracted values point at genuine support in
  the paper (retained for a separately frozen rubric; the current campaign
  formally scores L1/L2 only).

**The governing rule: annotate what the paper claims, not what is
astrophysically true.** If the paper says a star is unbound and you
disagree scientifically, record the paper's claim and put your disagreement
in `notes`. The paper PDF is the only evidence input for gold — for the
expert and for any scribe alike.

## 2. What counts as a candidate (L1)

### Terminology and Stella's scope

The language used for fast-moving stars has never been entirely consistent.
*High-velocity star* is a broad description, and the categories gathered under
it overlap. Brown (2015), for example, discusses hypervelocity stars (HVSs) as
unbound stars whose extreme velocities point to ejection through interaction
with a massive black hole. Other authors use *HVS* for any unbound star,
regardless of where it came from, while *bound HVS* is sometimes used for a
possible massive-black-hole ejectee that has not escaped the Galaxy.

The terminology around runaways is similarly variable. *Runaway star*
traditionally refers especially to a young O- or B-type star ejected from its
birth cluster, association, or the Galactic disc, but papers do not always use
the same velocity threshold. A star ejected from the disc or a cluster at close
to, or above, the Galactic escape speed may instead be called a
*hyper-runaway*. More general labels such as *high-velocity* and
*extreme-velocity star* are often based on thresholds chosen for a particular
study. The name alone therefore tells us neither whether a star is unbound nor
why the authors think it is moving so quickly.

For Stella, the useful common ground is not the label or the proposed ejection
mechanism, but Galactic boundness:

> **A candidate is an object that the paper's final treatment leaves possibly
> gravitationally unbound from the Milky Way.**

This definition is deliberately broader than the classical, origin-based use
of HVS. Objects that can be shown both to be unbound and to come from a massive
black hole are exceptionally rare; S5-HVS1 remains the only HVS confidently
associated with the Galactic Centre. Our scope is closer to the operational
focus of the Open Fast Stars Catalogue (Boubert et al. 2018), which brings
together candidates from the literature and examines their Galactic boundness,
even though it describes them as hypervelocity stars.

Boundness is itself model-dependent. A different Galactic potential, distance
prior, or kinematic measurement can change the answer. Stella does not resolve
those differences or decide whether a star is truly unbound. It records what
the paper concludes. This includes objects introduced as possibly unbound in
the paper, as well as previously known objects whose boundness the paper
genuinely re-assesses using new observations, revised distances or kinematics,
or a fresh bound/unbound analysis.

For context, see [Brown
(2015)](https://doi.org/10.1146/annurev-astro-082214-122230), [Boubert et al.
(2018)](https://doi.org/10.1093/mnras/sty1601), and [Koposov et al.
(2020)](https://doi.org/10.1093/mnras/stz3081).

### How to decide

Work through these questions for each object discussed in the paper:

1. **Does this paper itself treat the object as possibly unbound from the
   Milky Way?** If not, do not include it. Calling an object an HVS, runaway,
   or high-velocity star is not enough on its own.

2. **Does the paper's final treatment still leave the object possibly
   unbound?** If the final verdict is bound, do not include it. When a paper
   re-assesses a historical sample and concludes that most of its objects are
   bound, include only those it still singles out as possibly unbound. An
   object does not qualify merely because it appears in a table of previous
   candidates or has a tabulated bound/unbound probability.

3. **Did this paper introduce the candidate, or re-assess one from the
   literature?** Use `origin_type: introduced_by_this_paper` when the candidate
   is introduced here. Use `origin_type: cited_from_literature` when the paper
   materially re-assesses a known object with new observations, a new distance,
   revised kinematics, or a fresh bound/unbound verdict. Merely repeating an
   earlier label, confirming a radial velocity, or adding chemistry without
   re-evaluating Galactic boundness is cite-in-passing, not a re-assessment.

Never make a bound/unbound decision the paper does not make.

**No-candidate papers**: set `status: no_candidates`, leave `candidates`
empty, and note in `notes` which object groups you considered and why they
fall outside the definition (e.g. "Table 1 runaways: bound, paper never
questions Galactic boundness").

**Candidate tables must be complete**: L1 includes every object the paper
treats as a candidate, each with at least one paper-visible identifier or
Gaia source id and candidate-level evidence; record full L2 quantities for
every candidate (no row cap). If a table is too large to transcribe, stop
and flag it in `notes` for adjudication — never silently truncate.

## 3. Identity fields (L1)

Per candidate, at least one of these must be filled — do not invent a local
id just to fill the form:

- `paper_candidate_id`: the paper's main display id (table row label or
  name used in text, e.g. `S5-HVS1`, `HVS 7`, `J1234+5678`). Leave empty
  when the only visible identifier is a Gaia source id.
- `gaia_source_id`: strict form `Gaia DR2 123...` / `Gaia EDR3 123...` /
  `Gaia DR3 123...`, data release exactly as the paper states. Paper-visible
  only — never look it up in external databases.
- `aliases`: other paper-visible identifiers, excluding anything already in
  `paper_candidate_id` or `gaia_source_id`.

Coordinates, proper motions, velocities, distances, and probabilities are
physical quantities — they go in `quantities[]` (Section 4), never at
candidate top level. Fill coordinate/proper-motion fields when the paper
gives no usable name or Gaia id, or when the value is directly relevant to
the HVS claim; if coordinates are the only usable identity evidence, note
that for adjudication.

## 4. Quantities (L2) and evidence (L3)

Record **every** scored field the paper reports per candidate. Gold is
exhaustive over the vocabulary below; the scorer treats an absent gold
field as an assertion that the paper does not report it (an AI value there
scores as a presumed hallucination). Give verification priority to the four
key fields — radial velocity, distance, Galactic rest-frame velocity,
bound/unbound probability — but priority governs checking effort, never
permission to skip the rest. `field` names are dotted paths from the
controlled list; the upgrade script rejects typos.

### Quantity vocabulary (use only these)

Observed phase-space:

- `observed_phase_space.ra`
- `observed_phase_space.dec`
- `observed_phase_space.distance`
- `observed_phase_space.parallax`
- `observed_phase_space.proper_motion_ra`
- `observed_phase_space.proper_motion_dec`
- `observed_phase_space.radial_velocity`

Derived kinematics:

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

Bound assessment — exactly two probability slots:

- `bound_assessment.bound_probability`
- `bound_assessment.unbound_probability`

Record whichever probability the paper reports. **Escape probability is an
unbound probability** (escape ≡ unbound): record P_esc under
`unbound_probability`. Do not record escape velocity, escape-velocity
ratios, escape margins, ΔE, or ad-hoc bound-status metrics — rarely
comparable across papers, outside the scored vocabulary. Do not fill
photometry, spectroscopy, abundances, stellar parameters, quality flags, or
survey-specific columns.

### Mapping and choosing values

- A speed used for Galactic boundness that the paper gives as V_GSR, V_3D,
  v_rf, or a velocity in the Galactic/Galactocentric rest frame →
  `derived_kinematics.galactic_rest_frame_velocity` (the reference frame
  may sit in the header, caption, or text). A generic `total_velocity` in a
  non-Galactic frame is outside the HVS-boundness target — do not record it.
- When the paper gives several estimates for one quantity (with/without a
  Galactic-Centre-origin assumption, different distance models, ejection vs
  current velocity), record the one with the **fewest extra model
  assumptions**; put the rest in `notes`.

### Value rules — copy, never convert

Use the paper's value and unit **exactly as printed, never recompute or
convert** — not even pc↔kpc, log10 distance, distance modulus,
parallax↔distance, or km/s↔mas/yr. The AI side also preserves the printed
text, so converting on the gold side only misaligns the two.

- `value` is a single plain number as printed (`742`, `-12.3`, `1.3e5`): no
  units, operators, ranges, or footnote markers. The only exception is
  `ra`/`dec`, where sexagesimal strings (`12:34:02.88`, `+56:46:51.6`) may
  be copied verbatim with `unit: hms`/`dms`; never convert sexagesimal by
  hand. `unit` is free text — put the paper's form there (e.g.
  `log(D/kpc)` with value `0.936`; a distance modulus with `unit: mag`).
- Uncertainty: symmetric → `error`; asymmetric `743^{+15}_{-12}` →
  `lower_error: 12`, `upper_error: 15`.
- One-sided limit `v > 500` → `limit_kind: lower_limit` (or `upper_limit`),
  bound in `value`.
- Closed range `500-700` → `limit_kind: range`, `value` empty, bounds in
  `range_lower`/`range_upper`.
- Probabilities: normalize to a 0-1 fraction with empty unit
  (`99.995%` → `0.99995`). Origin-comparison metrics (p_MW vs p_LMC,
  likelihood ratios) are not bound probabilities — skip or remark in
  `notes`.

If a value is genuinely absent, leave the field out — absence is itself
information ("paper does not report" vs "annotator missed" is exactly what
the benchmark separates).

### Evidence

Every quantity and every candidate needs at least one PDF locator precise
enough to find in ~30 seconds, e.g. `"Table 2, row J1234+5678, col v_GC"` or
`"Sec 4.1, second paragraph"`. A short verbatim `quote` is encouraged for text claims;
for uncertainty forms, quote the printed form (`"743^{+15}_{-12}"`).

## 5. What is not scored

Do not fill structured method facts, a step-type checklist, solar
parameters, potential names, or method stages in gold. The AI side still
emits a schema-validated `method_chain[]` (with `parameters[]` and
field-level `method_refs`), but those are unscored diagnostics — they do
not enter scoring. Put a method detail in free-text `notes` only when it is
needed to explain a scored L1-L3 judgment (e.g. "distance uses the
no-Galactic-center-origin case", "bound probability assumes the McMillan
potential").

## 6. Workflow

Set `STELLA_GOLD_DIR` (in `.env` or the shell) to the gold repository's
`gold/` directory; the tools refuse to run without it. Open
`literature/<arxiv_id>/arxiv.pdf`, read the paper, and settle every
judgment in Sections 2–4 before any agent is involved.

### Scribe contract (when you use a scribe agent)

A scribe agent may transcribe the values and locators you have already
decided. To brief it, point it at this section and dictate your candidate
list and the values/locators to transcribe. It works under five hard rules:

1. **PDF-only evidence.** It reads only `literature/<arxiv_id>/arxiv.pdf`
   for its assigned paper, this guideline, `benchmark/templates/`, and this
   paper's own directory under `$STELLA_GOLD_DIR/<arxiv_id>/`. Nothing else
   in that paper's folder — the TeX, ECSV, and
   `literature_hvs_candidates.json` sit next to the PDF and are the easiest
   contamination mistake. It never opens any other paper's gold, and never
   AI artifacts (extracted JSON, TeX, ECSV, campaign `runs/`, campaign
   `scoring/`, or report pages).
2. **One direction, one write surface.** It runs in this public workspace
   and writes outward to the private gold repository only:
   `$STELLA_GOLD_DIR/<arxiv_id>/draft_<you>.json` (form path) or
   `annotation_<you>.yaml` (CLI fallback). No gold content may be copied
   into or committed to workspace files.
3. **No judgment.** It transcribes what you identified. If a choice is open
   (which estimate, field mapping, limit/range semantics, candidate in/out),
   it stops and asks. It never adds, removes, or reinterprets candidates.
4. **No final save.** It never runs `scripts/upgrade_gold_annotation.py`
   and never produces the final JSON twin; validation and final save are
   your acts.
5. **Single use.** One scribe session per paper, retired once the draft is
   delivered. A session that has read AI extraction output for a paper must
   never scribe that paper.

The form-path draft is an unvalidated checkpoint with this envelope; its
`payload` mirrors the annotation template and may be incomplete:

```json
{
  "schema": {
    "name": "benchmark.gold_form_draft",
    "version": 1
  },
  "saved_at": "<UTC ISO timestamp>",
  "payload": { "...": "same fields as the annotation YAML" }
}
```

Record the scribe in the optional `annotation_process` block (protocol
`expert_led_scribe.v1`, scribe agent runtime, model). Fully hand-filled
annotations are valid: omit the block or use `manual_pdf_only.v1`.

If the PDF and the LaTeX/ECSV pipeline view disagree, record the
discrepancy in `notes` as a finding (it measures our ingestion layer)
instead of silently following either side.

### Saving the annotation

**Form path** (recommended): run
`scripts/serve_gold_annotation.py --arxiv-id <id> --annotator <you>`, load
the scribe draft (or fill from scratch), verify every value against the
PDF, then **Validate** and **Save**. **Save Draft** writes the unvalidated
checkpoint above; final **Save** writes
`$STELLA_GOLD_DIR/<arxiv_id>/annotation_<you>.yaml` and generates the JSON
twin (with its leak-audit canary) from the same validated payload.

**CLI fallback**: copy `benchmark/templates/gold_annotation_template.yaml`
to `$STELLA_GOLD_DIR/<arxiv_id>/annotation_<you>.yaml`, fill it (the filled
`gold_annotation_example.yaml` shows every feature), and run
`python scripts/upgrade_gold_annotation.py $STELLA_GOLD_DIR/<arxiv_id>/annotation_<you>.yaml`
— it validates all controlled vocabularies, points at the offending line,
cross-checks the paper is sampled in the manifest, and writes the gold JSON
next to your YAML.

Then commit the YAML/JSON in the private gold repository and refresh the
integrity manifest here:
`conda run -n stella-env python scripts/update_gold_manifest.py`.
Never hand-edit the generated JSON; fix the YAML and re-validate.

**Budget**: no-candidate papers ~15-30 min; candidate papers ~45-90 min
depending on table size. If a paper takes far longer, stop and flag it in
`notes` — that is a finding about annotation cost, not a failure.
