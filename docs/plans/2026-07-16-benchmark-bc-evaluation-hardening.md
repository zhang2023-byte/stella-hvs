# Benchmark B/C Evaluation Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make Method B/C candidate extraction scientifically reliable and formally reproducible without paper-specific patches or enrichment-driven delivery loss.

**Architecture:** Put one bounded, independent scientific review before the candidate roster is sealed, then make the sealed roster the immutable input to both task surfaces within a method. Use `core_prov` as the formal scored product; treat FULL enrichment as a separately validated diagnostic. Keep deterministic normalization shared, pure, and restricted to representation.

**Tech Stack:** Python 3.12, Pydantic, JSON/YAML workflow contracts, `unittest`, the existing frozen validator and campaign scorer.

---

## Evidence and decision

The corrected 10-paper formal-dev evaluation is diagnostic rather than a winner-selection result. C CORE delivered the most papers and the greatest L1/L2 coverage, while one positive paper contributed nearly all of its false positives. B CORE and C FULL had perfect conditional precision only because one positive paper produced matched candidates. B FULL delivered no matched candidate. Paper-bootstrap confidence intervals overlap widely.

The implementation therefore targets three observed failure boundaries:

1. Candidate membership is currently cached and frozen before an independent reviewer can correct it.
2. FULL enrichment and provenance defects can erase otherwise usable scored-core output.
3. Scoring and sealing can drift from the code recorded by an old run.

Do not add paper IDs, object names, table-specific thresholds, or regexes for scientific inclusion. Do not change the multi-model possibly-unbound boundary or private gold until expert adjudication is complete.

## Target data flow

```text
paper context
  -> method-specific roster producer
  -> one independent roster-only review
  -> at most one roster revision
  -> sealed roster bundle + hash
       -> CORE fill -> core validation -> field/evidence review -> scoreable core
       -> optional FULL enrichment -> enrichment validation -> diagnostic product
```

The reviewer may change membership only before the roster hash is created. After sealing, no scaffold, candidate filler, repair loop, final reviewer, or normalizer may add, delete, reorder, or rename candidates.

## Task 0: Preserve the scorer correction already established by evaluation

**Files:**
- Modify: `src/stella/benchmark/identity.py`
- Modify: `src/stella/benchmark/scoring.py`
- Test: `tests/test_benchmark_identity.py`
- Test: `tests/test_benchmark_scoring.py`

**Step 1:** Keep a synthetic failing test showing that ASCII hyphen and Unicode dash/minus variants of one paper-visible name normalize identically.

**Step 2:** Keep name normalization limited to separator folding. It must not transliterate letters, change digits, infer aliases, or use coordinates.

**Step 3:** Keep the R4 degree synonym set exactly equal to the frozen L2 specification. Do not import the broader coordinate-parser vocabulary into scoring.

**Step 4:** Run:

```bash
conda run -n stella-env python -m unittest tests.test_benchmark_identity tests.test_benchmark_scoring
```

Expected: all identity/scoring tests pass.

**Step 5:** Before publication, release this unchanged-rule scorer fix with explicit correction provenance. Never overwrite a published scorecard in place.

## Task 1: Make formal sealing and scoring fail closed on provenance drift

**Files:**
- Modify: `src/stella/benchmark/run_contract.py`
- Modify: `src/stella/benchmark/dev_console_evaluation.py`
- Modify: `src/stella/benchmark/scoring.py`
- Modify: `src/stella/schema_registry.py`
- Modify: `scripts/seal_benchmark_run.py`
- Test: `tests/test_benchmark_run_contract.py`
- Test: `tests/test_benchmark_dev_console_groups.py`
- Test: `tests/test_benchmark_formal_scoring.py`
- Regenerate: `docs/versions.md`

**Step 1:** Write a test in which `run_config.json` records validator hash `A` while the current validator hash is `B`.

**Step 2:** Require sealing to fail with a short provenance-mismatch error before reading paper outputs. Do not silently validate an old run with current code.

**Step 3:** Write a test showing that a new evaluation ID writes to its own immutable scorecard directory and can name a superseded local evaluation without deleting it.

**Step 4:** Add scorer, identity-normalizer, and unit-table hashes to the formal scorecard provenance. Follow `docs/versioning-policy.md` for the required scorecard schema transition and patch release.

**Step 5:** Make the dev console score only already sealed runs or runs whose recorded validator matches the active validator exactly.

**Step 6:** Run the three targeted test modules, then the full suite.

## Task 2: Move scientific roster review before the seal

**Files:**
- Modify: `src/stella/benchmark/roster_bundle.py`
- Modify: `src/stella/benchmark/extraction_review.py`
- Modify: `src/stella/benchmark/extraction_run.py`
- Modify: `src/stella/benchmark/agentic_run.py`
- Test: `tests/test_benchmark_roster_bundle.py`
- Test: `tests/test_benchmark_extraction.py`
- Test: `tests/test_benchmark_agentic.py`

**Step 1:** Write a test where a producer over-includes a roster member and the roster reviewer removes it before bundle hashing.

**Step 2:** Write a test proving that the reviewer gets each candidate's `inclusion_anchor`, including its paper-text source references.

**Step 3:** Define one compact roster-review payload: overall decision, membership challenges, and a corrected roster only when needed. Keep the existing `hvs_roster` scientific rules as the only rule source.

**Step 4:** Permit at most one roster revision. Validate the revised roster with `roster_structure_errors`, then compute and persist the final bundle hash.

**Step 5:** Include reviewer model, reviewer prompt hash, and reviewer rule hash in the roster cache key. A bundle created under a different reviewer contract must not be a cache hit.

**Step 6:** Change `roster_stubs()` or the downstream prompt envelope so the sealed inclusion anchors remain visible to field generation and final evidence review without becoming mutable candidate fields.

**Step 7:** Keep the final reviewer field/evidence-only. Reject any post-seal membership mutation in both B and C.

**Step 8:** If the one-pass roster reviewer remains unstable on dense papers, replace only that reviewer with a stronger model. Do not add a second reviewer, paper-specific examples, or additional repair loops.

## Task 3: Make CORE the formal product and FULL an enrichment diagnostic

**Files:**
- Modify: `src/stella/benchmark/task_surfaces.py`
- Modify: `src/stella/benchmark/run_contract.py`
- Modify: `src/stella/benchmark/scoring.py`
- Modify: `src/stella/benchmark/dev_console.py`
- Modify: `benchmark/console/src/pages/RunPage.tsx`
- Test: `tests/test_extraction_task_surfaces.py`
- Test: `tests/test_benchmark_run_contract.py`
- Test: `tests/test_benchmark_formal_scoring.py`

**Step 1:** First make new formal B/C comparisons use `core_prov` only. Keep existing FULL runs as historical diagnostics.

**Step 2:** If FULL remains a maintained product, write a test where core is valid and enrichment is invalid. The manifest must report `core_valid` and `enrichment_invalid`; the scorer must consume the core document.

**Step 3:** Keep core identity, inclusion, 19 scored quantities, source evidence, and minimum method lineage blocking. Make non-scored enrichment findings non-blocking for L1/L2 only.

**Step 4:** Report core delivery and enrichment delivery separately in the console. Never collapse them into one success rate.

**Step 5:** Do not implement this split by deleting validation. Retain strict FULL validation for the enrichment product.

## Task 4: Shrink deterministic normalization to a shared mechanical boundary

**Files:**
- Modify: `src/stella/benchmark/extraction_run.py`
- Modify: `src/stella/benchmark/agentic_run.py`
- Create only if reuse is clear: `src/stella/benchmark/mechanical_normalization.py`
- Test: `tests/test_benchmark_extraction.py`
- Test: `tests/test_benchmark_agentic.py`

**Step 1:** Add tests proving that normalization is idempotent and identical for B/C.

**Step 2:** Snapshot candidate count, record IDs, scientific values, units, limit kinds, and inclusion decisions before normalization; assert they are unchanged afterward.

**Step 3:** Permit only unambiguous representation cleanup such as coordinate punctuation and exact code-owned identifier propagation.

**Step 4:** Remove semantic bibliography selection and any regex that decides which citation or scientific claim is correct. Return those failures to the model/reviewer or report them as limitations.

## Task 5: Fix the general quantity representation rule without value-specific patches

**Files:**
- Modify: `skills/hvs-candidates-extraction/rules/generic-quantity.yaml`
- Regenerate: generated skill and benchmark rule views with `scripts/generate_extraction_rule_views.py`
- Test: `tests/test_extraction_rules.py`
- Test: `tests/test_hvs_candidates_validation.py`

**Step 1:** Add one general sentence to `generic.quantity.uncertainty_limits`: uncertainty bounds around a central measurement are not a reported closed range and must never be converted into `range_lower`/`range_upper`.

**Step 2:** Keep the existing validator invariant: a true range has empty `value` plus both explicit bounds; a measurement has `value` plus optional error fields.

**Step 3:** Regenerate rule views rather than editing generated blocks.

**Step 4:** Do not change `generic.quantity.multiple_estimates`; the observed alternative-estimate disagreement is legitimate and rare.

## Task 6: Complete expert scientific adjudication outside the extraction runs

**Files:**
- Potentially modify after expert decision: `skills/hvs-candidates-extraction/rules/hvs-science.yaml`
- Regenerate after a rule change: generated rule views
- Use for private correction: the existing `benchmark_gold_annotation_form` workflow
- Follow: `docs/versioning-policy.md`

**Step 1:** Have the expert correct the flagged gold completeness finding through the human annotation workflow. Do not let an extraction agent write gold.

**Step 2:** Ask the expert to decide the general multi-model boundary: whether a paper that retains a reasonable unbound/borderline scenario but does not confirm an HVS remains inside “possibly unbound.”

**Step 3:** If the answer changes gold scientific judgments, annotation protocol, or candidate inclusion meaning, create a new campaign. Do not mutate `hvs-extraction-v2` or reinterpret its test split.

**Step 4:** Keep the current object-level prose-anchor rule. The dense-table over-extraction is a failure to apply the existing rule, not evidence that another paper-specific rule is needed.

## Task 7: Run a preregistered validation sequence

**Files:**
- Modify only if execution contract changes: `workflows/definitions/benchmark_extraction_run.yaml`
- Output: campaign-scoped run archives and local scorecards

**Step 1:** Freeze code, rule profiles, gold snapshot, scorer hashes, models, temperature, budgets, and cache policy before the next formal run.

**Step 2:** Run a cache-hit repeat to test downstream surface/reviewer/validator stability.

**Step 3:** Run a second repeat with an isolated roster cache root. Report exact roster-set agreement per paper; a cache hit must never be presented as evidence of roster repeatability.

**Step 4:** Run the full 10-paper formal-dev B CORE/C CORE matrix only after Tasks 1–6 are frozen. Do not score the historical regression groups.

**Step 5:** Accept the architecture only if core delivery is complete or every exception is an explicit external failure, negative-paper false positives do not regress, dense-paper roster errors materially fall, and no new value/unit mismatch class appears.

**Step 6:** If one roster reviewer with a stronger model still fails the cold-cache repeat, document candidate-boundary instability as a current model limitation. Do not add more prompt rules.

**Step 7:** Keep the 40-paper test split sealed until the dev architecture and release contract are preregistered.

## Out of scope

- Paper-specific inclusion rules or name maps.
- More reviewer rounds or unbounded tool budgets.
- Using matched-pair L2 agreement alone as a headline quality metric.
- Re-scoring regression-only groups.
- Automatically changing private gold from AI findings.
