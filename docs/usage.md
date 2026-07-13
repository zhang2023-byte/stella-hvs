# CLI Cookbook

This page is a small human-operator cookbook. It is not the workflow contract
and it is not an exhaustive copy of every command-line option.

For day-to-day use, describe the intended task in natural language. Agents
route it through [`workflows/stella_workflows.yaml`](../workflows/stella_workflows.yaml)
and load the selected definition under [`workflows/definitions/`](../workflows/definitions/).

## Sources of Truth

| Question | Authoritative source |
|---|---|
| Which workflow should run? | `workflows/stella_workflows.yaml` |
| What are its inputs, checks, commands, outputs, validators, and network policy? | `workflows/definitions/<workflow_id>.yaml` |
| What flags and defaults does a script accept right now? | `python scripts/<script>.py --help` |
| Which artifacts are canonical, generated, private, or committed? | [`docs/outputs.md`](outputs.md) |
| What fields does a structured artifact accept? | Pydantic models and generated skill schema references |
| What versions and benchmark campaign are current? | [`src/stella/schema_registry.py`](../src/stella/schema_registry.py) and generated [`docs/versions.md`](versions.md) |

Do not copy workflow policy, complete argument lists, schema field definitions,
or current version literals into this page. Those details change at their
authoritative source.

## Running a Script Manually

Run project commands inside the Stella environment:

```bash
conda run -n stella-env python scripts/<script>.py --help
conda run -n stella-env python scripts/<script>.py <arguments>
```

Read `--help` immediately before a manual run when exact flags or defaults
matter. For network, LLM, download, generated-data, or benchmark work, read the
selected workflow definition before executing the command.

Date arguments used by literature commands accept:

```text
YYYY-MM-DD
YYYY-MM
YYYY
```

An omitted end date means today. Month and year end dates expand to the end of
that month or year; future dates are clipped to today.

## Validate One Paper's Structured Artifacts

Replace `<arxiv_id>` with the paper identifier.

```bash
conda run -n stella-env python scripts/validate_catalog_review.py \
  --arxiv-id <arxiv_id> --require-complete

conda run -n stella-env python scripts/validate_catalog_extraction.py \
  --arxiv-id <arxiv_id> --require-reviewed

conda run -n stella-env python scripts/generate_extraction_rule_views.py --check
conda run -n stella-env python scripts/validate_hvs_candidates.py \
  --arxiv-id <arxiv_id> --require-complete
```

These validators check structure and provenance consistency. They do not
replace paper reading or scientific judgment. For extraction rules and paper
review steps, use the corresponding workflow and referenced skill.

## Regenerate Reading Views

JSON remains the source of truth. Rebuild Markdown and indexes instead of
editing generated views:

```bash
conda run -n stella-env python scripts/render_literature_notes.py
conda run -n stella-env python scripts/build_catalog_index.py
conda run -n stella-env python scripts/build_hvs_candidates_index.py --fail-on-skipped
```

Use the `index_or_markdown_regeneration` workflow when the intended target is
ambiguous or when source JSON may need repair first.

## Preview Catalog Changes Without Network or Writes

Review an object-catalog rebuild without querying SIMBAD/Gaia or modifying
`catalog/`:

```bash
conda run -n stella-env python scripts/merge_hvs_candidate_catalog.py rebuild \
  --literature-dir literature \
  --catalog-dir catalog \
  --enrichment-mode off \
  --external-merge-mode off \
  --dry-run True \
  --fail-on-skipped
```

Calculate a dynamics preview from already cached Gaia enrichment without
writing object JSON:

```bash
conda run -n stella-env python scripts/calculate_hvs_dynamics.py \
  --catalog-dir catalog \
  --external-cache-mode required \
  --dry-run True
```

Network-enabled merge or dynamics refreshes require the permissions and checks
declared by `object_catalog_merge` or `hvs_dynamics_calculate`.

## Build and Preview the Catalog Site

The catalog site is generated from object-level catalog JSON:

```bash
conda run -n stella-env python scripts/build_hvs_catalog_web.py \
  --catalog-dir catalog \
  --web-dir catalog/web

conda run -n stella-env python scripts/serve_catalog_web.py \
  --mode static \
  --port 8080
```

The helper binds to `127.0.0.1` by default. Do not expose it on the local
network unless that is explicitly intended.

Prepare the committable GitHub Pages snapshot only after verifying the local
static build:

```bash
python scripts/prepare_pages_site.py \
  --source catalog/web/static \
  --pages-dir pages
```

Use `hvs_catalog_web_build` for a local build and
`hvs_catalog_pages_prepare` for the deployment artifact. A push is a separate
external action.

## Benchmark Operations

Benchmark work is intentionally not reproduced as a command catalog here. Its
data-flow and contamination boundaries are stricter than ordinary CLI use.

- Route preparation, extraction, finalization, and scoring through the
  corresponding `benchmark_*` workflow definition.
- Read [`benchmark/README.md`](../benchmark/README.md) for benchmark structure.
- Read [`benchmark/GUIDELINE.md`](../benchmark/GUIDELINE.md) for expert gold
  annotation.
- Read [`docs/benchmark-plan.md`](benchmark-plan.md) and
  [`docs/benchmark-l2-spec.md`](benchmark-l2-spec.md) for campaign and scoring
  methodology.
- Obtain explicit authority before real LLM/API calls, downloads, or publishing.
- Never copy expert gold or private scoring details into this workspace.

## Failure and Recovery

- Preserve completed outputs when a workflow supports partial progress.
- Inspect the command's structured report, audit record, or JSONL log before
  retrying.
- Use a workflow's documented retry policy; formal benchmark retries must keep
  the same method fingerprint.
- Use `--dry-run` when supported if scope or replacement behavior is uncertain.
- If a generated view is wrong, fix its canonical input or renderer and rebuild
  it; do not patch the generated file.

For environment installation and dependency problems, see
[`docs/setup.md`](setup.md). For artifact locations and ownership, see
[`docs/outputs.md`](outputs.md).
