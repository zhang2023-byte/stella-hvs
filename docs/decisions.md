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

`literature_hvs_contributions` v2 and
`benchmark.hvs_contribution_annotation` v2 share the scientific shape while
using different evidence locators; their v1 forms remain readable history. A
contribution needs a paper-supported
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

Each current contribution may contain the fixed eighteen structured quantities.
The retired v1-only
`derived_kinematics.galactocentric_tangential_velocity` path is unstructured.
One
quantity appears at most once and holds a non-empty unordered `values` list.
Conditional, adopted prior, comparison, alternative, and explicitly superseded
values remain eligible only when each value independently satisfies that
quantity's definition. Exact duplicate scientific records may be removed;
array order and display ordinals carry no meaning. A condition records a
reported assumption but cannot make an ineligible value eligible.

Passing a selection, query, quality-control, or sample-entry threshold does not
turn that threshold into an object-attributed reported value. Such thresholds
are not propagated merely because an object passed the workflow. A threshold is
eligible only when the paper separately reports or adopts it as a scientific
object-level result, bound, or constraint for the object or explicitly defined
group.

Numeric text, coordinate format, uncertainty or limit shape, condition,
`paper_preferred`, `source`, evidence, and `source_note` preserve the paper's
representation. No writer converts units, calculates missing values, derives a
probability complement, propagates an unreported result, synthesizes a radius
or speed, averages results, or creates cross-quantity scenarios.

Observed phase-space quantities are observer-centred at a reported epoch;
distance is heliocentric, proper motions are equatorial components, and radial
velocity is heliocentric or barycentric rather than LSR/GSR. Galactocentric
positions and velocities represent the current, integration-t=0, or stated
reference-epoch state. `galactocentric_radius` is the three-dimensional
spherical radius. `tangential_velocity` is the heliocentric sky-plane speed
magnitude, while `galactic_rest_frame_velocity` is a three-dimensional total
speed magnitude in the Galactic or Galactocentric rest frame. Orbit-event and
other-time values, cylindrical radii or velocities, and other material results
outside the vocabulary belong in `contribution_summary`.

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

All 50 papers have expert-approved contribution Gold v1. The existing named
dev10 selection still targets v1, and test40 has no contribution selection.
Both splits remain closed to new formal scoring until the quantity-v2 rules are
applied through PDF-grounded re-review, controlled Gold-v2 revision, and new
split-specific value-free selections.

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

Original-50 read-only paper review and approved revision may operate on
disjoint paper paths, but the same paper is never assigned twice. Batch
sessions never stage, commit, push, or publish selections. After every batch is
complete, one new integration owner audits the exact 50-paper changed path set,
validates the complete cohort, and owns the single selective private commit and
any later selection publication.

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

## D12. Benchmark extraction has one frozen hierarchical concurrency policy

All benchmark profiles use the same execution policy: at most ten papers run
concurrently, and each paper may run at most fifty frozen quantity candidates
concurrently after its roster is complete. Development and test profiles do
not carry separate concurrency defaults. Worker capacity is distinct from
provider request rate: all paper workers, quantity workers, and simultaneous
benchmark runs in the workspace share one exact cross-process rolling window
capped at 400 request starts per minute against the documented 500 RPM
TokenDance account and key limits. Provider HTTP 429
responses reduce the shared ceiling through 320, 240, and 160 RPM; each clean
60-second window restores one step. `Retry-After` is authoritative when it is
longer than the local retry delay.

The paper roster remains the stable quantity-work manifest. Parallel results
are assembled in roster order, one candidate failure does not cancel siblings,
and resume retries only retryable failed candidates. Previously successful
candidate bytes remain unchanged; replaced failure records are retained as
append-only attempt artifacts. The complete execution policy is frozen into
the benchmark method and fingerprint, cannot be overridden by a hidden worker
environment variable, and any later policy change requires a new run id.
