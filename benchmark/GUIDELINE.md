# Contribution-First Gold Annotation Guideline

Status: approved contribution protocol v1 (2026-08-22). Gold files live only
in the external private repository selected by `STELLA_GOLD_DIR`. Record the
Git short hash of this file in each annotation's `guideline_version` field.

This guideline defines the scientific annotation target and the original
50-paper migration protocol. That migration is AI-assisted and receives
paper-level expert approval. A future unseen evaluation sample must use a
separately approved protocol without AI preannotation. In every protocol the
paper PDF is the normative scientific evidence, and the production extractor
being evaluated is never a gold input.

## 1. Scientific product

The canonical unit is one current-paper/object contribution record. Gold asks
what the current paper actually does to each identifiable HVS-related object,
not whether Stella believes the object is truly unbound and not whether the
paper was historically first.

Gold records:

- the complete paper-local contribution set;
- `candidates_found` versus `follow_up`, classified from paper behavior;
- the paper's own object-level `paper_boundness.status`;
- every explicitly object-attributed value in the 19-field vocabulary as a
  grouped unordered multiset;
- the paper's explicit `paper_preferred` treatment and value provenance;
- concise notes for important scientific results outside the structured fields;
- PDF locators supporting contribution decisions, assessed boundness, values,
  and meaningful exclusions.

The exact schema belongs to the Pydantic models and generated schema reference.
Do not add local fields, scenario identifiers, sequence numbers, or structured
spectroscopy/photometry labels to an annotation.

### Shared normative scientific rules

The following block is generated from
`skills/hvs-candidates-extraction/rules/*.yaml`. It is shared by contribution
gold and the contribution extractor. Do not edit the block by hand; update the
YAML source and run `scripts/generate_extraction_rule_views.py`.

<!-- BEGIN GENERATED RULE PROFILE: hvs_contribution_v1 -->

### `paper.claims.reported_not_truth` — Follow the paper's claims

Base every scientific claim only on the supplied paper sources. Report the paper's claims rather than your own view of astrophysical truth, and do not strengthen, weaken, or replace its conclusions.

### `hvs.contrib.paper_local_boundary` — Classify contributions from current-paper behavior only

The canonical unit is one current-paper/object contribution record: what the paper actually does to each identifiable HVS-related object. Include any substantive current-paper research on such an object; the work need not be a new boundness assessment, so spectroscopy, stellar parameters, chemistry, photometry, variability, astrometry, radial velocity, kinematics, and other current-paper results all qualify. Exclude objects mentioned only in background, introduction, or comparison prose without substantive current-paper analysis, and exclude values attached only to those background mentions. Apply the decision per object, not once per paper. Knowledge outside the supplied paper may never create eligibility.

### `hvs.contrib.candidates_found` — Classify the paper's own systematic-search entries

Use candidates_found when the object enters the paper through the current paper's own systematic search, selection, or independent processing of raw or archival data, and the paper retains it as an HVS or Galactic-unbound candidate. A blind or systematic current-paper search remains candidates_found even when one selected object was already known. Author wording such as new, known, rediscovered, or first is not decisive; the sample-entry path is.

### `hvs.contrib.follow_up` — Require a current-paper prior-candidate anchor

Use follow_up when the object enters the paper because prior work already treats it as an HVS or Galactic-unbound candidate and the current paper performs substantive object-level research on it. The current paper must itself supply the prior-candidate anchor through target-selection text, sample origin, method text, an object-attributed statement, or a paper-visible citation. A targeted prior candidate stays follow_up even when the paper downloads raw data, re-reduces spectra, remeasures kinematics, or performs a new orbit calculation. Include a prior candidate that the current paper concludes is bound; the reassessment is scientifically valuable and stays as follow_up with paper_boundness.status bound.

### `hvs.contrib.paper_boundness` — Record the paper's own object-level boundness summary

Every contribution carries paper_boundness.status with exactly one value: unbound for an unhedged retained unbound or escaping conclusion; possibly_unbound for an explicitly hedged retained conclusion such as possible, probable, likely, marginal, or model-dependent; bound when the overall object-level conclusion is bound or not unbound; no_overall_conclusion when the paper assesses boundness but supplies only numbers, incompatible conditional results, or no coherent synthesis; not_assessed when the paper substantively studies the object without assessing Galactic boundness. When multiple scenarios are reported and the paper explicitly synthesizes them, record that synthesis; when it does not, use no_overall_conclusion. Never derive a status from a probability, a threshold, a favored potential, or a model chosen by you. candidates_found may use only unbound, possibly_unbound, or no_overall_conclusion; follow_up may use all five values.

### `hvs.contrib.background_exclusion` — Exclude background-only mentions and preserve meaningful near misses

Do not include background, introduction, or comparison-only mentions of objects, and never attach values to them. Preserve scientifically relevant exclusions as paper-level reviewed exclusions: current-paper search targets finally rejected that were not prior HVS or Galactic-unbound candidates and are never retained as candidates_found, and other meaningful near misses. Give each reviewed exclusion a concise reason and manuscript evidence; do not inventory ordinary background objects, controls, or unrelated table rows.

### `hvs.contrib.required_note_evidence` — Require a contribution note and current-paper evidence

Every included object requires a non-empty contribution_note describing what the current paper actually did and recording important unstructured results not represented by the structured field vocabulary, and one or more contribution_evidence locators into the current paper. Do not invent fixed structured labels for spectroscopy, astrometry, chemistry, photometry, variability, origin studies, or other follow-up modes; the note is the extensibility surface. For not_assessed contributions the note must state that no new boundness conclusion was reported.

### `hvs.contrib.complete_identifiable_set` — Return the complete identifiable contribution set

Return every qualifying contribution object that is individually identifiable in the supplied manuscript; do not sample, cap, or choose representative objects. Exhaust every accessible table whose members are covered by a valid anchor for contribution eligibility. When qualifying members are individually identifiable only through a compressed range notation in the manuscript, submit the range string verbatim as a range group; the program expands it mechanically, so never expand a range into names yourself and never invent identities. If the manuscript states that additional qualifying objects exist only in unavailable external material, return the identifiable subset, record the unidentifiable remainder as a reviewed exclusion with manuscript evidence, and never invent identities.

### `hvs.contrib.paper_visible_identity` — Preserve paper-visible identity per contribution

Create one contribution record per scientific object and order records by first appearance in the manuscript. Copy every manuscript-visible name or source identifier for that object verbatim and cite lines containing that identifier verbatim. Group aliases only when the manuscript supports that they identify the same object; do not invent, normalize, externally resolve, merge uncertain identities, or split one object across records. Submit compressed range notations as verbatim range groups and let the program expand them.

### `hvs.contrib.all_values_after_l1` — Collect every explicitly object-attributed value after L1

Once assigned an included object, inspect all current-paper material for every explicitly object-attributed value in the structured vocabulary that the paper presents as part of its analysis or comparison: current-paper measurements or derivations, recomputations, adopted prior values, cited comparison values, values under distinct potentials, priors, methods, data releases, or epochs, and explicitly superseded historical values. Do not filter values by whether the current paper originated them. Do not return values from background-only mentions of other objects. Do not select only the final, favored, easiest, or most unbound value.

### `hvs.contrib.nineteen_fields` — Use exactly the nineteen structured fields

Collect values only for the structured vocabulary: observed_phase_space.ra, observed_phase_space.dec, observed_phase_space.distance, observed_phase_space.parallax, observed_phase_space.proper_motion_ra, observed_phase_space.proper_motion_dec, observed_phase_space.radial_velocity, derived_kinematics.galactocentric_x, derived_kinematics.galactocentric_y, derived_kinematics.galactocentric_z, derived_kinematics.galactocentric_radius, derived_kinematics.galactocentric_vx, derived_kinematics.galactocentric_vy, derived_kinematics.galactocentric_vz, derived_kinematics.tangential_velocity, derived_kinematics.galactocentric_tangential_velocity, derived_kinematics.galactic_rest_frame_velocity, bound_assessment.bound_probability, and bound_assessment.unbound_probability. Do not add structured spectroscopy, stellar-parameter, chemical-abundance, photometry, variability, or origin fields; unstructured results belong in the contribution note.

### `hvs.contrib.grouped_multivalue` — Group values per field as an unordered multiset

Group all values of one field into a single field group whose values list is never empty; each field occurs at most once per object. Do not create measurement IDs or sequence numbers; array order and any display-only ordinal are not canonical and are never scored. Deduplicate only exact repeated presentations of the same value under the same condition and provenance; retain values that differ scientifically in value, uncertainty, method, condition, source, or author treatment. Record condition_note for the potential, prior, method, epoch, data release, or other condition a value belongs to; it may be empty only when the paper states no condition or distinction.

### `hvs.contrib.value_evidence` — Support every value component with current-paper evidence

Every populated numeric component of a value needs one direct evidence locator in the current paper that preserves the printed representation; context evidence establishes meaning, unit, frame, or condition but never replaces direct evidence. Use exact file paths with the smallest inclusive line ranges that preserve the evidence, submit exact non-empty substrings for directly sourced numeric components where the stage contract requires them, separate discontinuous passages into separate references, and never cite comments, blank lines, isolated structure, or another object's value.

### `hvs.contrib.no_derivation` — Report reported values without derivation or combination

Copy numeric content, sign, precision, and unit without calculation, inference, rounding, or unit conversion; remove only presentation markup needed to form a machine-readable numeric string. Do not derive missing quantities, do not derive the complementary bound or unbound probability, do not average or combine values, and do not derive a boundness status from numbers. Do not combine conditions across fields: there is no scenarios array, no scenario reference, and no cross-field scenario join in this contract.

### `hvs.contrib.paper_preferred` — Record the paper's explicit preference only

Set paper_preferred to true only when the paper explicitly calls the value adopted, preferred, fiducial, final, recommended, current, or a replacement used for its analysis; false only when the paper explicitly calls the value superseded, replaced, rejected, non-adopted, or an alternative; null when the paper gives no explicit preference. Never use a fewest-assumptions or final-treatment fallback and never choose a preferred value yourself. Multiple true values are allowed when the paper explicitly prefers multiple conditional results.

### `hvs.contrib.source_provenance` — Preserve value provenance without guessing

Set source to this_paper, prior_work, or unclear; provenance is orthogonal to preference, so a prior-work value may be the current paper's preferred adopted input. Do not infer a source category that the current paper does not support. When useful, preserve paper-visible source or citation details in the value's optional notes without turning them into structured matching keys.

<!-- END GENERATED RULE PROFILE: hvs_contribution_v1 -->

## 2. Original 50-paper migration protocol

This protocol is restricted to papers already present in the frozen V6
50-paper sample. The migrated records are calibration and regression material,
not a new unseen evaluation set.

### Stage A — clean PDF-only AI preannotation

Use one fresh context for exactly one paper. The preannotation worker may read
only:

- `literature/<arxiv_id>/arxiv.pdf`;
- this guideline;
- the contribution annotation template and generated schema reference.

It must not read legacy gold or notes, TeX/ECSV, production
`hvs_contribution_extraction` output, run artifacts, scorecards, scoring details,
or another paper. It produces a complete contribution annotation draft with PDF
locators. Never reuse this context for another paper.

### Stage B — legacy-note reconciliation

In a separate paper-scoped context, compare the clean preannotation with the
legacy annotation selected by the frozen V6 gold-selection profile. Legacy
content is a hint for possible omissions or disagreements; it is neither truth
nor evidence. Check uncertain points in the current PDF, record the conflicts,
and produce one integrated contribution draft. Never mechanically map V6
`origin_type`, final-treatment choices, or single selected values into the new
schema.

The reconciliation stage must not inspect production extraction output, runs,
scorecards, or scoring details.

### Stage C — paper-level expert review

The expert reads the paper and reviews the complete integrated draft as a
whole. The expert may focus on suspicious, ambiguous, or high-impact parts,
request corrections, and then approve or reject the paper. The expert is not
expected to start from an empty form, manually re-extract every value, or
separately certify every locator.

Final save means the named expert approves the annotation at paper level. It
does not claim independent manual extraction or item-by-item expert
verification. The annotation must therefore record:

```yaml
annotation_process:
  protocol: contribution_migration_ai_assisted_v1
  preannotation_agent: "..."
  preannotation_model: "..."
  reconciliation_agent: "..."
  reconciliation_model: "..."
  expert_review_scope: paper_level
```

The top-level `annotator` is the approving expert.

### Stage D — final save and cleanup

Validate the expert-approved payload, write its YAML/JSON twin atomically to
`$STELLA_GOLD_DIR/<arxiv_id>/annotation_<annotator>.*`, and generate the JSON
canary from the same validated document. After both final files exist, delete
the known preannotation, conflict report, and integrated draft for that paper.
Only final gold remains in the private repository.

Before the first overwrite, the private gold repository must have a clean
commit or tag preserving the V6 annotations. Do not refresh the V6 public gold
manifest: V6 reproduction uses that historical private-gold commit. A later
contribution campaign creates its own hash-only manifest.

## 3. Future unseen gold

The migration protocol above must never be extended to a new unseen benchmark
sample. Future unseen gold uses a separately approved expert protocol without
AI preannotation and without production-extractor access. Do not infer that
this section activates such a campaign; campaign sampling, assignment, and
formal scoring require their own later decisions.

## 4. Evidence and review semantics

- `evidence_basis` remains `pdf` because PDF locations are the final scientific
  evidence surface even when an AI prepared them.
- AI may generate all PDF locators. Paper-level approval does not mean the
  expert manually relocated every item.
- A legacy note may trigger a PDF check but cannot appear as the evidence for a
  final contribution, status, value, or exclusion.
- Evidence quotes are optional and short. Locator text must be sufficient for a
  later audit to find the relevant PDF passage, table, row, column, caption, or
  note.
- Every populated numeric value keeps direct PDF evidence. Context evidence may
  explain meaning, frame, unit, condition, or attribution but never replaces
  direct value evidence.
- Scientific disagreement with the paper belongs in notes; gold records what
  the paper reports.

## 5. Final paper checklist

Before approval, review the paper-level questions below:

1. Does the draft include every identifiable object receiving substantive
   current-paper HVS-related research and exclude background-only mentions?
2. Is each object classified from its entry path as `candidates_found` or
   `follow_up`, independent of novelty claims by the authors?
3. Does `paper_boundness.status` report the paper's synthesis without deriving
   a status from probabilities or choosing a Stella-preferred scenario?
4. Are all reported values retained as same-field value lists, including
   conditional, prior-work, alternative, and explicitly superseded values?
5. Is `paper_preferred` set only from explicit author treatment?
6. Is `source` one of `this_paper`, `prior_work`, or `unclear`, with optional
   citation or attribution detail placed in the value's `notes`?
7. Are important unstructured spectroscopy, stellar-parameter, chemistry,
   photometry, variability, origin, or other results summarized in the
   contribution note?
8. Are meaningful near misses recorded without inventorying ordinary
   background objects?
9. Were all unresolved legacy-note conflicts either corrected or consciously
   accepted during the paper-level review?

Warnings may require attention but are not automatic scientific errors. A
paper remains unapproved until the expert explicitly accepts the complete
draft.
