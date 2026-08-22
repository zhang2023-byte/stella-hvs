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
unseen holdout. Opening it is a user decision recorded through the campaign
`test_ready` flag plus explicit call authority (D16); the network diagnostic
script is a status report, not an automatic gate. The frozen test40 run
`v6-test40-dsv4flash0731-roster-max-field-low-peerrev2-pin-r1-20260818`
(2026-08-18, method fingerprint unchanged) hit an unstable gateway window:
15 papers ended network-terminal and were recovered node-by-node in debug
container `v6-test40-netdebug-01-20260818` over three retry passes
(49 → 17 → 7 → 0 network-terminal nodes), finalized transport-clean, and
scored as scorecard
`v6-test40-netdebug-01-20260818--gold-evaluation-test-primary-v1`. Two
roster failures (1912.10125, 2509.24010) were later shown to be false
`context_mutation` errors from a system defect (the roster/field immutability
re-resolution dropped the frozen reviewed TeX root), not scientific
failures. After repairing that defect and the identity matcher (LaTeX-markup
alias normalization; bare Gaia source numbers bridged from prefixed ids),
debug container `v6-test40-netdebug-02-20260818` re-ran both papers through
the explicit rerun-roster channel, recovered all 49 network-terminal nodes
in one pass, and was scored as the current scorecard
`v6-test40-netdebug-02r2-20260818--gold-evaluation-test-primary-v1`
(supersedes the two earlier test40 scorecards; L1 micro F1 0.8235, L2
coverage 0.7470). The method fingerprint and all scientific rules are
unchanged; the remaining losses concentrate in rule/gold eligibility
caliber on survey-style tables and provenance papers, not in the repaired
systems.

The candidate evaluation method is frozen by the current preregistration and
the run configuration, not by prose in this file:

| Component | Frozen choice |
|---|---|
| Roster | `deepseek-v4-flash-0731`, DeepSeek endpoint pinned without fallback, tool submission, thinking enabled, effort `max` |
| Core fields | `deepseek-v4-flash-0731`, DeepSeek endpoint pinned without fallback, tool submission, effort `low` |
| Field repair | Four scientific slots, two format-correction rounds, two transport retries per logical call, 12-request physical ceiling |
| Peer review | Deterministic narrow missing-field review, at least two agreeing peers, bounded to three physical requests |
| Current method fingerprint | `be8e5871d21b87670fcd4b87336bcc9256cddc1a353c460f1b0a0e388627eaff` |

A parallel contribution-first contract is implemented but remains
pre-campaign: `literature_hvs_contributions` v1 (paper-object contribution
records with grouped multivalue measurements), local non-formal
`hvs_contribution_extraction` runs under `runs/hvs-contribution-extraction`,
an approved contribution gold guideline, an original-50 migration workflow
and paper-level expert review form, a layered L0/L1a/L1b/L2a/L2b scorer
exercised only on synthetic fixtures, timeline catalog, and explicit dynamics
input selection. No contribution performance result exists, no campaign is
bound to it, and `ACTIVE_BENCHMARK_CAMPAIGN` remains `hvs-extraction-v6`.
The original 50-paper split is calibration/regression material for this
redesign, not a new clean held-out claim. Its migration has not yet begun.

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
- Scoring the network-debug recovery of the 2026-08-18 outage run (scorecard
  `v6-dev10-netdebug-01-20260818--gold-evaluation-dev-primary-v1`) restored
  full L0 delivery (10/10 papers, 48/48 complete candidates) and raised L2
  coverage to 0.988 while strict agreement over compared rows stayed at 0.994:
  the outage-window coverage losses were dominated by transport, not by the
  scientific method.
- Higher field effort, disabled field thinking, and the V4 Pro `json_object`
  roster route are rejected for this evaluation. They had worse delivery or
  coverage without a compensating accuracy benefit.

These conclusions are supported by the immutable V6 scorecards under
`benchmark/campaigns/hvs-extraction-v6/scoring/`. Exact run-level metrics and
costs should be read from those artifacts rather than copied into this status
page.

## Open risks

- Gateway instability can still produce terminal network failures. The network
  debug mode (D16) recovers them node-by-node without wasting quota on whole
  reruns, and the diagnostic script now also reports roster-level network
  deaths, but a formally clean single-pass run remains preferable when the
  gateway is calm.
- Roster decisions retain stochastic scientific variance: the recurring
  false-empty positive paper and repeated extra positive-paper candidates have
  not been eliminated by field-stage repairs.
- The main residual field failure is a rejected single-round evidence
  correction. Additional evidence rounds could increase drift and are not part
  of the frozen evaluation method.
- The V6 result includes the completed frozen test40 cohort, but it is one
  historical 50-paper evaluation and does not establish performance on
  prospective literature.
- The contribution gold migration is AI-assisted. Its metadata and reporting
  must say paper-level expert approval, not independent manual extraction or
  item-by-item expert verification. Production extractor output must remain
  excluded from both preannotation and reconciliation.
- The migration overwrites the working private annotation twins. Starting it
  before a clean private-repository commit or tag would break the intended V6
  recovery path.

Any change to models, provider pins, prompts, rules, request policies, budgets,
worker settings, component hashes, or pricing coverage requires a new method
fingerprint and new immutable run IDs. Network debug runs never change the
method: they rebuild the frozen configuration from the source run config.

## Next gate

1. The frozen test40 evaluation is complete and scored (network-recovered
   lineage, see above). Do not tune the method or the scientific rules on
   test40 and do not reopen rejected development routes without a new,
   gold-blind engineering hypothesis.
2. Any future full-test claim stays bound to this one immutable run lineage
   (`v6-test40-dsv4flash0731-roster-max-field-low-peerrev2-pin-r1-20260818`
   plus its finalized debug containers); new configurations require new run
   IDs and a new method fingerprint.
3. Before contribution migration, create and verify a clean private-gold
   commit or tag preserving V6. Then migrate the original 50 papers with fresh
   PDF-only AI preannotation, separate legacy-note reconciliation, paper-level
   expert approval, validated final twins, and temporary-artifact cleanup. Do
   not refresh the V6 public gold manifest.
4. Use the migrated 50 only for contribution calibration and regression. A
   later formal contribution campaign requires a newly sampled unseen cohort,
   a separately approved non-preannotation gold protocol, and its own frozen
   hash-only manifest.
5. The remaining V6 test40 losses are eligibility-caliber disagreements
   (bound/marginally-bound survey-table members, bare-table-row anchors,
   prior-candidate reassessment, D6/runaway taxonomy) plus one model-side
   coordinate-format partial (2507.00150). Any rule change addressing them
   must be recalibrated on the dev split first, then validated by a new
   frozen run; system-side scoring repairs are exempt and stay covered by
   the superseding-scorecard chain.
