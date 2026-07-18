# B-core Legacy Clean Start Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Produce a clean Stella 0.5.0 repository state where B-core is the only active direct benchmark path, C/FULL are safe readable legacy interfaces, existing public results are canonical, and mechanical provenance gaps are closed.

**Architecture:** Keep historical implementations and artifacts readable while gating all new active entrypoints to B-core. Centralize the legacy opt-in policy in a small benchmark policy module, enforce it in CLI and dev-console backends, then make the React setup UI reflect the same contract. Preserve ignored local evidence, publish only the existing aggregate hardened-B scorecard, and avoid all gold/LLM activity.

**Tech Stack:** Python 3.12, `argparse`, dataclasses, JSON/YAML workflow contracts, React/TypeScript/Vitest, `unittest`, generated schema/rule views.

**Skills:** @Code, @writing-plans

---

### Task 1: Preserve local evidence and canonicalize the hardened-B result

**Files:**
- Move: `kimi-export-session_-20260718-062932.md` → `notes/session-exports/2026-07-18/kimi-export-session_-20260718-062932.md`
- Preserve: `/tmp/stella-sync-dup-backup/` → `notes/session-exports/2026-07-18/sync-duplicate-backup/`
- Create: `benchmark/campaigns/hvs-extraction-v3/scoring/v3-dev-hardened-b-core-r1/scorecard.json`

**Step 1:** Record SHA256 for the Kimi export, temporary duplicate backup, ignored scorecard backup, sealed run manifest, and scorecard-declared run-manifest hash.

**Step 2:** Move the conversation and temporary duplicate files into ignored `notes/`; copy the scorecard into its canonical public path.

**Step 3:** Verify the canonical scorecard is byte-identical to the ignored backup, references `v3-dev-hardened-b-core-r1`, matches the sealed run-manifest SHA256, contains only public aggregate fields, and leaves the paused Method C run unchanged.

**Step 4:** After the canonical scorecard is staged, delete only the redundant ignored scorecard backup. Never delete either run directory.

### Task 2: Write failing tests for the legacy creation boundary

**Files:**
- Create: `src/stella/benchmark/method_policy.py`
- Modify: `tests/test_benchmark_cli.py`
- Modify: `tests/test_benchmark_dev_console.py`
- Modify: `benchmark/console/src/pages/SetupPage.test.tsx`
- Modify: `tests/test_workflow_manifest.py`

**Step 1:** Add tests asserting the active direct policy is Method B + `core_prov`, with Method C and FULL marked legacy.

**Step 2:** Add CLI tests asserting B defaults to `core_prov`, FULL requires `--allow-legacy-full`, and C requires `--allow-legacy-method-c`.

**Step 3:** Add backend tests asserting new Method C or FULL dev requests are rejected and historical C summaries are read-only/non-resumable.

**Step 4:** Replace the frontend FULL-selection test with assertions that setup exposes only Method B and a locked `core_prov` surface in both formal and regression scopes.

**Step 5:** Run the targeted tests and confirm they fail for the missing policy enforcement:

```bash
conda run -n stella-env python -m unittest \
  tests.test_benchmark_cli \
  tests.test_benchmark_dev_console \
  tests.test_workflow_manifest
cd benchmark/console && npm test -- --run src/pages/SetupPage.test.tsx
```

Expected: new legacy-boundary assertions fail before implementation.

### Task 3: Enforce B-core creation while retaining explicit legacy CLIs

**Files:**
- Create: `src/stella/benchmark/method_policy.py`
- Modify: `scripts/run_benchmark_extraction.py`
- Modify: `scripts/run_agentic_extraction.py`
- Modify: `src/stella/benchmark/dev_console.py`
- Modify: `benchmark/console/src/pages/SetupPage.tsx`

**Step 1:** Define `PRIMARY_DIRECT_METHOD = "B"`, `PRIMARY_TASK_SURFACE = "core_prov"`, legacy method/surface sets, and a side-effect-free opt-in validator.

**Step 2:** Make both direct CLIs default to `core_prov`; require `--allow-legacy-full` for FULL and `--allow-legacy-method-c` for Method C. Keep dry-run and historical implementation code available.

**Step 3:** Make dev-console request parsing accept only B-core for both formal and regression creation. Mark current-campaign Method C histories read-only so resume and external-failure retry gates stay closed.

**Step 4:** Remove Method C and FULL choices from setup cards, keep history/run rendering types unchanged, and remove the duplicated setup help line.

**Step 5:** Run the targeted tests from Task 2 and expect all to pass.

### Task 4: Close roster-cache and audit-contract gaps

**Files:**
- Modify: `src/stella/benchmark/roster_bundle.py`
- Modify: `src/stella/benchmark/extraction_run.py`
- Modify: `src/stella/benchmark/agentic_run.py`
- Modify: `src/stella/benchmark/mechanical_normalization.py`
- Modify: `src/stella/benchmark/run_contract.py`
- Modify: `tests/test_benchmark_roster_bundle.py`
- Modify: relevant extraction/run-contract tests if component fixtures require the new key

**Step 1:** Add failing tests proving reviewer provider changes the shared roster key, `revise` without challenges fails, and skipped/out-of-order candidate IDs fail.

**Step 2:** Add `reviewer_provider` to `roster_shared_key` and reviewer provenance at both B and C call sites.

**Step 3:** Require at least one challenge for `revise`, and require `record_id` to equal the ordered `arxiv_id:cand-NNN` sequence.

**Step 4:** Correct normalization change paths to `candidates[i].core.observed_phase_space.<field>.value` and update the run-manifest validator docstring to v3.

**Step 5:** Run:

```bash
conda run -n stella-env python -m unittest \
  tests.test_benchmark_roster_bundle \
  tests.test_benchmark_extraction \
  tests.test_benchmark_agentic \
  tests.test_benchmark_run_contract
```

Expected: PASS.

### Task 5: Synchronize ADRs, workflows, results, outputs, and release notes

**Files:**
- Modify: `docs/adr/0009-b-core-primary-method-c-and-full-legacy.md`
- Modify: `docs/benchmark-plan.md`
- Modify: `docs/plans/2026-07-16-benchmark-bc-evaluation-hardening.md`
- Modify: `docs/outputs.md`
- Create: `docs/releases/0.5.0.md`
- Modify: `workflows/definitions/benchmark_extraction_run.yaml`
- Modify: `workflows/definitions/benchmark_dev_console.yaml`
- Modify: related workflow tests

**Step 1:** Reframe ADR 0009 as an engineering prioritization decision, correct B call counts and distinct C delivery evidence, and state that hardened-B reviewer accepted every roster without revision.

**Step 2:** Replace ambiguous “before/after” language with `V3 pre-architecture baseline` and `V3 post-architecture hardened-B validation`. Publish the three canonical scorecard aggregates and mark hardened C as an incomplete, unsealed, unscored diagnostic with no planned continuation.

**Step 3:** Make active workflow definitions route only B-core creation while documenting C/FULL as explicit legacy interfaces and preserving historical inspection.

**Step 4:** Update output ownership/provenance text for reviewer provider and add 0.5.0 release notes, including no migration of immutable old run manifests.

**Step 5:** Run workflow/reference tests and `git diff --check`.

### Task 6: Rebuild generated frontend assets and run the full verification matrix

**Files:**
- Regenerate: `src/stella/web/assets/benchmark-console/`

**Step 1:** Run frontend tests and production build:

```bash
cd benchmark/console
npm test -- --run
npm run build
```

Expected: all Vitest tests pass and the committed bundle references the newly built hashed assets.

**Step 2:** Run generated-view checks:

```bash
conda run -n stella-env python scripts/generate_extraction_rule_views.py --check
conda run -n stella-env python scripts/generate_schema_docs.py --check
conda run -n stella-env python scripts/generate_version_reference.py --check
```

Expected: all checks exit 0.

**Step 3:** Run full Python verification:

```bash
conda run -n stella-env python -m unittest discover tests
```

Expected: all tests pass, including contamination and workflow-manifest suites.

**Step 4:** Recheck the canonical scorecard/run-manifest hashes, confirm no active extraction/scoring processes, and run `git diff --check`.

### Task 7: Create the clean local 0.5.0 baseline

**Files:**
- Stage only files listed in this plan plus the canonical hardened-B scorecard and generated console bundle.

**Step 1:** Review `git diff`, verify ignored notes and run archives are not staged, and confirm no private-gold content appears in the staged patch.

**Step 2:** Commit the atomic contract/data/documentation cleanup:

```bash
git commit -m "chore(benchmark): establish B-core legacy boundary"
```

**Step 3:** Confirm `git status --short` is empty. If and only if release notes, versions, and all gates pass, create local tag `v0.5.0`; do not push.

**Step 4:** Report the commit/tag, canonical scorecards, preserved legacy artifacts, test totals, and the next B-only debugging gate.
