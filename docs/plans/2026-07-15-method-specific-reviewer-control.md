# Method-Specific Reviewer Control Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make Method B an end-to-end deterministic workflow with a tool-free reviewer, while keeping Method C end-to-end agentic with bounded, stall-aware reviewer finalization.

**Architecture:** The two methods continue to share the reviewer model, `hvs_reviewer` scientific rule profile, challenge schema, severity policy, and post-review revision contract. Method B sends the packed paper context and extraction to a fixed whole-response review call with bounded structured-output retries and no tool definitions. Method C retains the read-only ReAct reviewer, but reserves finalization calls, detects repeated tool batches and length exhaustion, forces `submit_review`, and records explicit failure reasons.

**Tech Stack:** Python 3, OpenAI-compatible chat completions, unittest, YAML workflow contracts, Markdown ADRs.

---

### Task 1: Lock the method boundary with failing tests

**Files:**
- Modify: `tests/test_benchmark_extraction.py`
- Modify: `tests/test_benchmark_agentic.py`
- Modify: `tests/test_extraction_rules.py`
- Modify: `tests/test_benchmark_cli.py`

**Step 1: Write failing workflow-review tests**

Add a Method B test whose fake reviewer captures the request and asserts that the request contains the packed paper context but no `tools` or `tool_choice`. Add retry tests for malformed and truncated structured replies.

**Step 2: Write failing agentic-control tests**

Add `ReactUnit` tests proving that an identical consecutive read/search batch switches to forced `submit_review`, `finish_reason=length` switches to forced finalization, finalization is limited to two calls, and failure exposes a non-empty reason.

**Step 3: Write contract tests**

Replace the shared-reviewer-source assertion with assertions that Method B calls the workflow reviewer and Method C calls the agentic reviewer. Assert each CLI method fingerprint records its reviewer orchestration and Method B omits the tool-loop component.

**Step 4: Run the focused tests and confirm failure**

Run:

```bash
conda run -n stella-env python -m unittest \
  tests.test_benchmark_extraction \
  tests.test_benchmark_agentic \
  tests.test_extraction_rules \
  tests.test_benchmark_cli
```

Expected: new assertions fail because both methods still call the shared ReAct reviewer and the tool loop has no finalization policy.

### Task 2: Implement the Method B workflow reviewer

**Files:**
- Modify: `src/stella/benchmark/extraction_review.py`
- Modify: `src/stella/benchmark/extraction_run.py`
- Modify: `scripts/run_benchmark_extraction.py`
- Test: `tests/test_benchmark_extraction.py`

**Step 1: Add a tool-free prompt**

Implement `build_workflow_reviewer_system_prompt(...)` and `workflow_review_task_prompt(...)`. The system prompt must state that the reviewer has no tools, all permitted inputs are in the user message, high-impact scientific checks take priority, and the only accepted reply is the structured review JSON.

**Step 2: Add a bounded direct review runner**

Implement `run_workflow_review(...)` with one initial call plus at most two correction calls. Parse `{"review": {...}}` or the bare review object, validate with `review_structure_errors`, archive every request/response, accumulate usage, trace calls, and return an explicit failure reason for transport, truncation, parse, or structure exhaustion. Never add tool schemas to the request.

**Step 3: Route Method B only after validation passes**

Replace Method B's `run_independent_review(...)` call with `run_workflow_review(...)`. If validator errors or CJK failures remain after repair, skip reviewer execution and finish as validator failure. Persist the review artifact and preserve the existing one-round high-severity revision behavior for valid documents.

**Step 4: Make provenance describe the workflow reviewer**

Set `reviewer_orchestration` to `workflow_whole_response`, record the bounded structured retry count, and remove Method B's `tool_loop` component and `reviewer_max_tool_calls` parameter from its method fingerprint.

**Step 5: Run Method B tests**

Run:

```bash
conda run -n stella-env python -m unittest tests.test_benchmark_extraction tests.test_benchmark_cli
```

Expected: all Method B workflow, retry, validation-skip, provenance, and CLI tests pass.

### Task 3: Bound and finalize the Method C agentic reviewer

**Files:**
- Modify: `src/stella/benchmark/tool_loop.py`
- Modify: `src/stella/benchmark/extraction_review.py`
- Modify: `src/stella/benchmark/agentic_run.py`
- Modify: `scripts/run_agentic_extraction.py`
- Test: `tests/test_benchmark_agentic.py`
- Test: `tests/test_benchmark_run_trace.py`

**Step 1: Add an opt-in finalization policy to `ReactUnit`**

Add reviewer-only configuration for two reserved finalization calls and consecutive tool-batch stall detection. Preserve existing extractor behavior when the policy is disabled.

**Step 2: Detect the two observed terminal failures**

When a reviewer repeats an identical non-submit tool batch, or returns `finish_reason=length` without a valid payload, append one concise finalization instruction and switch subsequent requests to forced `submit_review`. At the normal research boundary, enter the same finalization phase instead of returning `None`.

**Step 3: Prevent repeated evidence growth**

Do not execute or append full results for research tools requested during finalization. Return a short rejection directing the model to submit. Stop after the reserved calls and expose `review_submission_missing`, `review_repeated_tool_stall`, or `review_length_exhausted` as the failure reason.

**Step 4: Wire Method C and fix its failure path**

Rename the shared runner to `run_agentic_review(...)`, enable the finalization policy, skip review when pre-review validation is already invalid, and replace the undefined `review_unit.calls` reference with `review_outcome.calls`.

**Step 5: Update provenance and run focused tests**

Record `reviewer_orchestration=agentic_read_tools`, the 32-call total budget, two reserved finalization calls, and stall policy in Method C's method fingerprint.

Run:

```bash
conda run -n stella-env python -m unittest \
  tests.test_benchmark_agentic \
  tests.test_benchmark_run_trace
```

Expected: all tool-loop and Method C tests pass, including deterministic replay of stall and length responses.

### Task 4: Update the benchmark methodology contract

**Files:**
- Create: `docs/adr/0006-end-to-end-reviewer-orchestration.md`
- Modify: `docs/adr/0003-benchmark-methodology-and-boundaries.md`
- Modify: `docs/benchmark-plan.md`
- Modify: `workflows/definitions/benchmark_extraction_run.yaml`
- Modify: `tests/test_extraction_rules.py`
- Modify: workflow/manifest contract tests as required

**Step 1: Record the decision**

Document that B/C now compare end-to-end paradigms rather than isolating extractor orchestration. Record the controlled common factors and the loss of extractor-only causal attribution.

**Step 2: Update executable and human contracts**

Describe Method B's tool-free workflow reviewer, Method C's bounded read-only agentic reviewer, validation-before-review gate, explicit review failure taxonomy, and new-run requirement. Remove claims that B/C share one reviewer orchestration.

**Step 3: Run contract tests**

Run:

```bash
conda run -n stella-env python -m unittest \
  tests.test_extraction_rules \
  tests.test_workflow_manifest
```

Expected: generated rule views remain unchanged and workflow contracts match the new method boundary.

### Task 5: Full verification

**Files:**
- Verify all modified files

**Step 1: Check generated views**

```bash
conda run -n stella-env python scripts/generate_extraction_rule_views.py --check
conda run -n stella-env python scripts/generate_schema_docs.py --check
```

Expected: both commands succeed without changing files.

**Step 2: Run the complete Python suite**

```bash
conda run -n stella-env python -m unittest discover tests
```

Expected: all tests pass without network calls.

**Step 3: Run static checks**

```bash
git diff --check
git status --short
```

Expected: no whitespace errors; only intentional source, test, workflow, ADR, and plan changes remain.
