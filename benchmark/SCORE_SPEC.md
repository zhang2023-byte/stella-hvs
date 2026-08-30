# HVS Contribution Benchmark Score Specification

Status: **APPROVED v3.0.0 (2026-08-28)**.

This document owns the current contribution-first L0, L1, and L2 scoring
semantics. It defines no composite score or automatic pass/fail threshold.
Candidate-era V6 scorecards and contribution scorecard v1 remain immutable
historical records governed by the contracts frozen with those runs.

## 1. Evaluation inputs and privacy

Formal scoring requires:

- one finalized contribution extraction run;
- one named, public, value-free, immutable JSON Gold selection covering the
  requested papers in campaign order; and
- exact hashes for every selected private annotation and scored AI document.

Every new score also binds the contribution Gold and AI target schemas, this
specification's version and SHA-256, and a SHA-256 over the maintained scorer
source set. A result-neutral implementation repair therefore has distinct
provenance even when the frozen extraction method and selected inputs are
unchanged.

Missing, duplicate, changed, or mismatched inputs fail preflight before any
scorecard is written. The scorer never selects Gold by filename and never falls
back to another expert. Public scorecards contain aggregate counts, rates, and
hashes only. Identities, values, evidence, notes, matching rows, and item-level
comparisons remain private.

The original V6 50-paper cohort is reused as a distinct contribution benchmark:
dev10 is exposed development evaluation, and its 40-paper complement remains
closed until contribution Gold is migrated and approved. Reuse of the cohort is
not an unseen-generalization claim.

## 2. L0 delivery

L0 is the only delivery layer. There is no separate top-level delivery score.
It reports:

- the exhaustive paper-state counts (`complete`, `partial`, `failed`,
  `network_failed`, `interrupted`, `pending`, `running`, and `skipped`);
- expected, delivered, missing, schema-valid, and schema-invalid contribution
  document counts and rates; and
- delivered objects whose `quantity_extraction_status` is `complete` or
  `failed`, plus the complete rate.

A missing or invalid document is a delivery failure, not a scientifically
correct empty roster. A roster-success/quantity-failure object remains
available to L1, while its quantities remain unavailable to L2. Provider usage,
estimated cost, latency, retry state, and failure class are operational metadata
outside all quality layers.

Missing and schema-invalid documents are disjoint. `delivery_rate` is delivered
documents divided by expected documents. `schema_valid_rate` is schema-valid
documents divided by delivered documents and is null when no document was
delivered; this prevents absence from being counted a second time as a format
error.

## 3. L1 contribution-object identification

L1 asks whether the system found the correct paper/object contributions and
matched them to the correct scientific objects. Gold and AI contributions are
paired deterministically and one-to-one within a paper using the shared identity
matcher:

1. parsed full Gaia identifiers;
2. overlap between normalized paper-visible identifiers; and
3. unambiguous coordinates when identifiers are insufficient.

Each contribution may be paired at most once. Unmatched AI contributions are
`ai_only`; unmatched Gold contributions are `gold_only`. L1 reports micro
precision, recall, and F1 with the underlying matched, `ai_only`, and
`gold_only` counts. The complete identifier set is not independently scored:
omission of a secondary identifier matters only when it prevents the object
from matching.

## 4. L2 quantity completeness and accuracy

L2 covers the eighteen quantity paths approved by the current contribution
schema. Historical v1/v1 input pairs retain their frozen nineteen-path scope.
Every quantity value on an unmatched Gold object remains `gold_only`, so an L1
miss cannot disappear from the numerical evaluation.

Within each matched object and quantity, Gold and AI `values` are unordered
multisets. Deterministic bipartite assignment optimizes, in order:

1. maximum number of paired values;
2. maximum strict agreements;
3. maximum lenient agreements; and
4. deterministic full-record fingerprints as the final tie-break.

`condition`, `source_note`, array order, and display ordinals are never matching
keys. Unmatched Gold values are `gold_only`; unmatched AI values are `ai_only`.
L2 reports:

- value recall: paired values divided by Gold values;
- value precision: paired values divided by AI values;
- strict agreement rate: strict agreements divided by paired values;
- strict end-to-end rate: strict agreements divided by all Gold values; and
- paired, mismatch, lenient, `gold_only`, and `ai_only` counts.

The strict agreement rate must never be presented without value recall or the
strict end-to-end rate. High accuracy on a small delivered subset cannot
compensate for missing objects or values.

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

The following remain visible diagnostics but are not formal quality layers:

- `contribution_type` accuracy and confusion on L1-matched objects;
- `paper_boundness.status` coverage, accuracy, and confusion, including
  `gold_only` for unmatched Gold objects;
- `paper_preferred` and `source` agreement on matched value pairs; and
- required `contribution_summary` and `contribution_evidence` presence.

The public diagnostics contain only aggregate counts and rates. Summary and
evidence text, locators, and per-object audit rows remain private.

`contribution_type` records the paper/object contribution role rather than a
physical object property. `paper_boundness.status` records the current paper's
scientific claim rather than Stella's inferred global truth. Both remain in the
canonical contribution contract and diagnostic audit, but neither defines a
core score layer. Summary wording is never scored as text.

L0, L1, L2, diagnostics, and operations remain visible separately. There is no
composite score and no pass/fail quality verdict.

## 7. Output integrity

New public `benchmark.hvs_contribution_scorecard` v2 artifacts contain the
three quality layers, diagnostics, aggregate counts and rates, ordered exact
input-hash lists, and the scoring-contract binding. The top-level
`l0`/`l1`/`l2`/`diagnostics` structure is the only writable v2 wire shape and is
validated against its generated strict schema before publication.
Private `benchmark.hvs_contribution_scoring_details` v2 artifacts contain
paper-level matching rows and the same provenance binding, and stay outside this
repository. `scored_run.json` stages the exact validated public scorecard
payload; emission validates it again and copies that canonical shape without
rebuilding it. Both outputs are write-once for their label. Historical v1
artifacts remain readable and are never rewritten, migrated, or rescored.
