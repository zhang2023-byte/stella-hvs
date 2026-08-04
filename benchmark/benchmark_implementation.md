# Benchmark Implementation Status

Status owner: current benchmark implementation, observed development results,
known defects, and the next engineering gate. Update this file whenever the
active campaign, current result, implementation blocker, or next gate changes.

## Current state

Stella 0.8.0 keeps the staged roster-plus-core-field extractor as the canonical
`hvs_candidate_extraction` workflow. `hvs-extraction-v6` is the only writable
campaign. It mechanically inherits V5's 50-paper order, fixed
10-development/40-test split, sampling weights, and gold hash without
resampling or changing expert judgment.

V6 is in **development hardening** and is **not test-ready**. V1-V5 remain
readable history. The 25 pre-promotion experimental runs and their logs,
evaluations, diagnostics, probes, locks, and file hashes are preserved in the
read-only `hvs-extraction-scratch-legacy` campaign and cannot enter V6 scores.

New terminal runs store L0 format counts and normalized roster/core-field usage,
then automatically write an immutable `run_cost.json` bound to the active
TokenDance CNY snapshot. Formal scorecards use the version-7
L0/operations/L1/L2 envelope with no composite score. Estimated API cost never
enters quality scoring. Historical runs and scorecards are not migrated,
overwritten, or rescored.

The generated legacy dev10 cost inventory covers 21 explicitly audited
end-to-end runs across scratch and V2-V5. Under
`tokendance-2026-08-03-screenshots-v1`, recorded telemetry totals 168,363,279
tokens and a known CNY subtotal of 304.552747. One scratch run is marked as
reconstructed from its ten paper artifacts because its final top-level config
and summary were later overwritten by a one-paper attempt. Partial telemetry
remains visibly partial rather than being converted to zero cost.

The public V6 gold assignment preserves V5's primary/additional annotator
mapping. After explicit authorization, `dev-primary-v1` was rebound to V6 for
the complete 10-paper development split without changing private annotation
files or their hashes. The immutable
`tokendance-2026-08-03-screenshots-v1` snapshot covers the current
`bigmodel/glm-5.2` and `deepseek/deepseek-v4-pro` routes plus six flat-priced
comparison routes. All eight entries use the provider-specific input, output,
and cached-input rates visible in the authorized screenshots. The tiered
`minimax/minimax-m3` schedule is preserved as a deferred route and deliberately
does not satisfy scoring coverage until per-request prompt-length telemetry can
select its `<=512K` or `>512K` tier. No screenshot, authentication, or account
data is stored.

The canonical deliverable is a v3 core artifact. It keeps a successful roster
even when field extraction fails, so candidate identity remains available to
L1 and the missing fields are visible in L2. Full-field and method-chain work
are separate supplements bound to an immutable core hash; no real supplement
model adapter is registered yet.

The independent comparison path is `coding_agent_baseline`. It receives the
same archived paper boundary, science rules, and v3 output contract, but does
not reuse staged intermediate artifacts.

## Latest development evidence

The last pre-promotion dev10 run completed and was scored:

| Measure | Result |
|---|---:|
| Paper delivery | 6 / 10 |
| L1 precision / recall / F1 | 0.941 / 0.681 / 0.790 |
| L2 delivered rows / gold rows | 20 / 164 |
| L2 coverage | 0.122 |

This is better than the earlier direct-writer core baseline on several
candidate-discovery measures, but it does **not** establish a stable
development workflow. Four papers were unavailable. The roster stage was the
dominant bottleneck: initial structured submission was not reliable enough,
and no downstream field logic can recover candidates after a whole-roster
failure.

The run also exposed:

- a gap between the intended explicit group-wide probability rule and model
  behavior in at least one eligible table;
- incorrect uncertainty direction in some extracted quantities;
- incomplete aggregation of repair and usage records from failed papers;
- repeated physical request indices on correction attempts.

### Targeted GLM-5.2 thinking-control evidence

On 2026-07-30, six immutable targeted-development runs compared two repeats
of three GLM-5.2 roster configurations on `2209.03560` (three gold
candidates) and `2602.16925` (gold negative). DeepSeek V4 Pro core-field
extraction and all prompts, rules, budgets, and worker settings were fixed.
The code revision was `c94a833`.

| Roster configuration | L1 delivery | Positive-paper recall by repeat | Negative-paper delivery | Format corrections | Roster tokens | Reasoning tokens | Total run wall time |
|---|---:|---:|---:|---:|---:|---:|---:|
| thinking disabled | 4 / 4 | 1 / 2 | 2 / 2 | 0 | 100,943 | 0 | 77.761 s |
| thinking enabled, effort high | 4 / 4 | 2 / 2 | 2 / 2 | 0 | 129,682 | 28,222 | 526.005 s |
| thinking enabled, effort max | 2 / 4 | 1 / 2 | 1 / 2 | 2 | 491,175 | 344,719 | 3,524.065 s |

The formal scorer correctly rejected these targeted runs because formal V5
scoring accepts only a complete dev10. A private-gold, read-only diagnostic
over the two frozen papers found repeat-pooled L1 recall and L2 coverage of
0.5/0.5 for thinking disabled, 1.0/1.0 for effort high, and 0.5/0.5 for
effort max, with no false-positive candidates. These are diagnostic results,
not formal V5 scores.

Effort `max` is rejected as a roster default: both failed paper-attempts used
64,000 reasoning tokens on the initial request and another 64,000 on the
same-setting format correction without producing a submission tool call.
Thinking disabled removed the structured-submission failure and was fast, but
its positive-paper decision varied across repeats. Effort `high` is the
provisional route to expand on additional hard development papers; it was
scientifically stable in this small comparison but remained materially slower
than disabled thinking.

The experiment also showed that revision `c94a833` reset
`physical_request_index` to one for a roster format correction when no
field-style shared budget was supplied. The archived runs preserve that
bookkeeping defect. Revision `2805226` shares a six-request counter across the
roster initial and format-correction logical calls without reducing the
existing maximum of three transport attempts per logical call. The full-dev
repeats below showed that the evidence-correction path still creates a fresh
counter, however, so an initial request and its evidence correction can both
be recorded as physical request one. A failed evidence correction also omits
its repair history from the terminal failure envelope, causing the operational
summary to undercount evidence corrections even though attempts and usage are
preserved. The scientific behavior gaps and these remaining bookkeeping
defects must be measured and fixed on new immutable runs.

The following controls behaved as intended and are retained:

- one shared maximum of three physical field requests per candidate, including
  transport retry and correction requests;
- deterministic reviewed-group retention for unresolved “and others” groups;
- safe progress logging without credentials, full contexts, model replies, or
  hidden reasoning;
- immutable run IDs, atomic configuration creation, and no selective resume or
  score splicing;
- TeX-authoritative interpretation with optional, path-confined ECSV addressing.

### Full dev10 GLM-5.2 high repeats

On 2026-07-30, three immutable complete-development runs expanded the frozen
`thinking=enabled, reasoning_effort=high` roster route to all ten development
papers. The method fingerprint was
`123b28e6448f2471074400dbce85bd76abcf15a7e8b205c569f0526e35be4342`,
the code revision was `a424472`, and DeepSeek V4 Pro remained fixed for core
fields. All three run manifests, ordered L1/L2 coverage, and 60 recorded
paper-artifact hashes were independently verified.

| Repeat | Paper delivery | L1 precision / recall / F1 | L2 coverage | L2 strict agreement over compared rows | API calls | Tokens | Wall time |
|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | 10 / 10 | 0.959 / 1.000 / 0.979 | 0.665 | 0.991 | 76 | 2,765,956 | 1,842.179 s |
| 2 | 9 / 10 | 1.000 / 0.957 / 0.978 | 0.634 | 1.000 | 66 | 2,255,977 | 1,783.545 s |
| 3 | 8 / 10 | 1.000 / 0.957 / 0.978 | 0.701 | 1.000 | 67 | 2,384,011 | 2,816.911 s |

Candidate identity was strong when a roster was delivered, but delivery
degraded across repeats and therefore the route is not stable:

- `1804.10179` delivered the same 30/30 true-positive roster in all three
  repeats, but only 4/34 gold core quantities were strictly delivered each
  time.
- `1807.00427` delivered 3/3 true-positive candidates in every repeat, while
  field completion varied from 1/3 to 2/3 to 3/3.
- `1902.05061` delivered 2 true positives and 2 false positives in repeat one,
  then failed its roster evidence correction in repeats two and three. The
  failures were respectively `evidence_validation_failure` and
  `correction_drift`, producing two false negatives in each failed repeat.
- `2209.03560` delivered 3/3 candidates and 24/24 strict core quantities in
  all repeats, but repeat three needed a roster format correction and took
  1,007.772 seconds.
- `2401.02017` delivered 9/9 candidates and 54/54 strict core quantities in
  all repeats, but seven of nine field calls required format correction in
  every repeat.
- All delivered negative-paper rosters were empty with zero false-positive
  candidates. `2304.11269` nevertheless became a delivery failure in repeat
  three after both the initial and format-correction calls failed structured
  submission. `2602.16925` was scientifically empty in all repeats, but its
  wall time varied from 43.118 to 962.601 seconds and repeat one required a
  format correction.

The terminal operational summaries recorded 29 format corrections, 9 evidence
corrections, 31 tail-truncation salvages, 209 physical API attempts, and
7,405,944 tokens. The request ledgers show two additional failed roster
evidence corrections, so the actual evidence-correction count is 11. This
discrepancy is the failure-envelope accounting defect described above, not a
change to the scientific scores.

### DeepSeek V4 Flash full-dev comparison

On 2026-07-31, two immutable complete-development runs used the production
`deepseek-v4-flash-0731` route for both roles. Roster thinking was enabled and
compared `reasoning_effort=max` with `reasoning_effort=high`; core-field
extraction was fixed at `reasoning_effort=low`. Temperature, prompts, rules,
budgets, worker settings, and the shared three-request field policy were fixed.
The code revision was `0dfe34d`, and the two method fingerprints differed only
in the roster effort setting.

The gateway rejects forced `tool_choice` while V4 Flash thinking is active.
The declared route therefore exposes exactly one typed submission tool without
forcing it; the local contract still requires exactly one matching tool call
and sends missing calls through the bounded correction path. Authorized
capability probes and both formal runs confirmed typed tool submission at all
three requested effort settings.

| Roster effort | Paper delivery | L1 precision / recall / F1 | L2 coverage | L2 strict agreement over compared rows | L2 strict end-to-end delivery | API calls | Tokens | Wall time |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| max | 10 / 10 | 0.940 / 1.000 / 0.969 | 0.945 | 0.994 | 0.939 | 80 | 2,507,961 | 906.728 s |
| high | 9 / 10 | 0.959 / 1.000 / 0.979 | 0.866 | 0.993 | 0.860 | 79 | 2,372,727 | 1,321.462 s |

Both routes recovered all 47 gold candidates and kept all five delivered
negative papers free of false positives. The `max` route added three false
positive candidates: two on `1902.05061` and one on `2209.03560`. The `high`
route added two: one on each of those papers. Disabling coordinate matching did
not change either L1 result.

The `max` route delivered 154 strict matches and one within-gold-error match
over 164 gold quantities, with nine `gold_only` and two `ai_only` rows. It had
no value, unit, or limit-kind mismatch. The `high` route delivered 141 strict
matches, with 22 `gold_only`, two `ai_only`, and one limit-kind mismatch. Its
loss came from one roster transport failure on `1807.02028` and one field
failure each on `1804.10179` and `1902.05061`; transport retries consumed the
shared request budget in both field failures. The failures remain frozen and
were scored as unavailable or missing L2 values rather than retried away.

These runs share the campaign, split, and gold snapshot with the three GLM-5.2
high repeats. The V4 Flash configurations achieved substantially higher L2
coverage than the GLM-plus-DeepSeek-V4-Pro repeats (0.866-0.945 versus
0.634-0.701). This is a full-pipeline comparison, not an isolated roster-model
claim: the core-field model and V4 Flash structured-output contract changed at
the same time. L1 is mixed rather than uniformly better: V4 Flash `high`
matches the best GLM repeat at 47 true positives and two false positives,
whereas V4 Flash `max` trades one additional false positive for complete paper
and field delivery in this single repeat.

## Next gate

1. Do not promote V4 Flash `max` from one complete run. Repeat the exact
   immutable configuration before treating its 10/10 delivery and 0.945 L2
   coverage as stable; compare roster false positives, transport failures,
   corrections, cache telemetry, and cost across repeats.
2. Share the roster request budget with evidence correction, preserve failed
   repair history, and add regression tests for monotonic physical request
   indices and correction totals from failed papers.
3. Add general fixtures for the observed group-wide probability,
   uncertainty-direction, limit-kind, and structured-submission failures; do
   not add paper IDs, object names, or table-specific exceptions.
4. Diagnose V4 Flash's extra positive-paper candidates and its remaining
   `gold_only` probability rows through general inclusion and group-statement
   rules. Do not change accepted candidate identity from gold-aware diagnosis.
5. Decide explicitly whether transport retries should continue consuming the
   same three-request scientific correction budget. Any policy change requires
   a new method fingerprint and immutable run IDs.
6. Keep the 40-paper test closed until the workflow is stable, method inputs
   are frozen, and an explicit test release is authorized.

The generated private-gold report may visualize current scorecards and failure
trends, but it remains beside the external gold store. Item-level gold content
and rendered paper comparisons must never move into this repository.

<!-- BEGIN GENERATED: benchmark-history-comparison -->
Historical V4 scorecards remain useful context but are not V5 runs:

| Metric | Higher-delivery V4 run | Lower-delivery V4 run |
|---|---:|---:|
| Valid paper delivery | 7 | 6 |
| L1 precision | 0.833 | 1.000 |
| L1 recall | 0.106 | 0.064 |
| L1 F1 | 0.189 | 0.120 |
| L2 coverage | 0.305 | 0.201 |
| L2 strict agreement | 0.980 | 1.000 |
| L2 strict end-to-end delivery | 0.299 | 0.201 |
<!-- END GENERATED: benchmark-history-comparison -->
