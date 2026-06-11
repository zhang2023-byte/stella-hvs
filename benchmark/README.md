# Expert Gold-Standard Benchmark

This directory holds everything for the expert-vs-AI extraction benchmark:
the sampling manifest, the annotation guideline, expert gold annotations,
archived AI runs, and scoring outputs. The frozen surface it evaluates is
tagged `benchmark-freeze-v1` (extraction schema family v0.1, skill text,
validator, identity matcher).

## Layout

| Path | Role | Written by |
|---|---|---|
| `manifest/sampling_manifest.json` | which papers, which strata, which roles, which weights | `scripts/build_benchmark_manifest.py` (deterministic, seeded) |
| `GUIDELINE.md` | expert annotation rules (English; versioned by git commit) | humans |
| `templates/` | blank + filled annotation YAML templates | humans |
| `gold/<arxiv_id>/` | expert annotations (`annotation_<annotator>.yaml` + upgraded `.json`) | **human workflow only** |
| `runs/<run_id>/` | archived AI extraction runs with tooling provenance | extraction pipeline (Phase 2) |
| `scoring/` | scoring outputs (Phase 4) | scoring scripts |
| `workbench/` | generated evidence review pages (git-ignored, regenerable) | `scripts/build_review_workbench.py` |

## Anti-contamination rules

Defined in AGENTS.md ("Benchmark Anti-Contamination Rules") and enforced by
`tests/test_benchmark_contamination.py`:

1. `gold/` is written only by the human annotation workflow
   (`scripts/upgrade_gold_annotation.py`).
2. AI runs never read `gold/`; run inputs come only from
   `literature/<arxiv_id>/`.
3. Blind-role papers are never shown AI output; the workbench refuses them
   unconditionally.

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
chronological systematic sampling, fixed seed. Roles: 12 blind (5 double-
annotated for inter-annotator agreement) + 35 verification. Details and
exact thresholds live in the manifest's `design` block and
`src/stella/benchmark/sampling.py`.

Every sampled paper passed the PDF/abs arXiv version consistency check at
manifest build time (`warnings: []`).

## Reproduction

```bash
# Regenerate the manifest (byte-identical for the same corpus and seed)
conda run -n stella-env python scripts/build_benchmark_manifest.py

# Validate + upgrade an expert annotation
conda run -n stella-env python scripts/upgrade_gold_annotation.py \
    benchmark/gold/<arxiv_id>/annotation_<annotator>.yaml

# Build review pages for all verification-role papers
conda run -n stella-env python scripts/build_review_workbench.py --all-verification
```

Annotation workflow for experts: read `GUIDELINE.md`, then section 8
("Mechanics") for the step-by-step.
