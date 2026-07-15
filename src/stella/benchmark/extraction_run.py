"""Direct-API extraction runs for the benchmark (Phase 2 pipeline).

Staged generation (pipeline 0.4). Single-shot full-document generation
cannot survive large catalog papers (legacy extractions reach 190K+ output
tokens, far over any single response), so every paper runs the same
surface-neutral protocol — the scheduler is deterministic code, never the model:

1. **Shared roster** (one whole-response workflow call): the model sees only
   candidate-selection rules and a compact roster schema. The resulting
   identifier roster and minimum inclusion anchors are shared by FULL and
   CORE for the same method/model/provider/context/code fingerprint.
2. **Surface scaffold** (one call): the model fills ``extraction``, the full
   ``method_chain`` and ``candidate_groups_considered`` while preserving the
   shared roster exactly. It cannot add, delete, or reorder candidates.
3. **Batch fill** (k calls): for each roster slice (default 8 stubs) the
   model produces complete CandidateRecord objects. Output per call stays
   far below response limits; the paper context prefix repeats verbatim,
   so gateway prompt caching absorbs most of the input cost. A batch whose
   reply hits the provider's output-token limit (``finish_reason ==
   "length"``) is split in half and refilled — dense papers can exceed the
   65K completion cap with as few as 8 candidates.
4. **Independent review** (one tool-free workflow call): the complete packed
   paper context and merged extraction are submitted together for structured
   review; high-severity challenges trigger one targeted extractor revision.

A deterministic merge assembles the full document. The frozen validator
gates it as a whole, and repair is targeted: errors under ``candidates[i]``
(bracketed semantic paths *and* dotted pydantic paths like
``$.candidates.8.x``) re-run only the owning batch; everything else re-runs
the scaffold. Every repair must preserve the shared roster, and scaffold
repairs are rejected unless the method_chain stays
structurally sound (``step-NN`` ids, ascending order, backward-only
``depends_on``) — a "repair" that renumbers steps would silently invalidate
every batch's ``method_refs``. Batch repair feedback embeds the *current*
method_chain because the scaffold may have been repaired after the batch's
original prompt was built. Each repair carries only the unit's latest
response plus feedback (no history snowball). Other contracts are unchanged
from pipeline 0.2:

- ``schema``/``generated_at``/``paper``/``inputs`` are overwritten
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
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from stella.lit.llm_batch import (
    LLMTransportError,
    build_chat_completion_payload,
    chat_completion_raw,
    extract_json_object,
)
from stella.lit.extraction_rules import render_rule_profile, rule_profile_sha256
from stella.lit.schema_templates import (
    build_core_provenance_candidate_template,
    build_hvs_candidates_template,
)
from stella.schema_registry import STELLA_RELEASE

from .context_pack import PackedContext, pack_paper_context
from .extraction_review import (
    DEFAULT_REVIEWER_MODEL,
    reviewed_delivery_status,
    run_workflow_review,
)
from .task_surfaces import (
    CORE_PROV,
    FULL,
    get_task_surface,
    hydrate_surface_document,
    surface_binding,
    task_surface_schema_view,
    validate_generated_candidate,
    validate_surface_document,
)
from .run_trace import RunTrace, response_trace_metadata, stream_trace_callback
from .roster_bundle import (
    canonical_sha256,
    frozen_roster_errors,
    get_or_create_roster_bundle,
    roster_identifier_contract,
    roster_shared_key,
    roster_structure_errors,
    roster_stubs,
)
from .tool_loop import accumulate_usage, archive_request

PIPELINE_NAME = "stella-benchmark-extraction"
# 0.5.0: extraction surface moved to schema v0.2 first batch
# (total_velocity removed, inline-thebibliography citations accepted,
# input_catalog direct producers for catalog-adopted stellar parameters and
# quality flags).
# 0.6.0: schema v0.2 second batch — bound_assessment keeps only the two
# probability slots (escape probability records as unbound_probability),
# and units must be plain spellings (validator rejects LaTeX markup in
# `unit`).

TRUNCATION_FEEDBACK = (
    "your reply hit the output token limit and was cut off; return "
    "MINIFIED JSON (no indentation or spaces) and keep free-text fields "
    "terse"
)

DEFAULT_BATCH_SIZE = 8
DEFAULT_MAX_REPAIR_ROUNDS = 3
DEFAULT_UNIT_RETRIES = 2  # parse/structure retries within one unit call
# The initial scaffold gets a larger budget: everything else depends on
# it, and converging on a topologically ordered method_chain can take a
# few attempts (pilot-05: a hard failure at 3 calls).
SCAFFOLD_RETRIES = 4
MAX_ERRORS_IN_FEEDBACK = 80

CJK_RE = re.compile(r"[一-鿿]")
CJK_EXEMPT_KEYS = {"raw_value", "component_raw_value"}
# Candidate-scoped error paths come in two spellings: the semantic
# validator emits "candidates[8].core...", pydantic emits dotted
# "$.candidates.8.core...". Both must route to the owning batch.
CANDIDATE_ERROR_RE = re.compile(r"^\$?\.?candidates[.\[](\d+)")
STEP_ID_RE = re.compile(r"^step-(\d{2})$")

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


def papers_with_existing_artifacts(run_dir: Path, papers: list[str]) -> list[str]:
    """Papers whose directory under ``run_dir`` already holds run artifacts.

    Rerunning a paper into a non-empty directory interleaves two attempt
    streams and clobbers per-call archives (observed 2026-07-06 on
    2401.02017: a retry launched while the original process was still
    alive destroyed both runs' auditability). Callers must refuse to
    start and tell the operator to delete the paper directory first.
    """

    dirty: list[str] = []
    for arxiv_id in papers:
        paper_dir = run_dir / arxiv_id
        if any(
            (paper_dir / name).exists()
            for name in ("attempts", "report.json", "literature_hvs_candidates.json")
        ):
            dirty.append(arxiv_id)
    return dirty


def git_short_hash(workspace: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def build_system_prompt(workspace: Path, task_surface: str = FULL) -> str:
    skill_dir = workspace / "skills" / "hvs-candidates-extraction"
    surface = get_task_surface(task_surface)
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
        "===== CANONICAL EXTRACTION RULE PROFILE: hvs_extractor =====",
        render_rule_profile(workspace, "hvs_extractor", "prompt"),
        f"===== TASK SURFACE: {surface.id} =====",
        surface.instruction,
        "===== GENERATIVE SCHEMA REFERENCE =====",
        task_surface_schema_view(workspace, task_surface),
        "===== COORDINATE FRAME REFERENCE =====",
        (skill_dir / "references" / "coordinate_frames.md").read_text(encoding="utf-8"),
    ]
    return "\n\n".join(parts)


def _context_block(context: PackedContext) -> str:
    return "===== PAPER INPUT FILES =====\n" + context.text


def build_workflow_roster_system_prompt(workspace: Path) -> str:
    return "\n\n".join(
        [
            "You are the candidate-roster stage of a fixed HVS extraction workflow. "
            "No tools are available: all paper inputs are in the user message. "
            "Identify candidates only; do not design method_chain steps and do not "
            "infer any FULL or CORE field requirements. Return one JSON object only.",
            "===== ROSTER RULE PROFILE: hvs_roster =====",
            render_rule_profile(workspace, "hvs_roster", "prompt"),
        ]
    )


def build_workflow_roster_prompt(
    skeleton: dict[str, Any], context: PackedContext
) -> str:
    identity = {
        "paper": skeleton.get("paper", {}),
        "inputs": skeleton.get("inputs", {}),
    }
    return "\n\n".join(
        [
            _context_block(context),
            "===== PAPER IDENTITY =====",
            json.dumps(identity, ensure_ascii=False, indent=2),
            "===== SURFACE-NEUTRAL ROSTER TASK =====",
            "Return {\"extraction\": {\"status\": \"candidates_found\"|\"no_candidates\", "
            "\"summary\": \"...\"}, \"candidates\": [...], "
            "\"candidate_groups_considered\": [...]}. Each candidate contains only "
            "identifiers and inclusion_anchor. identifiers contains record_id, "
            "paper_candidate_id, gaia_source_id, and all[] with source_refs. "
            "inclusion_anchor contains a short summary and source_refs proving why "
            "this object enters the roster. Do not emit method_chain or any FULL/CORE "
            "quantities. Preserve candidate order deterministically.",
            "===== CANONICAL IDENTIFIERS CONTRACT =====",
            roster_identifier_contract(
                str((skeleton.get("paper") or {}).get("arxiv_id") or "")
            ),
        ]
    )


def build_scaffold_prompt(
    skeleton: dict,
    context: PackedContext,
    roster_rules: str,
    task_surface: str = FULL,
    frozen_roster_bundle: dict[str, Any] | None = None,
) -> str:
    """Build the downstream scaffold, optionally from a frozen roster."""

    if frozen_roster_bundle is None:
        roster_instruction = (
            "For `candidates`, return an EXHAUSTIVE roster of identifier stubs: "
            "one entry per object the paper treats as possibly unbound from the "
            "Milky Way, each containing ONLY the `identifiers` object (record_id, "
            "paper_candidate_id, gaia_source_id, all[] with source_refs). The "
            "roster must be complete even if there are hundreds of objects."
        )
    else:
        roster_instruction = (
            "A separate surface-neutral stage has frozen the candidate roster. "
            "Return `candidates` EXACTLY as the identifier stubs below. Do not "
            "add, delete, reorder, or change identifiers. The inclusion anchors "
            "are evidence only.\n"
            + json.dumps(
                {
                    "frozen_roster": roster_stubs(frozen_roster_bundle),
                    "inclusion_anchors": [
                        candidate.get("inclusion_anchor", {})
                        for candidate in frozen_roster_bundle.get("candidates", [])
                        if isinstance(candidate, dict)
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )

    return "\n\n".join(
        [
            _context_block(context),
            "===== SKELETON =====",
            json.dumps(skeleton, ensure_ascii=False, indent=2),
            "===== ROSTER RULE PROFILE: hvs_roster =====",
            roster_rules,
            "===== STAGE 1: SCAFFOLD AND ROSTER =====",
            "Complete the skeleton EXCEPT candidate details. Fill "
            "`extraction` (status, summary), "
            + (
                "the minimum `method_chain` needed to support candidate inclusion and populated core quantities, "
                if task_surface == CORE_PROV
                else "the full `method_chain`, "
            )
            + "and `candidate_groups_considered` exactly per the skill. "
            + roster_instruction
            + " Do not include any other candidate fields yet. Apply the roster "
            "rule profile above. Keep "
            "`extraction.summary` consistent with the roster you "
            "actually list. The files above ARE the paper's source: do not "
            "use status 'source_missing' when they are present. Keep "
            "`schema`, `paper`, and `inputs` unchanged. Return ONLY "
            "the JSON document, minified (no indentation or extra "
            "whitespace).",
        ]
    )


def build_batch_prompt(
    scaffold: dict,
    stubs: list[dict],
    context: PackedContext,
    task_surface: str = FULL,
) -> str:
    """Stage 2: full CandidateRecord objects for one roster slice."""

    scaffold_view = {
        "extraction": scaffold.get("extraction", {}),
        "method_chain": scaffold.get("method_chain", []),
        "candidate_groups_considered": scaffold.get(
            "candidate_groups_considered", []
        ),
    }
    parts = [
            _context_block(context),
            "===== DOCUMENT SCAFFOLD (already fixed) =====",
            json.dumps(scaffold_view, ensure_ascii=False, indent=2),
            "===== STAGE 2: FILL THESE CANDIDATES =====",
            json.dumps({"roster_stubs": stubs}, ensure_ascii=False, indent=2),
    ]
    if task_surface == CORE_PROV:
        parts.extend(
            [
                "===== CODE-GENERATED CORE CANDIDATE TEMPLATES =====",
                json.dumps(
                    {
                        "candidates": [
                            build_core_provenance_candidate_template(stub["identifiers"])
                            for stub in stubs
                        ]
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            ]
        )
    parts.append(
            "Return a JSON object {\"candidates\": [...]} containing one "
            + (
                "complete CORE+PROV candidate record "
                if task_surface == CORE_PROV
                else "COMPLETE CandidateRecord "
            )
            + "per roster stub above, in the same "
            "order, with identical record_id values. Every quantity needs "
            "raw_value/value, source_refs, and method_refs pointing at the "
            "scaffold's existing step ids. Follow the skill and schema "
            "exactly. Return ONLY that JSON object, minified (no "
            "indentation or extra whitespace)."
    )
    return "\n\n".join(parts)


def scaffold_structure_errors(
    document: Any,
    arxiv_id: str,
    *,
    repair: bool = False,
    frozen_roster: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Cheap deterministic checks before accepting a stage-1 scaffold.

    ``repair=True`` adjusts the method_chain guidance: during the initial
    generation the model is free to renumber the whole chain into a
    consistent order, but a repair must preserve existing step ids because
    batch records already reference them.
    """

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
    if status == "source_missing":
        errors.append(
            "status 'source_missing' is impossible here: the paper's source "
            "files are verifiably present in your input (the pipeline packed "
            "them). If candidates lack proper catalog names, identify them "
            "by the labels the paper itself uses; if some objects are not "
            "individually identifiable in the provided files, list the "
            "identifiable ones and document the remainder in "
            "candidate_groups_considered"
        )
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
    # method_chain structural guards: a scaffold (or scaffold repair) that
    # renumbers, reorders, or forward-references steps would invalidate
    # every batch's method_refs, so reject it before it is ever accepted.
    order_hint = (
        "never renumber or insert between existing steps; append new "
        "steps at the end"
        if repair
        else "renumber the ENTIRE chain into one consistent ascending "
        "order (step-01, step-02, ...) in which every depends_on points "
        "at an earlier step"
    )
    chain = document.get("method_chain")
    if isinstance(chain, list):
        previous_number = 0
        earlier_ids: set[str] = set()
        for index, step in enumerate(chain):
            step_id = str(step.get("id", "")) if isinstance(step, dict) else ""
            match = STEP_ID_RE.match(step_id)
            if match is None:
                errors.append(
                    f"method_chain[{index}].id must match 'step-NN' "
                    f"(got {step_id!r})"
                )
                continue
            number = int(match.group(1))
            if number <= previous_number:
                errors.append(
                    f"method_chain[{index}].id {step_id} breaks ascending "
                    f"order — {order_hint}"
                )
            previous_number = max(previous_number, number)
            depends = step.get("depends_on")
            for dep in depends if isinstance(depends, list) else []:
                if dep not in earlier_ids:
                    errors.append(
                        f"method_chain[{index}].depends_on {dep!r} must "
                        f"reference an earlier step id — {order_hint}"
                    )
            earlier_ids.add(step_id)
    if frozen_roster is not None:
        errors.extend(frozen_roster_errors(document, frozen_roster))
    return errors


def scaffold_step_ids(scaffold: dict) -> set[str]:
    """The step ids batches are allowed to reference in method_refs."""

    chain = scaffold.get("method_chain")
    return {
        str(step.get("id"))
        for step in (chain if isinstance(chain, list) else [])
        if isinstance(step, dict) and step.get("id")
    }


def _unknown_method_ref_errors(
    value: Any, step_ids: set[str], path: str
) -> list[str]:
    """Find method_refs entries pointing at nonexistent scaffold steps."""

    findings: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "method_refs" and isinstance(item, list):
                for ref in item:
                    if isinstance(ref, str) and ref not in step_ids:
                        findings.append(
                            f"{path}.method_refs: unknown method_chain id "
                            f"{ref!r} (use only the scaffold's existing "
                            "step ids)"
                        )
            else:
                findings.extend(
                    _unknown_method_ref_errors(item, step_ids, f"{path}.{key}")
                )
    elif isinstance(value, list):
        for index, item in enumerate(value):
            findings.extend(
                _unknown_method_ref_errors(item, step_ids, f"{path}[{index}]")
            )
    return findings


def batch_structure_errors(
    payload: Any, stubs: list[dict], step_ids: set[str] | None = None
) -> list[str]:
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
        if step_ids is not None:
            errors.extend(
                _unknown_method_ref_errors(
                    record, step_ids, f"candidates[{index}]"
                )
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
            match = re.search(r"candidates[.\[](\d+)", error.split(":")[0])
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
    pipeline_name: str = PIPELINE_NAME,
) -> dict:
    """Overwrite provenance-bearing fields the model must not control."""

    document["schema"] = skeleton["schema"]
    document["generated_at"] = skeleton["generated_at"]
    document["paper"] = skeleton["paper"]
    document["inputs"] = skeleton["inputs"]
    extraction = document.get("extraction")
    if not isinstance(extraction, dict):
        extraction = {}
        document["extraction"] = extraction
    extraction["extracted_at"] = extracted_at
    extraction["extractor"] = pipeline_name
    extraction.pop("tooling", None)
    extraction["provenance"] = {
        "stella_release": STELLA_RELEASE,
        "producer": pipeline_name,
        "git_commit": prompt_version,
        "runtime": pipeline_name,
        "model_id": served_model_id or requested_model,
        "component_hashes": {},
        "parameters": request_parameters,
    }
    return document


def repair_feedback(
    errors: list[str],
    cjk_paths: list[str],
    scope: str,
    *,
    method_chain: list | None = None,
) -> str:
    lines = [
        f"Your previous {scope} reply failed validation. Fix every issue "
        "below and return the complete corrected JSON (not a diff), "
        "minified (no indentation or extra whitespace).",
    ]
    if scope == "scaffold":
        lines.append(
            "You may add or split method steps, but NEVER renumber, reuse, "
            "or delete existing step ids — candidate records already "
            "reference them. Append new steps at the END with the next "
            "sequential id; never insert between existing steps."
        )
    if method_chain is not None:
        lines.append(
            "CURRENT method_chain (this supersedes the scaffold shown in "
            "your original prompt; every method_refs id must reference one "
            "of these step ids and match their step_type semantics):"
        )
        lines.append(json.dumps(method_chain, ensure_ascii=False))
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
    review_calls: int = 0
    repair_rounds: int = 0
    review_challenges: int = 0
    review_fix_targets: int = 0
    validator_errors: int = 0
    validator_warnings: int = 0
    validator_warning_messages: list[str] = field(default_factory=list)
    validator_findings: list[dict[str, Any]] = field(default_factory=list)
    validator_groups: list[dict[str, Any]] = field(default_factory=list)
    transport_error: dict[str, Any] | None = None
    roster_bundle_id: str = ""
    roster_cache_hit: bool = False
    roster_calls: int = 0
    shared_roster_usage: dict[str, int] = field(default_factory=dict)
    downstream_usage: dict[str, int] = field(default_factory=dict)
    cjk_paths: list[str] = field(default_factory=list)
    usage_totals: dict[str, int] = field(default_factory=dict)
    error: str = ""


class _Unit:
    """One generation unit (the scaffold or one batch) with pruned history."""

    def __init__(self, name: str, base_messages: list[dict]) -> None:
        self.name = name
        self.base_messages = base_messages
        self.latest_content: str = ""
        self.last_finish_reason: str = ""
        self.last_parse_error: str = ""
        self.calls = 0

    def parse_failure_errors(self) -> list[str]:
        """Actionable feedback for a reply that did not parse as JSON.

        At temperature 0 a bare "not a JSON object" retry regenerates the
        same broken output (observed on 1804.10179: three identical parse
        failures), so the feedback must pin down WHERE the JSON breaks.
        """

        detail = self.last_parse_error or "reply is not a JSON object"
        return [f"your reply was not parseable JSON — {detail}"]

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
    reviewer_model: str = DEFAULT_REVIEWER_MODEL,
    prompt_version: str,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_repair_rounds: int = DEFAULT_MAX_REPAIR_ROUNDS,
    max_tokens: int | None = None,
    timeout_seconds: int = 1800,
    request_extra: dict | None = None,
    reviewer_request_extra: dict | None = None,
    task_surface: str = FULL,
    method_fingerprint: str = "",
    validator_module=None,
    transport: Callable[..., dict] | None = None,
    reviewer_transport: Callable[..., dict] | None = None,
    trace: RunTrace | None = None,
    stream_responses: bool = False,
    roster_cache_root: Path | None = None,
) -> PaperRunResult:
    """Run one paper through the staged protocol, archiving everything."""

    transport = transport or chat_completion_raw
    reviewer_transport = reviewer_transport or transport
    validator = validator_module or load_frozen_validator(workspace)
    paper_dir = run_dir / arxiv_id
    attempts_dir = paper_dir / "attempts"
    attempts_dir.mkdir(parents=True, exist_ok=True)

    result = PaperRunResult(arxiv_id=arxiv_id, status="failed")
    if trace is not None:
        trace.emit(
            "paper.started",
            paper_id=arxiv_id,
            stage="context",
            status="running",
        )

    def emit_paper_completed() -> None:
        if trace is not None:
            trace.emit(
                "paper.completed",
                paper_id=arxiv_id,
                stage="final",
                status=result.status,
                data={
                    "usage_totals": dict(result.usage_totals),
                    "validator_errors": result.validator_errors,
                    "validator_warnings": result.validator_warnings,
                    "error": result.error,
                },
            )
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
    if trace is not None:
        trace.emit(
            "context.packed",
            paper_id=arxiv_id,
            stage="context",
            status="completed",
            data={"files": len(context.files), "chars": len(context.text)},
            payload_kind="context.manifest",
            payload=context.manifest(),
        )
    def archive_review(name: str, response: dict, messages: list[dict]) -> None:
        (attempts_dir / f"{name}.response.json").write_text(
            json.dumps(response, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (attempts_dir / f"{name}.request.json").write_text(
            json.dumps(archive_request(messages), ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )

    request_parameters: dict[str, Any] = {"temperature": 0}
    if stream_responses:
        request_parameters["stream_responses"] = True
    request_parameters["rule_profile_id"] = "hvs_extractor"
    request_parameters["rule_profile_sha256"] = rule_profile_sha256(
        workspace, "hvs_extractor"
    )
    request_parameters["review_rule_profile_id"] = "hvs_reviewer"
    request_parameters["review_rule_profile_sha256"] = rule_profile_sha256(
        workspace, "hvs_reviewer"
    )
    request_parameters.update(surface_binding(workspace, task_surface))
    request_parameters["reviewer_model"] = reviewer_model
    if max_tokens is not None:
        request_parameters["max_tokens"] = max_tokens
    if request_extra:
        request_parameters.update(request_extra)
    if method_fingerprint:
        request_parameters["method_fingerprint"] = method_fingerprint
    system_prompt = build_system_prompt(workspace, task_surface)
    roster_rules = render_rule_profile(workspace, "hvs_roster", "prompt")
    reviewer_kwargs = {
        "api_key": api_key,
        "base_url": base_url,
        "model": reviewer_model,
        "temperature": 0,
        "timeout_seconds": timeout_seconds,
        "extra_body": dict(reviewer_request_extra or {}),
    }
    stage_log: list[dict] = []

    def call_unit(unit: _Unit, feedback: str | None) -> dict | None:
        """One transport call for a unit; returns the parsed JSON or None."""

        unit.calls += 1
        result_slot: dict[str, Any] = {}
        messages = unit.messages(feedback)
        request_payload = build_chat_completion_payload(
            model=model,
            messages=messages,
            temperature=0,
            max_tokens=max_tokens,
            extra_body={
                **(request_extra or {}),
                **(
                    {"stream": True, "stream_options": {"include_usage": True}}
                    if stream_responses
                    else {}
                ),
            },
        )
        request_parent = None
        call_id = f"{arxiv_id}:{unit.name}:{unit.calls}"
        started = time.monotonic()
        if trace is not None:
            request_parent = trace.emit(
                "llm.request.started",
                paper_id=arxiv_id,
                stage=unit.name,
                summary=f"{unit.name} call {unit.calls}",
                data={"call": unit.calls, "model": model},
                payload_kind="llm.request",
                payload=request_payload,
                call_id=call_id,
                node_id=unit.name,
                source_node_id=unit.name,
                target_node_id="provider",
                attempt=1,
            )["seq"]
        stream_callback = (
            stream_trace_callback(
                trace,
                paper_id=arxiv_id,
                stage=unit.name,
                call_id=call_id,
                parent_seq=request_parent,
            )
            if trace is not None and stream_responses
            else None
        )
        try:
            transport_kwargs: dict[str, Any] = dict(
                api_key=api_key,
                base_url=base_url,
                model=model,
                messages=messages,
                temperature=0,
                max_tokens=max_tokens,
                timeout_seconds=timeout_seconds,
                extra_body=request_extra or None,
            )
            if stream_responses:
                transport_kwargs.update(
                    {"stream": True, "on_stream_event": stream_callback}
                )
            response = transport(**transport_kwargs)
        except Exception as exc:
            if isinstance(exc, LLMTransportError):
                exc.with_context(stage=unit.name, call_id=call_id)
                result.transport_error = exc.to_dict()
                _write_transport_error(attempts_dir, exc)
            result.error = f"{unit.name}: {type(exc).__name__}: {exc}"
            if trace is not None:
                trace.emit(
                    "llm.request.failed",
                    paper_id=arxiv_id,
                    stage=unit.name,
                    status="failed",
                    summary=result.error,
                    duration_ms=int((time.monotonic() - started) * 1000),
                    parent_seq=request_parent,
                    call_id=call_id,
                    node_id=unit.name,
                    source_node_id="provider",
                    target_node_id=unit.name,
                )
            return None
        (attempts_dir / f"{unit.name}-call-{unit.calls:02d}.response.json").write_text(
            json.dumps(response, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (attempts_dir / f"{unit.name}-call-{unit.calls:02d}.request.json").write_text(
            json.dumps(archive_request(messages), ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
        accumulate_usage(result.usage_totals, response.get("usage") or {})
        if trace is not None:
            trace.emit(
                "llm.response.completed",
                paper_id=arxiv_id,
                stage=unit.name,
                status="completed",
                data={"call": unit.calls, **response_trace_metadata(response)},
                payload_kind="llm.response",
                payload=response,
                usage=response.get("usage") or {},
                duration_ms=int((time.monotonic() - started) * 1000),
                parent_seq=request_parent,
                call_id=call_id,
                node_id=unit.name,
                source_node_id="provider",
                target_node_id=unit.name,
            )
            served = str(response.get("model") or "")
            if served and served != model:
                trace.emit(
                    "llm.served_model.changed",
                    paper_id=arxiv_id,
                    stage=unit.name,
                    status="completed",
                    data={"requested_model": model, "served_model": served},
                    parent_seq=request_parent,
                    call_id=call_id,
                    node_id=unit.name,
                    source_node_id="provider",
                    target_node_id=unit.name,
                )
        result_slot["served_model"] = str(response.get("model") or "")
        choice = (response.get("choices") or [{}])[0]
        content = (choice.get("message") or {}).get("content") or ""
        unit.latest_content = content
        unit.last_finish_reason = str(choice.get("finish_reason") or "")
        nonlocal served_model_id
        if result_slot["served_model"]:
            served_model_id = result_slot["served_model"]
        try:
            parsed = extract_json_object(content)
            unit.last_parse_error = ""
            return parsed
        except (ValueError, json.JSONDecodeError) as exc:
            detail = str(exc)[:200]
            if isinstance(exc, json.JSONDecodeError):
                lo = max(0, exc.pos - 120)
                snippet = content[lo : exc.pos + 120].replace("\n", " ")
                detail += (
                    f" | the text around the broken position reads: "
                    f"...{snippet}... | fix the JSON structure exactly there"
                )
            unit.last_parse_error = detail
            entry = {
                "unit": unit.name,
                "call": unit.calls,
                "parse_error": str(exc)[:200],
            }
            if unit.last_finish_reason and unit.last_finish_reason != "stop":
                entry["finish_reason"] = unit.last_finish_reason
            stage_log.append(entry)
            return None

    served_model_id = ""

    frozen_bundle: dict[str, Any] | None = None
    frozen_stubs: list[dict[str, Any]] | None = None
    if roster_cache_root is not None:
        roster_system = build_workflow_roster_system_prompt(workspace)
        roster_prompt = build_workflow_roster_prompt(skeleton, context)
        shared_key, key_components = roster_shared_key(
            method="B",
            arxiv_id=arxiv_id,
            model=model,
            provider=dict(request_extra or {}),
            prompt_sha256=canonical_sha256(
                {"system": roster_system, "task": roster_prompt}
            ),
            rule_sha256=rule_profile_sha256(workspace, "hvs_roster"),
            context_sha256=canonical_sha256(
                {"manifest": context.manifest(), "text": context.text}
            ),
            code_version=prompt_version,
        )

        def produce_roster() -> dict[str, Any]:
            before = dict(result.usage_totals)
            unit = _Unit(
                "roster",
                [
                    {"role": "system", "content": roster_system},
                    {"role": "user", "content": roster_prompt},
                ],
            )
            payload: dict[str, Any] | None = None
            feedback: str | None = None
            for _ in range(1 + SCAFFOLD_RETRIES):
                parsed = call_unit(unit, feedback)
                if parsed is None and result.error:
                    break
                structure_errors = (
                    unit.parse_failure_errors()
                    if parsed is None
                    else roster_structure_errors(parsed, arxiv_id)
                )
                if not structure_errors:
                    payload = parsed
                    break
                feedback = repair_feedback(structure_errors, [], "roster")
            result.roster_calls = unit.calls
            if payload is None:
                raise RuntimeError(result.error or "roster structured output failed")
            usage = {
                key: int(result.usage_totals.get(key, 0)) - int(before.get(key, 0))
                for key in result.usage_totals
                if int(result.usage_totals.get(key, 0)) - int(before.get(key, 0))
            }
            return {
                "method": "B",
                "arxiv_id": arxiv_id,
                "producer": {
                    "model": model,
                    "served_model": served_model_id or model,
                    "provider": dict(request_extra or {}),
                    "code_version": prompt_version,
                },
                "extraction": payload.get("extraction", {}),
                "candidates": payload.get("candidates", []),
                "candidate_groups_considered": payload.get(
                    "candidate_groups_considered", []
                ),
                "usage": usage,
            }

        try:
            frozen_bundle, result.roster_cache_hit = get_or_create_roster_bundle(
                cache_root=roster_cache_root,
                shared_key=shared_key,
                key_components=key_components,
                paper_dir=paper_dir,
                producer=produce_roster,
            )
        except Exception as exc:
            if not result.error:
                result.error = f"roster: {type(exc).__name__}: {exc}"
            result.status = (
                "transport_error" if result.transport_error else "roster_failed"
            )
            _write_report(paper_dir, result, [], stage_log)
            emit_paper_completed()
            return result
        result.roster_bundle_id = str(frozen_bundle.get("bundle_id") or "")
        result.shared_roster_usage = {
            str(key): int(value)
            for key, value in (frozen_bundle.get("usage") or {}).items()
            if isinstance(value, int)
        }
        frozen_stubs = roster_stubs(frozen_bundle)
        stage_log.append(
            {
                "stage": "roster",
                "bundle_id": result.roster_bundle_id,
                "cache_hit": result.roster_cache_hit,
                "calls": result.roster_calls,
                "candidates": len(frozen_stubs),
            }
        )

    # ---- Stage 1: surface-specific scaffold -----------------------------
    scaffold_unit = _Unit(
        "scaffold",
        [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": build_scaffold_prompt(
                    skeleton,
                    context,
                    roster_rules,
                    task_surface,
                    frozen_roster_bundle=frozen_bundle,
                ),
            },
        ],
    )
    scaffold: dict | None = None
    feedback: str | None = None
    for _ in range(1 + SCAFFOLD_RETRIES):
        parsed = call_unit(scaffold_unit, feedback)
        if parsed is None and result.error:
            break
        if scaffold_unit.last_finish_reason == "length":
            structure_errors = [TRUNCATION_FEEDBACK]
        else:
            structure_errors = (
                scaffold_unit.parse_failure_errors()
                if parsed is None
                else scaffold_structure_errors(
                    parsed, arxiv_id, frozen_roster=frozen_stubs
                )
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
        emit_paper_completed()
        return result

    roster = scaffold["candidates"]
    step_ids = scaffold_step_ids(scaffold)
    orphan_calls = 0  # calls made by units later abandoned (splits, rebatches)

    def fill_batch_groups(
        groups: list[list[dict]], prefix: str
    ) -> tuple[list[_Unit], list[list[dict]], list[list[dict]]] | None:
        """Fill every stub group; split groups whose replies truncate.

        Returns (units, records_list, final_groups) aligned 1:1 in roster
        order, or None on a hard failure (transport error or a group that
        cannot be filled).
        """

        nonlocal orphan_calls
        work: list[tuple[str, list[dict]]] = [
            (f"{prefix}{number:03d}", stubs)
            for number, stubs in enumerate(groups, 1)
        ]
        units: list[_Unit] = []
        records_list: list[list[dict]] = []
        final_groups: list[list[dict]] = []
        position = 0
        while position < len(work):
            name, stubs = work[position]
            unit = _Unit(
                name,
                [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": build_batch_prompt(
                            scaffold, stubs, context, task_surface
                        ),
                    },
                ],
            )
            records: list[dict] | None = None
            feedback: str | None = None
            split = False
            parse_failures = 0

            def split_group(reason: str) -> None:
                half = (len(stubs) + 1) // 2
                work[position : position + 1] = [
                    (f"{name}a", stubs[:half]),
                    (f"{name}b", stubs[half:]),
                ]
                stage_log.append(
                    {
                        "unit": name,
                        "call": unit.calls,
                        reason: [half, len(stubs) - half],
                    }
                )

            for _ in range(1 + DEFAULT_UNIT_RETRIES):
                parsed = call_unit(unit, feedback)
                if parsed is None and result.error:
                    return None
                if unit.last_finish_reason == "length":
                    if len(stubs) > 1:
                        # The reply cannot fit the provider's output cap;
                        # retrying identically would truncate again. Halve.
                        split_group("split_for_truncation")
                        split = True
                        break
                    feedback = repair_feedback(
                        [TRUNCATION_FEEDBACK], [], unit.name
                    )
                    continue
                if parsed is None:
                    parse_failures += 1
                    if parse_failures >= 2 and len(stubs) > 1:
                        # Long replies keep breaking at the same JSON spot
                        # even with position feedback (deterministic
                        # decoding); a shorter reply is the reliable fix.
                        split_group("split_for_parse_failure")
                        split = True
                        break
                    feedback = repair_feedback(
                        unit.parse_failure_errors(), [], unit.name
                    )
                    continue
                structure_errors = batch_structure_errors(parsed, stubs, step_ids)
                if isinstance(parsed, dict):
                    structure_errors.extend(
                        error
                        for candidate in parsed.get("candidates") or []
                        for error in validate_generated_candidate(
                            candidate, task_surface
                        )
                    )
                if not structure_errors:
                    records = parsed["candidates"]
                    break
                feedback = repair_feedback(structure_errors, [], unit.name)
            if split:
                orphan_calls += unit.calls
                continue
            if records is None:
                orphan_calls += unit.calls
                return None
            units.append(unit)
            records_list.append(records)
            final_groups.append(stubs)
            position += 1
        return units, records_list, final_groups

    def repaired_unit_reply(
        unit: _Unit,
        errors: list[str],
        cjk: list[str],
        structure_check: Callable[[dict], list[str]],
        method_chain: list | None = None,
    ) -> dict | None:
        """Repair a unit against validator feedback, retrying structure
        rejections instead of silently discarding the repair (a dropped
        record in a repair reply must not freeze the error plateau)."""

        extra: list[str] = []
        for _ in range(1 + DEFAULT_UNIT_RETRIES):
            parsed = call_unit(
                unit,
                repair_feedback(
                    extra + errors, cjk, unit.name, method_chain=method_chain
                ),
            )
            if parsed is None and result.error:
                return None
            if unit.last_finish_reason == "length":
                extra = [TRUNCATION_FEEDBACK]
                continue
            structure_errors = (
                unit.parse_failure_errors()
                if parsed is None
                else structure_check(parsed)
            )
            if not structure_errors:
                return parsed
            stage_log.append(
                {
                    "unit": unit.name,
                    "call": unit.calls,
                    "repair_rejected": structure_errors[:5],
                }
            )
            extra = structure_errors
        return None

    # ---- Stage 2: batch fill ---------------------------------------------
    filled = fill_batch_groups(split_batches(roster, batch_size), "batch-")
    if filled is None:
        result.status = "transport_error" if result.error else "batch_failed"
        result.batch_calls = orphan_calls
        _write_report(paper_dir, result, [], stage_log)
        emit_paper_completed()
        return result
    batch_units, batch_records, batch_groups = filled
    result.batch_count = len(batch_groups)
    result.batch_calls = orphan_calls + sum(u.calls for u in batch_units)

    # ---- Merge, validate, targeted repair ---------------------------------
    document: dict = {}
    errors: list[str] = []
    warnings: list[str] = []
    cjk_paths: list[str] = []

    def validate_current() -> tuple[
        list[str], dict[int, list[str]], list[str], dict[int, list[str]]
    ]:
        nonlocal document, errors, warnings, cjk_paths
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
        document = hydrate_surface_document(document, task_surface)
        surface_errors = validate_surface_document(document, task_surface)
        report = validator.validate_hvs_candidates_report(
            document, workspace=workspace, require_complete=True
        )
        errors = surface_errors + list(report.errors)
        warnings = list(report.warnings)
        result.validator_warning_messages = list(warnings)
        result.validator_findings = [
            {
                "severity": "error",
                "rule_id": "task_surface.contract",
                "path": "$",
                "root_key": "task_surface.contract",
                "message": error,
            }
            for error in surface_errors
        ] + (
            list(report.finding_dicts())
            if callable(getattr(report, "finding_dicts", None))
            else []
        )
        result.validator_groups = _group_validator_findings(result.validator_findings)
        cjk_paths = find_cjk_strings(document)
        scaffold_errors, candidate_errors = route_errors(errors)
        scaffold_cjk = [p for p in cjk_paths if not p.startswith("$.candidates[")]
        candidate_cjk: dict[int, list[str]] = {}
        for path in cjk_paths:
            match = re.match(r"^\$\.candidates\[(\d+)\]", path)
            if match:
                candidate_cjk.setdefault(int(match.group(1)), []).append(path)
        if trace is not None:
            trace.emit(
                "validation.completed",
                paper_id=arxiv_id,
                stage="validation",
                status="passed" if not errors and not cjk_paths else "needs_repair",
                data={
                    "errors": len(errors),
                    "warnings": len(warnings),
                    "cjk_paths": len(cjk_paths),
                },
                payload_kind="validation.result",
                payload={
                    "errors": errors,
                    "warnings": warnings,
                    "cjk_paths": cjk_paths,
                },
            )
        return scaffold_errors, candidate_errors, scaffold_cjk, candidate_cjk

    for round_index in range(max_repair_rounds + 1):
        (
            scaffold_errors,
            candidate_errors,
            scaffold_cjk,
            candidate_cjk,
        ) = validate_current()
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
            parsed = repaired_unit_reply(
                scaffold_unit,
                scaffold_errors,
                scaffold_cjk,
                lambda d: scaffold_structure_errors(
                    d,
                    arxiv_id,
                    repair=True,
                    frozen_roster=frozen_stubs,
                ),
            )
            if parsed is not None:
                scaffold = parsed
                step_ids = scaffold_step_ids(scaffold)
                if len(scaffold["candidates"]) != len(roster):
                    # Roster changed size: rebuild batches entirely.
                    roster = scaffold["candidates"]
                    orphan_calls += sum(u.calls for u in batch_units)
                    filled = fill_batch_groups(
                        split_batches(roster, batch_size),
                        f"rebatch-{round_index}-",
                    )
                    if filled is None:
                        result.status = (
                            "transport_error"
                            if result.error
                            else "batch_failed"
                        )
                        result.batch_calls = orphan_calls
                        _write_report(paper_dir, result, errors, stage_log)
                        emit_paper_completed()
                        return result
                    batch_units, batch_records, batch_groups = filled
                    result.batch_count = len(batch_groups)
                    result.batch_calls = orphan_calls + sum(
                        u.calls for u in batch_units
                    )
                    continue
            elif result.error:
                break

        # Map candidate index -> owning batch via the actual group sizes
        # (groups are uneven after truncation splits).
        owners: list[int] = []
        for number, group in enumerate(batch_groups):
            owners.extend([number] * len(group))
        affected = sorted(set(candidate_errors) | set(candidate_cjk))
        repaired_batches: set[int] = set()
        for index in affected:
            if index >= len(owners):
                continue
            batch_number = owners[index]
            if batch_number in repaired_batches:
                continue
            repaired_batches.add(batch_number)
            unit = batch_units[batch_number]
            unit_errors = [
                error
                for i in candidate_errors
                if i < len(owners) and owners[i] == batch_number
                for error in candidate_errors[i]
            ]
            unit_cjk = [
                path
                for i in candidate_cjk
                if i < len(owners) and owners[i] == batch_number
                for path in candidate_cjk[i]
            ]
            stubs = batch_groups[batch_number]
            parsed = repaired_unit_reply(
                unit,
                unit_errors,
                unit_cjk,
                lambda d, s=stubs: batch_structure_errors(d, s, step_ids),
                method_chain=scaffold.get("method_chain", []),
            )
            if parsed is not None:
                batch_records[batch_number] = parsed["candidates"]
            elif result.error:
                break
        if result.error:
            break
        result.batch_calls = orphan_calls + sum(u.calls for u in batch_units)

    # ---- Stage 3: tool-free workflow review + one revision ---------------
    review_failed = False
    review_result_failed = False
    pre_review_invalid = not result.error and bool(errors or cjk_paths)
    if pre_review_invalid:
        stage_log.append(
            {
                "stage": "review",
                "skipped": True,
                "reason": "pre_review_validation_failed",
                "errors": len(errors),
                "cjk": len(cjk_paths),
            }
        )
    elif not result.error:
        try:
            review_outcome = run_workflow_review(
                workspace=workspace,
                document=document,
                task_surface=task_surface,
                context=context,
                transport=reviewer_transport,
                transport_kwargs=reviewer_kwargs,
                archive=archive_review,
                usage_totals=result.usage_totals,
                trace=trace,
                trace_paper_id=arxiv_id,
                stream_responses=stream_responses,
            )
        except RuntimeError as exc:
            if isinstance(exc, LLMTransportError):
                result.transport_error = exc.to_dict()
                _write_transport_error(attempts_dir, exc)
            result.error = str(exc)
            review_failed = True
            stage_log.append(
                {"stage": "review", "failed": True, "error": result.error}
            )
        else:
            result.review_calls = review_outcome.calls
            request_parameters["reviewer_served_model"] = (
                review_outcome.served_model or reviewer_model
            )
            review_failed = review_outcome.failed
            if review_outcome.payload is None:
                review_result_failed = True
                result.error = review_outcome.failure_reason
                stage_log.append(
                    {
                        "stage": "review",
                        "calls": review_outcome.calls,
                        "failed": True,
                        "error": review_outcome.failure_reason,
                    }
                )
            else:
                (paper_dir / "review.json").write_text(
                    json.dumps(
                        review_outcome.payload, ensure_ascii=False, indent=2
                    )
                    + "\n",
                    encoding="utf-8",
                )
                result.review_challenges = len(review_outcome.challenges)
                grouped = dict(review_outcome.actionable_by_candidate)
                document_issues = grouped.pop(-1, [])
                result.review_fix_targets = len(grouped) + (
                    1 if document_issues else 0
                )
                revision_failed = False

                if document_issues:
                    parsed = repaired_unit_reply(
                        scaffold_unit,
                        document_issues,
                        [],
                        lambda d: scaffold_structure_errors(
                            d,
                            arxiv_id,
                            repair=True,
                            frozen_roster=frozen_stubs,
                        ),
                    )
                    if parsed is None:
                        revision_failed = True
                    else:
                        previous_roster = roster
                        scaffold = parsed
                        step_ids = scaffold_step_ids(scaffold)
                        roster = scaffold["candidates"]
                        if roster != previous_roster:
                            orphan_calls += sum(u.calls for u in batch_units)
                            filled = fill_batch_groups(
                                split_batches(roster, batch_size),
                                "review-rebatch-",
                            )
                            if filled is None:
                                revision_failed = True
                            else:
                                batch_units, batch_records, batch_groups = filled
                                result.batch_count = len(batch_groups)

                if grouped and not revision_failed:
                    owners: list[int] = []
                    for number, group in enumerate(batch_groups):
                        owners.extend([number] * len(group))
                    repaired_batches: set[int] = set()
                    for index in sorted(grouped):
                        if not 0 <= index < len(owners):
                            revision_failed = True
                            continue
                        batch_number = owners[index]
                        if batch_number in repaired_batches:
                            continue
                        repaired_batches.add(batch_number)
                        batch_errors = [
                            issue
                            for candidate_index, issues in grouped.items()
                            if (
                                0 <= candidate_index < len(owners)
                                and owners[candidate_index] == batch_number
                            )
                            for issue in issues
                        ]
                        stubs = batch_groups[batch_number]
                        parsed = repaired_unit_reply(
                            batch_units[batch_number],
                            batch_errors,
                            [],
                            lambda d, s=stubs: batch_structure_errors(
                                d, s, step_ids
                            ),
                            method_chain=scaffold.get("method_chain", []),
                        )
                        if parsed is None:
                            revision_failed = True
                            break
                        batch_records[batch_number] = parsed["candidates"]

                if revision_failed and not result.error:
                    review_result_failed = True
                    result.error = (
                        "review_revision_failed: extractor did not return a "
                        "valid targeted revision"
                    )
                review_failed = review_failed or revision_failed
                stage_log.append(
                    {
                        "stage": "review",
                        "calls": review_outcome.calls,
                        "challenges": len(review_outcome.challenges),
                        "fix_targets": result.review_fix_targets,
                        "revision_failed": revision_failed,
                        "error": result.error if revision_failed else "",
                    }
                )

            if not result.error:
                validate_current()

    result.batch_calls = orphan_calls + sum(u.calls for u in batch_units)
    (paper_dir / "literature_hvs_candidates.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    result.validator_errors = len(errors)
    result.validator_warnings = len(warnings)
    result.cjk_paths = cjk_paths
    if pre_review_invalid:
        result.status = "validator_errors"
    elif result.error and not review_result_failed:
        result.status = "transport_error"
    else:
        result.status = reviewed_delivery_status(
            review_failed=review_failed,
            errors=errors,
            cjk_paths=cjk_paths,
        )
    _write_report(paper_dir, result, errors, stage_log)
    emit_paper_completed()
    return result


def _write_report(
    paper_dir: Path,
    result: PaperRunResult,
    errors: list[str],
    stage_log: list[dict],
) -> None:
    paper_dir.mkdir(parents=True, exist_ok=True)
    result.downstream_usage = {
        key: max(
            0,
            int(value)
            - (
                int(result.shared_roster_usage.get(key, 0))
                if not result.roster_cache_hit
                else 0
            ),
        )
        for key, value in result.usage_totals.items()
    }
    (paper_dir / "report.json").write_text(
        json.dumps(
            {
                "arxiv_id": result.arxiv_id,
                "status": result.status,
                "scaffold_attempts": result.scaffold_attempts,
                "batch_count": result.batch_count,
                "batch_calls": result.batch_calls,
                "review_calls": result.review_calls,
                "repair_rounds": result.repair_rounds,
                "review_challenges": result.review_challenges,
                "review_fix_targets": result.review_fix_targets,
                "stage_log": stage_log,
                "validator_errors": errors,
                "validator_warnings": result.validator_warning_messages,
                "validator_warnings_count": result.validator_warnings,
                "validator_findings": result.validator_findings,
                "validator_groups": result.validator_groups,
                "cjk_paths": result.cjk_paths,
                "usage_totals": result.usage_totals,
                "roster_bundle_id": result.roster_bundle_id,
                "roster_cache_hit": result.roster_cache_hit,
                "roster_calls": result.roster_calls,
                "shared_roster_usage": result.shared_roster_usage,
                "downstream_usage": result.downstream_usage,
                "transport_error": result.transport_error,
                "error": result.error,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def write_harness_error_report(
    *,
    run_dir: Path,
    arxiv_id: str,
    error: Exception,
    trace: RunTrace | None = None,
) -> PaperRunResult:
    """Persist an unexpected Method B paper failure without aborting its Run."""

    message = f"{type(error).__name__}: {error}"
    result = PaperRunResult(
        arxiv_id=arxiv_id,
        status="harness_error",
        error=message,
    )
    stage_log = [
        {
            "stage": "harness",
            "error_type": type(error).__name__,
            "message": str(error),
        }
    ]
    _write_report(run_dir / arxiv_id, result, [], stage_log)
    if trace is not None:
        trace.emit(
            "paper.completed",
            paper_id=arxiv_id,
            stage="final",
            status="harness_error",
            data={"error": message},
            node_id="final",
        )
    return result


def _group_validator_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for finding in findings:
        key = (str(finding.get("severity") or ""), str(finding.get("root_key") or "validator"))
        grouped.setdefault(key, []).append(finding)
    return [
        {
            "severity": severity,
            "root_key": root_key,
            "count": len(items),
            "rule_ids": sorted({str(item.get("rule_id") or "") for item in items}),
            "paths": sorted({str(item.get("path") or "") for item in items}),
            "messages": sorted({str(item.get("message") or "") for item in items}),
        }
        for (severity, root_key), items in sorted(grouped.items())
    ]


def _write_transport_error(attempts_dir: Path, exc: LLMTransportError) -> None:
    stage = re.sub(r"[^A-Za-z0-9._-]+", "-", exc.stage or "transport")
    call_suffix = exc.call_id.rsplit(":", 1)[-1] if exc.call_id else "1"
    try:
        call_number = int(call_suffix)
    except ValueError:
        call_number = 1
    path = attempts_dir / f"{stage}-call-{call_number:02d}.transport-error.json"
    path.write_text(
        json.dumps(exc.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
