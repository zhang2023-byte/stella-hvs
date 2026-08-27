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
- every explicitly object-attributed value in the 19-quantity vocabulary as a
  grouped unordered multiset;
- the paper's explicit `paper_preferred` treatment and value provenance;
- concise summaries for important scientific results outside the structured quantities;
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

Do not infer a Galactic-unbound anchor from an HVS or hypervelocity-star
classification; candidate, runaway, or high-velocity labels; sample or
catalogue membership; a name-only list; a bare table row or citation; an
ejection mechanism or origin claim; or numerical values alone. You must
not choose a probability threshold, compute a complementary probability,
or select a model or Galactic potential to create an anchor.

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
name-only lists, and HVS-labelled headings or tables do not propagate an
anchor. The same group-level evidence may support each covered object.

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

Validate the expert-approved payload and atomically publish its one canonical,
write-once JSON document at
`$STELLA_GOLD_DIR/<arxiv_id>/annotation_<annotator>.json`. The document includes
the deterministic canary derived from the same validated annotation. Never
write or require a YAML twin. After the final JSON exists, delete the known
preannotation, conflict report, and integrated draft for that paper. Only final
Gold remains in the active gold root; a verified V6 preservation pair may
remain only in the separate archive described below.

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

Do not refresh the V6 public gold manifest. V6 reproduction uses the frozen
selection plus the verified historical private-Git ref. A later contribution
campaign creates its own hash-only manifest. The active contribution Gold is
JSON-only.

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
