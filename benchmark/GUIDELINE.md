# Contribution-First Gold Annotation Guideline

Status: approved contribution protocol v1, aligned with the 2026-08-28 rule
profile. Gold files live only in the external private repository selected by
`STELLA_GOLD_DIR`. Record the Git short hash of this file in each annotation's
`guideline_version` field.

This is the human protocol for `benchmark.hvs_contribution_annotation` v1. The
paper PDF is the normative scientific evidence. Production extraction output,
runs, scorecards, private scoring details, and external catalog knowledge are
never Gold inputs. Final publication requires paper-level expert approval.

## 1. What counts as a contribution

The canonical unit is one current-paper/object contribution. Inclusion needs
both:

1. a paper-supported Galactic-unbound anchor; and
2. substantive object-level work by the current paper.

An HVS or hypervelocity label is not an anchor by itself because its meaning
varies across papers. It may support an anchor only when this paper explicitly
defines the class as unbound from or escaping the Milky Way and clearly applies
that definition to the object or identifiable group. Runaway and high-velocity
labels remain insufficient; proper names, catalogues, and sample memberships
remain insufficient by themselves. Also accept a paper-defined numerical,
physical, or flag criterion only when the paper clearly shows that the object
satisfies it. Do not choose a threshold, complementary probability, model, or
Galactic potential yourself.

Current-paper observing, measurement, processing, analysis, modelling, or
material use of object-level data is substantive. Background mentions, simple
restatements, comparison-only prose, and values with no role in the paper's
analysis do not qualify.

## 2. Roster decisions

For every qualifying object:

- use `candidates_found` when it enters through the current paper's
  reproducible search, selection, or analysis workflow;
- use `follow_up` when it was preselected because of a historical
  Galactic-unbound claim and the current paper performs substantive work;
- retain a follow-up even when the paper concludes `bound` or does not reassess
  boundness;
- record every paper-visible identifier with its own PDF evidence, without
  adding external aliases or an unprinted Gaia release or prefix;
- write a concise `contribution_summary` and at least one
  `contribution_evidence` locator.

Record exactly one `paper_boundness.status`:

| Status | Use when |
|---|---|
| `unbound` | The paper gives an unhedged unbound or escaping conclusion. |
| `possibly_unbound` | The paper explicitly concludes that unboundness remains possible, hedged, or model-dependent. |
| `bound` | The paper's overall conclusion is bound or not unbound. |
| `no_overall_conclusion` | The paper assesses boundness but does not synthesize its conditional or numerical results. |
| `not_assessed` | The paper performs substantive work but does not assess Galactic boundness. |

`candidates_found` permits only `unbound`, `possibly_unbound`, or
`no_overall_conclusion`; `follow_up` permits all five statuses. Every assessed
status needs PDF evidence. For `not_assessed`, the summary must say that no new
boundness assessment or conclusion was reported.

### Compressed identifier ranges

The final Gold schema has no `range_groups` field. `range_groups` is a transient
production-roster submission mechanism, not a Gold record type. When the PDF
contains an otherwise qualifying, unambiguous stable-prefix integer range, use
the project deterministic parser rather than manually guessing its members,
then store each generated member as an ordinary one-object contribution. Its
identifier evidence points to the PDF range notation, and all generated members
must genuinely share the same contribution type, summary basis, evidence, and
paper boundness.

The accepted grammar covers integer singles and ascending closed ranges under
one stable prefix, common printed or TeX dashes, preserved zero padding, and at
most 50 generated members. Prefix resets, suffixes, descending or empty ranges,
duplicates, and identifier collisions fail closed. A trailing phrase such as
“and others” never creates objects; record that non-enumerable remainder once in
`reviewed_exclusions`. Ambiguous notation is likewise one meaningful exclusion,
not a guessed roster.

## 3. Structured quantities

After an object is included, collect every explicitly object-attributed value
that the paper reports or adopts in the structured vocabulary, including
conditional, prior-work, comparison, alternative, and explicitly superseded
values. Use one quantity group with an unordered `values` list; do not keep only
the final or preferred value.

The nineteen allowed quantity paths are:

- `observed_phase_space.ra`, `observed_phase_space.dec`,
  `observed_phase_space.distance`, `observed_phase_space.parallax`,
  `observed_phase_space.proper_motion_ra`,
  `observed_phase_space.proper_motion_dec`, and
  `observed_phase_space.radial_velocity`;
- `derived_kinematics.galactocentric_x`,
  `derived_kinematics.galactocentric_y`,
  `derived_kinematics.galactocentric_z`,
  `derived_kinematics.galactocentric_radius`,
  `derived_kinematics.galactocentric_vx`,
  `derived_kinematics.galactocentric_vy`,
  `derived_kinematics.galactocentric_vz`,
  `derived_kinematics.tangential_velocity`,
  `derived_kinematics.galactocentric_tangential_velocity`, and
  `derived_kinematics.galactic_rest_frame_velocity`;
- `bound_assessment.bound_probability` and
  `bound_assessment.unbound_probability`.

Copy numeric representations without calculation, conversion, averaging, or
complementing probabilities. Preserve coordinate format, uncertainty or limit
shape, condition, explicit `paper_preferred`, `source`, and optional
`source_note`. Results outside the vocabulary belong in
`contribution_summary`, not new structured fields.

In Gold, PDF `evidence` collectively supports the printed numeric components of
one value; `context_evidence` may establish meaning, unit, frame, condition, or
attribution. This is the PDF representation of the production contract's
part-labelled direct evidence. The production rule about TeX and converted
ECSV source authority does not apply to Gold: for Gold, the PDF is authoritative.

## 4. Meaningful exclusions

Use `reviewed_exclusions` only for scientifically relevant near misses that a
later reviewer could reasonably mistake for contributions: for example,
objects analyzed in the paper but lacking a qualifying Galactic-unbound anchor,
or qualifying members that cannot be identified or deterministically
enumerated. Group repeated cases when the paper defines a group or they share
one reason. Do not inventory ordinary background objects, controls, unrelated
rows, generic mentions, or bibliography-only material.

## 5. Canonical rule reference

The block below is generated from
`contracts/hvs-contributions/rules/*.yaml`. It is the shared scientific rule
profile used by production extraction and Gold review. Production-specific
phrases such as “assigned contribution,” TeX/ECSV evidence, submission schema,
and transient `range_groups` are mapped to the PDF/Gold representation by
Sections 1--4 above; they do not add fields to the Gold schema. Do not edit the
generated block by hand. Update its YAML owner and run
`python -m stella schema generate`.

<!-- BEGIN GENERATED RULE PROFILE: hvs_contribution_v1 -->

### `paper.claims.reported_not_truth` — Follow the paper's claims

Base scientific claims only on the supplied paper materials. Report the
paper's claims rather than external truth or your own inference. Preserve
each claim's subject, scope, attribution, uncertainty, and stated
conditions; do not strengthen, weaken, combine, or replace the paper's
conclusions.

### `hvs.contrib.galactic_unbound_anchor` — Require a Galactic-unbound anchor

Use only the supplied paper. An object has a qualifying anchor only when
the paper explicitly reports that this paper or prior work treated it as
unbound from or escaping the Milky Way. Accept hedged or model-dependent
statements when the work being described retains possible unboundness as
scientifically viable. An explicit prose conclusion is unnecessary when
the paper defines a numerical rule, physical test, or flag for Galactic
unboundness and clearly shows that the object satisfies it.

### `hvs.contrib.no_proxy_anchor` — Do not use proxy evidence

An HVS or hypervelocity-star label is not a Galactic-unbound anchor by
itself because its meaning varies across papers. It may support an anchor
only when the supplied paper explicitly defines that class as unbound from
or escaping the Milky Way and clearly applies that defined classification
to the object or identifiable group. Proper names, catalogue or sample
membership, HVS-labelled headings or tables, name-only lists, and bare
table rows or citations remain insufficient by themselves and do not
substitute for that definition and application. Do not infer an anchor
from candidate, runaway, or high-velocity labels; an ejection mechanism or
origin claim; or numerical values alone. You must not choose a probability
threshold, compute a complementary probability, or select a model or
Galactic potential to create an anchor.

### `hvs.contrib.candidates_found` — Classify objects found by the current paper

Use candidates_found when the paper applies a reproducible search,
selection, or analysis workflow to a source dataset or population; the
object enters the paper's sample or results because it satisfies that
workflow; and the current paper retains a qualifying Galactic-unbound
anchor for it. The workflow need not be blind, and the object need not be
new. A previously known object remains candidates_found when recovered
independently through this workflow. If the paper preselected the object
because of its prior Galactic-unbound status, use follow_up instead.

### `hvs.contrib.follow_up` — Classify follow-up of prior unbound claims

Use follow_up when the paper includes an object because of a qualifying
historical Galactic-unbound anchor and performs substantive object-level
work on it. Using new or reprocessed data does not make it
candidates_found. The type remains follow_up whether the current paper
retains, rejects, or does not reassess Galactic unboundness.

### `hvs.contrib.substantive_object_work` — Define substantive object-level work

Object-level work is substantive when the current paper observes,
measures, processes, analyzes, or models the object, or materially uses
its object-level data or results in the paper's own analysis. A new
Galactic-boundness assessment is not required. Background, introduction,
or comparison-only mentions, simple restatements of prior results, and
values listed without an analytical role do not by themselves qualify.

### `hvs.contrib.paper_boundness` — Record the current paper's boundness conclusion

Every contribution records exactly one paper_boundness.status for the
current paper: unbound for an unhedged unbound or escaping conclusion;
possibly_unbound for an explicitly hedged or model-dependent conclusion
that retains possible unboundness; bound for an overall bound or
not-unbound conclusion; no_overall_conclusion when the paper assesses
Galactic boundness but gives no overall conclusion; and not_assessed when
it does not assess Galactic boundness. candidates_found may use only
unbound, possibly_unbound, or no_overall_conclusion; follow_up may use all
five statuses.

### `hvs.contrib.boundness_synthesis` — Do not synthesize a boundness conclusion

Follow the paper's explicit overall conclusion for the object. When the
paper explicitly synthesizes conditional results, record that synthesis.
When it reports incompatible conditional results without an overall
synthesis, use no_overall_conclusion rather than possibly_unbound. Never
derive a status from raw numbers or from a threshold, model, or Galactic
potential that you choose.

### `hvs.contrib.group_level_anchor` — Limit group-level anchors

A group- or table-level statement may supply a Galactic-unbound anchor to
all members only when the paper explicitly identifies the named group or
table and states that all of its members satisfy a qualifying
Galactic-unbound criterion. Each included object must also be individually
identifiable in the supplied paper. Statements about only some members,
name-only lists, and HVS-labelled headings or tables by themselves do not
propagate an anchor. The same group-level evidence may support each
covered object.

### `hvs.contrib.complete_identifiable_set` — Return the complete identifiable set

Return every qualifying object identifiable in the supplied paper, either
directly or through an accepted deterministic range group; do not sample,
cap, or choose representatives. Exhaust every accessible table whose
members have a valid anchor. If additional qualifying members appear only
in unavailable external material, return the identifiable subset and
record the unidentifiable remainder as one reviewed exclusion.

### `hvs.contrib.deterministic_range_groups` — Submit deterministic identifier ranges without expanding them

When a verbatim compressed identifier notation unambiguously enumerates
otherwise qualifying objects that share one contribution type, summary,
evidence basis, and paper_boundness, submit it once as a range group and
never enumerate its members yourself. Only the program may expand an
accepted range under its strict deterministic grammar. It must preserve
the original notation and evidence, reject ambiguous or unsupported
syntax, and record any non-enumerable remainder as one reviewed exclusion.

### `hvs.contrib.paper_visible_identity` — Preserve paper-visible identity

Create one contribution per scientific object. For directly named objects,
copy every identifier that the supplied paper shows exactly as written and
attach evidence that contains it. For a range-derived object, use only the
identifier produced deterministically from the verbatim paper notation and
attach that notation's evidence. Treat identifiers as an unordered set and
merge them only when the paper shows that they refer to the same object. Do
not add external aliases, normalize or complete identifiers, add an
unprinted Gaia release or prefix, merge uncertain identities, or split one
object across records.

### `hvs.contrib.required_summary_evidence` — Require a contribution summary and evidence

Every contribution requires a concise, non-empty contribution_summary
stating what the current paper did, plus one or more current-paper
contribution_evidence locators that directly support it. Use the summary
to preserve important results not represented by the structured quantity
vocabulary. For not_assessed, state that the paper did not assess Galactic
boundness. Keep research modes in free text rather than creating fixed
categories.

### `hvs.contrib.reviewed_exclusions` — Record only meaningful near misses

Use reviewed_exclusions only for scientifically meaningful near misses
that could reasonably be mistaken for contributions and need explanation.
Typical cases are objects or groups analyzed by the current paper but
lacking a qualifying Galactic-unbound anchor, and otherwise qualifying
members that are neither directly identifiable nor deterministically
enumerable. Give each a concise reason and paper evidence. Group repeated
cases by a paper-defined group or common reason. Do not inventory ordinary
background objects, controls, generic mentions, unrelated table rows, or
bibliography-only material.

### `hvs.contrib.all_values_after_l1` — Collect all reported or adopted values

For the assigned contribution, collect every explicitly object-attributed
value in the structured vocabulary that the current paper reports or adopts
in its analysis or comparison. Include current-paper results,
recomputations, adopted prior values, cited comparison values, alternative
conditional values, and explicitly superseded historical values. Do not
limit extraction to values produced by this paper or to the preferred,
final, easiest, or most-unbound value. Do not collect values for other
objects mentioned only in background.

### `hvs.contrib.structured_quantity_scope` — Use only the structured quantity vocabulary

Use only the nineteen quantity paths declared by the submission schema.
Do not create structured quantities for spectroscopy, stellar parameters,
chemical abundances, photometry, variability, origin, or other results
outside that vocabulary; those results belong in contribution_summary
rather than this module.

### `hvs.contrib.coordinate_and_frame_mapping` — Preserve coordinate and reference-frame meaning

For RA and Dec, preserve the reported decimal or sexagesimal representation
and declare its coordinate_format; do not convert it. Map other
observed_phase_space quantities only to the corresponding reported
quantity, preserving any stated frame, convention, epoch, or data release
in condition and context evidence. Galactocentric positions and velocity
components require an explicitly Galactocentric frame.

### `hvs.contrib.velocity_mapping` — Distinguish the structured velocity quantities

Use tangential_velocity for a paper-defined transverse or tangential speed
that is not explicitly Galactocentric. Use
galactocentric_tangential_velocity only for an explicitly Galactocentric
tangential or cylindrical component. Use galactic_rest_frame_velocity only
for a total speed defined in the Galactic or Galactocentric rest frame and
used in Galactic-boundness analysis. Never substitute radial velocity, a
generic total speed, a component, escape velocity, or an escape margin.

### `hvs.contrib.probability_mapping` — Map only Galactic boundness probabilities

Use bound_probability and unbound_probability only for true Galactic bound
or unbound probabilities reported by the paper. An explicitly Galactic
escape probability maps to unbound_probability. Do not substitute origin
probabilities, classification confidence, escape velocity, ratios,
margins, or other statistics.

### `hvs.contrib.group_level_values` — Limit group-level value propagation

A value, limit, or condition stated for every member of a named group or
table may apply to the assigned object only when the paper explicitly
defines that scope and the object is individually identifiable as a member.
The same group-level evidence may support each covered object. Do not
propagate from statements about only some members, a bare heading or table,
or membership alone.

### `hvs.contrib.grouped_multivalue` — Group values per quantity as an unordered multiset

Use one non-empty values group per quantity and treat its values as
unordered. Deduplicate repeated presentations of the same scientific value
with the same uncertainty, condition, preference, and provenance; retain
values that differ in any of those respects. Record in condition the
potential, prior, method, epoch, data release, frame, convention, or other
stated distinction; use an empty string only when the paper states none.

### `hvs.contrib.uncertainty_limits` — Preserve uncertainty and limit semantics

Use error for a symmetric uncertainty and lower_error with upper_error for
an asymmetric uncertainty; never mix the two forms. Represent a one-sided
bound with the corresponding limit_kind. Represent a closed range with
range_lower and range_upper and no central value. Do not reinterpret
uncertainty bounds around a measurement as a reported range.

### `hvs.contrib.no_derivation` — Preserve reported numerical representations

Copy numeric content, sign, precision, and unit without calculation,
inference, rounding, or unit conversion; remove only presentation markup
needed for a machine-readable numeric string. Preserve a reported boundness
probability as either its unitless 0--1 fraction or its 0--100 percent
representation. Do not derive missing or complementary quantities, average
or combine values, infer a boundness status, or create cross-quantity
scenario joins.

### `hvs.contrib.value_evidence` — Support every numeric component

Give every populated numeric component exactly one direct evidence locator
in the current paper that preserves its printed representation. Use context
evidence for meaning, unit, frame, or condition, never as a substitute for
direct evidence. Use the smallest exact locator and raw fragment required by
the submission schema, separate discontinuous passages, and never cite
another object's value or non-evidentiary source structure.

### `hvs.contrib.source_authority` — Use manuscript text for scientific meaning

Use the author manuscript for scientific meaning, definitions, captions,
headers, notes, and conditions. Use converted ECSV only for exact table
addressing and interpret it through its mapped manuscript source. If ECSV
materially conflicts with the manuscript, use a manuscript-supported value
with text evidence; otherwise do not submit the unresolved value. Never let
converted ECSV override the paper.

### `hvs.contrib.paper_preferred` — Record only the paper's explicit preference

Set paper_preferred to true only when the paper explicitly marks a value as
adopted, preferred, fiducial, final, recommended, current, or a replacement
used in its analysis. Set it to false only when the paper explicitly marks
the value as superseded, replaced, rejected, non-adopted, or alternative;
otherwise use null. Never choose a preference yourself. Multiple true
values are allowed when the paper explicitly prefers multiple conditional
results.

### `hvs.contrib.source_provenance` — Preserve value provenance without guessing

Set source to this_paper, prior_work, or unclear only as supported by the
current paper. Provenance is independent of preference, so an adopted
prior-work value may be paper_preferred. Use source_note only for useful
paper-visible source or citation detail; do not turn it into a matching key.

<!-- END GENERATED RULE PROFILE: hvs_contribution_v1 -->

## 6. Original 50-paper migration protocol

This protocol is restricted to papers already present in the frozen V6
50-paper sample. The migrated records are calibration and regression material,
not a new unseen evaluation set.

### Stage A — clean PDF-only AI preannotation

Use one fresh context for exactly one paper. The preannotation worker may read
only:

- `literature/<arxiv_id>/arxiv.pdf`;
- this guideline;
- `benchmark/templates/hvs_contribution_annotation_template.yaml`; and
- `contracts/generated/benchmark.hvs_contribution_annotation.v1.schema.json`.

It must not read legacy Gold or notes, TeX/ECSV, production contribution output,
run artifacts, scorecards, scoring details, or another paper. It produces a
complete contribution annotation draft with PDF locators. Never reuse this
context for another paper.

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

Validate the expert-approved payload and atomically publish its one canonical
JSON document at
`$STELLA_GOLD_DIR/<arxiv_id>/annotation_<annotator>.json`. The document includes
the deterministic canary derived from the same validated annotation. Never
write or require a YAML twin. After the final JSON exists, delete the known
preannotation, conflict report, and integrated draft for that paper unless the
save request explicitly retains migration work for audit. Retained work stays
only in the configured ignored work directory and is never active Gold or
scoring input. Only final Gold enters the active gold root; a verified V6
preservation pair may remain only in the separate archive described below.

If that canonical path already belongs to the same annotator's selected V6
YAML/JSON twin, replacement is allowed only with explicit `supersede`
authority, the exact frozen V6 selection id, and an explicit clean private-Git
commit or tag. Verify the selected pair against both the historical public hash
inventory and that Git ref. In one transaction, archive it outside the active
gold root as
`<private-gold-repo>/legacy-v6/<arxiv_id>/annotation_<annotator>_old.{yaml,json}`,
then publish the contribution JSON; any publication failure restores the
legacy pair. A mismatched annotator, non-unique selection, missing ref, hash
mismatch, partial pair, or existing archive fails closed. The `_old` pair is
preservation material only and never participates in active selection or
scoring.

If the active path already contains contribution Gold, a reviewed correction
uses the same save operation but a distinct revision transaction. It requires
explicit `supersede` authority, paper-level expert approval, an exact expected
current SHA, and an active canonical already committed in private Git `HEAD`.
The request must retain its paper-scoped migration audit: refusal or failure to
enumerate those artifacts happens before rollback-backup or canonical writes,
and no audit cleanup follows a successful revision. Under a paper-scoped lock
whose work path is verified as ignored by the private Git repository, write an
ignored transient backup, recheck the active bytes, and use same-directory
fsync-and-rename replacement. A later failure restores the exact backup; a
success removes it. Private Git, rather than a second artifact store, provides
durable revision history. This branch does not require or modify the V6
preservation ref or `legacy-v6` archive.

Contribution selections are active-only: the selected expert, filename, and
SHA must match the current canonical exactly. The resolver never chooses a
different expert, hash, Git revision, or fallback file. A malformed or
mismatched SHA, uncommitted active base, concurrent drift, unignored lock path,
stale rollback backup, or rollback failure fails closed. This correction
capability does not publish a new selection or imply that any annotation has
been revised. These transaction mechanics do not change the scientific rules
recorded by an annotation's `guideline_version`.

Do not refresh the V6 public gold manifest. V6 reproduction uses the frozen
selection plus the verified historical private-Git ref. A later contribution
campaign creates its own hash-only manifest. The active contribution Gold is
JSON-only.

## 7. Future unseen Gold

The migration protocol above must never be extended to a new unseen benchmark
sample. Future unseen gold uses a separately approved expert protocol without
AI preannotation and without production-extractor access. Do not infer that
this section activates such a campaign; campaign sampling, assignment, and
formal scoring require their own later decisions.

## 8. Evidence and review semantics

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
- Scientific disagreement with the paper belongs in
  `annotation_process.process_note`; Gold records what the paper reports.

## 9. Final paper checklist

Before approval, review the paper-level questions below:

1. Does every included object have both a qualifying Galactic-unbound anchor
   and substantive current-paper work?
2. Were HVS, runaway, high-velocity, sample-membership, and numerical proxies
   rejected unless the paper supplies the required anchor?
3. Is each object classified from its sample-entry path as `candidates_found`
   or `follow_up`, independent of novelty wording and final boundness?
4. Does `paper_boundness.status` preserve the paper's synthesis without a
   reviewer-chosen threshold, probability complement, model, or potential?
5. Are identifiers paper-visible and evidence-bearing, with deterministic
   range members materialized as ordinary contributions and non-enumerable
   remainders recorded only once?
6. Are all values in the nineteen-path vocabulary retained as unordered
   same-quantity lists, including conditional, prior-work, alternative, and
   explicitly superseded values?
7. Are uncertainty, limit, coordinate, probability, `paper_preferred`,
   `source`, `condition`, and `source_note` fields faithful to the PDF and free
   of reviewer calculation?
8. Does every value have sufficient direct PDF `evidence`, with
   `context_evidence` used only for meaning or attribution?
9. Are important unstructured spectroscopy, stellar-parameter, chemistry,
   photometry, variability, origin, or other results preserved in
   `contribution_summary`?
10. Are `reviewed_exclusions` limited to meaningful near misses, and were all
    legacy-note conflicts corrected or consciously accepted during paper-level
    review?

Warnings may require attention but are not automatic scientific errors. A
paper remains unapproved until the expert explicitly accepts the complete
draft.
