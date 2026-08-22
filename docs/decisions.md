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

Formal evaluation has L0 single-run delivery and format validity, L1 candidate
identity, and L2 core-field transcription. Supporting evidence is required for
accepted fields but is not a scored layer. L0, L1, and L2 remain separate; no
composite score or automatic pass/fail decision is produced. Token usage and
TokenDance-based CNY estimates are operational metadata outside all layers.

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

## D6. V6 is active; prior campaigns are read-only

`hvs-extraction-v6` is the only writable campaign. It inherits V5's exact
50-paper order, 10-development/40-test split, and gold hash. V1-V5 remain
readable history. The pre-promotion staged experiments are preserved with a
hash inventory in `hvs-extraction-scratch-legacy`; that campaign is unscoreable
and immutable.

V6 entered development hardening under this decision. D15 supersedes the
original not-test-ready restriction and defines the current evaluation gate.
Formal test scoring still requires an immutable full-test run, a persistent
release, private-gold authority, and explicit user authorization.

## D7. The comparison baseline is independent

`coding_agent_baseline` is the only maintained comparison extractor. It uses
the same archived paper boundary, shared science rules, and v3 output contract,
but cannot reuse staged intermediate artifacts. The same L0/L1/L2 scorer may
compare its immutable V6 runs.

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

## D11. Cost estimation is offline and snapshot-bound

Formal scoring never reads live prices. An explicitly authorized preparation
workflow converts uniquely identified TokenDance routes into an immutable CNY
snapshot without retaining cookies, tokens, or account data. The sealed run
manifest is the sole usage source; roster proposals and candidate field results
are counted once, including retries and corrections.

The scorer requires price coverage for every API route and uses decimal
arithmetic. Incomplete provider telemetry yields a partial or unavailable
estimate, never a fabricated zero. The estimate is reproducible operational
metadata, not a supplier invoice and not an input to L0, L1, or L2.

## D12. Field request policy is fingerprinted; peer review is bounded and code-triggered

The per-candidate field request policy (shared physical-request cap across
initial, transport retry, format correction, and evidence correction) lives
inside `HvsExtractionMethodConfig`, so any policy change forces a new method
fingerprint and new immutable run IDs, as the benchmark rules already
required.

One bounded post-field step is part of the frozen method, gated by the same
policy: deterministic code compares delivered core fields across the same
roster, and when at least two delivered candidates filled one field with an
identical value, unit, limit kind, and direct-evidence locator while another
delivered candidate left it null, that candidate receives exactly one
targeted re-examination request with its own physical-request allowance.
The review response uses a narrow `submit_reviewed_fields` contract that can
carry only the flagged field quantities; code validates each quantity,
merges it into the hydrated previous delivery, and records the applied and
confirmed-null fields. A failed review keeps the original delivery, and no
model ever sees another candidate's full record — only the shared source
locator and printed value. The review is recorded in the candidate's repair
history as `peer_consistency_review` and its usage enters the sealed run
manifest like any other physical request.

## D13. Field-stage transport retries and scientific corrections are decoupled

The per-candidate field budget (D12) now separates two accounting layers:
scientific slots, one per logical submission (the initial request, each
format-correction round, the drift-guarded evidence correction), and a
per-call transport-retry allowance for automatic retries. A hard physical
ceiling bounds their sum. Consequences:

- A transient transport failure inside any logical call no longer starves
  the remaining scientific slots; the candidate keeps its full correction
  ladder.
- A non-retryable protocol rejection refunds its scientific slot and is
  marked `scientific_slot_refunded` in the attempt record, because the model
  never had a chance to answer; the physical request still counts toward
  the ceiling.
- The format ladder is elastic within its bounds: a correction round that
  fails with format-class errors again starts another round (up to
  `max_format_correction_rounds`) while slots remain, instead of terminating
  the candidate with request slots unused. Evidence correction remains a
  single drift-guarded round.
- The roster stage and the peer-consistency review keep the legacy shared
  accounting; only the field stage opts into the decoupled budget.

Both layers live in the fingerprinted `HvsFieldRequestPolicy`, so changing
any allowance requires a new method fingerprint and immutable run IDs.

## D14. Transport-retry pools are per logical call; every stage uses the decoupled budget

The transport-retry allowance is now scoped to one logical call instead of
one candidate: every logical submission (initial, each format-correction
round, the evidence correction, the peer review) owns a full retry pool, so
retries spent on an early call can no longer starve later correction calls.
The budget keeps a cumulative retry ledger for audit records and the
monotonic physical-request index, and the retry count per call stays
hard-bounded by the transport attempt loop. This supersedes the D13
exception: the roster stage and the peer-consistency review now use the
same decoupled accounting as the field stage.

- The roster stage replaces its hardcoded shared ledger with a
  fingerprinted `HvsRosterRequestPolicy` (three scientific slots, two
  per-call retries, physical ceiling ten with one spare request), so its
  terminal classifications are unchanged while its accounting becomes
  policy-visible and reproducible.
- The peer-consistency review keeps one scientific slot by contract but
  gains per-call transport retries under its `max_physical_provider_requests`
  physical ceiling (default three), so a single transient network failure
  no longer aborts a review.
- Both policies and the field policy share ladder validators: the
  scientific pool must cover the initial request, every format-correction
  round, and the evidence correction, and the physical ceiling must cover
  the full ladder with per-call retries, so no ceiling can silently
  truncate the correction ladder. The field ceiling rises from ten to
  twelve (four slots times three attempts) to satisfy that invariant.
- All allowances remain fingerprinted method configuration; any change
  requires a new method fingerprint and new immutable run IDs.

## D15. Test40 is a frozen evaluation cohort with a preregistered network gate

The 40-paper split is opened for one frozen evaluation after a complete dev10
has no terminal network failure. Recovered transport attempts are allowed;
terminal network failures block that hourly gate. The extraction method,
provider pins, request policies, component hashes, and pricing snapshot remain
frozen before the first test request.

The first full-test run is immutable and remains the operational record.
Network recovery may use a new run ID but may never overwrite or splice the
original archive. Reports keep L0 delivery and operations separate from L1/L2
scientific quality. After results are inspected, this test40 is an evaluation
cohort rather than a permanently unseen holdout; future unseen claims require
prospective literature.

## D16. Network debug runs decouple gateway recovery from formal runs

This amends D15: opening the test split is a user decision (the campaign
`test_ready` flag plus explicit call authority), not an automatic network
gate. The `check_benchmark_network_gate` script is demoted to a diagnostic
status report — including the roster-level network-death blind spot, which is
now reported as terminal — and no longer blocks anything by itself.

A network debug run is one mutable, non-formal container under
`benchmark/campaigns/hvs-extraction-v6/debug/<debug_run_id>/`, initialized
from one terminal formal run (completed or interrupted, scope full_dev or
full_test):

- Init imports every successful artifact byte-identically with recorded
  hashes, binds the frozen method fingerprint (rebuilt from the source
  run config, never retyped), the campaign manifest, and the source pricing
  snapshot, and refuses when the workspace no longer reproduces the source
  prepared inputs. The source formal archive is never touched.
- Manual retries are node-granular and network-only: roster network deaths
  rerun the whole paper chain, failed candidate field extractions rerun only
  that candidate (`retry_only`), and transport-failed peer-consistency
  reviews rerun once. Completed reviews are never repeated (flags recompute
  deterministically and only surface uncovered null fields). Scientific
  failures are non-retryable and stay visible. Every retry invocation needs
  explicit user authority; prior attempts/usages/repair history are merged
  forward so the artifact history stays append-only.
- Finalization requires every paper transport-clean, reassembles
  per-paper paper_result/core artifacts, records still-copied file hashes
  against the source archive, aggregates usage under the frozen pricing
  snapshot, and writes a content-hashed `debug_result.json` lineage
  certificate. Chain cost accounting equals the debug result's cumulative
  usage; per-run cost sidecars of the source chain are not summed.
- A finalized clean debug run is scorable for both dev and test splits:
  formal scoring verifies the debug config/result content hashes, the
  source run binding and campaign split, and the frozen snapshot, then
  scores the recovered view. The public scorecard (v8) carries a
  `network_debug` lineage block so a recovered evaluation is always
  visibly labeled.

## D17. Pricing snapshots accept published DeepSeek list prices with peak-band flat routes

DeepSeek moved to explicit peak/off-peak (peak-valley) CNY pricing with
Beijing-time windows. Snapshots may now name `DeepSeek`
(`https://api-docs.deepseek.com/…`) as their source alongside TokenDance,
and carry a `time_tiered_schedules` section: one entry per covered route
with the timezone, explicit peak windows, and both band rate sets. The
validator anchors each schedule by requiring its peak rates to equal the
flat route rates exactly, so a flat route always prices the peak band and
estimates are upper bounds; the off-peak band stays recorded, and tiered
schedules never satisfy coverage. `tokendance-2026-08-18-deepseek-peakvalley-v1`
(flash-0731 and pro-0813) is the active snapshot; earlier snapshots remain
readable and keep their runs' original cost bindings. Non-DeepSeek routes
stay on their original snapshots until a combined, honestly-sourced one is
prepared.

## D18. Contribution-first HVS contract is a parallel pre-gold family (0.9.0)

The V6 candidate contract conflated contribution existence, entry path, and
final boundness. A parallel `literature_hvs_contributions` v1 family now
records what each paper actually does to each identifiable HVS-related
object: `contribution_type` (candidates_found / follow_up, classified per
object from paper behavior), a paper-reported five-value
`paper_boundness.status` that is never probability-derived, a mandatory
contribution note and evidence, and grouped multivalue measurements over
the same 19 fields with explicit `paper_preferred` tri-state and
`source.kind` provenance. Bound reassessments stay included as follow_up.

Boundaries frozen with it:

- V6 artifacts, runs, scorecards, gold, and readers are untouched;
  `hvs-extraction-v6` stays the only active campaign and the only formal
  evaluation. Contribution scores are a separate scientific target and are
  never compared with V6 scores.
- The implementation is pre-gold: annotation tooling exists but formal
  saving is disabled until expert-approved guideline wording and a campaign
  binding exist; the scorer ran only on synthetic fixtures; no mechanical
  migration from V6 gold exists or is permitted.
- The derived contribution catalog is an evidence timeline, not an
  input-selection policy: it stores no authoritative global boundness state,
  never flattens values, and the web view labels "latest reported status"
  as a paper report only.
- Contribution-based dynamics require an explicit
  `hvs_dynamics.input_selection` record (selector, rationale, one full-record
  fingerprint and numeric snapshot for every consumed measurement field, and
  a required source-file hash) and fail closed when it is missing or stale;
  inputs are never chosen from preference, order, uncertainty, or boundness.
- Local contribution runs live under the ignored
  `runs/hvs-contribution-extraction` root with immutable run ids and are
  never benchmark results.
