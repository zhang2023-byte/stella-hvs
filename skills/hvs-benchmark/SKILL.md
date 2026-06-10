---
name: hvs-benchmark
description: Expert-adjudicated benchmark for Stella HVS candidate extraction. Use when an agent needs to select a stratified benchmark paper sample, collect independent extraction variants, build cross-variant alignment and the expert review site, finalize gold-standard candidate files from expert verdicts, or score variants against gold with detection and field-level metrics.
---

# HVS Extraction Benchmark

This skill drives the benchmark for the `hvs_candidate_extraction` stage. The
gold standard is built by multi-source cross-checking plus expert adjudication,
not by trusting any single extraction run.

## Pipeline

```text
sample            scripts/benchmark_select_sample.py    -> benchmark/manifest/
collect variants  scripts/benchmark_collect_variants.py -> benchmark/variants/<variant_id>/
align             scripts/benchmark_align_candidates.py -> benchmark/alignment/   (generated)
review            scripts/build_benchmark_review.py     -> benchmark/review/      (generated)
                  scripts/serve_benchmark_review.py     -> benchmark/adjudication/ (expert verdicts)
finalize gold     scripts/benchmark_finalize_gold.py    -> benchmark/gold/
score             scripts/benchmark_score.py            -> benchmark/reports/     (generated)
```

Each step has a workflow contract in `workflows/stella_workflows.yaml`
(ids prefixed `hvs_benchmark_`); route execution through it.

## Data Isolation (canonical statement)

Extraction workers must never read `benchmark/gold/`,
`benchmark/adjudication/`, `benchmark/alignment/`, `benchmark/manifest/`, or
any other variant's directory. A benchmark variant worker writes only
`benchmark/variants/<variant_id>/<arxiv_id>/literature_hvs_candidates.json` and
must not open the paper's production
`literature/<arxiv_id>/literature_hvs_candidates.json`. Variant workers read
the same inputs as production extraction (`literature/<arxiv_id>/` archived
assets, `catalog_review.json`, `catalog_extraction.json`, ECSV tables) and
follow `skills/hvs-candidates-extraction/SKILL.md` for extraction semantics.

## Verdict vocabulary

| Item kind            | Verdicts                                            |
| -------------------- | --------------------------------------------------- |
| `candidate_presence` | `accept` (with `base_variant`), `reject`            |
| `candidate_addition` | `add_missing` (with full candidate `added_payload`) |
| `field_value`        | `accept`, `accept_variant`, `fix` (with corrected `fixed_payload`), `reject_field` |

Every verdict records the expert id, an ISO timestamp, and a free-text
rationale. Gold files are standard `stella.literature_hvs_candidates.v7`
records and must pass
`scripts/validate_hvs_candidates.py --path <gold> --require-complete`.

## References

- `references/adjudication_protocol.md` — expert-facing protocol: verdict
  semantics, evidence standards, ambiguity handling, spot-check obligations.
- `references/metrics.md` — formal metric definitions, kept in sync with
  `src/stella_benchmark/field_specs.py`.
