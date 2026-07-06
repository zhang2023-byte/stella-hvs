# Expert Gold-Standard Benchmark

This directory holds the public side of the expert-vs-AI extraction
benchmark: the sampling manifest, the annotation guideline, annotation
templates, archived AI runs, and scoring outputs. The expert gold
annotations themselves live in an external **private** gold repository
pointed to by `STELLA_GOLD_DIR` (its `gold/` directory) and must never enter
this workspace; this repository keeps only their SHA256 integrity records.
The frozen surface the benchmark evaluates is tagged `benchmark-freeze-v1`
(extraction schema family v0.1, skill text, validator, identity matcher).

## Layout

| Path | Role | Written by |
|---|---|---|
| `manifest/sampling_manifest.json` | which papers, which strata, which weights | `scripts/build_benchmark_manifest.py` (deterministic, seeded) |
| `manifest/gold_manifest.json` | SHA256 integrity records for the external gold store | `scripts/update_gold_manifest.py` |
| `GUIDELINE.md` | expert annotation rules and the expert-led scribe protocol (English; versioned by git commit) | humans |
| `templates/` | blank + filled annotation YAML templates | humans |
| `$STELLA_GOLD_DIR/<arxiv_id>/` (external, private) | expert annotations (`annotation_<annotator>.yaml` + upgraded `.json` with canary) | **human annotation workflow only** |
| `runs/<run_id>/` | archived AI extraction runs with tooling provenance (local data, ignored by git) | extraction pipeline (Phase 2) |
| `scoring/<run_label>/scorecard.json` | public scorecards (counts and rates only, `stella.benchmark_scorecard.v0.2`) | `scripts/score_benchmark_run.py` |
| (private repo) `scoring-details/`, `comparison/` | per-row details and the rendered HTML report (embed gold values) | `scripts/score_benchmark_run.py`, `scripts/build_benchmark_report.py` |

## Anti-contamination rules

Defined in AGENTS.md ("Benchmark Anti-Contamination Rules") and enforced by
`tests/test_benchmark_contamination.py`:

1. The gold store is written only by the human annotation workflow
   (`scripts/serve_gold_annotation.py` and
   `scripts/upgrade_gold_annotation.py`).
2. AI runs never read the gold store; run inputs come only from
   `literature/<arxiv_id>/`.
3. Expert gold annotation is expert-led and PDF-only in evidence: the expert
   judges from the PDF before any agent is involved; a scribe agent may
   transcribe values but reads only the same PDF. Human annotation tools must
   not read or display AI outputs, TeX, ECSV, or run artifacts.

The PDF (`literature/<arxiv_id>/arxiv.pdf`) is the normative evidence
source for experts. The AI reads the TeX/ECSV pipeline view; disagreements
between the two views are recorded findings (they measure the ingestion
layer), not annotation errors.

## Sampling design (summary)

Frame: every archived paper with `literature_hvs_candidates.json` except
three Phase-2 pilot papers (tuning leakage). Stratification variables are
paper-intrinsic only — tool products may serve as declared proxies, never
as exclusion criteria. Primary stratum: legacy-status candidates proxy
(positives oversampled, inverse-probability weights recorded per paper).
Secondary: deterministic TeX table complexity. Era: implicit via
chronological systematic sampling, fixed seed. All 47 sampled papers are
expert-led annotations with PDF-only evidence (see the protocol in
`GUIDELINE.md`). Details and exact thresholds live in the
manifest's `design` block and
`src/stella/benchmark/sampling.py`.

Every sampled paper passed the PDF/abs arXiv version consistency check at
manifest build time (`warnings: []`).

## Deferred AI Alignment

The expert gold contract is calibrated independently of the frozen AI
extraction schema. Required AI-to-gold projection rules and the later
extraction-template alignment are recorded in
[`docs/schema-v0.2-notes.md`](../docs/schema-v0.2-notes.md). Complete the
scorer-owned projection before Phase 4; do not rewrite archived AI runs.

## Reproduction

All gold-touching commands read `STELLA_GOLD_DIR` (set it in `.env` or the
shell to the private gold repository's `gold/` directory), or accept an
explicit `--gold-dir`.

```bash
# Regenerate the manifest (byte-identical for the same corpus and seed)
conda run -n stella-env python scripts/build_benchmark_manifest.py

# Serve the local expert annotation form
conda run -n stella-env python scripts/serve_gold_annotation.py \
    --arxiv-id <arxiv_id> \
    --annotator <annotator>

# Validate + upgrade an expert annotation
conda run -n stella-env python scripts/upgrade_gold_annotation.py \
    "$STELLA_GOLD_DIR"/<arxiv_id>/annotation_<annotator>.yaml

# Refresh the gold integrity manifest in this repository
conda run -n stella-env python scripts/update_gold_manifest.py

# Leak-audit an archived run against the private gold store
conda run -n stella-env python scripts/audit_extraction_run.py \
    benchmark/runs/<run_id>

# Run the agentic (ReAct + reviewer) extraction pipeline — method C
conda run -n stella-env python scripts/run_agentic_extraction.py \
    --arxiv-id <arxiv_id> --run-id <run_id>

# Score an archived run (public scorecard + private details;
# L2 per docs/benchmark-l2-spec.md v0.2)
conda run -n stella-env python scripts/score_benchmark_run.py \
    --run-dir benchmark/runs/<run_id>

# Render the human-readable report from scorer outputs
# (writes into the private gold repository, next to gold/)
conda run -n stella-env python scripts/build_benchmark_report.py
```

The form can also save interruption-safe drafts as
`$STELLA_GOLD_DIR/<arxiv_id>/draft_<annotator>.json`; drafts are not validated
and are not final gold annotations. Formal annotation YAML and JSON omit empty
optional fields; schema defaults restore those values when they are read again.

Annotation workflow for experts: read `GUIDELINE.md` section 2 (the
expert-led scribe protocol), then section 7 ("Mechanics") for the
step-by-step. Expert gold annotations score L1-L3
only: candidate sets, key values, and PDF evidence. AI method chains remain
schema-validated diagnostics and are not expert-benchmarked in this version.
The benchmark report is post-gold only: it renders the scorer's outputs
(scorecards plus private details) for any set of scored runs, it is not
consulted while annotating, and its generated HTML stays in the private
gold repository.
