# HVS Contribution Benchmark Score Specification

Status: **APPROVED v2.0.0 (2026-08-28)**.

This document owns the current contribution-first L0, L1, and L2 scoring
semantics. It defines no composite score or automatic pass/fail threshold.
Candidate-era V6 scorecards remain immutable historical records governed by the
contract frozen with those runs; their scores are not comparable with the
contribution target.

## 1. Evaluation inputs and privacy

Formal scoring requires:

- one finalized contribution extraction run;
- one named, public, value-free, immutable JSON Gold selection covering the
  requested papers in campaign order; and
- exact hashes for every selected private annotation and scored AI document.

Missing, duplicate, changed, or mismatched inputs fail preflight before any
scorecard is written. The scorer never selects Gold by filename and never falls
back to another expert. Public scorecards contain aggregates, rates, delivery
paper IDs, and hashes only. Identities, values, evidence, notes, matching rows,
and item-level comparisons remain private.

The original V6 50-paper cohort is reused as a distinct contribution benchmark:
dev10 is exposed development evaluation, and its 40-paper complement remains
closed until contribution Gold is migrated and approved. Reuse of the cohort is
not an unseen-generalization claim.

## 2. L0 delivery and format validation

L0 reports whether each expected paper delivered a contribution document,
whether that document validates against `literature_hvs_contributions` v1, and
how many delivered objects have `quantity_extraction_status` equal to
`complete` or `failed`.

A missing or invalid document is a delivery failure, not a scientifically
correct empty roster. A roster-success/quantity-failure object remains available
to L1 and L2a; its quantities are unavailable to L2b. Provider usage and
estimated cost are operational metadata outside all quality layers.

## 3. L1 roster and contribution type

### 3.1 L1a object identity

Gold and AI contributions are paired deterministically and one-to-one within a
paper using the shared identity matcher:

1. parsed full Gaia identifiers;
2. overlap between normalized paper-visible identifiers; and
3. unambiguous coordinates when identifiers are insufficient.

Each contribution may be paired at most once. Unmatched AI contributions are
`ai_only`; unmatched Gold contributions are `gold_only`. L1a reports micro
precision, recall, and F1. The complete identifier set is not independently
scored: omission of a secondary identifier matters only when it prevents the
object from matching.

### 3.2 L1b contribution type

On L1a-matched objects, L1b reports `contribution_type` accuracy and the full
`candidates_found`/`follow_up` confusion counts. Roster misses remain visible in
L1a and are not converted into type errors.

## 4. L2 scientific content

### 4.1 L2a paper boundness

On L1a-matched objects, L2a reports coverage, accuracy, and confusion for the
five `paper_boundness.status` values. Every unmatched Gold object contributes a
`gold_only` status and all of its quantity values remain `gold_only` in L2b.

### 4.2 L2b multivalue quantities

L2b covers the nineteen quantity paths approved by the contribution schema.
Within each matched object and quantity, Gold and AI `values` are unordered
multisets. Deterministic bipartite assignment optimizes, in order:

1. maximum number of paired values;
2. maximum strict agreements;
3. maximum lenient agreements; and
4. deterministic full-record fingerprints as the final tie-break.

`condition`, `source_note`, array order, and display ordinals are never matching
keys. Unmatched Gold values are `gold_only`; unmatched AI values are `ai_only`.
Report value recall, value precision, strict agreement over paired values, and
the underlying paired, mismatch, lenient, `gold_only`, and `ai_only` counts.

## 5. Value comparison

The comparison functions are shared with the frozen V6 quantity comparator;
this section states the active semantics without reviving the candidate target.

- Parse printed numbers after folding Unicode signs, removing leading
  approximation marks, and removing thousands separators. `value_match` uses a
  relative tolerance of `1e-9`.
- `within_gold_error` is lenient agreement. For asymmetric uncertainty, use the
  upper error when AI is higher and the lower error when AI is lower. Extracted
  uncertainty agreement is not separately scored.
- Normalize unit spelling and harmless LaTeX residue only. Never convert scale
  or dimensions. A unit on only one side is reported as
  `unit_missing_one_side`.
- Decimal and sexagesimal coordinates may match across formats when both axes
  agree within 0.5 arcsec.
- Exact values, upper limits, lower limits, and ranges are distinct;
  `limit_kind` must match, and a range compares both endpoints.
- Bound and unbound probabilities compare as fractions after interpreting an
  explicit percent representation. Never derive a complementary probability.

Evidence is required by the production and Gold schemas before scoring, but
quotation wording or locator similarity is not a quality metric.

## 6. Diagnostics and interpretation

On matched value pairs, report agreement for explicit `paper_preferred` and
`source`. A wrong preference or source category does not change the value match.
Audit the presence of required `contribution_summary` and
`contribution_evidence` on matched objects; never score summary wording as text.

L0, L1a, L1b, L2a, L2b, diagnostics, and operations remain visible separately.
High agreement on delivered pairs cannot compensate for roster or coverage
loss. There is no composite score and no pass/fail quality verdict.

## 7. Output integrity

The public `benchmark.hvs_contribution_scorecard` contains only aggregate
counts, rates, and input hashes. Private
`benchmark.hvs_contribution_scoring_details` contains paper-level matching rows
and stays outside this repository. Both outputs are write-once for their label;
a correction creates a new record with explicit provenance and, when needed, a
supersedes relationship.
