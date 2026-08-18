# Stella

Stella is an autonomous agent for hypervelocity-star (HVS) research. It turns
information scattered across papers, tables, and external catalogs into a
traceable, reproducible, and maintainable object-level catalog.

Live example: [Stella HVS Catalog](https://zhang2023-byte.github.io/stella-hvs/).
The current catalog covers post-Gaia DR3 HVS literature from January 2022
through April 2026.

## Why Stella exists

Questions such as “How many hypervelocity stars have been discovered?” or
“How fast are they moving?” sound simple, but the answers depend on papers,
selection criteria, Galactic-potential models, and tables maintained in many
different places. A manually maintained catalog is difficult to keep current.
Stella organizes literature retrieval, structured review, candidate extraction,
object merging, physical checks, and website publication into auditable
workflows.

## Quick start

```bash
conda env create -f environment.yml
conda activate stella-env
cp .env.example .env
```

See [`docs/guide.md`](docs/guide.md) for installation details, credentials, and
common local operations.

Stella's primary interface is natural language. Ask an agent working in this
repository to perform requests such as:

```text
Fetch HVS literature for 2026-03.
Review the structured data assets for 2402.10714.
Extract HVS candidates from 2402.10714.
Rebuild the object-level HVS catalog.
Calculate catalog dynamics.
Build the local catalog website.
Open the expert gold-annotation form for 1902.05061.
```

The agent first reads [`AGENTS.md`](AGENTS.md), selects a workflow through
[`workflows/stella_workflows.yaml`](workflows/stella_workflows.yaml), and loads
only the matching definition and skill. Exact execution contracts live under
`workflows/definitions/`; there is no duplicate Markdown workflow manual.

## Data flow

```text
fetch literature
  -> review paper data assets
  -> extract internal tables
  -> extract HVS candidates
  -> merge object catalog
  -> calculate dynamics
  -> build web catalog
  -> prepare Pages snapshot
```

Each step writes machine-readable data first, then generates Markdown, indexes,
or HTML. If a generated view is wrong, fix its canonical record or renderer
instead of editing the generated file.

## Four reading routes

| Question | Start here |
|---|---|
| How do I install, run, preview, or recover? | [`docs/guide.md`](docs/guide.md) |
| Where is data stored, who may change it, and when do versions change? | [`docs/data-contract.md`](docs/data-contract.md) |
| Why does Stella exist and where is it going? | [`docs/vision.md`](docs/vision.md) |
| How is the benchmark organized and where are its contracts? | [`benchmark/README.md`](benchmark/README.md) |

Open these files only when their narrower subject is needed:

- [`docs/decisions.md`](docs/decisions.md): durable design decisions that still
  affect the current system.
- [`docs/versions.md`](docs/versions.md): the current version table generated
  from code.
- [`CHANGELOG.md`](CHANGELOG.md): release history.
- [`benchmark/GUIDELINE.md`](benchmark/GUIDELINE.md): expert gold-annotation
  protocol.
- [`benchmark/SCORE_SPEC.md`](benchmark/SCORE_SPEC.md): normative L0/L1/L2 scoring contract.
- [`benchmark/benchmark_implementation.md`](benchmark/benchmark_implementation.md):
  current implementation status, known problems, and next gate.

## Development and verification

```bash
conda run -n stella-env python -m unittest discover tests
conda run -n stella-env python scripts/generate_extraction_rule_views.py --check
conda run -n stella-env python scripts/generate_schema_docs.py --check
```

Versions, schemas, workflows, and generated views each have one source of
truth. See [`AGENTS.md`](AGENTS.md) and
[`docs/data-contract.md`](docs/data-contract.md) for maintenance boundaries.

## License

MIT — see [LICENSE](LICENSE).
