# ADR 0009: B-core as the primary method; Method C and FULL enrichment as legacy

- Status: Accepted
- Date: 2026-07-18

## Context

Three evaluation rounds compared Methods B and C on delivery, L1/L2 quality,
cost, and failure modes:

- V1 (gold8, FULL era, 3 runs each): both methods varied widely run to run;
  C's mean end-to-end was slightly higher but well inside overlapping
  variance.
- V2 corrected 10-paper dev evaluation: C CORE delivered the most papers and
  the greatest L1/L2 coverage, but one positive paper contributed nearly all
  of its false positives, and paper-bootstrap confidence intervals overlapped
  widely (see `docs/plans/2026-07-16-benchmark-bc-evaluation-hardening.md`).
- V3 dev baseline (core_prov): B delivered 8/10 papers with L1 micro F1 0.593
  and `delivery_end_to_end_strict` 0.556; C delivered 6/10 with F1 0.226
  (precision 0.171) and end-to-end 0.406.

Cost per successfully delivered paper in the V3 baseline: B used ≈0.7M
tokens and 3–9 LLM calls per paper when roster production/review and final
review are counted; C used ≈4.4M tokens and 23–440 calls per
paper — roughly 6× the tokens and an order of magnitude more network
exposures per delivery. Failure modes are asymmetric: B fails cheap and fast
(validator errors on the whole-response document), while only C exposes
multi-hour papers to transport failures with no mid-paper checkpoint — the
dense-table paper 1804.10179 consumed ≈11.6M tokens across three interrupted
hardened-C attempts without a delivery. C nevertheless has demonstrated
distinct capabilities on individual papers: baseline C delivered the dense
1804.10179 case, and the incomplete hardened-C run delivered 2401.02017 while
hardened B did not. These are real diagnostic signals, but not a stable
aggregate advantage.

The post-architecture hardened-B run also regressed to 7/10 delivery, L1 F1
0.286, and L2 end-to-end 0.248. Its roster reviewers all returned `accepted`
with zero challenges, so the evidence does not support attributing the recall
loss to reviewer over-tightening. The new roster architecture is therefore not
accepted yet and requires B-only root-cause analysis.

The available dev evidence does not scientifically prove that C is inferior.
It is sufficient for an engineering priority decision: B is simpler, cheaper
per experiment, and easier to debug, while C's present cost and network
fragility are not justified by a stable aggregate gain.

## Decision

1. Method B with the core_prov surface (B-core) is the primary formal
   extraction method. Optimization, prompt/rule iteration, and the
   pre-registered validation effort concentrate on B-core.
2. Method C becomes a legacy method. Its contract, code, and historical runs
   remain readable and reproducible, and its interfaces (agentic tool loop,
   bounded read-tool reviewer orchestration) are kept for possible future
   extension. Normal workflows and the dev console cannot create, resume, or
   retry it. Direct CLI reproduction requires explicit legacy opt-in. No new
   formal Method C run is started without an explicit new decision.
3. FULL enrichment remains a legacy diagnostic surface. New workflows and the
   dev console expose only `core_prov`; direct CLI reproduction requires an
   explicit FULL legacy opt-in. Formal scoring still consumes only the CORE
   delivery (ADR 0008).
4. This decision does not alter the frozen v3 sample, the dev/test boundary,
   gold handling rules, or the sealed 40-paper test split. When a test run is
   authorized, it uses B-core.
5. In-flight v3 dev artifacts remain immutable diagnostics. The hardened-C run
   is intentionally preserved incomplete, unsealed, and unscored; it is not
   scheduled for completion. Historical artifacts are not migrated or
   rewritten by this decision.

## Consequences

- The B/C hardening plan
  (`docs/plans/2026-07-16-benchmark-bc-evaluation-hardening.md`) re-centers:
  its Task 7 pre-registered validation sequence is interpreted as B-core
  validation; Method C acceptance criteria are retired unless Method C is
  reactivated by a new ADR.
- Expert adjudication (hardening plan Task 6) and the possibly-unbound
  boundary question are method-neutral and unchanged.
- The hardened-B regression blocks acceptance of the roster-review
  architecture. The next engineering task is paper/stage root-cause analysis,
  followed by a minimal B/Core cold-cache validation.
- Method A's status is unchanged: separate execution plan once the unified
  adapter exists.
- Legacy means maintained readability and contract validity, not active
  optimization. Method C defects are documented as known limitations rather
  than fixed, unless they block reproduction of historical runs.
