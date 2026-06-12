"""Direct-API extraction runs for the benchmark (Phase 2 pipeline).

Staged generation (pipeline 0.3). Single-shot full-document generation
cannot survive large catalog papers (legacy extractions reach 190K+ output
tokens, far over any single response), so every paper runs the same
two-stage protocol — the scheduler is deterministic code, never the model:

1. **Scaffold + roster** (one call): the model fills ``extraction``, the
   full ``method_chain``, ``candidate_groups_considered``, and an
   exhaustive candidate roster of identifier stubs only. Listing *which*
   objects qualify is decoupled from describing them, which removes the
   output-length pressure that made models sample "representative"
   candidates.
2. **Batch fill** (k calls): for each roster slice (default 8 stubs) the
   model produces complete CandidateRecord objects. Output per call stays
   far below response limits; the paper context prefix repeats verbatim,
   so gateway prompt caching absorbs most of the input cost.

A deterministic merge assembles the full document, the frozen validator
gates it as a whole, and repair is targeted: errors at ``$.candidates[i]``
re-run only the owning batch, everything else re-runs the scaffold (which
must never renumber existing step ids). Each repair carries only the unit's
latest response plus feedback (no history snowball). Other contracts are
unchanged from pipeline 0.2:

- ``schema_version``/``generated_at``/``paper``/``inputs`` are overwritten
  back from the code-generated skeleton, and ``extraction.tooling`` is
  filled programmatically (model id from the API response) — the model
  cannot misstate its own provenance.
- Free text must be English: a deterministic CJK scan routes findings like
  validator errors and records leftovers as warnings.
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
PIPELINE_VERSION = "0.3"
PROMPT_TEMPLATE_VERSION = "v0.3"

DEFAULT_BATCH_SIZE = 8
DEFAULT_MAX_REPAIR_ROUNDS = 3
DEFAULT_UNIT_RETRIES = 2  # parse/structure retries within one unit call
MAX_ERRORS_IN_FEEDBACK = 80

CJK_RE = re.compile(r"[一-鿿]")
CJK_EXEMPT_KEYS = {"raw_value", "component_raw_value"}
CANDIDATE_ERROR_RE = re.compile(r"^\$?\.?candidates\[(\d+)\]")

PILOT_PAPERS = ("1901.04559", "2011.10206", "2101.10878")

SCAFFOLD_KEYS = (
    "extraction",
    "method_chain",
    "candidates",
    "candidate_groups_considered",
)


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
        "(HVS) literature. You work without tools: every input file you are "
        "allowed to use is included verbatim in the user message; you cannot "
        "open files or browse. Text and table files are line-numbered with "
        "the `N|` prefix; use those exact physical line numbers in "
        "source_refs (the numbering prefix itself is not part of the file "
        "content; `~~~ ... omitted ~~~` markers stand for uncited "
        "bibliography lines you do not need). Extraction runs as a staged "
        "protocol; each request tells you which stage you are in and what "
        "JSON to return. Follow the extraction skill and schema reference "
        "below exactly. All free-text fields you write (summaries, "
        "descriptions, reasons) must be in English. Reply with ONLY the "
        "requested JSON — no markdown fences, no commentary.",
        "===== EXTRACTION SKILL =====",
        (skill_dir / "SKILL.md").read_text(encoding="utf-8"),
        "===== SCHEMA REFERENCE =====",
        (skill_dir / "references" / "schema.md").read_text(encoding="utf-8"),
        "===== COORDINATE FRAME REFERENCE =====",
        (skill_dir / "references" / "coordinate_frames.md").read_text(encoding="utf-8"),
    ]
    return "\n\n".join(parts)


def _context_block(context: PackedContext) -> str:
    return "===== PAPER INPUT FILES =====\n" + context.text


def build_scaffold_prompt(skeleton: dict, context: PackedContext) -> str:
    """Stage 1: scaffold plus exhaustive identifier roster."""

    return "\n\n".join(
        [
            _context_block(context),
            "===== SKELETON =====",
            json.dumps(skeleton, ensure_ascii=False, indent=2),
            "===== STAGE 1: SCAFFOLD AND ROSTER =====",
            "Complete the skeleton EXCEPT candidate details. Fill "
            "`extraction` (status, summary), the full `method_chain`, and "
            "`candidate_groups_considered` exactly per the skill. For "
            "`candidates`, return an EXHAUSTIVE roster of identifier stubs: "
            "one entry per object the paper treats as possibly unbound from "
            "the Milky Way, each containing ONLY the `identifiers` object "
            "(record_id, paper_candidate_id, gaia_source_id, all[] with "
            "source_refs). Do not include any other candidate fields yet. "
            "The roster must be complete even if there are hundreds of "
            "objects — never sample, truncate, or pick representatives; "
            "keep `extraction.summary` consistent with the roster you "
            "actually list. Keep `schema_version`, `paper`, and `inputs` "
            "unchanged. Return ONLY the JSON document.",
        ]
    )


def build_batch_prompt(
    scaffold: dict, stubs: list[dict], context: PackedContext
) -> str:
    """Stage 2: full CandidateRecord objects for one roster slice."""

    scaffold_view = {
        "extraction": scaffold.get("extraction", {}),
        "method_chain": scaffold.get("method_chain", []),
        "candidate_groups_considered": scaffold.get(
            "candidate_groups_considered", []
        ),
    }
    return "\n\n".join(
        [
            _context_block(context),
            "===== DOCUMENT SCAFFOLD (already fixed) =====",
            json.dumps(scaffold_view, ensure_ascii=False, indent=2),
            "===== STAGE 2: FILL THESE CANDIDATES =====",
            json.dumps({"roster_stubs": stubs}, ensure_ascii=False, indent=2),
            "Return a JSON object {\"candidates\": [...]} containing one "
            "COMPLETE CandidateRecord per roster stub above, in the same "
            "order, with identical record_id values. Every quantity needs "
            "raw_value/value, source_refs, and method_refs pointing at the "
            "scaffold's existing step ids. Follow the skill and schema "
            "exactly. Return ONLY that JSON object.",
        ]
    )


def scaffold_structure_errors(document: Any, arxiv_id: str) -> list[str]:
    """Cheap deterministic checks before accepting a stage-1 scaffold."""

    errors: list[str] = []
    if not isinstance(document, dict):
        return ["scaffold is not a JSON object"]
    for key in SCAFFOLD_KEYS:
        if key not in document:
            errors.append(f"scaffold is missing the '{key}' key")
    status = (document.get("extraction") or {}).get("status", "")
    roster = document.get("candidates")
    if not isinstance(roster, list):
        errors.append("candidates roster must be a list")
        roster = []
    if status == "no_candidates" and roster:
        errors.append("status no_candidates conflicts with a non-empty roster")
    if status == "candidates_found" and not roster:
        errors.append("status candidates_found requires a non-empty roster")
    seen: set[str] = set()
    for index, stub in enumerate(roster):
        identifiers = stub.get("identifiers") if isinstance(stub, dict) else None
        if not isinstance(identifiers, dict):
            errors.append(f"candidates[{index}] must contain an identifiers object")
            continue
        extra_keys = set(stub) - {"identifiers"}
        if extra_keys:
            errors.append(
                f"candidates[{index}] roster stub must contain ONLY "
                f"identifiers (found {sorted(extra_keys)})"
            )
        record_id = str(identifiers.get("record_id", ""))
        if not record_id.startswith(f"{arxiv_id}:cand-"):
            errors.append(
                f"candidates[{index}].identifiers.record_id must look like "
                f"'{arxiv_id}:cand-001'"
            )
        if record_id in seen:
            errors.append(f"duplicate record_id {record_id}")
        seen.add(record_id)
    return errors


def batch_structure_errors(payload: Any, stubs: list[dict]) -> list[str]:
    """Cheap deterministic checks before accepting a stage-2 batch."""

    if not isinstance(payload, dict) or not isinstance(
        payload.get("candidates"), list
    ):
        return ['batch reply must be {"candidates": [...]}']
    records = payload["candidates"]
    errors: list[str] = []
    if len(records) != len(stubs):
        errors.append(
            f"batch must contain exactly {len(stubs)} candidates "
            f"(got {len(records)})"
        )
        return errors
    for index, (record, stub) in enumerate(zip(records, stubs)):
        expected = stub["identifiers"]["record_id"]
        got = ""
        if isinstance(record, dict):
            got = str((record.get("identifiers") or {}).get("record_id", ""))
        if got != expected:
            errors.append(
                f"batch item {index} record_id mismatch: expected "
                f"{expected!r}, got {got!r}"
            )
    return errors


def split_batches(roster: list[dict], batch_size: int) -> list[list[dict]]:
    return [
        roster[start : start + batch_size]
        for start in range(0, len(roster), batch_size)
    ]


def merge_document(scaffold: dict, batches: list[list[dict]]) -> dict:
    document = dict(scaffold)
    document["candidates"] = [record for batch in batches for record in batch]
    return document


def route_errors(errors: list[str]) -> tuple[list[str], dict[int, list[str]]]:
    """Split validator errors into scaffold errors and per-candidate ones."""

    scaffold_errors: list[str] = []
    candidate_errors: dict[int, list[str]] = {}
    for error in errors:
        match = CANDIDATE_ERROR_RE.match(error.lstrip("$").lstrip("."))
        if match is None:
            match = re.match(r"^\$\.candidates\[(\d+)\]", error)
        if match is None:
            match = re.search(r"candidates\[(\d+)\]", error.split(":")[0])
        if match:
            index = int(match.group(1))
            candidate_errors.setdefault(index, []).append(error)
        else:
            scaffold_errors.append(error)
    return scaffold_errors, candidate_errors


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


def repair_feedback(errors: list[str], cjk_paths: list[str], scope: str) -> str:
    lines = [
        f"Your previous {scope} reply failed validation. Fix every issue "
        "below and return the complete corrected JSON (not a diff).",
    ]
    if scope == "scaffold":
        lines.append(
            "You may add or split method steps, but NEVER renumber, reuse, "
            "or delete existing step ids — candidate records already "
            "reference them."
        )
    if errors:
        shown = errors[:MAX_ERRORS_IN_FEEDBACK]
        lines.append(f"Errors ({len(errors)} total, showing {len(shown)}):")
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
    scaffold_attempts: int = 0
    batch_count: int = 0
    batch_calls: int = 0
    repair_rounds: int = 0
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
    hits = usage.get("prompt_cache_hit_tokens")
    if isinstance(hits, int):
        totals["prompt_cache_hit_tokens"] = (
            totals.get("prompt_cache_hit_tokens", 0) + hits
        )


class _Unit:
    """One generation unit (the scaffold or one batch) with pruned history."""

    def __init__(self, name: str, base_messages: list[dict]) -> None:
        self.name = name
        self.base_messages = base_messages
        self.latest_content: str = ""
        self.calls = 0

    def messages(self, feedback: str | None) -> list[dict]:
        if feedback is None or not self.latest_content:
            return list(self.base_messages)
        return self.base_messages + [
            {"role": "assistant", "content": self.latest_content},
            {"role": "user", "content": feedback},
        ]


def run_paper(
    *,
    workspace: Path,
    arxiv_id: str,
    run_dir: Path,
    api_key: str,
    base_url: str,
    model: str,
    prompt_version: str,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_repair_rounds: int = DEFAULT_MAX_REPAIR_ROUNDS,
    max_tokens: int | None = None,
    timeout_seconds: int = 1800,
    validator_module=None,
    transport: Callable[..., dict] | None = None,
) -> PaperRunResult:
    """Run one paper through the staged protocol, archiving everything."""

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
    system_prompt = build_system_prompt(workspace)
    stage_log: list[dict] = []

    def call_unit(unit: _Unit, feedback: str | None) -> dict | None:
        """One transport call for a unit; returns the parsed JSON or None."""

        unit.calls += 1
        result_slot: dict[str, Any] = {}
        try:
            response = transport(
                api_key=api_key,
                base_url=base_url,
                model=model,
                messages=unit.messages(feedback),
                temperature=0,
                max_tokens=max_tokens,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:
            result.error = f"{unit.name}: {type(exc).__name__}: {exc}"
            return None
        (attempts_dir / f"{unit.name}-call-{unit.calls:02d}.response.json").write_text(
            json.dumps(response, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        _accumulate_usage(result.usage_totals, response.get("usage") or {})
        result_slot["served_model"] = str(response.get("model") or "")
        choice = (response.get("choices") or [{}])[0]
        content = (choice.get("message") or {}).get("content") or ""
        unit.latest_content = content
        nonlocal served_model_id
        if result_slot["served_model"]:
            served_model_id = result_slot["served_model"]
        try:
            return extract_json_object(content)
        except (ValueError, json.JSONDecodeError) as exc:
            stage_log.append(
                {"unit": unit.name, "call": unit.calls, "parse_error": str(exc)[:200]}
            )
            return None

    served_model_id = ""

    # ---- Stage 1: scaffold + roster -------------------------------------
    scaffold_unit = _Unit(
        "scaffold",
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": build_scaffold_prompt(skeleton, context)},
        ],
    )
    scaffold: dict | None = None
    feedback: str | None = None
    for _ in range(1 + DEFAULT_UNIT_RETRIES):
        parsed = call_unit(scaffold_unit, feedback)
        if parsed is None and result.error:
            break
        structure_errors = (
            ["reply is not a JSON object"]
            if parsed is None
            else scaffold_structure_errors(parsed, arxiv_id)
        )
        stage_log.append(
            {
                "unit": "scaffold",
                "call": scaffold_unit.calls,
                "structure_errors": structure_errors[:10],
            }
        )
        if not structure_errors:
            scaffold = parsed
            break
        feedback = repair_feedback(structure_errors, [], "scaffold")
    result.scaffold_attempts = scaffold_unit.calls
    if scaffold is None:
        result.status = "transport_error" if result.error else "scaffold_failed"
        _write_report(paper_dir, result, [], stage_log)
        return result

    roster = scaffold["candidates"]
    batches = split_batches(roster, batch_size)
    result.batch_count = len(batches)

    # ---- Stage 2: batch fill ---------------------------------------------
    batch_units: list[_Unit] = []
    batch_records: list[list[dict]] = []
    for number, stubs in enumerate(batches, 1):
        unit = _Unit(
            f"batch-{number:03d}",
            [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": build_batch_prompt(scaffold, stubs, context),
                },
            ],
        )
        batch_units.append(unit)
        records: list[dict] | None = None
        feedback = None
        for _ in range(1 + DEFAULT_UNIT_RETRIES):
            parsed = call_unit(unit, feedback)
            if parsed is None and result.error:
                break
            structure_errors = (
                ["reply is not a JSON object"]
                if parsed is None
                else batch_structure_errors(parsed, stubs)
            )
            if not structure_errors:
                records = parsed["candidates"]
                break
            feedback = repair_feedback(structure_errors, [], unit.name)
        if records is None:
            result.status = (
                "transport_error" if result.error else "batch_failed"
            )
            result.batch_calls = sum(u.calls for u in batch_units)
            _write_report(paper_dir, result, [], stage_log)
            return result
        batch_records.append(records)
    result.batch_calls = sum(unit.calls for unit in batch_units)

    # ---- Merge, validate, targeted repair ---------------------------------
    document: dict = {}
    errors: list[str] = []
    warnings: list[str] = []
    cjk_paths: list[str] = []
    for round_index in range(max_repair_rounds + 1):
        document = merge_document(scaffold, batch_records)
        document = enforce_pipeline_fields(
            document,
            skeleton,
            served_model_id=served_model_id,
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
        scaffold_errors, candidate_errors = route_errors(errors)
        scaffold_cjk = [p for p in cjk_paths if not p.startswith("$.candidates[")]
        candidate_cjk: dict[int, list[str]] = {}
        for path in cjk_paths:
            match = re.match(r"^\$\.candidates\[(\d+)\]", path)
            if match:
                candidate_cjk.setdefault(int(match.group(1)), []).append(path)
        stage_log.append(
            {
                "round": round_index,
                "errors": len(errors),
                "scaffold_errors": len(scaffold_errors) + len(scaffold_cjk),
                "candidate_error_indices": sorted(
                    set(candidate_errors) | set(candidate_cjk)
                )[:30],
                "errors_sample": errors[:20],
            }
        )
        if (not errors and not cjk_paths) or round_index == max_repair_rounds:
            break
        result.repair_rounds = round_index + 1

        if scaffold_errors or scaffold_cjk:
            parsed = call_unit(
                scaffold_unit,
                repair_feedback(scaffold_errors, scaffold_cjk, "scaffold"),
            )
            if parsed is not None and not scaffold_structure_errors(parsed, arxiv_id):
                if len(parsed["candidates"]) == len(roster):
                    scaffold = parsed
                else:
                    # Roster changed size: rebuild batches entirely.
                    scaffold = parsed
                    roster = scaffold["candidates"]
                    batches = split_batches(roster, batch_size)
                    result.batch_count = len(batches)
                    batch_records = []
                    for number, stubs in enumerate(batches, 1):
                        unit = _Unit(
                            f"rebatch-{round_index}-{number:03d}",
                            [
                                {"role": "system", "content": system_prompt},
                                {
                                    "role": "user",
                                    "content": build_batch_prompt(
                                        scaffold, stubs, context
                                    ),
                                },
                            ],
                        )
                        parsed_batch = call_unit(unit, None)
                        if parsed_batch is None or batch_structure_errors(
                            parsed_batch, stubs
                        ):
                            result.status = "batch_failed"
                            _write_report(paper_dir, result, errors, stage_log)
                            return result
                        batch_records.append(parsed_batch["candidates"])
                    continue
            elif result.error:
                break

        affected = sorted(set(candidate_errors) | set(candidate_cjk))
        repaired_batches: set[int] = set()
        for index in affected:
            batch_number = index // batch_size
            if batch_number in repaired_batches or batch_number >= len(batch_units):
                continue
            repaired_batches.add(batch_number)
            unit = batch_units[batch_number]
            unit_errors = [
                error
                for i in candidate_errors
                if i // batch_size == batch_number
                for error in candidate_errors[i]
            ]
            unit_cjk = [
                path
                for i in candidate_cjk
                if i // batch_size == batch_number
                for path in candidate_cjk[i]
            ]
            parsed = call_unit(
                unit, repair_feedback(unit_errors, unit_cjk, unit.name)
            )
            stubs = batches[batch_number]
            if parsed is not None and not batch_structure_errors(parsed, stubs):
                batch_records[batch_number] = parsed["candidates"]
            elif result.error:
                break
        if result.error:
            break
        result.batch_calls = sum(unit.calls for unit in batch_units)

    result.batch_calls = sum(unit.calls for unit in batch_units)
    (paper_dir / "literature_hvs_candidates.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    result.validator_errors = len(errors)
    result.validator_warnings = len(warnings)
    result.cjk_paths = cjk_paths
    if result.error:
        result.status = "transport_error"
    elif errors:
        result.status = "validator_errors"
    elif cjk_paths:
        result.status = "ok_with_cjk_warnings"
    else:
        result.status = "ok"
    _write_report(paper_dir, result, errors, stage_log)
    return result


def _write_report(
    paper_dir: Path,
    result: PaperRunResult,
    errors: list[str],
    stage_log: list[dict],
) -> None:
    paper_dir.mkdir(parents=True, exist_ok=True)
    (paper_dir / "report.json").write_text(
        json.dumps(
            {
                "arxiv_id": result.arxiv_id,
                "status": result.status,
                "scaffold_attempts": result.scaffold_attempts,
                "batch_count": result.batch_count,
                "batch_calls": result.batch_calls,
                "repair_rounds": result.repair_rounds,
                "stage_log": stage_log,
                "validator_errors": errors,
                "validator_warnings_count": result.validator_warnings,
                "cjk_paths": result.cjk_paths,
                "usage_totals": result.usage_totals,
                "error": result.error,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
