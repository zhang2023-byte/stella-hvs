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
notes/YYYY/YYYY-MM/YYYY-MM.json   Monthly canonical record
notes/YYYY/YYYY-MM/YYYY-MM.md     Reading note generated from monthly JSON
notes/index.json                  Collection index rebuilt from monthly JSON
notes/index.md                    Yearly view generated from index JSON
literature/<arxiv_id>/record.json Per-paper verification evidence record
literature/<arxiv_id>/summary.md  Human-readable verification summary
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

With `--llm-review True`, weak rule matches that the LLM confirms should be
kept as weak matches. LLM review in rules mode should only decide whether weak
rule matches are retained or filtered; it should not change the strong/weak
grouping.

LLM classification or review should use title, search-returned abstract, and categories together. Do not send title-only payloads unless the user explicitly asks for a title-only comparison.

Use `scripts/annotate_catalog_data.py --on YYYY-MM`, `--on YYYY-MM,YYYY-MM`, or `--from DATE --to DATE` to add `catalog_assessment` fields to existing note JSON. That assessment should use abstract and brief content together, then refresh the sibling Markdown file.

Use `scripts/verify_literature_catalog.py` for deeper paper-level verification. It should keep the full evidence trail under `literature/<arxiv_id>/`, then sync a lightweight `catalog_verification` summary back into the matching monthly note JSON when the paper exists there, refresh that month Markdown file, and rebuild the collection index.

When the automated heuristic is not trustworthy, persist the agent's structured override into `literature/<arxiv_id>/record.json` via `scripts/apply_agent_catalog_adjudication.py`. Monthly note JSON and `notes/index.*` must prefer that `agent_adjudication` over the automated DeepXiv/PDF/source verdict.

## Engineering Rules

- Test in `stella-env`: `conda run -n stella-env python -m unittest discover tests`.
- Avoid real DeepXiv calls unless the user explicitly asks to rerun data collection; DeepXiv quota is limited.
- Preserve provenance in JSON: search source, queries, categories, score, whether brief was fetched, skipped reason, and `run_id`.
- Weak records must be listed after direct records; generated Markdown should keep a divider between the two groups.
- On rate limits, completed months must still save JSON, Markdown, and the partial summary.
- Do not revert existing generated notes or unrelated worktree changes. Commit only files relevant to the current task.
- Project-local reusable agent skills live under `skills/`. Prefer adding or updating a skill there when the workflow depends on nuanced judgment that simple heuristics cannot reliably capture.
- For complex single-paper catalog adjudication, prefer the repo-local `skills/literature-catalog-verifier/` workflow over extending keyword rules blindly.
- Keep `~/.codex/skills/literature-catalog-verifier` as a symlink to the repo-local `skills/literature-catalog-verifier/` folder when a global Codex entry is needed. Do not maintain a copied duplicate.
- For actual catalog ingestion after verification, use the repo-local `skills/catalog-ingestor/` workflow. It should produce machine-readable ingestion scaffolds under `literature/<arxiv_id>/catalog_ingest/` before any richer object-level normalization work.
- Keep `~/.codex/skills/catalog-ingestor` as a symlink to the repo-local `skills/catalog-ingestor/` folder when a global Codex entry is needed. Do not maintain a copied duplicate.
- Follow the boundary encoded in repo-local skills: deterministic scripts and tools should handle repeatable extraction and syncing, while the agent should handle context-heavy semantic adjudication and explicitly explain any override of automated heuristics.
- If you change runtime dependencies or environment bootstrap steps, update the checked-in environment spec and setup docs in the same change.

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

When changing runtime dependencies or environment setup, update:

- `environment.yml`
- `docs/setup.md`
- `README.md` setup guidance when needed

When adding scientific capabilities, design the result as machine-readable JSON first. Add Markdown, prose documentation, or website views only after the structured data model is clear.
