# Durable Stella Decisions

This document retains decisions that still govern the current system. Git
preserves implementation history and superseded plans.

## D1. Workflows and schemas each have one source of truth

`workflows/stella_workflows.yaml` routes intent. Each
`workflows/definitions/*.yaml` owns inputs, checks, commands, outputs,
validators, risk, and network policy. `src/stella/schema_registry.py` owns the
release, current and readable schemas, lifecycle, and active campaign.
Generated version and rule views are never edited by hand.

## D2. Persisted artifacts use local integer versions

Stella release, artifact schema, and benchmark campaign are independent axes.
Each artifact has an integer version within one canonical name. Component
hashes and fingerprints identify code, prompts, rules, providers, and models.
Historical artifacts are read through explicit compatible readers; current
writers emit only current contracts.

## D3. HVS science rules have one YAML source

`skills/hvs-candidates-extraction/rules/*.yaml` is normative for roster,
quantity, scientific, and evidence behavior. Profiles select the canonical
roster stage, canonical core-field stage, paper claims, and independent
coding-agent baseline. Generated SKILL and expert-guideline blocks must pass
`scripts/generate_extraction_rule_views.py --check`.

An explicit manuscript, caption, or note statement that assigns a condition to
a complete table or named object group may support each identifiable member.
A bare table may not. Unresolved “and others” content remains a reviewed group
instead of disappearing.

## D4. Gold, extraction, and scoring are isolated

Experts annotate from the PDF into the external private repository selected by
`STELLA_GOLD_DIR`. Extraction reads only paper-local archived inputs. Scoring is
an explicit private-gold operation in a separate context. Public scorecards
contain aggregates and hashes only.

Formal evaluation has L1 candidate identity and L2 core-field transcription.
Supporting evidence is required for accepted fields but is not a scored layer.
L1, L2, and delivery remain separate; no composite score or automatic pass/fail
decision is produced.

## D5. The staged core extractor is the canonical HVS workflow

`hvs_candidate_extraction` is Stella's sole product extraction workflow. It
uses an explicit roster stage followed by per-candidate core-field extraction.
Roster and core-field models are independent configuration roles. Every
candidate shares one maximum of three physical field requests across initial,
transport-retry, format-correction, and evidence-correction requests.

The v3 core artifact is the primary deliverable. A roster-success/field-failure
candidate remains in L1 and has missing L2 fields; only whole-roster failure
makes L1 unavailable. Run archives are immutable and never resumed or
overwritten.

Full-field and method-chain enrichment are separate supplements bound to the
source run and core artifact hash. They cannot add, remove, merge, or alter
core candidates or fields.

## D6. V5 is active; prior campaigns are read-only

`hvs-extraction-v5` is the only writable campaign. It inherits V4's exact
50-paper order, 10-development/40-test split, and gold hash. V1-V4 remain
readable history. The pre-promotion staged experiments are preserved with a
hash inventory in `hvs-extraction-scratch-legacy`; that campaign is unscoreable
and immutable.

V5 is development hardening and not test-ready. Formal test execution and
scoring require a future campaign-ready decision, an immutable full-test run,
a persistent release, private-gold authority, and explicit user authorization.

## D7. The comparison baseline is independent

`coding_agent_baseline` is the only maintained comparison extractor. It uses
the same archived paper boundary, shared science rules, and v3 output contract,
but cannot reuse staged intermediate artifacts. The same L1/L2 scorer may
compare its immutable V5 runs.

## D8. Documentation has fixed owners

The benchmark README is an overview and router.
`benchmark/benchmark_implementation.md` owns current status, known defects, and
the next gate. `benchmark/SCORE_SPEC.md` owns human-facing score decisions.
Release history belongs in `CHANGELOG.md`; current artifact ownership belongs
in `docs/data-contract.md`. Completed plans are deleted rather than archived in
new permanent documents.

## D9. Formal scoring selects expert gold explicitly per paper

Multiple experts may preserve independent PDF-only annotations for the same
paper. The public gold manifest is append-only at the file-record level: an
existing expert file cannot change or disappear, while a new annotator twin may
be appended.

Every new formal score requires one public, value-free, write-once selection
profile covering the exact campaign split in campaign order. The profile binds
each paper to one annotator and both private twin hashes. Missing or mismatched
records fail the evaluation without fallback. Ordinary reports compare only
runs that share the same selection profile; cross-expert sensitivity is a
separate future contract.

## D10. Annotation assignment is separate from draft and scoring state

A public, value-free, write-once campaign assignment profile records one
primary annotator and optional additional independent annotators per paper.
The primary role is the intended source for a later formal selection; an
additional role requests a parallel annotation but does not change scoring.

Recommendation queues are annotator-scoped. They combine assignment roles,
the public gold manifest, and only the existence of that annotator's private
draft file to classify work as new, resumable, or completed. Drafts represent
actual work in progress and may not be created as reservation markers. The
later gold selection remains the sole formal scoring input and still fails
closed on missing or mismatched twins.
