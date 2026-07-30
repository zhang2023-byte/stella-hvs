# Benchmark Implementation Status

Status owner: current benchmark implementation, observed development results,
known defects, and the next engineering gate. Update this file whenever the
active campaign, current result, implementation blocker, or next gate changes.

## Current state

Stella 0.7.0 promotes the staged roster-plus-core-field extractor to the
canonical `hvs_candidate_extraction` workflow. `hvs-extraction-v5` is the only
writable campaign. It mechanically inherits V4's 50-paper order, fixed
10-development/40-test split, and gold hash without resampling.

V5 is in **development hardening** and is **not test-ready**. V1-V4 remain
readable history. The 25 pre-promotion experimental runs and their logs,
evaluations, diagnostics, probes, locks, and file hashes are preserved in the
read-only `hvs-extraction-scratch-legacy` campaign and cannot enter V5 scores.

The canonical deliverable is a v3 core artifact. It keeps a successful roster
even when field extraction fails, so candidate identity remains available to
L1 and the missing fields are visible in L2. Full-field and method-chain work
are separate supplements bound to an immutable core hash; no real supplement
model adapter is registered yet.

The independent comparison path is `coding_agent_baseline`. It receives the
same archived paper boundary, science rules, and v3 output contract, but does
not reuse staged intermediate artifacts.

## Latest development evidence

The last pre-promotion dev10 run completed and was scored:

| Measure | Result |
|---|---:|
| Paper delivery | 6 / 10 |
| L1 precision / recall / F1 | 0.941 / 0.681 / 0.790 |
| L2 delivered rows / gold rows | 20 / 164 |
| L2 coverage | 0.122 |

This is better than the earlier direct-writer core baseline on several
candidate-discovery measures, but it does **not** establish a stable
development workflow. Four papers were unavailable. The roster stage was the
dominant bottleneck: initial structured submission was not reliable enough,
and no downstream field logic can recover candidates after a whole-roster
failure.

The run also exposed:

- a gap between the intended explicit group-wide probability rule and model
  behavior in at least one eligible table;
- incorrect uncertainty direction in some extracted quantities;
- incomplete aggregation of repair and usage records from failed papers;
- repeated physical request indices on correction attempts.

### Targeted GLM-5.2 thinking-control evidence

On 2026-07-30, six immutable targeted-development runs compared two repeats
of three GLM-5.2 roster configurations on `2209.03560` (three gold
candidates) and `2602.16925` (gold negative). DeepSeek V4 Pro core-field
extraction and all prompts, rules, budgets, and worker settings were fixed.
The code revision was `c94a833`.

| Roster configuration | L1 delivery | Positive-paper recall by repeat | Negative-paper delivery | Format corrections | Roster tokens | Reasoning tokens | Total run wall time |
|---|---:|---:|---:|---:|---:|---:|---:|
| thinking disabled | 4 / 4 | 1 / 2 | 2 / 2 | 0 | 100,943 | 0 | 77.761 s |
| thinking enabled, effort high | 4 / 4 | 2 / 2 | 2 / 2 | 0 | 129,682 | 28,222 | 526.005 s |
| thinking enabled, effort max | 2 / 4 | 1 / 2 | 1 / 2 | 2 | 491,175 | 344,719 | 3,524.065 s |

The formal scorer correctly rejected these targeted runs because formal V5
scoring accepts only a complete dev10. A private-gold, read-only diagnostic
over the two frozen papers found repeat-pooled L1 recall and L2 coverage of
0.5/0.5 for thinking disabled, 1.0/1.0 for effort high, and 0.5/0.5 for
effort max, with no false-positive candidates. These are diagnostic results,
not formal V5 scores.

Effort `max` is rejected as a roster default: both failed paper-attempts used
64,000 reasoning tokens on the initial request and another 64,000 on the
same-setting format correction without producing a submission tool call.
Thinking disabled removed the structured-submission failure and was fast, but
its positive-paper decision varied across repeats. Effort `high` is the
provisional route to expand on additional hard development papers; it was
scientifically stable in this small comparison but remained materially slower
than disabled thinking.

The experiment also showed that revision `c94a833` still reset
`physical_request_index` to one for a roster format correction when no
field-style shared budget was supplied. The archived runs preserve that
bookkeeping defect. A post-run fix now shares a six-request counter across the
roster initial/correction logical calls without reducing the existing maximum
of three transport attempts per logical call. Aggregate operational statistics
continue to include successful and failed papers. The scientific behavior gaps
remain development targets and must be measured on new immutable runs.

The following controls behaved as intended and are retained:

- one shared maximum of three physical field requests per candidate, including
  transport retry and correction requests;
- deterministic reviewed-group retention for unresolved “and others” groups;
- safe progress logging without credentials, full contexts, model replies, or
  hidden reasoning;
- immutable run IDs, atomic configuration creation, and no selective resume or
  score splicing;
- TeX-authoritative interpretation with optional, path-confined ECSV addressing.

## Next gate

1. Expand the frozen `thinking=enabled, reasoning_effort=high` route against
   disabled-thinking and a predeclared disabled-thinking rescue on the
   remaining hard development papers. Keep the core-field route fixed and do
   not repeat a 64K no-tool response with the same `max` settings.
2. Add general fixtures for the observed group-wide probability and
   uncertainty-direction failures; do not add paper IDs, object names, or
   table-specific exceptions.
3. Run a fresh full dev10 only after targeted roster submission is stable.
4. Evaluate delivery, L1, and L2 separately under `SCORE_SPEC.md`. Do not infer
   readiness from precision on the successful subset.
5. Keep the 40-paper test closed until the workflow is stable, method inputs
   are frozen, and an explicit test release is authorized.

A future private-gold report may visualize historical scorecards and failure
trends. That report is not part of the current implementation and must not move
item-level gold content into this repository.

<!-- BEGIN GENERATED: benchmark-history-comparison -->
Historical V4 scorecards remain useful context but are not V5 runs:

| Metric | Higher-delivery V4 run | Lower-delivery V4 run |
|---|---:|---:|
| Valid paper delivery | 7 | 6 |
| L1 precision | 0.833 | 1.000 |
| L1 recall | 0.106 | 0.064 |
| L1 F1 | 0.189 | 0.120 |
| L2 coverage | 0.305 | 0.201 |
| L2 strict agreement | 0.980 | 1.000 |
| L2 strict end-to-end delivery | 0.299 | 0.201 |
<!-- END GENERATED: benchmark-history-comparison -->
