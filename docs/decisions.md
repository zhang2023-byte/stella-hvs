# Durable Stella Decisions

This document contains only decisions that govern the current system. Git,
`CHANGELOG.md`, immutable campaign artifacts, and public scorecards preserve
superseded implementation history.

## D1. Product workflows, operations, schemas, and rules have distinct owners

`workflows/stella_workflows.yaml` owns the three public product workflows:
`literature_pipeline`, `gold_annotation`, and `benchmark`.
`workflows/operations.yaml` owns internal operation metadata. Cardinality is
request data; there are no separate one-paper and batch workflows.

`src/stella/schema_registry.py` owns the Stella release, artifact versions,
lifecycle, and the active benchmark campaign. Pydantic models own structural
schemas. `contracts/hvs-contributions/rules/*.yaml` owns the contribution
science rules and profile. `python -m stella schema generate` rebuilds JSON
Schema, version, and rule-profile views; generated content is never edited by
hand.

## D2. Authority is explicit and fails closed

Planning is the default and performs no external calls or canonical writes.
`--execute` grants no network, LLM, private-Gold, scoring, supersede, or
publication authority. Each grant is explicit and limited to the operation
that declares it.

Runs live under `runs/<workflow_id>/<run_id>/`, freeze their normalized request,
append events and attempts, preserve partial results, retry only unfinished or
network-failed work, and finalize one-way. A changed method, rule, prompt,
provider, budget, or implementation uses a new run ID and provenance.

## D3. Gold, production extraction, and scoring are isolated

Gold lives in the external private repository selected by `STELLA_GOLD_DIR`.
The PDF is its normative scientific evidence. Production extraction reads only
paper-local archived inputs and may not read Gold, scorecards, scoring details,
or prior run output. Scoring is a separately authorized private-Gold operation;
public scorecards contain aggregates and hashes only.

The original 50-paper contribution migration is the only AI-assisted Gold
exception. It uses a fresh PDF-only preannotation, a separate reconciliation
against the selected legacy annotation, and paper-level expert approval.
Legacy content is an omission signal, never truth or evidence. Production
extractor output remains forbidden in both contexts.

## D4. The scientific unit is one current-paper/object contribution

`literature_hvs_contributions` v1 and
`benchmark.hvs_contribution_annotation` v1 share the scientific shape while
using different evidence locators. A contribution needs a paper-supported
Galactic-unbound or escaping anchor and substantive current-paper object work.
HVS and hypervelocity terminology varies across papers, so its label alone is
not an anchor. It qualifies only when the supplied paper explicitly defines
the class as Galactic-unbound or escaping and clearly applies that definition
to the object or identifiable group. Runaway, high-velocity, sample, mechanism,
or numerical labels remain insufficient proxies.

`candidates_found` follows entry through the current paper's reproducible
search, selection, or analysis workflow. `follow_up` follows preselection by a
historical Galactic-unbound claim plus substantive current-paper work; it stays
included when the current paper reports `bound` or `not_assessed`.

`paper_boundness.status` records the current paper's own synthesis as
`unbound`, `possibly_unbound`, `bound`, `no_overall_conclusion`, or
`not_assessed`. No model or annotator chooses a threshold, derives a
complementary probability, or selects a Galactic model to create the anchor or
status.

## D5. Identity is paper-local, with one deterministic range exception

Canonical production and Gold identity is one unordered list of paper-visible
`{value, evidence}` identifiers. It has no preferred identifier, external alias,
or model-completed Gaia prefix. Display names and Gaia recognition are
downstream deterministic facets, not serialized scientific fields.

For an unambiguous stable-prefix integer notation, the model submits one
transient `range_groups` item and program code performs strict, capped,
fail-closed expansion. The parser preserves zero padding, accepts common
printed and TeX dashes, and rejects unsupported syntax, duplicates, and
case-insensitive collisions. Canonical production and Gold materialize ordinary
one-object contributions; neither schema persists `range_groups`. A
non-enumerable remainder produces one reviewed exclusion.

## D6. Quantities are grouped reported-value multisets

Each contribution may contain the fixed nineteen structured quantities. One
quantity appears at most once and holds a non-empty unordered `values` list.
Conditional, adopted prior, comparison, alternative, and explicitly superseded
values remain eligible. Exact duplicate scientific records may be removed;
array order and display ordinals carry no meaning.

Numeric text, coordinate format, uncertainty or limit shape, condition,
`paper_preferred`, `source`, evidence, and `source_note` preserve the paper's
representation. No writer converts units, calculates missing values, derives a
probability complement, averages results, or creates cross-quantity scenarios.
Important results outside the vocabulary belong in `contribution_summary`.

Production evidence uses part-labelled TeX/ECSV locators with manuscript text
authoritative for meaning. Gold uses PDF evidence that collectively supports
the printed components. This representation difference does not change the
shared scientific value.

## D7. The original V6 cohort is reused as a distinct contribution benchmark

The fixed 50-paper order and 10/40 split from `hvs-extraction-v6` are the
approved contribution benchmark cohort. Candidate-era and contribution-era
scores are different scientific targets even when they reuse papers. They use
different schemas, Gold selections, method fingerprints, and scorecards and
are never compared as one metric or described as unseen generalization.

Dev10 contribution Gold has a named, value-free, immutable selection. It is
being re-reviewed after the 2026-08-28 rule correction before new evaluation.
The remaining 40 papers stay closed until their contribution Gold is migrated,
expert-approved, and bound to a separate selection.

## D8. Gold selection is explicit and write-once

Multiple experts may retain independent annotations for one paper. Assignment
records intended work but is not scoring input. Formal scoring requires a
named, public, value-free selection that binds exactly one expert annotation
hash per paper in campaign order; it never chooses by filename or falls back to
another expert.

Contribution Gold is one active JSON document per expert and paper. An
original-V6 same-expert migration requires explicit supersede authority, a
clean preservation ref, frozen legacy hashes, and transactional archive/restore
behavior. A later contribution correction is a separate branch of the same
save operation: it requires paper-level approval, supersede authority, an exact
active SHA, retention of the paper migration audit, and an active canonical
that matches private Git `HEAD`. Audit enumeration fails before rollback-backup
or canonical writes, and no audit cleanup follows replacement. It acquires a
verified ignored paper lock, writes an ignored transient backup, checks for
drift again, and atomically replaces or restores the canonical bytes. A
successful transaction removes the backup; private Git provides durable
history. `legacy-v6` is unchanged by this branch.

Contribution selections are active-only and resolve only when their exact SHA
matches the current canonical; they never select another expert, Git revision,
or fallback value. Candidate-era manifests and legacy archives are not
rewritten or used as scoring fallbacks. Transaction-only wording changes do not
alter the scientific rule version recorded in existing annotations. This
decision defines capability and does not claim that a revision or replacement
selection has been published.

An approved original-50 batch migration may validate and save disjoint paper
paths concurrently in one shared private Gold worktree. This is paper-level
filesystem concurrency, not shared Git publication authority: no batch session
may stage, commit, push, or publish a selection, and the same paper is never
assigned twice. One integration owner audits the complete approved path set and
owns selective staging, the private commit, and later selection publication.

## D9. Contribution scores remain layered

Formal contribution reporting has exactly three quality layers: L0 delivery,
L1 contribution-object identification, and L2 quantity completeness/accuracy.
Delivery is part of L0 and is not emitted as a separate score. Contribution
type, the current paper's boundness claim, preference, provenance, summary
presence, and evidence presence remain diagnostics or audits. They remain in
the contribution contract but are not physical-object quality layers.

Unmatched Gold objects and values remain visible as `gold_only`; L1 misses
propagate into L2, and matched-pair agreement never substitutes for end-to-end
coverage. Cost is operational metadata. There is no composite score or
automatic pass/fail verdict. New contribution scorecards and private scoring
details use v2; immutable v1 artifacts remain readable and are never rewritten.
The writable v2 scorecard has one strict top-level wire shape. Each score binds
the target schemas, score-spec version and hash, scorer-source hash, and exact
selected-Gold and delivered-AI input hashes. Missing documents and delivered but
schema-invalid documents are disjoint L0 outcomes; format validity is measured
over delivered documents. Summary/evidence diagnostics expose aggregate
presence counts and rates only.

## D10. Documentation has fixed owners

`README.md` routes human readers; `docs/guide.md` owns CLI usage;
`docs/data-contract.md` owns artifact paths, privacy, lifecycle, and versioning;
`docs/vision.md` is non-normative product direction; `benchmark/README.md`
routes benchmark contracts; `benchmark/GUIDELINE.md` is the expert Gold
protocol; `benchmark/SCORE_SPEC.md` owns current contribution scoring; and
`benchmark/benchmark_implementation.md` owns current status, risks, and the
next gate.

Release history belongs in `CHANGELOG.md`. Generated views are regenerated from
their owners. Cross-session plans are temporary, stay untracked, and are
deleted when their delivery is complete.

## D11. Dynamics never silently selects scientific inputs

Contribution timelines are evidence views, not authoritative global boundness
states or input-selection policy. Dynamics requires an explicit
`hvs_dynamics.input_selection` snapshot with a rationale, source-file hash, and
fingerprints plus numeric snapshots for every consumed quantity. Missing or
stale selection fails closed; order, uncertainty, preference, or boundness
never silently selects an input.
