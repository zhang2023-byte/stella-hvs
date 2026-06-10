# Benchmark Metric Definitions

Formal definitions implemented in `src/stella_benchmark/metrics.py`. The scored
field registry is `src/stella_benchmark/field_specs.py`; keep this document in
sync with it.

## Candidate matching

A variant candidate matches a gold candidate using the same matcher as
cross-variant alignment:

1. **Tier 1 (gaia):** equal non-empty `identifiers.gaia_source_id`.
2. **Tier 2 (identifier overlap):** non-empty intersection of normalized
   `identifiers.all[].value` sets (casefold, collapse whitespace, strip leading
   `*` and brackets).

Matches are one-to-one, resolved greedily: tier-1 pairs first, then tier-2
pairs by descending identifier overlap. Unmatched variant candidates are false
positives; unmatched gold candidates are false negatives.

## Detection metrics (per variant)

- Per paper: TP = matched pairs, FP = |variant| − TP, FN = |gold| − TP.
- **micro P/R/F1** pooled over all manifest papers (papers with gold status
  `no_candidates` contribute FPs naturally).
- **macro F1**: mean per-paper F1 over papers with |gold| + |variant| > 0.
- **Paper status accuracy** and a confusion matrix over
  {candidates_found, no_candidates, other}.
- **No-candidate specificity**: among gold `no_candidates` papers, the fraction
  where the variant emitted zero candidates.
- 95% confidence intervals by bootstrap over papers (resample papers with
  replacement, 1000 reps, seeded).

## Field-level metrics (TP pairs only)

For each field in the registry, each pair is classified:

- `correct` — both present and matching;
- `wrong` — both present, not matching;
- `missing` — gold present, variant absent;
- `spurious` — variant present, gold absent.

Reported per field: accuracy = correct / (correct + wrong + missing);
conditional value accuracy = correct / (correct + wrong); hallucination rate =
spurious / (spurious + true-absent). Headline aggregate: micro accuracy over
all headline-field gold-present cells.

## Match predicates

- **Categorical / boolean** (`galactic_bound_claim`, `inclusion_basis`,
  `origin_type`, `paper_reassesses_unbound_status`): exact equality.
- **Label set** (`paper_labels`): exact set match for accuracy; Jaccard
  reported alongside.
- **Identifiers**: `gaia_source_id` exact; `paper_candidate_id` after
  normalization; `identifiers.all` exact set after normalization + Jaccard.
- **Quantity**: parse `value` to float; convert variant unit to gold unit via
  `astropy.units` with a v7 spelling alias table (`km s^-1`, `mas yr^-1`, …).
  Strict match: |v − g| ≤ max(abs_tol, 1e-6·|g|) — extraction should reproduce
  the published number exactly; the tolerance only absorbs float artifacts.
  Loose match (rel = 1e-2) is reported alongside to expose rounding/table
  mix-ups. Symmetric `error` is compared like a value; asymmetric errors
  require both `lower_error` and `upper_error` to match. `raw_value` is never
  scored.
- **Coordinates** (`ra`/`dec`, jointly): build `SkyCoord` per side from
  `coordinate_format` + `unit`; match if on-sky separation ≤ 1.0″ (0.1″ and 5″
  also reported). An unparseable side counts as `wrong`.
- **Citation fields**: `bibkey`, `arxiv_id`, `bibcode` exact after trim.
- `source_refs` are never scored (multiple valid refs can support one value).
- `candidate_groups_considered` is excluded from headline metrics.

## Adjudication-derived statistics

- Correction provenance: per variant, the fraction of gold items produced by
  accept / accept_variant / fix / reject / add_missing verdicts.
- Consensus audit: expert confirmation rate on spot-checked consensus items →
  estimated consensus error rate with a binomial confidence interval.
- Inter-expert agreement (when two adjudication sets exist for the same
  `alignment_digest`): Cohen's κ over verdict labels keyed by `item_id`,
  separately for presence and field items, plus raw percent agreement.
