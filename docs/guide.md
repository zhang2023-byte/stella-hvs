# Stella User Guide

This is the human guide to installation and daily operation. Normal Stella use
means describing a goal to an agent rather than memorizing every command. The
agent first reads
[`workflows/stella_workflows.yaml`](../workflows/stella_workflows.yaml), then
loads only the matching workflow definition and skill.

Use each script's `--help` output for exact parameters. See
[`data-contract.md`](data-contract.md) for data ownership and version rules, and
the generated [`versions.md`](versions.md) for current versions.

## 1. Installation

```bash
conda env create -f environment.yml
conda activate stella-env
cp .env.example .env
```

Update an existing environment after dependencies change:

```bash
conda env update -f environment.yml --prune
conda activate stella-env
```

The environment installs Stella as an editable package. Python dependencies
come from `pyproject.toml`; system and Node.js dependencies come from
`environment.yml`. LaTeXML is recommended for complex LaTeX tables:

```bash
brew install latexml
latexmlc --VERSION
```

Without LaTeXML, table extraction falls back to Pandoc and then the built-in
parser. Complex tables may lose structure.

### Check PDF tools

The paper PDF is the normative reading source for expert annotation and paper
review. Check the PDF tools once after installation:

```bash
conda run -n stella-env python -c "import fitz, pypdf, pdfplumber; print('python PDF packages OK')"
conda run -n stella-env pdfinfo -v
conda run -n stella-env pdftoppm -v
```

## 2. Credentials

Store project credentials in the uncommitted `.env` file:

```env
DEEPXIV_TOKEN=
ADS_API_TOKEN=
LLM_API_KEY=
LLM_BASE_URL=https://tokendance.space/gateway/v1
LLM_MODEL=deepseek-v4-pro
LLM_THINKING=
LLM_REASONING_EFFORT=
STELLA_GOLD_DIR=~/Documents/MyProject/stella-hvs-gold/gold
```

- Configure a DeepXiv token with
  `conda run -n stella-env deepxiv config`.
- Obtain an ADS token from the
  [NASA ADS Developer API](https://github.com/adsabs/adsabs-dev-api).
- `STELLA_GOLD_DIR` is needed only for expert annotation and isolated scoring.
  It must point to private gold outside this repository.
- `LLM_*` values are needed only for LLM review, catalog assessment, or
  benchmark calls.

Stella reads variables from `~/.env`, the repository-root `.env`, and the
current-directory `.env`, in that order. Never put secrets in `environment.yml`.

## 3. Daily operating rules

| Question | Source of truth |
|---|---|
| Which workflow should run? | `workflows/stella_workflows.yaml` |
| What are its inputs, checks, commands, outputs, and network limits? | The matching `workflows/definitions/<workflow_id>.yaml` |
| Which arguments does a script accept now? | `python scripts/<script>.py --help` |
| Is data canonical, generated, private, or committable? | [`data-contract.md`](data-contract.md) |
| Which fields does structured data contain? | The Pydantic model and generated skill schema reference |
| What are the current release, schemas, and campaign? | `src/stella/schema_registry.py` and [`versions.md`](versions.md) |

Use the Stella environment when running a script manually:

```bash
conda run -n stella-env python scripts/<script>.py --help
conda run -n stella-env python scripts/<script>.py <arguments>
```

Before any network, LLM, download, generated-data, or benchmark operation, read
the matching workflow definition.

## 4. Common local checks

### Validate one paper's records

```bash
conda run -n stella-env python scripts/validate_catalog_review.py \
  --arxiv-id <arxiv_id> --require-complete

conda run -n stella-env python scripts/validate_catalog_extraction.py \
  --arxiv-id <arxiv_id> --require-reviewed

conda run -n stella-env python scripts/generate_extraction_rule_views.py --check
conda run -n stella-env python scripts/validate_hvs_candidates.py \
  --arxiv-id <arxiv_id> --require-complete
```

These commands check structure and evidence-chain consistency. They do not
replace reading the paper or making scientific judgments.

### Rebuild reading views

```bash
conda run -n stella-env python scripts/render_literature_notes.py
conda run -n stella-env python scripts/build_catalog_index.py
conda run -n stella-env python scripts/build_hvs_candidates_index.py --fail-on-skipped
```

JSON is the source of truth. If a reading view is wrong, fix the upstream JSON
or renderer rather than editing generated Markdown.

### Preview the catalog without network access

```bash
conda run -n stella-env python scripts/merge_hvs_candidate_catalog.py rebuild \
  --literature-dir literature --catalog-dir catalog \
  --enrichment-mode off --external-merge-mode off \
  --dry-run True --fail-on-skipped

conda run -n stella-env python scripts/calculate_hvs_dynamics.py \
  --catalog-dir catalog --external-cache-mode required --dry-run True
```

### Build the local website

```bash
conda run -n stella-env python scripts/build_hvs_catalog_web.py \
  --catalog-dir catalog --web-dir catalog/web
conda run -n stella-env python scripts/serve_catalog_web.py \
  --mode static --port 8080
```

The server binds to `127.0.0.1` by default. Preparing a GitHub Pages snapshot
is a separate workflow, and pushing remains a separate external action.

## 5. Monthly literature and title triage

Monthly retrieval first runs deterministic title triage. Papers clearly about
HVSs, high-velocity, escaping, ejection, or runaway stars become
`rule-related`; the rest become `no-clear-title-evidence`. Optional LLM review
checks only the latter group.

The lexical rules live in `src/stella/lit/title_classifier.py`; this guide does
not copy them. Results are written to
`notes/YYYY/YYYY-MM/YYYY-MM.title-triage.json`. That file is a triage record,
not scientific evidence from a paper.

Real retrieval requires explicit network authorization. Use the
`monthly_literature_fetch` workflow instead of copying a complete argument list
that can become stale.

## 6. Benchmark operations

Benchmark work has stricter gold-isolation and sealing rules, so this guide does
not duplicate its commands:

- Start with [`../benchmark/README.md`](../benchmark/README.md) for current
  status and workflow routing.
- Use only [`../benchmark/GUIDELINE.md`](../benchmark/GUIDELINE.md) for expert
  annotation.
- See [`../benchmark/SCORE_SPEC.md`](../benchmark/SCORE_SPEC.md) for L0/L1/L2
  scoring.
- See [`../benchmark/benchmark_implementation.md`](../benchmark/benchmark_implementation.md)
  for current development evidence and the next gate.
- Run preparation, extraction, finalization, and scoring through the matching
  `benchmark_*` workflow.

Run a no-API V6 development preflight before a real extraction:

```bash
conda run -n stella-env python -u scripts/run_hvs_candidate_extraction.py \
  --run-id <new_run_id> --dev --preflight-only
```

Real model calls require explicit authority. V6 runs are immutable: after any
failure or implementation change, use a new run ID. Terminal runs automatically
persist `run_cost.json` using the active immutable pricing snapshot. Formal test
remains closed.

When a run ends with terminal network failures, recover them inside one network
debug container instead of rerunning the whole run (per-invocation authority
still required; init, status, and finalize make no provider calls):

```bash
conda run -n stella-env python -u scripts/run_hvs_network_debug.py \
  --init --source-run <failed_run_id> --debug-run-id <new_debug_id>
conda run -n stella-env python -u scripts/run_hvs_network_debug.py \
  --debug-run-id <new_debug_id> --status
conda run -n stella-env python -u scripts/run_hvs_network_debug.py \
  --debug-run-id <new_debug_id> --retry-failed
conda run -n stella-env python -u scripts/run_hvs_network_debug.py \
  --debug-run-id <new_debug_id> --finalize
```

The source run archive stays untouched; only network-terminal nodes (roster
deaths, failed candidate fields, transport-failed peer reviews) are retried,
and the finalized debug result is scorable for both splits with a public
lineage block.

## 7. Failure and recovery

- Preserve partial outputs already completed by the workflow, then use its
  structured report, audit, or JSONL record to determine state.
- Follow the workflow's retry policy. A V6 benchmark run is never resumed or
  overwritten; recover terminal network failures through the network debug
  container or start a new run after a scientific failure or change.
- Use `--dry-run` when scope or overwrite behavior is uncertain.
- Fix canonical input or the renderer before rebuilding a wrong generated view.
- When environment or dependency steps change, update `environment.yml`, this
  guide, and the brief README entry together.
