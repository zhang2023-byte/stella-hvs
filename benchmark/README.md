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
├── hvs-extraction-v2/   # frozen, read-only history
└── hvs-extraction-v3/   # active campaign
    ├── manifest/
    ├── runs/
    ├── scoring/
    └── releases/
```

`hvs-extraction-v1` preserves the previous manifests, public scorecards, and
local runs. `archive_inventory.json` records their pre/post-move paths, byte
sizes, and SHA256 values. Do not add formal runs to v1.

`hvs-extraction-v3` mechanically reuses the exact V2 50-paper order and fixed
10-dev/40-test split; it was not resampled. V1 and V2 are read-only, and V3 is
the only active campaign. User-facing commands
select it by ID and resolve all paths internally:

```bash
conda run -n stella-env python scripts/show_versions.py
conda run -n stella-env python scripts/run_benchmark_extraction.py \
  --campaign hvs-extraction-v3 --split dev --run-id <run_id> --model <model>
conda run -n stella-env python scripts/score_benchmark_run.py \
  --campaign hvs-extraction-v3 --split dev --run-id <run_id>
conda run -n stella-env python scripts/build_benchmark_report.py \
  --campaign hvs-extraction-v3 --run-label <run_label>
```

New direct and dev-console runs use Method B with `core_prov`; this is also the
default of `run_benchmark_extraction.py`. Method C and FULL are retained only as
legacy reproduction interfaces:

- Method B + FULL requires `--allow-legacy-full`.
- Method C requires `run_agentic_extraction.py --allow-legacy-method-c`.
- Method C + FULL requires both legacy flags.

The normal workflow and dev console never add these flags. Legacy execution
requires explicit authority, a new run ID, and the same contamination and
fingerprint rules as any other run. Existing C/FULL archives are read-only and
must not be migrated, resumed, sealed, or rewritten during repository cleanup.

Persistent test authorization records live directly under
`hvs-extraction-v3/releases/<run_id>.json`. The campaign builder preserves the
committed contract's creation-base `code_commit` during byte-for-byte rebuilds;
run code provenance is recorded separately in every `run_config.json`.
Seal and scoring recheck the recorded component hashes against current code.
Scorecards are append-only by evaluation label and may record `supersedes`
without changing an older result.

Gold annotations remain in the external private repository selected by
`STELLA_GOLD_DIR`. This public repository contains only the campaign-scoped
hash manifest. Expert annotation is PDF-only; extraction runs must never read
gold, scorecards, private details, or reports. See [GUIDELINE.md](GUIDELINE.md)
for the complete protocol.

Artifact schema versions come from `src/stella/schema_registry.py`; the
generated human reference is `docs/versions.md`. Campaign identity and artifact
schema version are separate concepts.

Release-specific compatibility notes are in
[`docs/releases/0.5.1.md`](../docs/releases/0.5.1.md).
