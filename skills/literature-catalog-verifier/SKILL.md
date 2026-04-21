---
name: literature-catalog-verifier
version: 0.2.0
description: Use when verifying whether an astronomy paper truly provides object-level or sample-level catalog data, and where that catalog is delivered. Especially useful when rule-based heuristics are unreliable, the paper mixes appendix tables with machine-readable full tables, or external repositories such as CDS, VizieR, China-VO, Zenodo, or survey archives are mentioned.
---

# Literature Catalog Verifier

Use this skill for paper-level catalog verification when simple keyword rules are not enough.

This skill encodes Stella's core division of labor:

- use scripts and deterministic tools for bounded work with clear inputs and outputs
- use the agent for context-dependent semantic judgment that cannot be captured reliably by fixed heuristics

This skill is designed for cases like:

- the paper has appendix tables, but it is unclear whether they are the full catalog or only an excerpt
- the paper mentions CDS, VizieR, China-VO, Zenodo, or another host, but it is unclear whether that host stores the paper's own catalog or is only cited as background infrastructure
- the paper mixes internally embedded tables with externally hosted machine-readable data
- the current automated `verify` result looks suspicious and needs an agent-style evidence review

Within this repository, prefer using existing evidence artifacts before re-fetching anything:

1. Read `literature/<arxiv_id>/record.json`
2. Read `literature/<arxiv_id>/summary.md`
3. If needed, inspect:
   - `literature/<arxiv_id>/deepxiv/raw.md`
   - `literature/<arxiv_id>/deepxiv/sections/*.md`
   - `literature/<arxiv_id>/pdf/paper.txt`
   - `literature/<arxiv_id>/source/extracted/*`
   - `literature/<arxiv_id>/source/catalog_tables/*.csv`

Only re-run `scripts/verify_literature_catalog.py --force` if the user explicitly wants a fresh verification run or the saved evidence is clearly incomplete.

For judgment rules and edge cases, read [references/rubric.md](references/rubric.md).

## Division Of Responsibility

Use repository scripts and tools for work that should be stable and repeatable:

- selecting papers from `notes/index.json`
- downloading arXiv metadata, abs pages, PDF, HTML, and source
- extracting PDF text
- unpacking source archives safely
- extracting tables and data-like files
- syncing lightweight verification summaries back into `notes/`

Do not reinvent those steps ad hoc if the scripts already produce the artifacts you need.

Use the agent for work that depends on reading context and resolving ambiguity:

- deciding whether appendix tables are the full catalog, only an excerpt, or only a format description
- deciding whether an external host truly stores the paper's own catalog
- deciding whether a repository mention is substantive delivery evidence or only background citation
- reconciling conflicting signals across DeepXiv, PDF text, source tables, and notes in the paper
- deciding when the automated heuristic is wrong and should be overridden

The key rule is:

- bounded extraction belongs in code
- nuanced adjudication belongs in the skill-guided agent workflow

## Evidence Refresh Policy

Default to the lightest-weight path that still gives enough evidence.

1. First read the saved evidence under `literature/<arxiv_id>/`.
2. If `record.json` already contains the needed artifacts and the user did not ask for a refresh, do not re-fetch.
3. If the saved record is missing an evidence layer that matters for the current ambiguity, refresh only to fill that gap.
4. Use `scripts/verify_literature_catalog.py --force` when the user explicitly wants a fresh run, or when the cached evidence is stale, incomplete, or clearly insufficient for the adjudication.

As a working rule:

- if the question is "what did the current automated pipeline conclude?", read the existing record
- if the question is "is that conclusion actually right?", inspect the saved evidence with agent judgment first
- only re-run networked verification when the saved evidence cannot answer the semantic question

## Workflow

1. Establish what the paper is claiming to provide.
Look for explicit phrases such as "catalog", "machine-readable table", "full table", "available electronically", "online material", "published in its entirety", or "catalog format".

2. Separate internal delivery from external delivery.
Do not collapse these into one judgment too early.
Track both:
   - `internal_delivery`: does the paper itself embed the relevant data in appendix/source tables?
   - `external_delivery`: does the paper explicitly state that the paper's own catalog or full machine-readable table is hosted elsewhere?

3. Distinguish strong evidence from weak evidence.
Strong evidence is explicit hosting language tied to the paper's own catalog or full table.
Weak evidence is a bare repository mention, bibliography entry, acknowledgement, or a methods-stage use of an archive.

4. Decide whether the appendix contains the full catalog, only a sample/excerpt, or just a schema/format table.
This matters. A paper can have:
   - internal sample rows only
   - internal full catalog
   - external full catalog
   - both internal and external delivery

5. Produce a structured judgment with evidence.
Do not only say "mixed" or "internal_only". Also record why.

6. If the judgment overrides the automated heuristic, say exactly what the heuristic missed.
Examples:
   - "China-VO was present but not recognized by the external-host whitelist."
   - "VizieR was mentioned only as background infrastructure, not as host for the paper's own catalog."

## Output Format

When reporting back, use this JSON shape unless the user asks for a different format:

```json
{
  "arxiv_id": "2401.02017",
  "has_catalog_data": true,
  "catalog_scope": "object_level_or_sample_level",
  "internal_delivery": "full|partial|format_only|none|unclear",
  "external_delivery": "full|partial|reference_only|none|unclear",
  "location_class": "internal_only|external_only|mixed|unclear",
  "primary_host": "cds|vizier|china-vo|zenodo|none|unclear",
  "confidence": "high|medium|low",
  "evidence": [
    "short quoted or paraphrased evidence 1",
    "short quoted or paraphrased evidence 2"
  ],
  "reasoning_notes": "One short paragraph explaining the call."
}
```

## Stella-Specific Sync

If the user wants the judgment persisted back into Stella:

1. Keep the full evidence trail under `literature/<arxiv_id>/`.
2. Treat `notes/YYYY/YYYY-MM/YYYY-MM.json` as the canonical monthly record.
3. Write only a lightweight summary into `paper.catalog_verification` unless the schema has already been expanded for richer agent judgments.
4. Regenerate the sibling monthly Markdown note.
5. Refresh `notes/index.json` and `notes/index.md`.

If the agent judgment disagrees with the current automated heuristic, say so explicitly and preserve the reason for the override.

Within this repository, the standard persistence step is:

```bash
conda run -n stella-env python scripts/apply_agent_catalog_adjudication.py ...
```

That script writes the structured override into `literature/<arxiv_id>/record.json`,
re-renders `literature/<arxiv_id>/summary.md`, syncs the effective
`catalog_verification` back into the matching monthly note JSON, and refreshes
`notes/index.json` plus `notes/index.md`.

If the next task is to organize the actual catalog tables for ingestion rather
than only judge their existence, hand off to
`skills/catalog-ingestor/SKILL.md`.
