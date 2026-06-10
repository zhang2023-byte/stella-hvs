# HVS Candidate-Extraction Benchmark

<!-- AGENT CONTAMINATION NOTICE: Extraction workers (canonical or variant) must
     NOT read benchmark/gold/, benchmark/adjudication/, benchmark/alignment/,
     benchmark/manifest/, or any variant directory other than the one they are
     writing. See "Benchmark Data Isolation" in AGENTS.md. -->

Expert-adjudicated gold standard for the `hvs_candidate_extraction` stage.
Multiple independent AI extraction variants are aligned, diffed, and adjudicated
item by item by a domain expert; the result is a per-paper gold
`literature_hvs_candidates.json` (standard v7 schema) plus full correction
provenance.

## Layout

```text
manifest/benchmark_manifest.json   frozen stratified paper sample      (committed)
variants/<variant_id>/             independent extraction runs         (committed)
  variant_meta.json                model, date, kind
  <arxiv_id>/literature_hvs_candidates.json
adjudication/<arxiv_id>.adjudication.json   expert verdicts            (committed)
gold/<arxiv_id>/                   final gold + provenance             (committed)
alignment/                         cross-variant diff + evidence       (generated, ignored)
review/                            expert review site                  (generated, ignored)
reports/                           scoring reports                     (generated, ignored)
```

Committed paths are non-regenerable source data (model runs are
nondeterministic; adjudication and gold are human judgment). Generated paths are
deterministic functions of the committed data; rebuild them, never hand-edit.

## Pipeline

```text
sample -> collect variants -> align -> adjudicate (review UI) -> finalize gold -> score
```

Driven through `workflows/stella_workflows.yaml` (ids prefixed
`hvs_benchmark_`). The expert-facing protocol lives in
`skills/hvs-benchmark/references/adjudication_protocol.md`.
