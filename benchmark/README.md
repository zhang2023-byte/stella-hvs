# Expert Gold-Standard Benchmark

`hvs-extraction-v1` is the frozen formal campaign for comparing HVS candidate
extraction methods. Its machine-readable contract is
[`manifest/campaign_manifest.json`](manifest/campaign_manifest.json): 50
papers, a fixed 10-paper dev split, and its exact 40-paper test complement.
The extraction surface remains anchored at `benchmark-freeze-v2`; this
campaign infrastructure does not change the schema, skill, or scientific
validator rules.

## Layout and boundary

| Path | Role |
|---|---|
| `manifest/sampling_manifest.json` | deterministic 50-paper sampling manifest (`v0.2`) |
| `manifest/campaign_manifest.json` | frozen `hvs-extraction-v1` split and analysis weights |
| `manifest/gold_manifest.json` | public SHA256 records for private gold JSON/YAML twins |
| `$STELLA_GOLD_DIR/<arxiv_id>/` | external private expert gold; never copied here |
| `runs/<run_id>/` | ignored local run archive, audit, seal manifest, and paper outputs |
| `releases/hvs-extraction-v1/<run_id>.json` | public hash-only authorization for a sealed clean test run |
| `scoring/<run_label>/scorecard.json` | public formal scorecard v0.3 |
| private `scoring-details/`, `report/` | gold-containing diagnostic details and HTML |

The gold workflow is unchanged: an expert judges only the paper PDF; an
optional scribe transcribes only that expert judgment from the same PDF; the
private gold store is written only by that workflow. AI runs read only their
paper-local literature inputs and never read gold, scorecards, reports, or
other run archives.

## Campaign and split

The campaign retains the original 47 papers and deterministically adds three
version-consistent supplemental papers. Dev contains the fixed ten papers,
balanced by the pre-gold `legacy_status` proxy and `table_complexity`; it does
not depend on gold truth or model performance. Previously exposed papers remain
dev permanently. Test is the exact 40-paper complement.

Dev primary metrics are unweighted. Test primary metrics are unweighted and
also report a clearly labelled post-stratified sensitivity to the 197-paper
evaluation frame. There is no validate split and no L3 scoring in this
campaign.

## Formal lifecycle

```bash
# Deterministically rebuild the two public contracts.
conda run -n stella-env python scripts/build_benchmark_manifest.py
conda run -n stella-env python scripts/build_benchmark_campaign.py

# After expert final saves, refresh public integrity hashes.
conda run -n stella-env python scripts/update_gold_manifest.py

# Create/run one formal Method B or C split (requires explicit API authority).
conda run -n stella-env python scripts/run_benchmark_extraction.py \
  --campaign-manifest benchmark/manifest/campaign_manifest.json \
  --split dev --run-id <run_id> --model <model>

# Method A first creates a formal contract, then uses prepare/launch/collect
# bundles under /tmp/stella-benchmark-agent-bundles/.
conda run -n stella-env python scripts/init_agent_run.py \
  --campaign-manifest benchmark/manifest/campaign_manifest.json --split dev \
  --run-id <run_id> --harness <name> --harness-version <version> --model <model>

# Audit and seal. The audit report must live inside the run directory.
conda run -n stella-env python scripts/audit_extraction_run.py \
  benchmark/runs/<run_id> --report benchmark/runs/<run_id>/leakage_audit.json
conda run -n stella-env python scripts/seal_benchmark_run.py benchmark/runs/<run_id>

# Only an explicitly authorized, sealed, clean test run may be released.
conda run -n stella-env python scripts/release_benchmark_test.py \
  --campaign-manifest benchmark/manifest/campaign_manifest.json \
  --run-dir benchmark/runs/<run_id>

# Formal scorecard v0.3: loads only the selected split's JSON gold twins.
conda run -n stella-env python scripts/score_benchmark_run.py \
  --campaign-manifest benchmark/manifest/campaign_manifest.json \
  --split dev --run-dir benchmark/runs/<run_id>
```

Formal scoring rejects dirty/legacy/mismatched contracts, a stale gold hash,
unsealed or contaminated runs, and test runs without a matching release. A
delivery with validator errors, `review_failed`, missing output, or unparsable
JSON is unavailable in primary L1/L2; parseable illegal outputs can appear only
in private `diagnostic_only` details. Public scorecards contain no gold values.

The report builder accepts only one v0.3 cohort with matching campaign hash,
split, and gold snapshot; it rechecks test release before rendering private
HTML. Historical v0.2 scorecards and old run layouts remain read-only records;
they are not inputs to this campaign.

See [`docs/benchmark-plan.md`](../docs/benchmark-plan.md) and
[`docs/adr/0001-hvs-extraction-v1-campaign.md`](../docs/adr/0001-hvs-extraction-v1-campaign.md)
for the decision record. The expert annotation protocol remains
[`GUIDELINE.md`](GUIDELINE.md).
