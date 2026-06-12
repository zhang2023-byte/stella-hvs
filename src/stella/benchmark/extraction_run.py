"""Direct-API extraction runs for the benchmark (Phase 2 pipeline).

One run extracts ``literature_hvs_candidates.json`` for a set of papers with
a single model, archiving everything needed to reproduce or audit it under
``benchmark/runs/<run_id>/``:

- ``run_config.json`` — model, prompt version (git commit), packing hashes,
  repair policy;
- ``<arxiv_id>/literature_hvs_candidates.json`` — the final document;
- ``<arxiv_id>/attempts/attempt-NN.response.json`` — raw API responses
  (served model id, usage, reasoning fields);
- ``<arxiv_id>/report.json`` — validator results, CJK findings, usage.

Pipeline contract:

- The model fills a code-generated skeleton; ``schema_version``,
  ``generated_at``, ``paper``, and ``inputs`` are *overwritten back* from
  the skeleton after parsing, and ``extraction.tooling`` is filled
  programmatically (model id taken from the API response, never from model
  text) — the model cannot misstate its own provenance.
- The frozen validator gates every attempt; validation errors are fed back
  for a bounded number of repair rounds (recorded in the run config).
  Repair rounds keep only the latest model response plus feedback — older
  rounds are dropped from the conversation, which caps request size (the
  gateway drops oversized long-running requests) and roughly halves input
  cost; the model only needs its newest document and the current errors.
- Free text must be English: a deterministic CJK scan triggers one repair
  round and is recorded as a warning if it persists.
- Inputs come only from ``literature/<arxiv_id>/`` via the deterministic
  context packer. The pipeline never reads expert annotations.
"""

from __future__ import annotations

import datetime as _dt
import importlib.util
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from stella.lit.llm_batch import chat_completion_raw, extract_json_object
from stella.lit.schema_templates import build_hvs_candidates_template

from .context_pack import PackedContext, pack_paper_context

PIPELINE_NAME = "stella-benchmark-extraction"
PIPELINE_VERSION = "0.2"
PROMPT_TEMPLATE_VERSION = "v0.2"

DEFAULT_MAX_REPAIR_ROUNDS = 3
MAX_ERRORS_IN_FEEDBACK = 80

CJK_RE = re.compile(r"[一-鿿]")
# Machine fields where CJK would be a data error caught by the validator
# anyway, and quoted source material is out of scope for the language scan.
CJK_EXEMPT_KEYS = {"raw_value", "component_raw_value"}

PILOT_PAPERS = ("1901.04559", "2011.10206", "2101.10878")


def load_frozen_validator(workspace: Path):
    """Import the frozen validator script as a module (no sys.path games)."""

    script = workspace / "scripts" / "validate_hvs_candidates.py"
    spec = importlib.util.spec_from_file_location("frozen_hvs_validator", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load validator from {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git_short_hash(workspace: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def build_system_prompt(workspace: Path) -> str:
    skill_dir = workspace / "skills" / "hvs-candidates-extraction"
    parts = [
        "You are a scientific data-extraction pipeline for hypervelocity-star "
        "(HVS) literature. You work in single-shot mode: every input file you "
        "are allowed to use is included verbatim in the user message; you "
        "cannot open files or browse. Text and table files are line-numbered "
        "with the `N|` prefix; use those exact physical line numbers in "
        "source_refs (the numbering prefix itself is not part of the file "
        "content). Follow the extraction skill and schema reference below "
        "exactly. The candidates list must be exhaustive: include every "
        "object the paper treats as possibly unbound from the Milky Way, "
        "even when there are dozens; never truncate, sample, or pick "
        "representatives, and keep extraction.summary consistent with what "
        "the document actually records. All free-text fields you write "
        "(summaries, descriptions, reasons) must be in English. Reply with "
        "ONLY the completed JSON document — no markdown fences, no "
        "commentary.",
        "===== EXTRACTION SKILL =====",
        (skill_dir / "SKILL.md").read_text(encoding="utf-8"),
        "===== SCHEMA REFERENCE =====",
        (skill_dir / "references" / "schema.md").read_text(encoding="utf-8"),
        "===== COORDINATE FRAME REFERENCE =====",
        (skill_dir / "references" / "coordinate_frames.md").read_text(encoding="utf-8"),
    ]
    return "\n\n".join(parts)


def build_user_prompt(skeleton: dict, context: PackedContext) -> str:
    return "\n\n".join(
        [
            "Complete the following literature_hvs_candidates.json skeleton "
            "for this paper. Keep `schema_version`, `paper`, and `inputs` "
            "unchanged. Fill `extraction` (status and summary), "
            "`method_chain`, `candidates`, and "
            "`candidate_groups_considered` according to the skill.",
            "===== SKELETON TO COMPLETE =====",
            json.dumps(skeleton, ensure_ascii=False, indent=2),
            "===== PAPER INPUT FILES =====",
            context.text,
            "Return ONLY the completed JSON document.",
        ]
    )


def find_cjk_strings(value: Any, path: str = "$") -> list[str]:
    """Return JSON paths of strings containing CJK characters."""

    findings: list[str] = []
    if isinstance(value, str):
        if CJK_RE.search(value):
            findings.append(path)
    elif isinstance(value, dict):
        for key, item in value.items():
            if key in CJK_EXEMPT_KEYS:
                continue
            findings.extend(find_cjk_strings(item, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            findings.extend(find_cjk_strings(item, f"{path}[{index}]"))
    return findings


def enforce_pipeline_fields(
    document: dict,
    skeleton: dict,
    *,
    served_model_id: str,
    requested_model: str,
    prompt_version: str,
    request_parameters: dict,
    extracted_at: str,
) -> dict:
    """Overwrite provenance-bearing fields the model must not control."""

    document["schema_version"] = skeleton["schema_version"]
    document["generated_at"] = skeleton["generated_at"]
    document["paper"] = skeleton["paper"]
    document["inputs"] = skeleton["inputs"]
    extraction = document.get("extraction")
    if not isinstance(extraction, dict):
        extraction = {}
        document["extraction"] = extraction
    extraction["extracted_at"] = extracted_at
    extraction["extractor"] = f"{PIPELINE_NAME}/{PIPELINE_VERSION}"
    extraction["tooling"] = {
        "agent_runtime": f"{PIPELINE_NAME}/{PIPELINE_VERSION}",
        "model_id": served_model_id or requested_model,
        "prompt_version": prompt_version,
        "request_parameters": request_parameters,
    }
    return document


def repair_feedback(errors: list[str], cjk_paths: list[str]) -> str:
    lines = [
        "Your previous JSON document failed validation. Fix every issue "
        "below and return the complete corrected JSON document (not a diff).",
    ]
    if errors:
        shown = errors[:MAX_ERRORS_IN_FEEDBACK]
        lines.append(f"Validator errors ({len(errors)} total, showing {len(shown)}):")
        lines.extend(f"- {error}" for error in shown)
    if cjk_paths:
        lines.append(
            "These fields contain non-English (CJK) text; rewrite them in "
            "English:"
        )
        lines.extend(f"- {path}" for path in cjk_paths[:40])
    return "\n".join(lines)


@dataclass
class PaperRunResult:
    arxiv_id: str
    status: str
    attempts: int = 0
    validator_errors: int = 0
    validator_warnings: int = 0
    cjk_paths: list[str] = field(default_factory=list)
    usage_totals: dict[str, int] = field(default_factory=dict)
    error: str = ""


def _accumulate_usage(totals: dict[str, int], usage: dict) -> None:
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = usage.get(key)
        if isinstance(value, int):
            totals[key] = totals.get(key, 0) + value
    details = usage.get("completion_tokens_details") or {}
    reasoning = details.get("reasoning_tokens")
    if isinstance(reasoning, int):
        totals["reasoning_tokens"] = totals.get("reasoning_tokens", 0) + reasoning


def run_paper(
    *,
    workspace: Path,
    arxiv_id: str,
    run_dir: Path,
    api_key: str,
    base_url: str,
    model: str,
    prompt_version: str,
    max_repair_rounds: int = DEFAULT_MAX_REPAIR_ROUNDS,
    max_tokens: int | None = None,
    timeout_seconds: int = 1800,
    validator_module=None,
    transport: Callable[..., dict] | None = None,
) -> PaperRunResult:
    """Run one paper end to end and archive everything under run_dir."""

    transport = transport or chat_completion_raw
    validator = validator_module or load_frozen_validator(workspace)
    paper_dir = run_dir / arxiv_id
    attempts_dir = paper_dir / "attempts"
    attempts_dir.mkdir(parents=True, exist_ok=True)

    result = PaperRunResult(arxiv_id=arxiv_id, status="failed")
    skeleton = build_hvs_candidates_template(
        literature_dir=workspace / "literature",
        arxiv_id=arxiv_id,
        workspace=workspace,
    ).copy()
    context = pack_paper_context(
        workspace, arxiv_id, list(skeleton["inputs"]["ecsv_paths"])
    )
    (paper_dir / "context_manifest.json").write_text(
        json.dumps(context.manifest(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    request_parameters: dict[str, Any] = {"temperature": 0}
    if max_tokens is not None:
        request_parameters["max_tokens"] = max_tokens
    base_messages = [
        {"role": "system", "content": build_system_prompt(workspace)},
        {"role": "user", "content": build_user_prompt(skeleton, context)},
    ]
    messages = list(base_messages)

    document: dict | None = None
    errors: list[str] = []
    warnings: list[str] = []
    cjk_paths: list[str] = []
    attempts_log: list[dict] = []
    for attempt in range(1, max_repair_rounds + 2):
        result.attempts = attempt
        try:
            response = transport(
                api_key=api_key,
                base_url=base_url,
                model=model,
                messages=messages,
                temperature=0,
                max_tokens=max_tokens,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:  # archived, then surfaced in the report
            result.error = f"{type(exc).__name__}: {exc}"
            break
        (attempts_dir / f"attempt-{attempt:02d}.response.json").write_text(
            json.dumps(response, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        _accumulate_usage(result.usage_totals, response.get("usage") or {})
        choice = (response.get("choices") or [{}])[0]
        content = (choice.get("message") or {}).get("content") or ""
        try:
            document = extract_json_object(content)
        except (ValueError, json.JSONDecodeError) as exc:
            errors = [f"response is not a JSON object: {exc}"]
            cjk_paths = []
        else:
            document = enforce_pipeline_fields(
                document,
                skeleton,
                served_model_id=str(response.get("model") or ""),
                requested_model=model,
                prompt_version=prompt_version,
                request_parameters=request_parameters,
                extracted_at=_dt.datetime.now().isoformat(timespec="seconds"),
            )
            report = validator.validate_hvs_candidates_report(
                document, workspace=workspace, require_complete=True
            )
            errors = list(report.errors)
            warnings = list(report.warnings)
            cjk_paths = find_cjk_strings(document)
        attempts_log.append(
            {
                "attempt": attempt,
                "error_count": len(errors),
                "errors_sample": errors[:25],
                "cjk_count": len(cjk_paths),
            }
        )
        if not errors and not cjk_paths:
            break
        if attempt >= max_repair_rounds + 1:
            break
        # Prune history: keep only the latest response and its feedback.
        messages = base_messages + [
            {"role": "assistant", "content": content},
            {"role": "user", "content": repair_feedback(errors, cjk_paths)},
        ]

    if document is not None:
        (paper_dir / "literature_hvs_candidates.json").write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    result.validator_errors = len(errors)
    result.validator_warnings = len(warnings)
    result.cjk_paths = cjk_paths
    if result.error:
        result.status = "transport_error"
    elif document is None:
        result.status = "no_document"
    elif errors:
        result.status = "validator_errors"
    elif cjk_paths:
        result.status = "ok_with_cjk_warnings"
    else:
        result.status = "ok"
    (paper_dir / "report.json").write_text(
        json.dumps(
            {
                "arxiv_id": arxiv_id,
                "status": result.status,
                "attempts": result.attempts,
                "attempts_log": attempts_log,
                "validator_errors": errors,
                "validator_warnings_count": len(warnings),
                "cjk_paths": cjk_paths,
                "usage_totals": result.usage_totals,
                "error": result.error,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return result
