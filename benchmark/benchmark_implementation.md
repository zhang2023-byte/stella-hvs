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

### V6 V4 Flash max repeats and core-field effort ladder

On 2026-08-05, ten immutable complete-development runs were executed in
`hvs-extraction-v6`, all formally scored against the
same `dev-primary-v1` gold selection profile
(`selection_manifest_sha256=0dfc49c85980…`) and bound to
`tokendance-2026-08-03-screenshots-v1`. The roster route was fixed at V4 Flash
`thinking=enabled, reasoning_effort=max`; only the core-field reasoning
controls varied. Seven runs at code revision `48f8be6` form the effort
ladder: one scored field-low repeat set
(three runs, method fingerprint `7263e44c…`, identical to the 2026-07-31 V5
max run), one scored field-high set (three runs, fingerprint `f2278835…`),
and one scored field-max run (fingerprint `ce31858a…`). Three further runs
at code revision `33f2ac2` (which added the `--core-field-thinking` freeze
knob) disable core-field thinking entirely (fingerprint `2a7adab0…`).

| Field effort | Run | L0 roster / core delivery | L1 micro P / R / F1 | L2 coverage | L2 strict agreement | L2 strict end-to-end | gold_only | API calls | Tokens | Wall time | Cost (CNY) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| low | r1 | 10 / 10 | 0.979 / 1.000 / 0.989 | 0.982 | 0.994 | 0.976 | 3 | 67 | 2,540,366 | 735.1 s | 1.569447 |
| low | r2 | 10 / 9+1 | 0.959 / 1.000 / 0.979 | 0.860 | 0.993 | 0.854 | 23 | 71 | 2,696,304 | 713.9 s | 1.003966 |
| low | r3 | 10 / 10 | 0.978 / 0.936 / 0.957 | 0.780 | 0.984 | 0.768 | 36 | 64 | 2,292,742 | 653.4 s | 0.803300 |
| high | r1 | 10 / 9+1 | 0.959 / 1.000 / 0.979 | 0.878 | 0.986 | 0.866 | 20 | 79 | 3,067,884 | 811.8 s | 1.443909 |
| high | r2 | 10 / 6+4 | 0.959 / 1.000 / 0.979 | 0.683 | 0.991 | 0.677 | 52 | 81 | 3,399,551 | 1,054.7 s | 1.379919 |
| high | r3c | 10 / 6+4 | 0.959 / 1.000 / 0.979 | 0.652 | 1.000 | 0.652 | 57 | 99 | 3,733,359 | 1,288.6 s | 1.478623 |
| max | r1 | 10 / 7+3 | 0.978 / 0.936 / 0.957 | 0.543 | 0.989 | 0.537 | 75 | 90 | 2,979,376 | 1,184.3 s | 1.584408 |
| nothink | r1 | 10 / 9+1 | 0.940 / 1.000 / 0.969 | 0.744 | 1.000 | 0.744 | 42 | 69 | 2,540,889 | 662.3 s | 0.657283 |
| nothink | r2 | 10 / 9+1 | 0.959 / 1.000 / 0.979 | 0.768 | 0.992 | 0.762 | 38 | 66 | 2,423,894 | 645.5 s | 0.574688 |
| nothink | r3 | 10 / 9+1 | 0.959 / 1.000 / 0.979 | 0.726 | 1.000 | 0.726 | 45 | 72 | 2,701,117 | 634.3 s | 0.615251 |

Two further field-high runs are frozen as operational history and were not
scored: `…-high-r3-20260805` was interrupted mid-run by provider quota
exhaustion (HTTP 402 `insufficient_quota`, six roster requests rejected in
under six seconds each, 4/10 delivered), and `…-high-r3b-20260805` exhausted
the remaining quota entirely (0/10, zero tokens). Neither is scientific
evidence; `r3c` is the replacement repeat.

Findings:

- Roster-level paper delivery was 10/10 in all ten scored runs, but L2
  coverage under the field-low fingerprint is not stable across repeats
  (0.945, 0.982, 0.860, 0.780 including the V5 original). The single V5
  10/10-and-0.945 result must not be promoted.
- Core-field reasoning effort degrades L2 monotonically from low upward:
  coverage ranges are 0.780-0.982 (low), 0.652-0.878 (high), 0.543 (max).
  Higher effort lowers V4 Flash structured-submission reliability (first-pass
  format validation 0.98-1.0 at low, 0.576 at high r3c, 0.648 at max), so
  format corrections consume the shared three-request field budget and
  failures surface as `gold_only` rows (up to 75 at max).
- Disabling core-field thinking entirely does not extend that trend: the
  no-think repeats land at 0.726-0.768 coverage, below the field-low range,
  with 38-45 `gold_only` rows and first-pass format rates of 0.864-0.949.
  Zero field reasoning tokens confirm the switch took effect. The
  effort-coverage relationship is therefore non-monotonic at the bottom, and
  field-low remains the best observed route. No-think is the cheapest
  configuration (0.575-0.657 CNY) because the field stage emits no reasoning
  tokens.
- `2209.03560` returned a false-empty roster twice (field-low r3 and
  field-max r1), each time costing exactly its three gold candidates. This
  roster decision variance is independent of the field configuration.
- `1902.05061` produced one or two false-positive candidates in every scored
  run of both campaigns; in all three no-think runs it was also the single
  partial paper, with the same two candidates failing field extraction. All
  delivered negative-paper rosters remained empty.
- L2 strict agreement over compared rows stayed high (0.984-1.000)
  regardless of effort; the quality loss is a delivery problem, not a
  value-accuracy problem.

### V6 field-low repeat pool expansion (r4-r9)

On 2026-08-05, six further immutable complete-development repeats of the
field-low fingerprint `7263e44c…` were executed at code revision `48f8be6`
(the same revision as the three existing V6 field-low runs) and formally
scored against `dev-primary-v1` (`selection_manifest_sha256=0dfc49c85980…`),
bound to `tokendance-2026-08-03-screenshots-v1`. The field-low pool is now
ten runs: the 2026-07-31 V5 original (revision `0dfe34d`) plus nine V6
repeats at `48f8be6`.

| Run | L0 roster / core delivery | L1 micro P / R / F1 | L2 coverage | L2 strict agreement | L2 strict end-to-end | gold_only | API calls | Tokens | Wall time | Cost (CNY) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| r4 | 10 / 10 | 0.959 / 1.000 / 0.979 | 0.939 | 0.987 | 0.927 | 10 | 73 | 2,663,808 | 965.3 s | 0.798233 |
| r5 | 10 / 8+2 | 0.959 / 1.000 / 0.979 | 0.896 | 0.986 | 0.884 | 17 | 66 | 2,522,096 | 890.5 s | 0.790407 |
| r6 | 10 / 10 | 0.979 / 1.000 / 0.989 | 0.957 | 0.987 | 0.945 | 7 | 64 | 2,362,384 | 735.1 s | 0.732233 |
| r7 | 10 / 10 | 0.940 / 1.000 / 0.969 | 0.951 | 0.994 | 0.945 | 8 | 67 | 2,583,796 | 788.7 s | 0.858818 |
| r8 | 10 / 10 | 0.979 / 1.000 / 0.989 | 0.970 | 0.981 | 0.951 | 5 | 69 | 2,629,408 | 772.1 s | 0.821473 |
| r9 | 10 / 9+1 | 0.940 / 1.000 / 0.969 | 0.951 | 0.987 | 0.939 | 8 | 71 | 2,778,002 | 793.2 s | 0.833645 |

Findings:

- Across the ten-run field-low pool, L2 coverage spans 0.780-0.982 and nine
  of ten runs recovered all 47 gold candidates (L1 recall 1.000). The single
  recall exception remains the `2209.03560` false-empty roster in the
  earlier field-low r3 (recall 0.936); it did not recur in the six new
  repeats.
- L1 false positives stayed at 1-3 per run; all delivered negative-paper
  rosters remained empty in every pool run.
- L2 strict agreement over compared rows stayed 0.981-1.000; the residual
  quality loss is delivery (`gold_only` 5-17 rows in the new runs), not
  value accuracy.
- Cost per repeat was 0.732-0.859 CNY with no quota interruptions.

### DeepSeek V4 Pro json_object roster repeats

On 2026-08-05, three immutable complete-development runs used DeepSeek V4
Pro for both roles at code revision `48d5cb9` (fingerprint `77a0e206…`),
formally scored against the same `dev-primary-v1` profile and pricing
snapshot. The roster route was V4 Pro `thinking=enabled,
reasoning_effort=max` over the roster-scoped `json_object`
content-submission contract (new `--roster-mode` freeze knob; the frozen
roster prompt hash matches the content-submission variant). The field role
kept the declared V4 Pro tool-submission contract, which injects
thinking-disabled, so core fields ran without reasoning. Two authorized
synthetic capability probes at effort `max` over streaming transport
returned exactly one schema-valid JSON object each before the formal runs.

| Run | L0 roster / core delivery | L1 micro P / R / F1 | L2 coverage | L2 strict agreement | L2 strict end-to-end | gold_only | API calls | Tokens | Wall time | Cost (CNY) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| r1 | 8 / 7+1 | 1.000 / 0.319 / 0.484 | 0.610 | 1.000 | 0.610 | 64 | 34 | 1,229,759 | 1,382.5 s | 2.933059 |
| r2 | 9 / 8+1 | 1.000 / 0.894 / 0.944 | 0.488 | 1.000 | 0.488 | 84 | 64 | 1,961,293 | 879.0 s | 1.395967 |
| r3 | 8 / 7+1 | 1.000 / 0.255 / 0.407 | 0.421 | 1.000 | 0.421 | 95 | 42 | 881,849 | 1,299.4 s | 1.149515 |

Findings:

- The V4 Pro roster produced zero false-positive candidates and perfect L2
  strict agreement (1.000) in all three runs, but roster terminal delivery
  is unstable and dominant: `1902.05061` failed with
  `extractor_terminal_failure` in all three repeats and `1804.10179` failed
  in two of three. When `1804.10179` succeeded (r2) it delivered the full
  30/30 true-positive roster.
- L1 recall spans 0.255-0.894 and L2 coverage 0.421-0.610, far below the
  field-low pool (recall 0.936-1.000, coverage 0.780-0.982). The V4 Pro
  json_object roster route is rejected as a candidate; the roster role
  stays on V4 Flash `thinking=enabled, reasoning_effort=max`.

### 2026-08-16 correction hardening, null-reconciliation rule, and provider degradation

Code revision `0ff0992` hardened the bounded-call correction messages (the
corrected submission must remain complete and apply each stated remedy,
including explicit nulls) and added canonical field rule
`hvs.field.null_reconciliation` (re-check every null core field against
identifier/qualification source lines, table captions and notes, and explicit
group-level statements). Value-free synthetic fixtures with deformation
coverage were added for group-statement propagation, letter-marked
sexagesimal coordinates, empty-quantity submissions, and mixed uncertainty
forms. The method fingerprint changed to `1881d237…`.

Three immutable runs were executed on 2026-08-16 and are frozen as
operational history; none is promotable evidence:

| Run | Code | Fingerprint | Delivered | Field candidate failures | Roster failures |
|---|---|---|---:|---:|---|
| `…field-low-presence-r1-20260816` | `0ff0992` | `1881d237…` | 8 / 10 | 6 | 2 (`1807.00427`, `1902.05061`) |
| `…field-low-presence-r2-20260816` | `0ff0992` | `1881d237…` | 8 / 10 | 2 | 2 (`1807.00427`, `1902.05061`) |
| `…field-low-r10-20260816` (same-day control) | `48f8be6` | `7263e44c…` | 6 / 10 | 0 | 4 (roster-terminal) |

The same-day control at the unchanged August-5 baseline configuration also
failed 4 papers at the roster stage with the same failure family
(`identifier_not_verbatim`, `correction_drift`, `malformed_arguments`), a
failure mode that never occurred in the ten-run field-low pool. The provider
route therefore degraded on 2026-08-16, and the two presence-rule runs cannot
attribute their roster losses (identical roster inputs) and much of their
field-side loss to the code change.

Field-side gold-blind indicators remain confounded but directional: presence
runs averaged 5,298-5,381 completion tokens per uncorrected candidate unit
versus 4,182-4,782 in the August-5 pool, and 14-23% of candidate units
needed format correction versus 0-8%. The null-reconciliation audit plausibly
lengthens submissions and raises first-pass format risk at field-low effort;
this must be re-measured against a healthy provider before any promotion
decision. No `presence-r3` was run. Total recorded spend: 1.506 + 0.981 +
0.670 CNY (known subtotals).

### 2026-08-16 provider pin verification and pinned presence-rule repeats

The degradation cause was identified as gateway multi-provider routing: the
extraction request never pinned a provider, so the gateway's price-first
routing silently moved `deepseek/deepseek-v4-flash-0731` to a different
provider endpoint on 2026-08-16. Code revision `ec6715e` added role-scoped
`--roster-provider-pin` / `--core-field-provider-pin` freeze knobs that write
`provider.only=[tag], allow_fallbacks=false` into the frozen
`request_overrides` (method-fingerprinted). A targeted canary on `1807.00427`
(roster-terminal-failed in all three unpinned Aug-16 runs) delivered
3/3 candidates with zero repairs and Galactic-rest-frame speeds identical to
the August-5 pool, confirming the deepseek endpoint restores the August-5
behavior.

Three immutable pinned dev10 repeats of the presence-rule configuration were
then executed at code revision `ec6715e`, fingerprint `4b9ddb8d…`, scored
against `dev-primary-v1` and `tokendance-2026-08-03-screenshots-v1`:

| Run | L0 roster / core | L1 micro P / R / F1 | L2 coverage | L2 strict agreement | gold_only | Tokens | Wall time |
|---|---|---:|---:|---:|---:|---:|---:|
| `…presence-pin-r1-20260816` | 10 / 10 | 0.979 / 1.000 / 0.989 | 0.982 | 0.988 | 3 | 2,407,205 | 658.9 s |
| `…presence-pin-r2-20260816` | 10 / 9+1 | 0.979 / 1.000 / 0.989 | 0.902 | 1.000 | 16 | 2,617,336 | 873.8 s |
| `…presence-pin-r3-20260816` | 10 / 10 | 0.940 / 1.000 / 0.969 | 0.939 | 0.994 | 10 | 2,928,217 | 775.4 s |

Findings:

- Under the pinned healthy provider, the presence-rule changes are
  operationally neutral: roster failures zero, candidate completeness
  47-50 per run, format-correction units 0-3, and uncorrected-candidate
  completion tokens 4,254-4,391 all sit inside the August-5 pool ranges. The
  elevated output length and format-failure rates of the unpinned Aug-16
  presence runs were provider artifacts, not rule effects.
- The null-reconciliation rule produced no measurable movement on the
  dominant group-probability loss: bound_probability fills stayed at 22-28 of
  30 per run (pool 21-28), and gold_only rows stayed in the pool range. The
  rule is retained as zero-cost insurance, but prompt-side exhortation alone
  does not fix group-statement propagation.
- The r2 partial paper is one `evidence_validation_failure` candidate, the
  same random single-candidate failure family the pool already shows.
- Future formal comparisons should pin the gateway provider explicitly;
  unpinned runs are exposed to silent endpoint drift and are not comparable
  across days.

## Next gate

1. ~~Repeat the exact immutable V4 Flash max configuration~~ Resolved on
   2026-08-05: ten scored V6 repeats show stable 10/10 roster delivery but
   unstable L2 coverage (0.543-0.982 across the effort ladder; 0.780-0.982 at
   field-low). Do not promote any configuration to test yet.
2. ~~Share the roster request budget with evidence correction, preserve failed
   repair history, and add regression tests~~ Resolved on 2026-08-05: the
   roster slot now shares one `ProviderRequestBudget(limit=10)` across the
   initial, format-correction, and evidence-correction logical calls
   (preserving every pre-existing per-logical transport maximum, with a spare
   unit so budget exhaustion stays unreachable and terminal classifications
   are unchanged), and the failed-evidence-correction envelope carries its
   `repair_history`. Regression tests pin monotonic physical request indices,
   the nine-request worst case, and terminal repair records. Note the
   2026-08-05 ladder also showed the *field* stage's shared three-request
   budget is where format corrections at high effort exhaust candidates; that
   field policy itself remains frozen.
3. Add general fixtures for the observed group-wide probability,
   uncertainty-direction, limit-kind, and structured-submission failures; do
   not add paper IDs, object names, or table-specific exceptions.
4. Diagnose V4 Flash's extra positive-paper candidates and its remaining
   `gold_only` probability rows through general inclusion and group-statement
   rules. Do not change accepted candidate identity from gold-aware diagnosis.
   The `1902.05061` false positives reproduce in every scored run, and the
   `2209.03560` false-empty roster recurs across fingerprints; both need
   roster-level, gold-blind diagnosis.
5. Decide explicitly whether transport retries should continue consuming the
   same three-request scientific correction budget. Any policy change requires
   a new method fingerprint and immutable run IDs.
6. Keep the 40-paper test closed until the workflow is stable, method inputs
   are frozen, and an explicit test release is authorized. Field-low is the
   provisional candidate route, now backed by a ten-run pool (L1 recall
   1.000 in 9/10 runs, L2 coverage 0.780-0.982); field-high, field-max, and
   field-nothink are rejected, and the V4 Pro json_object roster route is
   rejected for unstable roster delivery.

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
