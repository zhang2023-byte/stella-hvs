# HVS Extraction Score Specification

Status: **APPROVED v1.0.0 (2026-07-26)**.

This document owns the L1 and L2 scoring decisions presented to human users.
It defines no composite score, automatic pass/fail threshold, or third scored
layer. Supporting evidence is an acceptance requirement for extracted values,
not a metric.

## 1. Evaluation population and delivery

Scoring uses the paper order frozen in the current campaign and the exact
expert-gold snapshot named by its hash manifest. Public scorecards contain only
aggregate counts, rates, paper IDs needed for delivery accounting, and
provenance hashes. Candidate-level identities, values, notes, matching rows,
and evidence comparisons are private.

Delivery is reported before quality:

- L1 roster delivery: `complete`, `failed`, or `missing`.
- L2 core-field delivery: `complete`, `partial`, `failed`, or `missing`, plus
  candidate counts for completed and failed field extraction.

A successful roster followed by field failure still exposes its credible
candidates to L1. Its unavailable fields count as missing in L2 and the paper
is partial. A roster failure on a negative paper is a delivery failure; it
must never be reinterpreted as a correct empty roster.

## 2. L1 candidate identity

L1 compares candidate sets per paper. Matching is deterministic and one-to-one
using this ordered ladder:

1. exact Gaia source ID after parsing the paper-stated data release and numeric
   identifier;
2. normalized aliases and paper candidate IDs, using the versioned name
   normalizer;
3. coordinates, first with the propagated/default tight tolerance and then the
   documented fallback tolerance when identity fields are insufficient.

Each gold and extracted candidate may be matched at most once. Unmatched
extracted candidates are false positives; unmatched gold candidates are false
negatives. A delivered negative paper with an empty roster is a true negative
for paper delivery but contributes no candidate row to micro precision or
recall.

Report:

- micro precision, recall, and F1 over all candidate decisions;
- macro paper-level precision, recall, and F1;
- sampling-weighted sensitivity estimates where the campaign defines weights;
- paired paper bootstrap confidence intervals;
- a no-coordinate sensitivity analysis that disables the coordinate tier.

The primary scorecard must identify the matching and normalization versions.

## 3. L2 core fields

L2 evaluates the 19 core quantity paths:

- observed phase space: RA, Dec, distance, parallax, both proper-motion
  components, and radial velocity;
- derived kinematics: Galactocentric x, y, z, radius, vx, vy, vz, tangential
  velocity, Galactocentric tangential velocity, and Galactic-rest-frame
  velocity;
- bound and unbound probability.

For every L1-matched pair, create a gold-driven row for each gold quantity.
An extracted value in the scored vocabulary with no gold counterpart creates
an `ai_only` row. Every gold field on an unmatched gold candidate, unavailable
paper, or field-failed candidate creates a `gold_only` row. Quantities on an
unmatched extracted candidate are already penalized by L1 and do not enter L2.

Fields outside this vocabulary belong to optional supplements and never enter
formal L2.

### 3.1 Numeric comparison

Parse numeric strings after folding Unicode signs, removing leading
approximation marks, and removing thousands separators.

- `value_match`: relative difference is at most `1e-9`.
- `within_gold_error`: the extracted value lies within the gold uncertainty.
  For asymmetric uncertainty, use the upper error when the extracted value is
  higher and the lower error when it is lower.
- otherwise: `value_mismatch`.

Strict agreement includes exact and accepted cross-format coordinate matches.
Lenient agreement additionally includes `within_gold_error`. Stored extracted
uncertainties are validated and retained, but V5 does not score their numeric
agreement.

### 3.2 Units

Normalize spelling only; never convert dimensions or scale. The versioned
synonym table treats common printed spellings of `km/s`, `mas/yr`, degrees,
and identical base units as equal and removes harmless LaTeX markup residue.
Different normalized units produce `unit_mismatch`. If only one side has a
unit, compare the value and flag `unit_missing_one_side`.

### 3.3 Coordinates

Same-format coordinates compare after conversion to degrees. Decimal and
sexagesimal forms may match across formats when each axis is within 0.5
arcsec. This bridge absorbs printed rounding only; it is not permission for
the extractor to rewrite the paper's representation.

### 3.4 Limits and ranges

`limit_kind` must match. Exact values, upper limits, lower limits, and ranges
are semantically distinct. Ranges compare both bounds; one-sided limits
compare their reported bound. Never turn uncertainty bounds into a reported
range or invent a midpoint.

### 3.5 Probabilities

Bound and unbound probabilities normalize to fractions from zero to one. A
printed percent or a numeric magnitude above one is divided by 100 while its
printed form remains in supporting evidence. Do not derive complementary
probabilities. An explicit prose, caption, or note statement assigning one
condition to a complete table or named group may support each identifiable
member; a bare table cannot.

### 3.6 Historical projection

Read-only older artifacts may project `total_velocity` to
`galactic_rest_frame_velocity` for historical comparison when the specific
legacy scorer contract allows it. Such rows are flagged and reported both with
and without the projection. V3 core writers do not emit `total_velocity`, so
the projection is inactive for V5.

## 4. L2 aggregation

Report strict and lenient forms where applicable:

- agreement over compared rows;
- overall coverage: compared gold rows divided by all gold rows;
- matched-pair coverage;
- fill precision, with `ai_only` in the denominator;
- end-to-end delivery: matched rows divided by all gold rows;
- per-field coverage and agreement, including bound and unbound probability;
- paper bootstrap confidence intervals.

Also report row status counts and operational counts for real provider
attempts, tokens, elapsed time, format corrections, evidence corrections, and
tail-truncation rescue. Operational counts cover successful and failed papers.
They are diagnostics, not quality scores.

## 5. Supporting-evidence gate

Every non-null numeric component must carry valid direct evidence, with context
evidence where needed to establish identity, unit, frame, scenario, or group
condition. TeX is authoritative for meaning; mapped ECSV is an optional exact
row-and-column locator. Invalid or irrelevant evidence rejects the field before
L2. Evidence completeness, quotation similarity, and provenance quality do
not receive a separate score.

## 6. Interpretation

L1, L2, and delivery answer different questions and must remain visible
side-by-side. High precision on a small successful subset cannot compensate
for roster or field delivery failures. Formal outputs therefore never create a
single combined score or an automatic readiness decision.
