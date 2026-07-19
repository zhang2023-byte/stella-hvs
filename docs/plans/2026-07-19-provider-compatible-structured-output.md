# Provider-Compatible Structured Output Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make benchmark structured submissions portable across the exact DeepSeek and BigModel routes without weakening typed validation or permitting runtime fallback.

**Architecture:** Add one shared structured-output contract module that resolves a declared model/provider/mode before run creation, freezes the exact route and request overrides into method provenance, builds a forced typed submission tool for each stage, and parses exactly one target function call with local schema validation. Method B whole-response stages and the retained agentic submit path reuse the same parser semantics; no paper extraction is executed during this change.

**Tech Stack:** Python 3.11, OpenAI-compatible chat completions, Pydantic-generated JSON Schema, `unittest`, Stella run-config and roster-cache contracts.

---

### Task 1: Shared structured-output contract

**Files:**
- Create: `src/stella/benchmark/structured_output.py`
- Create: `tests/test_benchmark_structured_output.py`

**Steps:**

1. Write failing tests for route resolution, exact provider pinning, DeepSeek request overrides, forced tool construction, happy-path parsing, and rejection of missing, wrong, multiple, malformed, or locally schema-invalid submissions.
2. Run the focused test module and confirm the failures.
3. Implement the minimal central capability map, generation schemas, request builder, and strict parser without JSON repair or implicit fallback.
4. Run the focused module and confirm it passes.

### Task 2: Freeze contracts into Method B execution

**Files:**
- Modify: `scripts/run_benchmark_extraction.py`
- Modify: `src/stella/benchmark/extraction_run.py`
- Modify: `src/stella/benchmark/extraction_review.py`
- Modify: `src/stella/benchmark/roster_bundle.py`
- Modify: `tests/test_benchmark_extraction.py`
- Modify: `tests/test_benchmark_cli.py`
- Modify: `tests/test_benchmark_roster_bundle.py`
- Modify: `tests/test_benchmark_run_contract.py`

**Steps:**

1. Add failing tests proving role contracts enter method fingerprints, paper provenance, and roster-cache identity and cannot be changed after run initialization.
2. Add failing workflow tests for tool-call success and for no runtime downgrade after a rejected tool response or unsupported strict-json-schema fixture.
3. Resolve extractor/reviewer contracts before `run_config.json`, exact-pin providers, reject fallback models or undeclared routes, and pass only the frozen contracts into paper execution.
4. Replace Method B's ad hoc `response_format` parsing with the shared forced-tool request and strict parser while retaining existing bounded repair loops.
5. Run focused benchmark tests.

### Task 3: Align retained agentic submission semantics and preflight helper

**Files:**
- Modify: `src/stella/benchmark/tool_loop.py`
- Modify: `scripts/check_llm_endpoint.py`
- Modify: `tests/test_benchmark_agentic.py`
- Modify: `tests/test_llm_batch.py`

**Steps:**

1. Add failing tests that final forced agentic submission rejects missing, wrong, multiple, malformed, or schema-invalid tool calls under the same shared parser.
2. Reuse the shared parser for final submit calls without altering read-tool exploration semantics.
3. Add a synthetic-only structured probe helper whose result contains capability metadata but never prompt or response content; test long-context redaction behavior locally.
4. Run focused helper and agentic tests without any paper extraction.

### Task 4: Contract documentation and verification

**Files:**
- Modify: `workflows/definitions/benchmark_extraction_run.yaml`
- Modify: `docs/benchmark-plan.md`
- Modify: `docs/outputs.md`

**Steps:**

1. Document exact-route capability preflight, frozen structured modes, fail-closed behavior, and cache/provenance binding.
2. Explain that existing arbitrary `method.parameters` and extraction provenance parameter maps carry the new values, so persisted artifact shapes and scientific/campaign semantics do not change; do not bump schema, release, or campaign versions.
3. Run generated rule/schema checks, focused tests, and the full unittest suite.
4. Remove temporary probe scripts, selectively stage only this change, commit as `fix(benchmark): support provider-compatible structured output`, and verify the worktree is clean.
