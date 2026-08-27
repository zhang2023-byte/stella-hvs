# Stella Guide

Stella is a literature-to-catalog scientific workflow system for hypervelocity
star research. Every maintained action runs through the unified CLI:

```bash
conda run -n stella-env python -m stella <command> [...]
```

## Discover workflows and operations

```bash
python -m stella workflow list --json
python -m stella workflow show literature_pipeline --json
python -m stella operation show literature.extract_contributions --json
python -m stella schema list --json
python -m stella schema show literature_hvs_contributions --json
```

## Plan before executing

Plan/preflight validates the request, resolves phases, checks files, and
reports required authorities without external calls or canonical writes:

```bash
python -m stella workflow plan literature_pipeline --input request.json --json
```

An example `request.json` for the literature pipeline:

```json
{"papers": ["2601.08888"], "authorities": {"llm": true}}
```

The plan response lists `required_authorities` and `missing_authorities`.
`--execute` alone never grants network, LLM, private-Gold, scoring,
supersede, or publication authority; pass the matching `--allow-*` flag for
each authority the plan reports.

## Execute a workflow

```bash
python -m stella workflow run literature_pipeline \
    --input request.json --execute --allow-llm --json
```

Runs write an ignored, append-only audit directory under
`runs/<workflow_id>/<run_id>/` (frozen `run.json`, `events.jsonl`, per-paper
attempts). Successful papers are never retried inside one run; only
unfinished or network-failed papers resume; finalize is one-way.

## Gold annotation actions

Each `gold_annotation` invocation performs exactly one human action; nothing
chains open -> validate -> save unattended:

```bash
python -m stella workflow run gold_annotation --input gold-request.json \
    --execute --allow-gold-private --json
```

`gold-request.json` selects the action:

```json
{"expert": "expert-a", "papers": ["2601.08888"], "action": "open"}
```

Actions: `queue` lists pending work, `open` prepares the PDF-only form draft,
`validate` checks the draft without saving, `save` applies the expert-approval
gate and writes one JSON annotation per paper and expert into the private
store (`STELLA_GOLD_DIR`), and `selection` publishes the value-free public
selection manifest. Drafts live in the annotator-scoped work directory
(`STELLA_GOLD_WORK_DIR`).

`open` reports the local form URL and its unified-CLI command. Start the
loopback-only interactive form with:

```bash
python -m stella gold-form serve --paper 2601.08888 --expert expert-a
```

The form previews the archived PDF, edits and validates the JSON draft, and
requires an explicit final approval. A non-interactive save request must also
carry `"expert_approved": true`; existing final annotations and the public
selection manifest are write-once.

## Benchmark lifecycle

The default benchmark request runs `prepare`, `freeze`, `run`, and `finalize`;
the optional `resume` and `score` phases join only when requested:

```json
{"run_id": "dev10-001", "phases": ["prepare", "freeze", "run", "finalize"], "profile": "dev10"}
```

`prepare` freezes the dev10 contribution sample (the dev split of the fixed
cohort; `full50` needs explicit authorization), `freeze` writes the method
contract under the run id, `run` executes papers through fresh workers
(transport failures land in resumable `network_failed`; successful attempts
are immutable), and `finalize` persists the one-way terminal marker. `score`
needs the Gold/scoring authorities plus the public Gold selection and writes
separate L0/L1a/L1b/L2a/L2b reports: private details beside
`STELLA_GOLD_DIR`, value-free aggregates in `benchmark/scorecards/`.
Resume or score the same run by sending its existing `run_id`; the frozen
paper set, profile, and method remain authoritative. Scoring requires the
one-way finalization marker and verifies every selected private Gold hash.

## Generated contract views

```bash
python -m stella schema generate --json
python -m stella schema check --json
```

`schema generate` rebuilds `contracts/generated/*.schema.json` from the
Pydantic models and refreshes generated rule blocks; `schema check` fails on
drift and is read-only.

## Tests

```bash
conda run -n stella-env python -m unittest discover tests
```
