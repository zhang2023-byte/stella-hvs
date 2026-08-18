# Stella HVS Extraction Benchmark

This directory contains the public contracts and hash-only records used to
evaluate Stella's HVS candidate extraction workflow. Private expert gold,
item-level comparisons, run archives, and rendered gold reports do not belong
in this repository.

## Boundaries

- The fixed benchmark has 50 papers: 10 development papers and 40 sealed test
  papers. The paper order and split are inherited unchanged by
  `hvs-extraction-v6` from V5.
- V6 is the only writable campaign. V1-V5 and
  `hvs-extraction-scratch-legacy` are read-only history.
- V6 is evaluation-ready. Its one frozen test40 run remains gated by a
  complete dev10 with no terminal network failure and explicit authority for
  real model calls. A one-paper test smoke is diagnostic-only and cannot be
  scored.
- Formal evaluation reports L0 delivery and format validity, L1 candidate
  identity, and L2 core-field transcription separately. Supporting evidence is
  required for an accepted field but is not a scored layer. Usage and estimated
  cost are operational metadata outside all three layers.
- Public scorecards contain aggregate counts, rates, and hashes only. Expert
  annotations and row-level comparisons remain in the private gold repository.
- Multiple experts may annotate the same paper independently. Formal scoring
  requires a public, value-free, write-once profile that selects one annotator
  per paper; it never falls back to another expert.
- A separate public assignment profile reserves primary and optional parallel
  expert work before annotation. Drafts record actual work in progress and are
  not reservation markers.

## Route map

| Question | Owner |
|---|---|
| Current implementation, known problems, and next gate | [`benchmark_implementation.md`](benchmark_implementation.md) |
| L0/L1/L2 scoring decisions shown to users | [`SCORE_SPEC.md`](SCORE_SPEC.md) |
| Immutable TokenDance pricing snapshot | `benchmark_pricing_snapshot_prepare` workflow |
| Expert PDF-only gold annotation protocol | [`GUIDELINE.md`](GUIDELINE.md) |
| Expert assignment and reservations | `benchmark_gold_assignment_prepare` workflow |
| One expert's new/resume/completed queue | `benchmark_gold_annotation_queue` workflow |
| Per-paper expert selection | `benchmark_gold_selection_prepare` workflow |
| Agent isolation and campaign rules | [`AGENTS.md`](AGENTS.md) |
| Artifact ownership, privacy, and lifecycle | [`../docs/data-contract.md`](../docs/data-contract.md) |
| Durable engineering decisions | [`../docs/decisions.md`](../docs/decisions.md) |
| Exact executable workflows | [`../workflows/stella_workflows.yaml`](../workflows/stella_workflows.yaml) |

Campaign manifests, immutable public scorecards, and legacy archives live
under [`campaigns/`](campaigns/). Current schema and campaign lifecycle values
come only from [`../src/stella/schema_registry.py`](../src/stella/schema_registry.py).
