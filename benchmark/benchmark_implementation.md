# Benchmark Implementation Status

This document records only the current implementation state, evidence that
still affects a decision, unresolved risks, and the next gate. Historical
experiment detail remains in immutable run archives, public scorecards, and
Git history.

Normative scoring belongs in [`SCORE_SPEC.md`](SCORE_SPEC.md), campaign
lifecycle in `src/stella/schema_registry.py` and the active campaign manifest,
executable procedures in `workflows/definitions/`, and durable architecture
decisions in [`../docs/decisions.md`](../docs/decisions.md).

## Current state

`hvs-extraction-v6` is the only writable campaign. Its manifest is
`evaluation_ready` with `test_ready=true`; V1-V5 and
`hvs-extraction-scratch-legacy` remain read-only. V6 inherits the fixed
50-paper order, 10-development/40-test split, sampling design, and gold hash
without resampling or changing expert judgment.

The 40-paper split is a one-run frozen evaluation cohort, not a permanently
unseen holdout. It may be opened only after an hourly dev10 on the exact frozen
method has no terminal network failure. Recovered transport attempts are
allowed. The repository currently contains no public V6 full-test scorecard.

The candidate evaluation method is frozen by the current preregistration and
the run configuration, not by prose in this file:

| Component | Frozen choice |
|---|---|
| Roster | `deepseek-v4-flash-0731`, DeepSeek endpoint pinned without fallback, tool submission, thinking enabled, effort `max` |
| Core fields | `deepseek-v4-flash-0731`, DeepSeek endpoint pinned without fallback, tool submission, effort `low` |
| Field repair | Four scientific slots, two format-correction rounds, two transport retries per logical call, 12-request physical ceiling |
| Peer review | Deterministic narrow missing-field review, at least two agreeing peers, bounded to three physical requests |
| Current method fingerprint | `be8e5871d21b87670fcd4b87336bcc9256cddc1a353c460f1b0a0e388627eaff` |

The v3 core artifact is the scientific deliverable. A successful roster stays
in L1 even if field extraction fails; unavailable fields remain missing in L2.
Full-field and method-chain supplements are separate, core-hash-bound products
and cannot change core candidates or quantities. No production supplement
model adapter is registered.

Formal scorecards report L0, operations, L1, and L2 separately. Cost is
operational metadata, never a score. Public scorecards contain aggregates and
hashes only; expert gold, item-level comparisons, and rendered gold reports
remain outside this repository.

## Decision-relevant evidence

The evidence below is deliberately pooled or comparative. Single favorable
runs and superseded implementation snapshots are not promotion evidence.

- Ten comparable V4 Flash field-low runs established the lower-tail baseline:
  L1 recall was 1.000 in 9/10 runs, L2 coverage ranged from 0.780 to 0.982,
  and strict agreement over delivered rows stayed between 0.981 and 1.000.
  The main loss is therefore delivery, not transcription accuracy.
- Pinning the DeepSeek endpoint removed the silent cross-provider drift seen
  on 2026-08-16. Unpinned runs from that interval are operational history and
  are not comparable scientific evidence.
- The narrow peer-consistency review accepted 11 of 13 triggered repairs in
  its pinned triplet; every accepted fill matched gold. It removed most pooled
  group-probability omissions without allowing a review to replace the
  original candidate roster.
- Decoupling scientific corrections from transport retries removed the known
  format-ladder starvation. Per-logical-call retry pools then remained bounded
  through two real outage triplets, but those triplets had terminal network
  failures and cannot establish a calm-window quality baseline.
- Higher field effort, disabled field thinking, and the V4 Pro `json_object`
  roster route are rejected for this evaluation. They had worse delivery or
  coverage without a compensating accuracy benefit.

These conclusions are supported by the immutable V6 scorecards under
`benchmark/campaigns/hvs-extraction-v6/scoring/`. Exact run-level metrics and
costs should be read from those artifacts rather than copied into this status
page.

## Open risks

- Gateway instability can still produce terminal network failures. Retry
  recovery is bounded and observable, but it does not make a failed dev10
  eligible for the test gate.
- Roster decisions retain stochastic scientific variance: the recurring
  false-empty positive paper and repeated extra positive-paper candidates have
  not been eliminated by field-stage repairs.
- The main residual field failure is a rejected single-round evidence
  correction. Additional evidence rounds could increase drift and are not part
  of the frozen evaluation method.
- The current evidence is development-set evidence. It supports opening the
  preregistered evaluation gate, not a claim about prospective literature.

Any change to models, provider pins, prompts, rules, request policies, budgets,
worker settings, component hashes, or pricing coverage requires a new method
fingerprint and new immutable run IDs. It also invalidates the current dev10
network gate for test execution.

## Next gate

1. Complete a full dev10 on the exact frozen method and run the gold-blind
   network gate. The run must be terminal and have zero terminal network
   failures; recovered attempts may remain in L0 operations.
2. If the gate passes, obtain explicit authority for the one frozen test40
   model run. Freeze the same method, provider pins, request policies,
   component hashes, paper order, and pricing snapshot before the first
   request.
3. Verify the resulting archive without rewriting it, then create the
   persistent test release. A failed run remains the operational record;
   recovery uses a new run ID and never overwrites or splices results.
4. Score only after explicit private-gold authority, using the immutable
   evaluation selection profile. Publish aggregate scorecards only and report
   L0, operations, L1, L2, and cost separately.

If step 1 fails, repeat it with a new dev10 run ID after provider recovery.
Do not tune the method on test40 and do not reopen rejected development routes
without a new, gold-blind engineering hypothesis.
