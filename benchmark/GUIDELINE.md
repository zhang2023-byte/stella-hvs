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

Gold captures two scored layers for comparing AI extraction with manual extraction:

- **L1 — candidate set**: which objects the paper treats as HVS candidates
  (precision/recall after identity matching; false positives count on
  no-candidate papers).
- **L2 — values**: normalized quantity values, units, and limit semantics.

Every identity and value also carries supporting PDF evidence. Evidence is a
non-scored legality and audit requirement; unsupported values cannot enter L2.

### Shared normative extraction contract

The following block is generated from
`skills/hvs-candidates-extraction/rules/*.yaml`. It is the shared scientific,
identity, and value-selection contract for expert annotation and AI extraction.
Do not edit the generated block by hand; update the YAML source and run
`scripts/generate_extraction_rule_views.py`.

<!-- BEGIN GENERATED RULE PROFILE: coding_agent_baseline -->

### `paper.claims.reported_not_truth` — Follow the paper's claims

Base every scientific claim only on the supplied paper sources. Report the paper's claims rather than your own view of astrophysical truth, and do not strengthen, weaken, or replace its conclusions.

### `hvs.roster.final_treatment` — Apply the final Galactic-boundness treatment

Include an object only when the paper's final treatment retains at least one scientifically admissible analyzed scenario in which the object is unbound, likely unbound, possibly unbound, or escaping the Milky Way. A preferred bound scenario does not erase another retained unbound scenario, and "unconfirmed" wording does not exclude an object while possible unboundness remains. Treat an unbound scenario as rejected only when the paper withdraws it, declares it scientifically inadmissible, or concludes that it no longer supports possible Galactic unboundness.

### `hvs.roster.textual_anchor` — Require a textual decision anchor

Do not infer roster membership from an HVS, runaway, high-velocity, candidate, or survey label; a bare table row; a velocity threshold; or a tabulated probability alone. Require substantive manuscript text that anchors the object to the paper's final Galactic-boundness treatment. A group-level statement may anchor all individually identified members only when it explicitly defines the named group or table as the complete result of that treatment; a names-only list is insufficient.

### `hvs.roster.prior_reassessment` — Require material reassessment of prior candidates

A candidate reported in earlier literature qualifies only when this paper uses new information that it treats as decision-relevant to explicitly reassess Galactic boundness, and the result still leaves the object possibly unbound. New measurements or recomputations are not a material reassessment when the paper does not use them to test or update boundness, or states that they cannot change the classification. Exclude the object when the paper's final reassessment concludes that it is bound or likely bound.

### `hvs.roster.galaxy_bound_exclusions` — Exclude Galaxy-bound fast-star categories

Exclude ordinary runaways, cluster escapers, locally unbound Galactic-centre stars that remain bound to the Galaxy, high-velocity halo stars without a Galactic-unbound conclusion, and every object treated as bound or likely bound across all retained scenarios. An ejection mechanism or origin claim never substitutes for Galactic unboundness.

### `hvs.roster.complete_identifiable_set` — Return the complete identifiable set

Return every qualifying object that is individually identifiable in the supplied manuscript; do not sample, cap, or choose representative objects. Exhaust every accessible table whose members are covered by a valid group-level decision anchor. When qualifying members are individually identifiable only through a compressed range notation in the manuscript, submit the range string verbatim as a range group; the program expands it mechanically, so never expand a range into names yourself and never invent identities. If the manuscript states that additional qualifying objects exist only in unavailable external material, return the identifiable subset, record the unidentifiable remainder as a reviewed group with manuscript evidence, and never invent identities.

### `hvs.roster.paper_visible_identity` — Preserve paper-visible identity

Create one candidate record per scientific object and order candidate records by first appearance in the manuscript. Copy every manuscript-visible name or source identifier for that object verbatim and order identifiers by first appearance. Group aliases only when the manuscript supports that they identify the same object; do not invent, normalize, externally resolve, merge uncertain identities, or split one object across records. Do not expand compressed range notations into individual names yourself; submit them as range groups and let the program expand them.

### `hvs.roster.decision_evidence` — Support every roster decision with manuscript evidence

For each included candidate, give a one-to-three-sentence qualification stating the paper's qualifying final treatment and cite the substantive manuscript lines that support it. Cite every submitted identifier with lines containing that identifier verbatim. For each range group, cite the manuscript lines that contain the range notation verbatim. Use the smallest continuous line ranges that preserve the evidence and separate discontinuous passages into separate references. Blank lines, comments, isolated TeX structure, and bibliography entries are not decision evidence.

### `hvs.roster.reviewed_exclusions` — Record only meaningful near misses

Record only objects or paper-defined groups that could reasonably be mistaken for qualifying candidates. Qualifying groups submitted as range groups are not reviewed exclusions. Give each one a concise exclusion reason and substantive manuscript evidence; do not inventory ordinary background objects, controls, or unrelated table rows. When qualifying candidates exist, retain important near misses and objects explicitly rejected as bound. When no candidate qualifies, record every candidate-like object or group reviewed; leave both candidates and reviewed exclusions empty only when the manuscript contains no candidate-like object or group.

### `hvs.field.fixed_candidate` — Keep the assigned candidate fixed

The assigned candidate's roster membership, paper-visible identifiers, and qualification are fixed. Extract fields only for that candidate. Do not add, remove, rename, merge, split, or reassess any candidate, and do not report values belonging to another object.

### `hvs.field.reported_values_only` — Extract reported values without recomputation

Populate a core field only with a value explicitly reported for the assigned candidate in the supplied paper sources; otherwise return null. Copy numeric content, sign, precision, and unit without calculation, inference, rounding, or unit conversion. Remove only presentation markup needed to form a machine-readable numeric string, preserve the printed representation through direct evidence, and never derive one field from another except for the percent normalization defined by hvs.field.bound_probability.

### `hvs.field.multiple_estimates` — Prefer the estimate with the fewest added assumptions

When several reported estimates could fill the same field, choose an applicable estimate that requires the fewest additional model assumptions. If equally assumption-light estimates remain, use the paper's explicit final or fiducial choice; if the paper gives no such preference, use the first reported estimate. Never average or combine estimates, and do not output alternatives.

### `hvs.field.uncertainty_limits` — Preserve uncertainty and limit semantics

Represent a symmetric uncertainty with error and an asymmetric uncertainty with lower_error and upper_error; never mix the two forms. Represent a one-sided bound with value and the corresponding limit kind, and represent a closed range with range_lower and range_upper without inventing a central value. Never reinterpret uncertainty bounds around a central measurement as a reported range. Leave every non-applicable component null.

### `hvs.field.coordinates` — Preserve the printed coordinate representation

For RA or Dec, copy only the assigned coordinate component and preserve its printed decimal or sexagesimal representation. Declare the corresponding coordinate format and do not convert between decimal and sexagesimal forms or copy a coordinate pair into one value. Decimal coordinates use degrees; sexagesimal RA uses hour angle, and sexagesimal Dec uses degrees.

### `hvs.field.galactic_rest_frame_velocity` — Map only Galactic-rest-frame boundness speeds

Populate galactic_rest_frame_velocity only with a speed that the paper defines in the Galactic or Galactocentric rest frame and uses in its Galactic-boundness analysis. Labels such as V_GSR, V_3D, or v_rf support this mapping only when the paper's definition establishes the required frame and role. Do not substitute radial velocity, a heliocentric or otherwise generic total speed, a velocity component, escape velocity, or an escape margin.

### `hvs.field.bound_probability` — Map only true bound or unbound probabilities

Populate bound_probability or unbound_probability only with the corresponding probability explicitly reported by the paper. An explicit statement in manuscript prose, a table caption, or a table note that assigns one probability or limit condition to a complete table or named object group applies to every individually identifiable member of that stated group; multiple members may cite the same group-level direct evidence. A bare table without such a statement does not support propagation. Treat escape probability as unbound probability. Normalize a reported percent to a unitless fraction from zero to one while preserving the printed percent through direct evidence. Do not derive the complementary probability, guess a probability from an ordinary numeric threshold, extend a condition beyond its explicitly named group, or substitute escape velocity, velocity ratios, energy differences, origin probabilities, or other metrics.

### `hvs.field.candidate_origin` — Classify candidate origin from manuscript evidence

Use introduced_by_this_paper when this paper first presents the object as an HVS candidate or as possibly Galactic-unbound, even if the object itself was previously catalogued. Use cited_from_literature only when the manuscript treats the object as a prior HVS or Galactic-unbound candidate and materially reassesses its Galactic boundness; a citation used only for identity or unrelated data is insufficient. For cited_from_literature, return the exact citation key used in the relevant TeX passage and cite substantive manuscript evidence; for introduced_by_this_paper, return a null citation key and cite substantive manuscript evidence. Do not infer or reproduce bibliography metadata.

### `hvs.field.source_authority` — Use TeX for meaning and ECSV for addressing

Use the author TeX for scientific meaning, captions, headers, notes, definitions, selection conditions, methods, and analyzed scenarios. Use supplied ECSV only as a converted representation for exact row-and-column addressing. The TeX-ECSV mapping establishes source lineage but carries no scientific interpretation. Interpret ECSV through its mapped TeX source and never use ECSV to override the author TeX.

### `hvs.field.ecsv_evidence` — Submit ECSV locations rather than copied cells

For an ordinary ECSV cell, submit only its exact file path, physical data-line number, and machine column name; do not copy the column header or raw cell value, which are resolved mechanically. When one cell contains multiple scientific values and only one component supports the field, additionally submit the smallest exact non-empty substring that preserves that component's printed representation. Never rewrite, normalize, or invent the submitted substring.

### `hvs.field.tex_evidence` — Submit exact TeX locations and direct raw fragments

For TeX evidence, submit the exact file path and the smallest inclusive physical line range that preserves the evidence. When TeX is the direct source of a numeric component, also submit the smallest exact non-empty substring that preserves that component's printed representation. For explanatory evidence, submit no copied quotation. Use separate references for discontinuous passages, and do not cite comments, blank lines, or isolated TeX structure.

### `hvs.field.component_evidence` — Map every numeric component to one direct source

Every non-null numeric component must have exactly one direct_evidence item whose part label names that component; a null component has no direct-evidence item. Use context_evidence only for TeX passages that establish meaning, unit, frame, scenario, or selection conditions; context evidence never replaces direct evidence. The same source may support multiple components only through separate part-labelled direct-evidence items.

### `hvs.field.source_relevance` — Verify scientific source attribution

Choose evidence that actually belongs to the assigned candidate and supports the exact field or numeric component being submitted. A structurally valid locator or literal identifier match is not sufficient. Interpret aliases, continuation rows, shared measurements, captions, headers, and notes from the supplied source context, and never cite another object's value.

### `hvs.field.provenance_conflicts` — Prefer author TeX in material conversion conflicts

When mapped ECSV materially conflicts with author TeX in value, sign, uncertainty, limit, unit, row association, or quantity interpretation, treat the TeX as authoritative. If the TeX supports a trustworthy value, extract it with TeX direct evidence and record use_tex; otherwise return null for the field and record unresolved. Preserve both source locations, never use the conflicting ECSV cell as direct evidence for an accepted value, and do not report harmless whitespace, markup, quoting, or equivalent numeric formatting as a conflict.

<!-- END GENERATED RULE PROFILE: coding_agent_baseline -->

For gold annotation, the paper PDF is the only evidence input — for the expert
and for any scribe alike. Put scientific disagreement with the paper in
`notes`; never replace the paper's claim with the annotator's judgment.

## 2. What counts as a candidate (L1)

### Terminology and Stella's scope

This subsection explains the terminology behind the generated contract. The
generated rules above are normative if an explanatory example is ambiguous.

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

Apply `hvs.candidate.final_treatment`, `hvs.candidate.labels_insufficient`, and
`hvs.candidate.reassessment` to each object. Record
`origin_type: introduced_by_this_paper` for a candidate first proposed here,
and `origin_type: cited_from_literature` for a qualifying reassessment.

**No-candidate papers**: set `status: no_candidates`, leave `candidates`
empty, and note in `notes` which object groups you considered and why they
fall outside the definition (e.g. "Table 1 runaways: bound, paper never
questions Galactic boundness").

For the PDF-only gold workflow, if a visible table is too large to transcribe,
stop and flag it in `notes` for adjudication. If the PDF says additional
candidates exist only in an external file, apply `generic.candidate.complete`
to the PDF-identifiable subset and describe the inaccessible remainder in
`notes`.

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

## 4. Quantities (L2) and supporting evidence

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

Apply `hvs.quantity.bound_probability` to these two slots. Do not fill
photometry, spectroscopy, abundances, stellar parameters, quality flags, or
survey-specific columns.

### Mapping and choosing values

Apply `hvs.quantity.galactic_velocity` and
`generic.quantity.multiple_estimates`. Put alternative estimates not selected
for the canonical slot in `notes`.

### Value rules — copy, never convert

Apply `generic.quantity.copy_verbatim` and
`generic.quantity.uncertainty_limits`. The following bullets specify how those
rules map into the gold schema:

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
- Probabilities follow `hvs.quantity.bound_probability`.

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
parameters, potential names, or method stages in gold. Optional method-chain
supplements are unscored diagnostics and do not enter the core artifact. Put a
method detail in free-text `notes` only when it is needed to explain an L1/L2
judgment (e.g. "distance uses the
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

Another expert may annotate the same paper with a different stable handle;
their draft and final YAML/JSON twin remain separate. Publishing the second
twin appends new file records without changing the first expert's hashes.
Formal scoring does not treat either expert as an implicit default. A human
must create a write-once per-paper gold selection profile through the
`benchmark_gold_selection_prepare` workflow.

**Budget**: no-candidate papers ~15-30 min; candidate papers ~45-90 min
depending on table size. If a paper takes far longer, stop and flag it in
`notes` — that is a finding about annotation cost, not a failure.
