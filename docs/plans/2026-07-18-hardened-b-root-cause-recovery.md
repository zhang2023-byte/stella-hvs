# Hardened-B Root-Cause Audit and Recovery Plan

**Status:** first 0.5.1 implementation batch complete; expert gate and any new run remain pending

**Scope:** Compare the V3 pre-architecture Method B baseline with the first
post-architecture hardened-B validation without reading private gold or
changing either sealed run.

**Runs:**

- `v3-dev-baseline-b-core-r1` at `fd1bea5`
- `v3-dev-hardened-b-core-r1` at `48be612`

## Result

The hardened-B regression is not one roster-review failure. It is the sum of
two independent headline-metric losses plus two delivery limitations:

1. `2209.03560` changed from a three-candidate roster to `no_candidates` even
   though the roster producer prompt, rule profile, context, extractor model,
   and provider were identical. The new independent reviewer accepted the
   empty roster with no challenge. This is a scientific-boundary/repeatability
   failure and cannot be repaired by assuming that the reviewer removed
   candidates.
2. `1902.05061` preserved the same three-member roster but became unavailable
   because targeted candidate repairs were rejected whenever the model changed
   any non-record identifier evidence. A later archived repair had fixed the
   coordinate units; replacing its generated identifiers with the sealed
   roster identifiers reduces batch structure errors from two to zero and the
   full validator errors from six to one. The remaining source-line error would
   then be eligible for the normal next repair round.
3. `2401.02017` preserved the same nine-member roster but failed before the
   first batch was accepted. Its first eight-candidate response passed the
   candidate schema but was rejected by eight full-identifier equality errors.
   Restoring code-owned sealed identifiers reduces those structure errors to
   zero. This is the clearest general engineering defect.
4. `1804.10179` remained unavailable in both runs. The roster stayed at 30,
   but hardened-B ended with 45 validator errors rather than 13. This did not
   cause the score delta, but it means the dense-paper acceptance criterion is
   still unmet.

The public scorecard delta is therefore explained as follows: the five lost
true positives are the three `2209.03560` candidates and two matched
`1902.05061` candidates. `2401.02017` and `1804.10179` were unavailable in
both scorecards and do not explain the numeric delta, although their failure
modes still block architecture acceptance.

## Per-paper stage comparison

| Paper | Baseline-B | Hardened-B | First material difference |
|---|---|---|---|
| `1804.10179` | 30 roster, validator errors | 30 roster, validator errors | Same membership; error burden increased after semantic normalizer removal and stricter evidence preservation |
| `1807.00427` | 3 roster, ok | 3 roster, ok | No delivery regression |
| `1807.02028` | 0 roster, ok | 0 roster, ok | No difference |
| `1902.05061` | 3 roster, ok | 3 roster, validator errors | Batch repairs fixed fields but were discarded for non-record identifier drift |
| `2209.03560` | 3 roster, ok | 0 roster, ok | Identical roster contract produced the opposite scientific boundary decision; reviewer accepted it |
| `2304.11269` | 0 roster, ok | 0 roster, ok | No difference |
| `2401.02017` | 9 roster, validator errors | 9 roster, batch failed | Full identifier equality rejected otherwise schema-valid batch replies |
| `2403.03311` | 0 roster, ok | 0 roster, ok | No difference |
| `2507.07558` | 0 roster, ok | 0 roster, ok | No difference |
| `2602.16925` | 0 roster, ok | 0 roster, ok | No difference |

## Evidence for the `2209.03560` boundary

Both runs recorded:

- roster prompt SHA256 `720f9e7bcdf075cba77f8dc5a0366c3e45c2cf3a39cff4515cd6437b48c98594`;
- roster rule SHA256 `7f5379a4dcdac881cc84938bac7a3c26d0c1658dcd4e4924f2c3bdbae9943415`;
- context SHA256 `1a26a4bf9e96dc638cf9b4c6aff9264a6d583f59b78823f339460f6f7c892a4b`;
- extractor `deepseek-v4-pro` on provider preference `deepseek`;
- temperature 0 and no roster-cache hit.

The baseline interpreted a retained multi-potential scenario as “possibly
unbound”; the hardened run interpreted the paper's final preferred-potential
conclusion as excluding every candidate. Temperature 0 does not make an LLM
scientifically deterministic, and the roster reviewer did not resolve the
ambiguity: it accepted the producer's empty roster. This must pass the Task 6
expert gate before any general rule change.

## General engineering defect

`batch_structure_errors()` correctly protects count, order, and `record_id`,
but the hardened implementation also requires the entire generated
`identifiers` object—including aliases and source-reference text—to be bytewise
equal to the sealed roster stub. Candidate-fill and repair models repeatedly
returned the same ordered record IDs while refreshing identifier evidence.
The pipeline discarded the complete reply instead of treating the sealed
identifiers as code-owned immutable data.

This is an orchestration defect, not a scientific-rule defect. The safe repair
is deterministic hydration:

1. Require the candidate count and ordered `record_id` values to match the
   sealed batch exactly. A mismatch remains a hard rejection.
2. Once those identity anchors match, overwrite each returned `identifiers`
   object with a deep copy of the corresponding sealed roster identifiers
   before schema/validator checks.
3. Record the number/paths of restored identifier objects in the stage log.
4. Apply the same helper to initial batch fill, validator-driven targeted
   repair, and final-review-driven repair.
5. Do not relax candidate, source, method-ref, or full-document validation.

This keeps membership immutable and prevents model-generated identifier drift
from consuming repair rounds. It is consistent with the existing hardening
rule that exact code-owned identifier propagation is permitted mechanical
normalization.

## Completed 0.5.1 implementation batch

### Task 1: Add failing synthetic tests

- Add a unit test proving count/order/record-ID mutation remains rejected.
- Add a unit test proving non-record identifier drift is restored from the
  sealed stub.
- Add integration tests for both initial batch fill and a targeted repair,
  proving the final artifact retains the sealed identifiers without extra LLM
  retries.

### Task 2: Implement deterministic sealed-identifier hydration

- Add one shared helper in `src/stella/benchmark/extraction_run.py`.
- Invoke it before `batch_structure_errors()` in all three batch-acceptance
  paths.
- Add bounded structural stage-log evidence; do not persist model-proposed
  identifier changes.

### Task 3: Version and verify

- Treat this as a non-breaking bug fix and advance the Stella patch release to
  `0.5.1` according to `docs/versioning-policy.md`; no artifact-schema or
  campaign change is required.
- Regenerate `docs/versions.md` and update release notes.
- Run targeted extraction tests, generated-view checks, the full Python suite,
  frontend tests/build if UI assets change, and `git diff --check`.

### Verification checkpoint

- Synthetic initial-fill, validator-repair, and final-review-repair tests pass
  with sealed identifiers restored and no extra model retry.
- Count, order, and `record_id` mutation tests remain hard failures.
- Offline replay reduced every parseable identifier mismatch in the archived
  `1902.05061` batch replies to zero. Each archived `2401.02017` first-batch
  reply went from eight identifier mismatches to zero.
- `763` Python tests, generated extraction-rule/schema checks, `compileall`,
  and `git diff --check` pass. No frontend source or generated asset changed,
  so a frontend rebuild was not required.
- No LLM/API call, private-gold read, run mutation, seal, score, or test release
  occurred during implementation or verification.

## Expert gate before another formal run

After the engineering fix, prepare the `2209.03560` Task 6 decision from the
paper PDF only. The expert must decide the general rule: whether an object
remains inside “possibly unbound” when one reasonable analyzed Galactic
potential leaves it above escape speed but the paper's preferred/final model
calls it bound. If that decision changes candidate meaning or existing gold,
create a new campaign rather than mutating V3.

No new LLM run, gold edit, seal, score, or test release is authorized by this
audit alone. After the expert gate and frozen code, run one fresh B/Core dev
repeat with a new run ID and an isolated empty roster cache.
