# Known Issues: Legacy Extraction Files

Generated during the v0.1 data migration (2026-06-11). These
`literature_hvs_candidates.json` files fail strict validation with the
current validator. The issues predate the v0.1 migration (verified: the
migration is semantically a pure version-string + tooling rewrite) and
reflect extractions made under older schema shapes or with quality
problems (missing required fields, LaTeX residue in machine values,
wrong method_refs routing).

Policy: do not hand-fix; these papers are queued for re-extraction with
the validated pipeline after the benchmark (see benchmark plan). The
benchmark sampling manifest must treat them as a separate stratum or
exclude them from the verification set.

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
