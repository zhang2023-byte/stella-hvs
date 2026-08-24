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
