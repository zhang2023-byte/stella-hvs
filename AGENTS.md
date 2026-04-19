# Stella Agent Guide

This file is for future agents working in `stella-workspace`. Read it before changing code or running project workflows.

## Project Goal

Stella is not just a literature-listing tool. The project aims to build a data integration infrastructure for high-velocity star research. Literature retrieval is an upstream capability: first identify relevant papers, then extract methods, datasets, stellar objects, observables, orbit integrations, chemical information, and provenance into a reproducible high-velocity-star knowledge base and object-level catalog.

Long-term directions include:

- Daily or regular pushes of new field literature.
- Gaia-era literature consolidation, with per-star cross-comparisons of phase space, spectra, orbital results, chemistry, and possible origins across papers.
- Cross-matching and calibration between newly released datasets and the existing high-velocity-star object database.
- Ingesting newly reported high-velocity-star candidates from papers, comparing them against existing datasets, and updating the knowledge base.
- Reproducible physical validation workflows, including velocity conversion, orbit integration, origin tracing, and multi-model cross-checks.
- A database and website that make the catalog and knowledge layer searchable, verifiable, and reusable.

## Core Principle

JSON is the source of truth. Markdown is a human-readable view generated from JSON and must stay fully corresponding to it.

Default outputs:

```text
notes/YYYY-MM/YYYY-MM.json   Monthly canonical record
notes/YYYY-MM/YYYY-MM.md     Reading note generated from monthly JSON
notes/index.json             Collection index
notes/index.md               Index generated from index JSON
```

Do not manually edit generated Markdown to fix data or presentation issues. If an output is wrong, update the JSON record builder or Markdown renderer, then regenerate with `scripts/render_lit_notes.py`.

## Literature Workflow

The minimal default command only requires `--from`:

```bash
conda run -n stella-env python scripts/fetch_high_velocity_lit.py --from 2026-03
```

Defaults should remain quota-conscious:

- `--source deepxiv`
- `--classifier rules`
- `--llm-review False`
- `--brief True`
- `--max-results 20`
- `--categories astro-ph.GA`
- `--search-mode hybrid`

Default rule triage has two levels:

- `direct` / `rule-direct`: strong relevance; fetch DeepXiv brief.
- `weak` / `rule-weak*`: weak relevance; keep only search-stage metadata unless the user explicitly enables LLM review.

LLM classification or review should use title, search-returned abstract, and categories together. Do not send title-only payloads unless the user explicitly asks for a title-only comparison.

Use `scripts/annotate_catalog_data.py --on YYYY-MM` for specific monthly notes, or `--from DATE --to DATE` for ranges, to add `catalog_assessment` fields to existing note JSON. That assessment should use abstract and brief content together, then refresh the sibling Markdown file.

## Engineering Rules

- Test in `stella-env`: `conda run -n stella-env python -m unittest discover tests`.
- Avoid real DeepXiv calls unless the user explicitly asks to rerun data collection; DeepXiv quota is limited.
- Preserve provenance in JSON: search source, queries, categories, score, whether brief was fetched, skipped reason, and `run_id`.
- Weak records must be listed after direct records; generated Markdown should keep a divider between the two groups.
- On rate limits, completed months must still save JSON, Markdown, and the partial summary.
- Do not revert existing generated notes or unrelated worktree changes. Commit only files relevant to the current task.

## Change Checklist

When changing output structure, update:

- `src/high_velocity_lit/records.py`
- `src/high_velocity_lit/markdown.py`
- `docs/outputs.md`
- relevant tests

When changing CLI arguments or defaults, update:

- `scripts/fetch_high_velocity_lit.py`
- `docs/usage.md`
- the minimal README guidance when needed
- CLI parsing tests

When adding scientific capabilities, design the result as machine-readable JSON first. Add Markdown, prose documentation, or website views only after the structured data model is clear.
