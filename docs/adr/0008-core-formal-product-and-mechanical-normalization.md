# ADR 0008: CORE as the formal product and a shared mechanical normalizer

- Status: Accepted
- Date: 2026-07-17

## Context

ADR 0007 froze the pre-change V3 baseline. The corrected dev evaluation then
showed that FULL enrichment and provenance defects could erase otherwise
usable scored-core output: one strict coupled FULL validation drove both the
formal L1/L2 product and the non-scored enrichment groups. Separately, the
deterministic normalization stage had grown past representation cleanup into
semantic bibliography selection (rewriting `bibkey` and `bibliography_refs`
from paper-source scans), letting code silently decide which citation was
correct, and Method C never applied the stage at all.

## Decision

1. The sealed CORE view is the only formal scored product. For a FULL run,
   sealing validates each paper twice: the `core_projection` (candidates with
   code-owned canonical empty enrichment defaults) must pass the CORE_PROV
   surface contract and the frozen validator — core identity, inclusion, the
   19 scored quantities, source evidence, and minimum method lineage stay
   blocking — while the untouched FULL document keeps strict FULL validation
   for the enrichment diagnostic. Non-scored enrichment findings are
   non-blocking for L1/L2 only; no validation is deleted.
2. `benchmark.run_manifest` v3 records the decoupled envelopes with
   `validation_mode` `full_core` / `full_enrichment`; enrichment validity
   requires core validity, both deliveries share missing papers, and the
   legacy top-level paper/artifact views still equal `core_delivery`.
   Historical `coupled_full` (v2) and `core_prov` envelopes remain readable
   and contract-valid as historical diagnostics. Formal B/C run creation
   still accepts only `core_prov` (ADR 0007).
3. Formal scoring consumes the `core_delivery` envelope. L1 identity and the
   L2 scored vocabulary read only `identifiers`/`core`, so a core-valid paper
   with invalid enrichment still contributes its core to L1/L2; core-invalid
   papers stay diagnostic-only.
4. The dev console reports CORE delivery and enrichment delivery as separate
   figures; they are never collapsed into one success rate.
5. Deterministic normalization is one shared, pure, representation-only
   function (`mechanical_normalization.normalize_mechanical_representation`)
   called identically by Methods B and C. It canonicalizes sexagesimal
   coordinate punctuation only. Semantic bibliography selection and any regex
   that decides which citation or scientific claim is correct are removed;
   those failures return to the model/reviewer through the validation/repair
   loop or surface as delivery limitations.

## Consequences

- Stella advances to 0.5.0 with current schema `benchmark.run_manifest` v3
  (v1/v2 remain readable). No other persisted artifact shape changes; the
  scorecard keeps reporting CORE delivery counts only.
- The recorded `normalizer` component hash now covers
  `mechanical_normalization.py`; seal/scoring fail closed on drift against
  runs recorded under the old boundary, as designed in ADR 0007.
- A wrong `bibkey` or malformed `bibliography_refs` is no longer repaired by
  code. It is model/reviewer work: the frozen validator and repair loop feed
  it back, and unresolved defects land in the enrichment diagnostic or as
  invalid deliveries.
