# Known Issues: Legacy Extraction Files

Generated during the v0.1 data migration (2026-06-11). These
`literature_hvs_candidates.json` files fail strict validation with the
current validator. The issues predate the v0.1 migration (verified: the
migration is semantically a pure version-string + tooling rewrite) and
reflect extractions made under older schema shapes or with quality
problems (missing required fields, LaTeX residue in machine values,
wrong method_refs routing).

Policy: do not hand-fix; these papers are queued for re-extraction with
the validated pipeline after the benchmark (see benchmark plan).

Benchmark sampling policy: these papers **stay in the sampling frame like
any other paper**. The problems listed here belong to legacy extraction
*files*, not to the papers; the benchmark evaluates fresh frozen-pipeline
runs against expert gold, so legacy file quality never enters the
measurement path. Excluding these papers would bias the sample toward
easier papers and overstate pipeline performance. Sampling strata use only
paper-intrinsic, tool-independent variables (candidate-status proxy,
deterministic table complexity from the TeX inventory, submission date);
membership in this list must not be a design variable — at most a post-hoc
analysis footnote. Tool-derived labels may serve as declared stratification
proxies, never as exclusion criteria.

## Unfinished extractions

Five files carry a non-final extraction status. All five now have archived
sources and PDFs, so they are completable by the direct-API pipeline.

Only the three small ones are the Phase 2 pipeline **pilot set**; pilot
papers are excluded from benchmark sampling for one reason only — tuning
leakage (the pipeline prompt is iterated on them, so their scores would not
be unbiased). The two large catalogs are deliberately **kept in the
benchmark sampling frame**: large tables are an important difficulty
stratum and must not be burned in the dev set.

| arXiv ID | status | disposition |
|---|---|---|
| 2101.10878 | needs_review | pilot set (empty extraction; review also needs_review) |
| 2011.10206 | needs_review | pilot set (empty extraction) |
| 1901.04559 | partial | pilot set (one APOGEE/Sgr-stream HVS candidate) |
| 2003.12766 | needs_review | sampling frame (MMT HVS survey re-analysis, ~40 B stars, 6D tables) |
| 2206.13002 | source_missing (stale: source now archived) | sampling frame (~60 Sgr dSph candidates) |

| arXiv ID | validation errors |
|---|---|
| 1907.06348 | 2204 |
| 1906.05227 | 892 |
| 1808.02620 | 868 |
| 1804.10197 | 367 |
| 1805.04184 | 302 |
| 1805.03194 | 154 |
| 1902.05061 | 141 |
| 1907.06375 | 48 |
| 1811.04302 | 46 |
| 1806.08630 | 28 |
| 1810.04083 | 23 |
| 1912.02129 | 22 |
| 2012.09338 | 19 |
| 1810.02029 | 16 |
| 1807.05909 | 8 |
| 1810.05650 | 7 |
| 1807.00427 | 6 |
| 1901.04559 | 3 |
| 1912.10125 | 3 |
| 2004.12622 | 3 |
| 2004.13730 | 3 |
| 2106.02647 | 3 |
| 2107.13559 | 3 |
| 2108.06234 | 3 |
| 1802.07494 | 2 |
| 1803.02859 | 2 |
| 1811.11130 | 2 |
| 1812.00198 | 2 |
| 1812.00559 | 2 |
| 1812.04134 | 2 |
| 1812.08221 | 2 |
| 1901.08995 | 2 |
| 1901.10460 | 2 |
| 1912.12679 | 2 |
| 2110.02081 | 2 |
| 2110.11267 | 2 |
| 2111.14892 | 2 |
| 1807.02028 | 1 |
| 2003.12766 | 1 |
| 2112.08235 | 1 |

Total: 40 files, 5201 errors.
