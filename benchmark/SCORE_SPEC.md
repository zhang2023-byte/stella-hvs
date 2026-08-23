# HVS Extraction Score Specification

Status: **APPROVED v2.0.0 (2026-08-03)**.

This document owns the L0, L1, and L2 scoring decisions presented to human
users. It defines no composite score or automatic pass/fail threshold.
Supporting evidence is an acceptance requirement for extracted values, not a
metric. API cost is operational metadata beside the layers and never enters a
quality score.

## 1. Evaluation population and delivery

Scoring uses the paper order frozen in the current campaign and a public,
value-free, immutable gold selection profile. The profile selects exactly one
manifest-pinned expert YAML/JSON twin for every paper in the split. Missing,
duplicate, changed, or mismatched selections fail the whole evaluation before
any score is written; the scorer never chooses by filename order or falls back
to another expert. Public scorecards contain only aggregate counts, rates,
paper IDs needed for delivery accounting, and provenance hashes. Candidate-level
identities, values, notes, matching rows, and evidence comparisons are private.

Reports compare only scorecards bound to the same selection profile. A future
cross-expert sensitivity analysis requires a separate, explicitly labeled
reporting contract.

An annotation assignment profile may nominate the intended primary expert
before annotation, but it is not itself scoring input. Formal scoring remains
bound only to the later selection profile and its manifest-pinned twin hashes.

L0 reports single-run delivery and structural validity before scientific
quality:

- roster delivery: `complete`, `failed`, or `missing`;
- core-field delivery: `complete`, `partial`, `failed`, or `missing`, plus
  candidate counts for completed and failed field extraction.

A successful roster followed by field failure still exposes its credible
candidates to L1. Its unavailable fields count as missing in L2 and the paper
is partial. A roster failure on a negative paper is a delivery failure; it
must never be reinterpreted as a correct empty roster.

### 1.1 L0 delivery

Roster delivery partitions every expected paper into `complete`, `failed`, or
`missing`. Core-field delivery partitions every expected paper into
`complete`, `partial`, `failed`, or `missing`. The partitions are mutually
exclusive, preserve campaign order, and cover the split exactly.

`delivery_rate` is complete roster papers divided by expected papers.
`full_delivery_rate` is complete core-field papers divided by expected papers.
`usable_delivery_rate` is complete plus partial core-field papers divided by
expected papers. A failed negative roster is never counted as an empty result.

### 1.2 L0 format validation

One format unit is one roster slot or one candidate core-field logical call.
Every unit is classified exactly once:

- `valid_first_pass`: the first structured response passes structure and
  schema validation; a later evidence correction does not change this class;
- `valid_after_correction`: format correction ends in an accepted response;
- `invalid`: the format-repair budget is exhausted or the correction remains
  invalid;
- `not_observed`: transport or pre-request failure leaves no structured
  response to validate.

`observed_units` excludes `not_observed`. First-pass and final-valid rates both
use `observed_units` as their denominator. Delivery separately penalizes units
that were never observed. Corrupted or unsealed runs fail the integrity gate
and produce no scorecard.

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
uncertainties are validated and retained, but V6 does not score their numeric
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
the projection is inactive for V6.

## 4. L2 aggregation

Report strict and lenient forms where applicable:

- agreement over compared rows;
- overall coverage: compared gold rows divided by all gold rows;
- matched-pair coverage;
- fill precision, with `ai_only` in the denominator;
- end-to-end delivery: matched rows divided by all gold rows;
- per-field coverage and agreement, including bound and unbound probability;
- paper bootstrap confidence intervals.

Operational telemetry is reported outside L2. It covers every real provider
attempt, including retries and format or evidence corrections, and aggregates
prompt, cached input, uncached input, completion, reasoning, and total tokens
by roster and core-field role. Reasoning tokens are a completion-token subset
and are not charged twice.

Estimated API cost uses one immutable TokenDance CNY pricing snapshot and
`Decimal` arithmetic. Missing route coverage fails scoring preflight. Missing
provider usage leaves cost explicitly partial or unavailable rather than zero.
Cost is reported under `operations.estimated_api_cost`; it is not a billing
claim and never changes L0, L1, or L2.

## 5. Supporting-evidence gate

Every non-null numeric component must carry valid direct evidence, with context
evidence where needed to establish identity, unit, frame, scenario, or group
condition. TeX is authoritative for meaning; mapped ECSV is an optional exact
row-and-column locator. Invalid or irrelevant evidence rejects the field before
L2. Evidence completeness, quotation similarity, and provenance quality do
not receive a separate score.

## 6. Interpretation

L0, L1, and L2 answer different questions and must remain visible
side-by-side. High precision on a small successful subset cannot compensate
for roster or field delivery failures. Formal outputs therefore never create a
single combined score or an automatic readiness decision.

## 7. Pre-campaign contribution-first scoring contract

This section describes the implemented-but-not-formal scoring mechanics for the
contribution-first `literature_hvs_contributions` v1 family
(`benchmark.hvs_contribution_annotation` gold, `benchmark.hvs_contribution_scorecard`
public aggregates, `benchmark.hvs_contribution_scoring_details` private rows).
It is a separate scientific target: contribution scores are never comparable
with the V6 scores above, no campaign is bound to it, and no formal
contribution score exists yet. The original 50-paper AI-assisted gold migration
produces calibration/regression material only. Formal activation requires a
new unseen sample, its separately approved non-preannotation gold protocol,
and a new frozen campaign.

Layers, reported separately with no composite and no pass/fail verdict:

- **L0** — paper delivery, schema/format validity of the contribution
  document, and per-object measurement delivery
  (`measurements_complete` versus `measurement_extraction_failed`).
- **L1a** — paper-object contribution identity precision, recall, and F1 via
  the same stable identity matching as V6 (names, Gaia ids, bridged
  coordinates).
- **L1b** — `contribution_type` accuracy and confusion counts on L1a-matched
  objects only.
- **L2a** — `paper_boundness.status` coverage, accuracy, and confusion;
  every unmatched gold object propagates its status and all its measurement
  values to `gold_only`.
- **L2b** — multivalue measurement coverage and agreement. Within each
  L1a-matched object and field, gold and AI values are unordered multisets
  matched by a deterministic bipartite assignment that optimizes
  lexicographically: maximum paired values, then maximum strict agreement,
  then maximum lenient agreement, with deterministic value fingerprints as
  the final tie-break. The comparison ladder reuses the V6 numeric,
  probability, coordinate, unit, limit, and uncertainty rules unchanged.
  `condition_note`, `notes`, and array position are never matching keys.
  Unmatched gold values are `gold_only`; unmatched AI values are `ai_only`.
- **Diagnostics** — on matched value pairs only: `paper_preferred`
  agreement and `source` category agreement. A wrong preference or provenance
  never changes the value match itself.
- **Note/evidence audit** — required `contribution_note` presence and
  `contribution_evidence` presence on matched objects. Presence is audited;
  note wording is never scored as text.

Public contribution scorecards contain aggregates, rates, and input hashes
only. Candidate identities, notes, values, citations, and per-item
comparisons remain in the private details artifact. There is no composite
score and no pass/fail quality verdict in this contract either.
