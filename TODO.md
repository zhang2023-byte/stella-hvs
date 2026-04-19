# TODO

This file tracks deferred work that is intentionally not part of the current
implementation.

## Deferred: Semantic Agent Backend

Status: deferred until Stella is deployed on a stable coding-agent platform.

Current short-term approach:

- Keep using the remote OpenAI-compatible LLM backend for semantic tasks.
- Existing semantic tasks include weak relevance review and observational catalog assessment.
- Use the configured DeepSeek/OpenAI-compatible environment variables for these calls.

Future direction:

- Introduce a Stella-owned semantic job protocol so the pipeline can hand structured tasks to a reviewer backend.
- Keep the pipeline deterministic: create job JSON, validate result JSON, write results back into note JSON, then render Markdown.
- Support multiple reviewer backends behind one interface:
  - `llm`: current remote LLM API mode.
  - `pending`: write jobs for the active coding Agent to process manually or with its own sub-agent tools.
  - `command`: call a scriptable agent runner such as OpenClaw, Claude Code, Codex CLI, or a custom runner if a stable CLI/API exists.
- Version task instructions and output schemas, for example `catalog_assessment.v1`.
- Store provenance in results: reviewer backend, model/agent name, instruction version, reviewed time, confidence, and evidence.

Reason to defer:

- Different coding Agents expose sub-agent capabilities differently.
- Some sub-agent tools only exist inside an interactive agent session and cannot be called directly from Python.
- A premature backend abstraction would add complexity before Stella has a stable deployment target.
