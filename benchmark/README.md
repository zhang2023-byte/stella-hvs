# Stella Benchmark

This is the benchmark's only human entry point. It explains the current
campaign, completed experiments, failure conclusion, and next gate. Exact
execution details belong to `workflows/definitions/benchmark_*.yaml`; the
expert annotation protocol is in [`GUIDELINE.md`](GUIDELINE.md), the normative
L2 scoring contract is in [`L2_SPEC.md`](L2_SPEC.md), and contamination controls
and agent boundaries are in [`AGENTS.md`](AGENTS.md).

## Current conclusion (2026-07-19)

- `hvs-extraction-v4` is the only writable campaign. V1, V2, and V3 are
  read-only history.
- V4 mechanically preserves the same 50-paper sample, order, and fixed 10-dev /
  40-test split; no papers were resampled.
- `$STELLA_GOLD_DIR` is the one canonical private gold store. The public
  `gold_manifest.json` is only a hash-only integrity index produced by an
  independent gold-only task, not a second gold dataset.
- The V4 pre-engineering baseline, first engineering batch, post-engineering
  run, and two independent scoring passes are complete.
- **The first engineering batch failed the end-to-end improvement gate.** Valid
  delivery, L1 recall/F1, and strict L2 end-to-end delivery all fell. Better
  precision and agreement within the successful subset do not offset the
  increased number of unavailable deliveries.
- Do not enter the 40-paper test split or immediately repeat the full dev split.
  First run no-gold targeted diagnostics on the four failed papers.

## Frozen contract

- **Sample:** 50 papers with a fixed 10-dev / 40-test split. Never replace a
  paper based on gold or model output.
- **Formal direct path:** Method B with `core_prov`. Method C and FULL enrichment
  are readable legacy paths; normal workflows and the Dev Console do not
  create, resume, or retry them.
- **Current writers:** `benchmark.roster_bundle` version 3,
  `benchmark.run_manifest` version 4, and `benchmark.scorecard` version 4. Old
  sealed runs keep their original schemas and are not migrated.
- **Scoring:** report L1 micro F1, `agreement_over_compared_strict`, and
  `delivery_end_to_end_strict` side by side; do not combine them into one score.
- **Test gate:** run or score test only after a clean leakage audit, sealing, a
  matching release, and explicit user authorization.
- **Isolation:** AI extraction does not read gold, scorecards, reports, or
  previous run output. Scoring uses a fresh gold-only context.

See [`../docs/decisions.md`](../docs/decisions.md) for durable trade-offs and
[`../docs/data-contract.md`](../docs/data-contract.md) for data ownership.

## Completed V4 cycle

1. `b447234` created V4 and made V1, V2, and V3 read-only.
2. `v4-dev-pre-engineering-b-core-r1` was run, audited, and sealed. An
   independent gold-only task created the hash index and scored it.
3. `155eed7` introduced paper-first roster context, a genuinely independent
   reviewer roster, one bounded reconciliation attempt, unique ECSV
   display-label mapping, and new provenance/cache bindings.
4. `207541d` added a provider-compatible structured-output contract after the
   real DeepSeek endpoint rejected strict `json_schema`. The current
   DeepSeek/GLM routes use forced typed `tool_submission` without runtime
   fallback.
5. `v4-dev-post-engineering-b-core-r1` was run, audited, and sealed. A fresh
   gold-only task scored it, and `d5303b4` committed the public scorecard.

### Formally comparable results

The following table is generated from the two public scorecards. Do not edit it
by hand.

<!-- BEGIN GENERATED: benchmark-v4-comparison -->
| Metric | Pre-engineering | Post-engineering | Change |
|---|---:|---:|---:|
| Valid / invalid / missing | 7 / 3 / 0 | 6 / 4 / 0 | valid -1 |
| L1 micro precision | 0.833 | 1.000 | +0.167 |
| L1 micro recall | 0.106 | 0.064 | -0.043 |
| L1 micro F1 | 0.189 | 0.120 | -0.069 |
| L2 coverage | 0.305 | 0.201 | -0.104 |
| L2 agreement over compared, strict | 0.980 | 1.000 | +0.020 |
| L2 delivery end-to-end, strict | 0.299 | 0.201 | -0.098 |
| L2 fill precision, strict | 0.980 | 1.000 | +0.020 |

Sources:

- [Pre-engineering scorecard](campaigns/hvs-extraction-v4/scoring/v4-dev-pre-engineering-b-core-r1-score-v1/scorecard.json)
- [Post-engineering scorecard](campaigns/hvs-extraction-v4/scoring/v4-dev-post-engineering-b-core-r1-score-v1/scorecard.json)
<!-- END GENERATED: benchmark-v4-comparison -->

The scorecards have identical campaign SHA256, split, gold-manifest SHA256, and
selected-gold-snapshot SHA256 values. Their method fingerprints differ by
design because engineering changes occurred between the runs.

### Post-run failure distribution

| Paper | Final state | Value-free failure class |
|---|---|---|
| `1804.10179` | `roster_failed` | the reviewer failed to submit the target tool call in all three attempts |
| `1902.05061` | `validator_errors` | evidence source path ×1; citation support ×2 |
| `2209.03560` | `validator_errors` | raw-value source support ×6 |
| `2401.02017` | `roster_failed` | roster structured submission failed |

The other six papers finished with `ok`. The first paper also encountered two
infrastructure hangs with no progress for more than 600 seconds. Each process
was stopped, archived evidence was retained, and the same fingerprint was
resumed before the final run completed and sealed.

### Interpretation

- Precision, strict agreement, and fill precision describe only the subset
  successfully delivered and compared. Post had one additional unavailable
  delivery and missed more gold candidates and quantities.
- Paper-first context, an independent reviewer, unique ECSV mapping, and full
  provenance are sound general boundaries and should remain. This run did not
  show that they improve end-to-end quality.
- Forced `tool_submission` succeeded in a synthetic probe but failed at the
  roster/reviewer stages for two real papers. The present bottlenecks are
  long-context submission and general evidence construction, not unresolved
  gold judgment for paper 1804.
- One post-engineering run cannot fully separate engineering effects from model
  variance, but 4/10 unavailable deliveries are enough to require diagnosis
  before spending another complete dev run.

## Next gate

Proceed in this order:

1. Run no-gold targeted diagnostics on the roster-submission failures for
   `1804.10179` and `2401.02017`, and the evidence-validator failures for
   `1902.05061` and `2209.03560`. Use new run IDs, separate empty roster caches,
   and do not read previous outputs, scorecards, or gold.
2. Implement only the smallest general second-batch fixes for real long-context
   typed submission and evidence construction. Do not add paper IDs, object
   names, table-specific thresholds, or ad hoc regular expressions.
3. In targeted cold-cache regression, both roster cases must complete typed
   submission on the fixed route and both evidence cases must pass the same
   general rule. Runtime fallback, looser validators, and cache hits do not
   count as a pass.
4. After that gate passes, run a new formal 10-paper cold-cache dev repeat. The
   minimum gate is valid delivery of at least 7/10, with L1 recall/F1 and strict
   L2 end-to-end delivery no worse than the pre-engineering baseline.
5. Score with a fresh gold-only context. Add a second replicate only if the
   result is close to the gate or the failure set changes materially.
6. After dev passes, freeze the model, provider, mode, prompt, rules, budgets,
   and code revision. Test still requires explicit authorization.

## Tools and directories

```text
benchmark/campaigns/
├── hvs-extraction-v1/   # frozen history
├── hvs-extraction-v2/   # frozen history
├── hvs-extraction-v3/   # frozen history
└── hvs-extraction-v4/   # active
    ├── manifest/
    ├── runs/            # local, ignored
    ├── scoring/         # public scorecards
    └── releases/        # explicit test authorization
```

Display the current versions with:

```bash
conda run -n stella-env python scripts/show_versions.py
```

Use these workflows for normal operations instead of copying complete commands
from this document:

| Purpose | Workflow |
|---|---|
| Create or rebuild a campaign | `benchmark_campaign_prepare` |
| Expert annotation | `benchmark_gold_annotation_form` |
| Formal extraction | `benchmark_extraction_run` |
| Local development console | `benchmark_dev_console` |
| Audit, seal, or authorize a test release | `benchmark_run_finalize` |
| Isolated scoring and report generation | `benchmark_score_report` |

The public repository stores only hash-only manifests, release metadata, and
counts/rates scorecards. Gold, run archives, private details, and HTML reports
never enter a public commit.

## Historical V3 results

These results explain method history. Do not combine them unconditionally with
V4 as a single ranking:

| Experiment | Delivery | L1 P / R / F1 | L2 agreement | L2 end-to-end |
|---|---:|---:|---:|---:|
| `v3-dev-baseline-b-core-r1` | 8/10 | 0.889 / 0.444 / 0.593 | 0.987 | 0.556 |
| `v3-dev-baseline-c-core-r1` | 6/10 | 0.171 / 0.333 / 0.226 | 0.982 | 0.406 |
| `v3-dev-hardened-b-core-r1` | 7/10 | 1.000 / 0.167 / 0.286 | 1.000 | 0.248 |

`v3-dev-hardened-c-core-r1` produced only six reports. It was not completed,
sealed, or scored; it remains a legacy diagnostic and will not be resumed. See
[`../CHANGELOG.md`](../CHANGELOG.md) for current release history.
