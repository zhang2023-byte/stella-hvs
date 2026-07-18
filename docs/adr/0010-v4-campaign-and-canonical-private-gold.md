# ADR 0010: V4 campaign with one canonical private gold store

- Status: Accepted
- Date: 2026-07-19

## Context

The public scientific inclusion boundary and the canonical expert judgment for
candidate membership changed after V3 froze. Under the versioning policy, old
and new scores no longer measure an identical contract, so the frozen V3
campaign cannot be mutated or receive new formal runs.

The paper cohort does not need to change. V3 already contains the intended
fixed 50-paper order and proxy-balanced 10-dev/40-test split. Resampling would
introduce an unnecessary second change and weaken comparability.

Gold annotations are not campaign-owned scientific copies. The external
private repository selected by `STELLA_GOLD_DIR` is the one canonical gold
store, with its own private Git history. A public campaign may bind a frozen
state of that store only through a value-free, hash-only integrity index.

## Decision

1. Create `hvs-extraction-v4` and make it the only active, writable campaign.
   V1, V2, and V3 remain read-only history.
2. Generate V4's sampling manifest by byte-for-byte reuse of V3's committed
   public sampling manifest. Generate the V4 campaign manifest with the
   maintained builder. The paper order and 10-dev/40-test split do not change.
3. Do not create a second private campaign gold tree. Human annotation always
   reads and writes the single canonical `$STELLA_GOLD_DIR`.
4. Do not create V4 `gold_manifest.json` during public campaign setup. A fresh,
   isolated gold-authorized task may later generate V4's hash-only index from
   the canonical private store after the intended expert state is complete.
5. Before any engineering repair, run one formal V4 Method B + `core_prov` dev
   baseline from the clean V4 establishment commit with an independent empty
   roster cache, then audit and seal it. Scoring is a separate gold-only task.
6. Method C and FULL remain legacy read-only history and are not run for V4.

## Consequences

- V3 results remain historically interpretable under their frozen scientific
  contract; V4 results are not silently mixed with them.
- V4 preserves cohort continuity while changing only the campaign meaning that
  required a new ID.
- Public campaign setup remains possible in a strict no-gold context.
- The public hash index records integrity and snapshot identity, not ownership
  of a second canonical gold dataset.
- Extraction, audit/seal, and scoring remain separate contamination domains.
