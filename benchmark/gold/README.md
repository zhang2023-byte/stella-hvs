# Gold Standard — DO NOT READ DURING EXTRACTION

<!-- AGENT CONTAMINATION NOTICE: This directory holds the expert-adjudicated
     gold standard. Any agent performing candidate extraction (production
     hvs_candidate_extraction or benchmark variant extraction) must not open
     files under this directory. Only hvs_benchmark_gold_finalize and
     hvs_benchmark_score may read or write here. -->

Each `<arxiv_id>/literature_hvs_candidates.json` is a standard
`stella.literature_hvs_candidates.v7` record assembled from expert verdicts by
`scripts/benchmark_finalize_gold.py`. `gold_provenance.json` maps every gold
candidate and field to the adjudication item (or auto-consensus) that produced
it. Never edit these files by hand; re-run the finalize workflow after changing
adjudications.
