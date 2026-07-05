# Benchmark L2 Value-Scoring Specification

Status: **DRAFT v0.2-rc1 for rule-by-rule expert review (2026-07-06)** — not
yet implemented. The current scorer ships a "diagnostic draft" L2
(`l2_draft` in `stella.benchmark_scorecard.v0.1`); once every rule below is
approved, the scorer implements this contract as a formal `l2` block and the
scorecard schema bumps to `stella.benchmark_scorecard.v0.2`. Each rule
records its rationale and, where relevant, the open judgment that needs the
expert's sign-off (marked **JUDGMENT**).

Foundational principle (inherited from `benchmark/GUIDELINE.md` and
`docs/schema-v0.2-notes.md`): both gold and AI record the paper's **printed
value and unit verbatim** — L2 never converts physical quantities. The
normalizer only reconciles *spellings* of the same printed content.

## R1 — Comparison surface (one-sided, gold-driven)

For every matched candidate pair (L1 output), compare **each gold
`quantities[]` entry** against the AI candidate's same dotted field under
`core.*`. AI-only values are never penalized: the guideline instructs
experts to *prioritize* five key fields, so gold absence does not certify
paper absence. Spurious-value detection is deferred to L3 evidence checks.

Statuses per gold quantity: `value_match`, `value_match_cross_format` (R5),
`within_gold_error` (R3), `value_mismatch`, `unit_mismatch` (R4),
`limit_kind_mismatch` (R6), `gold_only` (AI field empty), plus boolean flags
`projected_from_total_velocity` (R2) and `unit_missing_one_side` (R4).

## R2 — Field projection (scorer-owned, per docs/schema-v0.2-notes.md)

- `derived_kinematics.galactic_rest_frame_velocity`: use the AI's same
  field; when empty, fall back to `derived_kinematics.total_velocity`,
  flagged `projected_from_total_velocity`. Aggregates are reported **with
  and without** projected rows so the projection can never silently carry a
  headline number. **JUDGMENT (R2a)**: keep this pragmatic unconditional
  fallback (recommended; frame verification from method_chain text is
  unreliable, and the flag preserves auditability), or restrict projection
  to candidates whose method_chain shows an explicit Galactic-frame step.
- `inclusion_assessment.galactic_bound_claim` is AI-only and never enters
  L1 or L2 (already enforced).
- No other cross-field projection in this version.

## R3 — Numeric equality ladder

1. Parse both `value` fields as floats after Unicode sign normalization.
2. `value_match`: relative difference ≤ 1e-9.
3. `within_gold_error`: |gold − ai| within the gold uncertainty —
   symmetric `error` when present; otherwise the **directional** asymmetric
   bound (`upper_error` when ai > gold, `lower_error` when ai < gold). The
   draft ignored asymmetric errors; formal L2 uses them.
4. Otherwise `value_mismatch`.

Headline metrics (R9) report **strict agreement** (`value_match` +
`value_match_cross_format` only) and **lenient agreement** (strict +
`within_gold_error`) separately. **JUDGMENT (R3a)**: confirm that
`within_gold_error` belongs in the lenient tier only, not in the headline
strict rate (recommended: yes — an AI quoting a different printed estimate
that happens to sit inside the error bar is not the same transcription).

## R4 — Units (spelling normalization only, no conversion)

- Canonical synonym table (extendable, versioned with the scorer):
  `km/s` = {km/s, km s^-1, km s-1, km s⁻¹, kms^-1, km/sec};
  `mas/yr` = {mas/yr, mas yr^-1, mas yr-1, mas yr⁻¹, mas/year};
  `deg` = {deg, degree, degrees, °}; identity for mas/pc/kpc/mag/dex and
  free-text transformed forms (`log(D/kpc)` etc.).
- Probability fields are compared unit-free after R7 normalization.
- `unit_mismatch` only when **both** sides carry units that normalize
  differently. One-sided missing unit compares values and sets
  `unit_missing_one_side`.
- **No dimensional conversion** (pc↔kpc, mas↔arcsec): both sides transcribe
  the same printed table, so a scale disagreement means one side
  mis-transcribed — that is exactly what L2 must count as `unit_mismatch`.
  **JUDGMENT (R4a)**: confirm no-conversion (recommended), or allow
  same-dimension scale conversion as a flagged lenient match.

## R5 — Coordinates (cross-format bridge)

RA/Dec may legitimately differ in *format* between the two views of the
same paper (PDF prints sexagesimal; the ECSV pipeline often holds decimal
degrees). Comparison ladder:

1. Same format: normalized text equality (Unicode minus, internal
   whitespace) for sexagesimal; R3 ladder for decimal.
2. Cross-format: convert **both** to degrees (gold converter already exists
   in `stella.benchmark.gold`; AI side uses `coordinate_format`/`unit`) and
   accept separations ≤ **0.5 arcsec** as `value_match_cross_format`.
3. Otherwise `value_mismatch`.

This is a *format* bridge, not a value conversion: 0.5 arcsec only absorbs
sexagesimal rounding at the printed precision. **JUDGMENT (R5a)**: confirm
the 0.5 arcsec bridge tolerance (recommended), or set a different value.

## R6 — Limits and ranges

- `limit_kind` must agree exactly; `range` compares both bounds with the R3
  ladder (draft used exact equality only); one-sided limits compare the
  bound value with R3 and require the same `limit_kind`.
- Disagreeing kinds → `limit_kind_mismatch` (a value that matches
  numerically but flips exact↔lower_limit is a semantic error, not a match).

## R7 — Probabilities

Bound/unbound probabilities normalize to 0–1 fractions on both sides
(`%` in unit or raw_value, or value > 1, divides by 100 — matching the gold
GUIDELINE's one allowed normalization). Origin-hypothesis metrics are out of
scope (not scored fields).

## R8 — Multi-estimate "pick one" disagreements

When the paper prints several estimates for one quantity, gold records the
fewest-assumption value; the AI's single slot may hold a different printed
estimate. Formal L2 counts this as `value_mismatch` by default. The
adjudication overlay (`benchmark/scoring/adjudications/<arxiv_id>.yaml`) may
reclassify specific rows to `alternative_printed_value`, which leaves the
strict rate but is reported as its own count. No automatic detection —
reclassification requires a human reading the paper. **JUDGMENT (R8a)**:
confirm this default-mismatch + manual-overlay design (recommended), or
count alternatives as lenient matches automatically (risks rewarding
wrong-row transcription).

## R9 — Aggregation

- Per-field table over the 23 scored fields: counts of every status.
- Coverage: `compared / gold_quantities`, reported over **all gold
  quantities on positive papers** (L1 misses propagate as `gold_only` on
  unmatched gold candidates — headline coverage deliberately couples to L1
  recall) and, separately, over matched pairs only.
- Strict and lenient agreement rates (R3), each with and without projected
  rows (R2), micro over quantities, macro over papers, sampling-weight
  weighted micro, and the same paired paper-level bootstrap CI machinery as
  L1 (seed 20260706).

## R10 — Schema and process

- Scorecard schema bumps to `stella.benchmark_scorecard.v0.2`: `l2_draft`
  is replaced by the formal `l2` block carrying the R9 aggregates plus the
  scorer-config echo (synonym-table version, bridge tolerance, projection
  mode). Private details keep per-row statuses.
- Tests: synthetic fixtures only (contamination rule — never real gold),
  one fixture per rule above, including a sexagesimal-vs-decimal regression
  modeled on the dec mismatch observed in the first dev round.
- The comparison dashboard and this spec stay consistent; disagreements
  between them resolve in favor of this spec once approved.

## Review checklist for the expert

- [ ] R2a projection fallback: pragmatic-with-flag vs frame-verified
- [ ] R3a within_gold_error stays lenient-only
- [ ] R4a no dimensional conversion
- [ ] R5a 0.5 arcsec cross-format bridge
- [ ] R8a pick-one default mismatch + manual overlay
- [ ] Any field-specific rules to add before implementation
