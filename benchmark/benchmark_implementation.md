# Benchmark Implementation Status

This document records only the current implementation state, evidence that
still affects a decision, unresolved risks, and the next gate. Historical
experiment detail remains in immutable run archives, public scorecards, and
Git history.

Normative scoring belongs in [`SCORE_SPEC.md`](SCORE_SPEC.md), campaign
lifecycle in `src/stella/schema_registry.py` and the active campaign manifest,
executable procedures in `workflows/operations.yaml`, and durable architecture
decisions in [`../docs/decisions.md`](../docs/decisions.md).

## Refactor state (0.10.0)

The 0.10.0 architecture refactor moved all maintained execution behind
`python -m stella` with fake-transport offline acceptance. The dev10
contribution Gold migration has now completed under the new runtime; no real
contribution `dev10` or `full50` extraction run has yet been launched. The retired V6
network-debug container, supplements, coding-agent baseline, and report
builders are deleted; historical V6 artifacts and scorecards stay readable.

## Current state

`hvs-extraction-v6` is the only writable campaign. Its manifest is
`evaluation_ready` with `test_ready=true`; V1-V5 and
`hvs-extraction-scratch-legacy` remain read-only. V6 inherits the fixed
50-paper order, 10-development/40-test split, and sampling design. Its legacy
candidate Gold inventory remains unchanged; contribution scoring binds a
separate named JSON-only selection.

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

The contribution-first target is active: `literature_hvs_contributions` v1
records paper-object contributions with grouped multivalue measurements, and
the benchmark runtime freezes and scores it through L0/L1a/L1b/L2a/L2b. The
original V6 50-paper sample is the approved fixed contribution benchmark
cohort. Its dev10 Gold migration is complete; the 40-paper complement remains
closed until its contribution Gold is migrated. No contribution performance
result exists yet, and reuse of this cohort is not an unseen-generalization
claim.

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
- The contribution Gold migration is AI-assisted. Its metadata and reporting
  must say paper-level expert approval, not independent manual extraction or
  item-by-item expert verification. Production extractor output must remain
  excluded from both preannotation and reconciliation.
- Dev10 migration is preserved by a private-repository checkpoint and legacy
  archives. The same preservation gate applies before migrating the remaining
  40 papers.

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
3. Run and score contribution dev10 only against its named immutable selection.
   Keep candidate-era scorecards separate and make no unseen-generalization
   claim from the reused cohort.
4. Migrate the remaining 40 papers with the same isolation, reconciliation,
   expert approval, preservation, and deterministic-save gates before opening
   full50 contribution scoring.
5. The remaining V6 test40 losses are eligibility-caliber disagreements
   (bound/marginally-bound survey-table members, bare-table-row anchors,
   prior-candidate reassessment, D6/runaway taxonomy) plus one model-side
   coordinate-format partial (2507.00150). Any rule change addressing them
   must be recalibrated on the dev split first, then validated by a new
   frozen run; system-side scoring repairs are exempt and stay covered by
   the superseding-scorecard chain.
