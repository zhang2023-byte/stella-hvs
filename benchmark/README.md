# Stella Benchmark

Benchmark artifacts are scoped by immutable campaign ID. There are no global
manifest, runs, scoring, or releases directories.

```text
benchmark/campaigns/
├── hvs-extraction-v1/   # frozen, read-only history
│   ├── manifest/
│   ├── runs/
│   ├── scoring/
│   └── archive_inventory.json
└── hvs-extraction-v2/   # active campaign
    ├── manifest/
    ├── runs/
    ├── scoring/
    └── releases/
```

`hvs-extraction-v1` preserves the previous manifests, public scorecards, and
local runs. `archive_inventory.json` records their pre/post-move paths, byte
sizes, and SHA256 values. Do not add formal runs to v1.

`hvs-extraction-v2` reuses the same deterministic 50-paper sample and fixed
10-dev/40-test split. It is the only active campaign. User-facing commands
select it by ID and resolve all paths internally:

```bash
conda run -n stella-env python scripts/show_versions.py
conda run -n stella-env python scripts/run_benchmark_extraction.py \
  --campaign hvs-extraction-v2 --split dev --run-id <run_id> --model <model>
conda run -n stella-env python scripts/score_benchmark_run.py \
  --campaign hvs-extraction-v2 --split dev --run-id <run_id>
conda run -n stella-env python scripts/build_benchmark_report.py \
  --campaign hvs-extraction-v2 --run-label <run_label>
```

Gold annotations remain in the external private repository selected by
`STELLA_GOLD_DIR`. This public repository contains only the campaign-scoped
hash manifest. Expert annotation is PDF-only; extraction runs must never read
gold, scorecards, private details, or reports. See [GUIDELINE.md](GUIDELINE.md)
for the complete protocol.

Artifact schema versions come from `src/stella/schema_registry.py`; the
generated human reference is `docs/versions.md`. Campaign identity and artifact
schema version are separate concepts.
