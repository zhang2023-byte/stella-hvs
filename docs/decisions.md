# Durable Stella Decisions

This document retains only decisions that still affect the current system and
a small set of unresolved questions. Git preserves implementation steps,
completed plans, and full historical diffs; they are not copied into a
`docs/archive/` directory.

## D1. Workflows and schemas each have one source of truth

**Decision**

- `workflows/stella_workflows.yaml` only routes a human intention to one
  definition.
- `workflows/definitions/*.yaml` owns each workflow's inputs, checks, commands,
  outputs, validators, risk, and network policy.
- `src/stella/schema_registry.py` owns the current release, artifact versions,
  readable versions, lifecycle states, and active campaign.
- Human documentation explains purpose and boundaries. It does not copy full
  workflows, schemas, or current version literals.

**Reason and consequence**

An agent loads one definition and only the skills named by that definition.
`docs/versions.md` is generated from the registry, and exact CLI parameters
come from `--help`. The repository can contain many implementation files while
keeping each task's context small and explicit.

## D2. Persisted artifacts use local integer versions

**Decision**

The Stella release, artifact schema, and benchmark campaign are independent
axes. Each artifact uses an integer schema only within its canonical name;
nested structures do not create their own version sequences. Provenance hashes
and fingerprints identify prompts, models, providers, and validators.

**Reason and consequence**

This avoids maintaining many version numbers without clear semantics. Old data
is read through explicit legacy readers or migrations in the registry, while
normal writers emit only the current envelope.

## D3. HVS scientific rules have one YAML source

**Decision**

`skills/hvs-candidates-extraction/rules/*.yaml` is the normative source for
candidate, quantity, scientific-judgment, and agent-evidence rules.
`profiles.yaml` explicitly selects subsets for the extractor, roster, reviewer,
and expert. Method A reads a generated SKILL view and the guideline's shared
block; Methods B and C render profiles at runtime.

**Reason and consequence**

Experts and methods no longer maintain similar rule copies by hand. Generated
views must pass `scripts/generate_extraction_rule_views.py --check` and must not
be edited manually.

## D4. Scientific and data boundaries of the benchmark

**Decision**

- Experts determine gold from the PDF and store it in the external private
  repository selected by `STELLA_GOLD_DIR`.
- AI extraction reads only `literature/<arxiv_id>/`, never gold, scorecards,
  reports, or previous run output.
- An optional scribe handles one PDF only, and that context may never be reused
  for extraction, scoring, or toolchain development.
- Formal scope consists of L1 candidate finding and L2 value transcription.
  Report them side by side without a combined score.
- Dev may iterate. Test scoring requires a clean leakage audit, sealing, a
  matching release, and explicit authorization.

**Reason and consequence**

Experiment validity depends on isolated data flow, not just prompt wording.
Contamination controls are in
[`../benchmark/AGENTS.md`](../benchmark/AGENTS.md), and the expert protocol is
in [`../benchmark/GUIDELINE.md`](../benchmark/GUIDELINE.md).

## D5. B/Core is the current formal direct path

**Decision**

Method B with `core_prov` is the only direct primary path for new V4 dev runs,
regression, and any future authorized test. Method C and FULL enrichment remain
readable legacy. Normal workflows and the Dev Console do not create, resume, or
retry them. Reproduction requires an explicit legacy opt-in and a new run ID.

CORE is the formal delivery. A deterministic normalizer may repair
representation only; it may not choose candidates, select scientific values,
or guess evidence. An independent reviewer works before roster sealing, and
run, sealing, and scoring fail closed on component provenance.

**Reason and consequence**

This is an engineering priority based on current dev evidence, cost, and ease
of diagnosis. It is not scientific proof that Method C is worse. Reactivating
C or FULL requires a new durable decision and explicit authorization.

## D6. V4 and one canonical private gold store

**Decision**

`hvs-extraction-v4` is the only writable campaign; V1, V2, and V3 are read-only.
V4 mechanically inherited the same 50-paper order and 10-dev / 40-test split.
The private repository contains one canonical gold dataset. A campaign's public
`gold_manifest.json` is only a hash-only integrity index.

Run archives, seals, and scorecards are append-only. New writers do not migrate
or overwrite old runs. Formal comparisons accept only immutable scorecards
with the same campaign hash, split, and gold snapshot.

**Reason and consequence**

Campaigns do not copy gold or create campaign-specific gold branches, while
public integrity checks and reproducible comparisons remain possible.

## D7. Documentation has fixed owners and a size budget

**Decision**

- The README is the only human entry point. The guide, data contract, vision,
  and benchmark README are its four reading routes.
- The root AGENTS file contains only cross-workflow rules. Benchmark-specific
  rules belong in `benchmark/AGENTS.md`.
- Release history is appended to one changelog, and durable decisions are
  appended to this document.
- Delete a completed plan in the same delivery instead of moving it to an
  archive.
- Tests maintain an allowlist of permanent Markdown. A proposed new document
  must name its distinct audience, one unique question, source of truth, update
  trigger, and why no current owner can hold it.

**Reason and consequence**

Git already preserves complete text history. Repository documentation serves
current understanding, current operation, and durable contracts only.

## Unresolved decisions

The following questions lack enough evidence and must not be answered through
temporary fields or paper-specific rules:

- Should typed fields be added for Galactic longitude/latitude, total proper
  motion, or catalog source?
- Does `galactocentric_radius` need a stricter producer-provenance category?
- Should Stella define a controlled unit vocabulary? The current benchmark
  normalizes spelling only.
- Should distance and velocity explicitly retain their printed forms?
- Should a single quantity slot become a method-tagged, multi-estimate
  collection with corresponding set scoring?
- Is a proper-motion-aware identity fallback needed? Reopen this only if new
  benchmark evidence shows coordinate matching has become the bottleneck.

An expert must decide these questions before they enter a new schema or
campaign, following the version rules in
[`data-contract.md`](data-contract.md).
