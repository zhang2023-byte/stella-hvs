# Stella HVS Extraction Benchmark

This directory contains the public contracts and hash-only records used to
evaluate Stella's HVS extraction workflows. Private expert-approved gold,
item-level comparisons, run archives, and rendered gold reports do not belong
in this repository.

## Boundaries

- The fixed benchmark has 50 papers: 10 exposed development papers and a
  40-paper complement. The paper order and split are inherited unchanged by
  `hvs-extraction-v6` from V5.
- `hvs-extraction-v6` supplies the approved fixed 50-paper benchmark cohort.
  V1-V5 and `hvs-extraction-scratch-legacy` are read-only history.
- Historical candidate-era results and current contribution results reuse the
  cohort but remain separate targets, distinguished by schema, frozen method,
  named Gold selection, and scorecard.
- Formal contribution evaluation reports L0 delivery and format validity, L1a
  object identity, L1b contribution type, L2a paper boundness, and L2b
  multivalue quantities separately. Evidence is required but not scored as
  wording, and usage/cost remain operational metadata.
- Public scorecards contain aggregate counts, rates, and hashes only. Expert
  annotations and row-level comparisons remain in the private gold repository.
- Multiple experts may annotate the same paper independently. Formal scoring
  requires a public, value-free, write-once named profile under
  `benchmark/gold_selections/` that selects one annotator per paper; it never
  falls back to another expert.
- A separate public assignment profile reserves primary and optional parallel
  expert work before annotation. Drafts record actual work in progress and are
  not reservation markers.
- The contribution-first contract is the current target. Dev10 Gold is under
  rule-aligned expert re-review; the other 40 papers remain closed until their
  annotations are migrated and approved. Production extractor output is
  forbidden Gold input.

## Route map

| Question | Owner |
|---|---|
| Current implementation, known problems, and next gate | [`benchmark_implementation.md`](benchmark_implementation.md) |
| L0/L1/L2 scoring decisions shown to users | [`SCORE_SPEC.md`](SCORE_SPEC.md) |
| Contribution scientific rules and gold protocols | [`GUIDELINE.md`](GUIDELINE.md) |
| Original-50 contribution Gold migration | `gold_annotation` workflow, validate/save actions |
| One expert's annotation queue | `gold_annotation` workflow, queue action |
| Immutable expert selection | `gold_annotation` workflow, selection action |
| Agent isolation and campaign rules | [`AGENTS.md`](AGENTS.md) |
| Artifact ownership, privacy, and lifecycle | [`../docs/data-contract.md`](../docs/data-contract.md) |
| Durable engineering decisions | [`../docs/decisions.md`](../docs/decisions.md) |
| Exact executable workflows | [`../workflows/stella_workflows.yaml`](../workflows/stella_workflows.yaml) |

Campaign manifests, immutable public scorecards, and legacy archives live
under [`campaigns/`](campaigns/). Current schema and campaign lifecycle values
come only from [`../src/stella/schema_registry.py`](../src/stella/schema_registry.py).
