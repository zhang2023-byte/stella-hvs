# Benchmark L2 Value-Scoring Specification

Status: **APPROVED v0.2 (2026-07-06)** — every rule below was reviewed and
signed off rule-by-rule by the expert on 2026-07-06 (R1 amended, R2a/R3a/
R4a/R5a decided, R8 redesigned without an adjudication overlay, R9 extended
with the layering clause). The scorer implements this contract as the formal
`l2` block in `stella.benchmark_scorecard.v0.2`, replacing the retired
`l2_draft` diagnostic.

Foundational principle (inherited from `benchmark/GUIDELINE.md` and
`docs/schema-v0.2-notes.md`): both gold and AI record the paper's **printed
value and unit verbatim** — L2 never converts physical quantities. The
normalizer only reconciles *spellings* of the same printed content.

## R1 — Comparison surface (gold-driven rows plus hallucination audit)

For every matched candidate pair (L1 output), compare **each gold
`quantities[]` entry** against the AI candidate's same dotted field under
`core.*`.

Gold is **exhaustive over the scored vocabulary**: the guideline requires
the expert to record every scored field the paper reports (the scribe makes
transcription cheap), so an absent gold field asserts the paper does not
report that quantity. Therefore, within the 23 scored fields, an AI value
with no gold counterpart is presumed hallucinated and recorded as
**`ai_only`** — it counts against the fill-precision metric (R9). There is
**no adjudication overlay**: if an `ai_only` row turns out to be an expert
omission, the fix is to correct the gold annotation itself and re-score
(single source of truth).

Fields outside the scored vocabulary (photometry, spectroscopy, stellar
parameters, `derived_kinematics.total_velocity` itself) never enter L2.
Quantities on unmatched AI candidates (L1 false positives) do not enter L2
either — they are already penalized by L1 precision.

Statuses per row: `value_match`, `value_match_cross_format` (R5),
`within_gold_error` (R3), `value_mismatch`, `unit_mismatch` (R4),
`limit_kind_mismatch` (R6), `gold_only` (AI field empty), `ai_only` (R1),
plus boolean flags `projected_from_total_velocity` (R2),
`unit_missing_one_side` (R4), and `gold_note_present` (R8).

## R2 — Field projection (scorer-owned, per docs/schema-v0.2-notes.md)

- `derived_kinematics.galactic_rest_frame_velocity`: use the AI's same
  field; when empty, fall back to `derived_kinematics.total_velocity`,
  flagged `projected_from_total_velocity`. Aggregates are reported **with
  and without** projected rows so the projection can never silently carry a
  headline number. In the "without" view a projected row counts as
  `gold_only`. **Decided (R2a)**: unconditional fallback — frame
  verification from method_chain free text is unreliable; the flag plus the
  dual aggregates preserve auditability.
- The projection applies to the gold-driven direction only. An AI
  `total_velocity` with no gold `galactic_rest_frame_velocity` row is *not*
  `ai_only`: the gold vocabulary deliberately excludes whole speeds whose
  Galactic rest frame is not stated, so gold absence there does not certify
  paper absence.
- `inclusion_assessment.galactic_bound_claim` is AI-only and never enters
  L1 or L2 (already enforced).
- No other cross-field projection in this version. When the schema v0.2
  revision removes `derived_kinematics.total_velocity` from the AI surface,
  this rule becomes a no-op for new runs and remains only for scoring
  archived v0.1 runs.

## R3 — Numeric equality ladder

1. Parse both `value` fields as floats after normalization: Unicode
   sign folding, leading approximation markers (`~`, `≈`, `∼`) stripped,
   thousands-separator commas removed. (Gold forbids these characters; the
   AI side may transcribe them verbatim — they do not change the printed
   number.)
2. `value_match`: relative difference ≤ 1e-9.
3. `within_gold_error`: |gold − ai| within the gold uncertainty —
   symmetric `error` when present; otherwise the **directional** asymmetric
   bound (`upper_error` when ai > gold, `lower_error` when ai < gold). The
   draft ignored asymmetric errors; formal L2 uses them.
4. Otherwise `value_mismatch`.

**Decided (R3a)**: headline metrics (R9) report **strict agreement**
(`value_match` + `value_match_cross_format` only) and **lenient agreement**
(strict + `within_gold_error`) separately. `within_gold_error` never enters
the strict tier — an AI quoting a different printed estimate that happens
to sit inside the error bar is not the same transcription.

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
- **Decided (R4a): no dimensional conversion** (pc↔kpc, mas↔arcsec): both
  sides transcribe the same printed table, so a scale disagreement means
  one side mis-transcribed (usually the AI converting instead of copying) —
  that is exactly what L2 must count as `unit_mismatch`.

## R5 — Coordinates (cross-format bridge)

RA/Dec may legitimately differ in *format* between the two views of the
same paper (PDF prints sexagesimal; the ECSV pipeline often holds decimal
degrees). Comparison ladder:

1. Same format: both sides are converted to degrees (gold via
   `stella.benchmark.gold._coordinate_value_degrees`; AI via its declared
   `coordinate_format`, falling back to the same unit heuristic) and
   compared with the R3 exact rung.
2. Cross-format: convert **both** to degrees and accept per-axis absolute
   differences ≤ **0.5 arcsec** as `value_match_cross_format` (counted in
   the strict tier). RA differences are compared without a cos(dec)
   correction, which only makes the bridge stricter.
3. Otherwise `value_mismatch`.

This is a *format* bridge, not a value conversion: 0.5 arcsec only absorbs
sexagesimal rounding at the printed precision. **Decided (R5a)**: bridge
tolerance is 0.5 arcsec.

## R6 — Limits and ranges

- `limit_kind` must agree exactly (empty string means a plain measurement);
  disagreeing kinds → `limit_kind_mismatch` outright — a value that matches
  numerically but flips exact↔lower_limit is a semantic error, not a match.
- `range` rows compare both bounds with the R3 ladder; one-sided limits
  compare the bound value with R3 under the same `limit_kind`.

## R7 — Probabilities

Bound/unbound probabilities normalize to 0–1 fractions **on both sides**
(`%` in unit or raw_value, or |value| > 1, divides by 100 — matching the
gold GUIDELINE's one allowed normalization). This is the specification's
only numeric normalization exception; it exists because the gold guideline
itself licenses percent→fraction transcription, so both spellings coexist
legitimately. Origin-hypothesis metrics are out of scope (not scored
fields).

## R8 — Multi-estimate "pick one" disagreements

When the paper prints several estimates for one quantity, gold records the
fewest-assumption value (per GUIDELINE §6) and lists the alternatives in
the quantity `notes`; the AI's single slot may hold a different printed
estimate. **Decided (R8a, redesigned)**:

1. Formal L2 counts a different printed estimate as `value_mismatch` — no
   free pass, and **no adjudication overlay** (the draft's
   `benchmark/scoring/adjudications/` design is dropped).
2. Every row carries a `gold_note_present` flag. A `value_mismatch` with a
   gold note is the triage signature of a pick-one disagreement; the
   private details and the HTML report surface the note text so a human can
   separate selection disagreements from real transcription errors at a
   glance.
3. The remedy is prompt-side, not scorer-side: the shared task
   clarifications inject the same fewest-assumption selection rule into
   both extraction pipelines (versioned prompt change).

## R9 — Aggregation and layering

Row population. Three sources feed the aggregates:

1. matched pairs: gold-driven rows (R1) plus `ai_only` rows;
2. unmatched gold candidates on positive papers: every gold quantity
   becomes `gold_only` (L1 misses propagate — headline coverage
   deliberately couples to L1 recall);
3. papers whose AI output is missing entirely: as (2).

Rates (each computed strict and lenient, and with/without projected rows):

- **agreement_over_compared** = strict (or lenient) matches / compared
  rows, where compared = gold-driven rows the AI filled. Pure transcription
  accuracy on found stars; independent of L1.
- **coverage** = compared / gold quantities — reported end-to-end (all
  gold quantities on positive papers) and matched-pairs-only.
- **delivery_end_to_end** = strict (or lenient) matches / all gold
  quantities on positive papers. The user-facing composite: "of everything
  the papers report for true candidates, how much did the method deliver
  correctly?"
- **fill_precision** = strict (or lenient) matches / (compared + ai_only).
  The hallucination-sensitive precision from the R1 amendment.

Each rate is reported micro (pooled over quantities), macro (mean of
per-paper rates), and sampling-weight weighted micro, plus a per-field
status table over the 23 scored fields and paper-level bootstrap CIs
(paired with L1: same seed 20260706, same resample unit).

**Layering clause (approved)**: the benchmark reports three headline
numbers side by side — L1 micro F1 (finding stars),
`agreement_over_compared` strict (transcribing found stars), and
`delivery_end_to_end` strict (composite output quality).
**L1 and the end-to-end L2 rate must never be combined into a single
composite score**: delivery_end_to_end already embeds L1 recall, so any
weighted sum would count the same miss twice. There is no single fused
benchmark score by design.

## R10 — Schema and process

- Scorecard schema is `stella.benchmark_scorecard.v0.2`: `l2_draft` is
  replaced by the formal `l2` block carrying the R9 aggregates plus the
  scorer-config echo (synonym-table version, bridge tolerance, projection
  mode, probability normalization, bootstrap seed). The public scorecard
  stays counts-and-rates only.
- Private details (`stella.benchmark_scoring_details.v0.2`) keep per-row
  statuses **with the gold and AI display values and gold note text**; they
  are written next to the external gold store, never inside the workspace.
- The human-readable comparison view is generated **from the scorer's own
  outputs** by `scripts/build_benchmark_report.py` (it replaced the
  standalone `benchmark/comparison/build_gold_ai_comparison.py`, which
  duplicated matching logic). The report covers every scored run —
  including method A (legacy skill-agent extractions under `literature/`),
  method B (direct-API pipeline), and method C (agentic pipeline) — side by
  side, and is written to the private repository next to the gold store.
- Tests: synthetic fixtures only (contamination rule — never real gold),
  at least one fixture per rule above, including a sexagesimal-vs-decimal
  regression modeled on the dec mismatch observed in the first dev round.
- Disagreements between any rendered view and this spec resolve in favor
  of this spec.
