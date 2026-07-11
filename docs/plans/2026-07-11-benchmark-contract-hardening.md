# Benchmark Contract Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the active benchmark campaign reproducible and internally consistent, repair CLI/path/documentation drift, and add regression coverage for the repository-level contracts that existing unit tests missed.

**Architecture:** Keep `src/stella/schema_registry.py` as the version source of truth and `CampaignPaths` as the campaign-scoped path source of truth. Treat the committed campaign manifest as an immutable contract whose freeze reference is supplied explicitly rather than derived from a moving `HEAD`; keep actual run code provenance in `run_config.json`. Make release helpers consume the already campaign-scoped `releases/` directory without appending the campaign ID a second time.

**Tech Stack:** Python 3.12, `unittest`, argparse CLIs, JSON/YAML workflow contracts, Markdown documentation.

---

### Task 1: Audit repository contracts

**Files:**
- Inspect: `src/stella/schema_registry.py`
- Inspect: `src/stella/benchmark/paths.py`
- Inspect: `workflows/definitions/benchmark_*.yaml`
- Inspect: `scripts/*.py`
- Inspect: `docs/**/*.md`

**Steps:**
1. Run every script with `--help` and record failures.
2. Check local Markdown links and workflow `referenced_paths`.
3. Regenerate version documentation and compare it with the committed file.
4. Search active code and docs for stale campaign IDs, legacy schema envelopes, and obsolete global benchmark paths.

### Task 2: Add failing regression tests

**Files:**
- Modify: `tests/test_benchmark_campaign.py`
- Modify: `tests/test_benchmark_test_release.py`
- Modify: `tests/test_benchmark_cli.py`
- Modify: `tests/test_versioning_policy.py`

**Steps:**
1. Add a campaign-builder test proving an explicit freeze reference produces stable bytes independently of current `HEAD`.
2. Add a release test proving a campaign-scoped releases root writes `<root>/<run_id>.json`.
3. Add a CLI test proving `release_benchmark_test.py --campaign` resolves campaign paths.
4. Add documentation/registry assertions for current draft envelopes and campaign identity.
5. Run the focused tests and confirm they fail for the intended reasons.

### Task 3: Repair campaign and release implementation

**Files:**
- Modify: `scripts/build_benchmark_campaign.py`
- Modify: `src/stella/benchmark/campaign.py`
- Modify: `src/stella/benchmark/test_release.py`
- Modify: `scripts/release_benchmark_test.py`
- Modify: benchmark workflow definitions as needed
- Regenerate: `benchmark/campaigns/hvs-extraction-v2/manifest/campaign_manifest.json`

**Steps:**
1. Add an explicit freeze-reference input and deterministic default derived from the committed contract rather than moving `HEAD`.
2. Keep run code provenance separate and preserve exact campaign hash binding.
3. Stop double-appending campaign ID beneath a campaign-scoped release root.
4. Add `--campaign` path resolution to the release CLI.
5. Run focused tests until green.

### Task 3A: Harden repository path boundaries

**Files:**
- Create: `src/stella/lit/arxiv_ids.py`
- Modify: literature and benchmark CLIs that join arXiv IDs, run IDs, or labels into paths
- Modify: private-gold annotation, audit, scoring, report, and migration CLIs

**Steps:**
1. Centralize modern arXiv ID validation and reject path traversal before any directory join.
2. Require run IDs, run labels, campaign IDs, and paper IDs to be one safe path segment.
3. Reject gold, private scoring details, and benchmark report paths inside the public workspace.
4. Add regression tests for traversal attempts and runtime anti-contamination guards.

### Task 4: Repair documentation and generated references

**Files:**
- Modify: `docs/benchmark-plan.md`
- Modify: `docs/usage.md`
- Modify: `docs/outputs.md`
- Modify: `docs/benchmark-l2-spec.md`
- Modify: `benchmark/GUIDELINE.md`
- Modify: `benchmark/README.md`
- Modify: stale script docstrings

**Steps:**
1. Replace active-v1 statements with the registry-backed v2 state while preserving v1 as read-only history.
2. Document structured schema references rather than writer-inactive legacy strings.
3. Correct release paths and executable CLI examples.
4. Correct the gold draft envelope to match the actual writer.
5. Regenerate `docs/versions.md` and verify no diff remains after a second generation.

### Task 5: Verify the complete repository

**Steps:**
1. Run focused benchmark, CLI, schema, and versioning tests.
2. Run `python -m compileall` over source, scripts, and tests.
3. Run every script with `--help`.
4. Re-run the local Markdown-link and workflow-reference audit.
5. Rebuild sampling and campaign manifests in a temporary directory and byte-compare them with committed artifacts.
6. Exercise a synthetic test-release write/find round trip.
7. Run `conda run -n stella-env python -m unittest discover tests`.
8. Inspect `git diff --check` and the final worktree diff; remove all temporary artifacts.
