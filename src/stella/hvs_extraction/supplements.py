"""Bound, non-mutating supplement experiments for v3 core artifacts."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from stella.benchmark.campaign import sha256_file
from stella.benchmark.paths import validate_path_segment
from stella.hvs_extraction.prepare import RUNS_RELATIVE_DIR
from stella.hvs_extraction.roster_stage import _atomic_write_json
from stella.schema_registry import require_schema, schema_ref

SupplementType = Literal["full_fields", "method_chain"]
SupplementAdapter = Callable[[SupplementType, dict[str, Any]], dict[str, Any]]
SUPPLEMENT_ROOT = RUNS_RELATIVE_DIR.parent / "supplements"
FULL_GROUPS = (
    "photometry",
    "spectroscopy",
    "stellar_parameters",
    "abundances",
    "quality_flags",
    "orbit",
    "astrophysical_origin",
    "extra",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_core(
    workspace: Path, source_run_id: str, arxiv_id: str
) -> tuple[Path, dict[str, Any]]:
    path = (
        workspace
        / RUNS_RELATIVE_DIR
        / source_run_id
        / "papers"
        / arxiv_id
        / "literature_hvs_candidates.json"
    )
    document = json.loads(path.read_text(encoding="utf-8"))
    require_schema(
        document, "literature_hvs_candidates", require_current=True
    )
    if (document.get("paper") or {}).get("arxiv_id") != arxiv_id:
        raise ValueError(f"{arxiv_id} core artifact identity mismatch")
    return path, document


def preflight_supplement(
    workspace: Path,
    *,
    run_id: str,
    source_run_id: str,
    arxiv_ids: list[str],
    supplement_type: SupplementType,
) -> dict[str, Any]:
    """Validate selection and immutable source bindings without writing."""

    run_id = validate_path_segment(run_id, "supplement run id")
    source_run_id = validate_path_segment(source_run_id, "source run id")
    if supplement_type not in {"full_fields", "method_chain"}:
        raise ValueError(f"unknown supplement type: {supplement_type!r}")
    if not arxiv_ids or len(arxiv_ids) != len(set(arxiv_ids)):
        raise ValueError("supplement papers must be non-empty and unique")
    run_dir = workspace / SUPPLEMENT_ROOT / run_id
    if run_dir.exists():
        raise FileExistsError(f"supplement run already exists: {run_id}")
    source_config_path = (
        workspace / RUNS_RELATIVE_DIR / source_run_id / "run_config.json"
    )
    source_config = json.loads(source_config_path.read_text(encoding="utf-8"))
    require_schema(source_config, "benchmark.run_config", require_current=True)
    if (source_config.get("campaign") or {}).get("campaign_id") != "hvs-extraction-v5":
        raise ValueError("supplements require a V5 source run")
    configured = set(source_config.get("papers") or [])
    bindings: dict[str, str] = {}
    for value in arxiv_ids:
        arxiv_id = validate_path_segment(str(value), "paper id")
        if arxiv_id not in configured:
            raise ValueError(f"{arxiv_id} is not in the source run")
        core_path, _ = _load_core(
            workspace, source_run_id, arxiv_id
        )
        bindings[arxiv_id] = sha256_file(core_path)
    return {
        "run_id": run_id,
        "source_run_id": source_run_id,
        "supplement_type": supplement_type,
        "papers": list(arxiv_ids),
        "core_artifact_sha256": bindings,
        "run_created": False,
        "api_calls": 0,
    }


def fake_supplement_adapter(
    supplement_type: SupplementType, core_document: dict[str, Any]
) -> dict[str, Any]:
    """Deterministic adapter used only by fixtures and contract tests."""

    if supplement_type == "full_fields":
        return {
            "records": [
                {
                    "record_id": candidate["record_id"],
                    "photometry": [],
                    "spectroscopy": [],
                    "stellar_parameters": {},
                    "abundances": [],
                    "quality_flags": [],
                    "orbit": {},
                    "astrophysical_origin": {},
                    "extra": [],
                }
                for candidate in core_document.get("candidates") or []
            ]
        }
    return {"steps": [], "field_links": []}


def _validate_payload(
    supplement_type: SupplementType,
    payload: dict[str, Any],
    core_document: dict[str, Any],
) -> None:
    known_ids = {
        candidate["record_id"]
        for candidate in core_document.get("candidates") or []
    }
    if supplement_type == "full_fields":
        if set(payload) != {"records"} or not isinstance(payload["records"], list):
            raise ValueError("full-fields adapter must return only records")
        seen: set[str] = set()
        for record in payload["records"]:
            if not isinstance(record, dict) or set(record) != {
                "record_id",
                *FULL_GROUPS,
            }:
                raise ValueError("full-fields record has an invalid shape")
            record_id = str(record["record_id"])
            if record_id not in known_ids or record_id in seen:
                raise ValueError("supplement record_id is unknown or duplicated")
            seen.add(record_id)
        return
    if set(payload) != {"steps", "field_links"}:
        raise ValueError("method-chain adapter must return steps and field_links")
    if not isinstance(payload["steps"], list) or not isinstance(
        payload["field_links"], list
    ):
        raise ValueError("method-chain steps and field_links must be arrays")
    step_ids = {
        str(step.get("id"))
        for step in payload["steps"]
        if isinstance(step, dict) and step.get("id")
    }
    if len(step_ids) != len(payload["steps"]):
        raise ValueError("method-chain steps require unique ids")
    for link in payload["field_links"]:
        if not isinstance(link, dict) or set(link) != {
            "record_id",
            "core_field_path",
            "step_id",
        }:
            raise ValueError("method-chain field link has an invalid shape")
        if link["record_id"] not in known_ids or link["step_id"] not in step_ids:
            raise ValueError("method-chain field link has an unknown target")


def run_supplement(
    workspace: Path,
    *,
    run_id: str,
    source_run_id: str,
    arxiv_ids: list[str],
    supplement_type: SupplementType,
    adapter: SupplementAdapter | None,
    preflight_only: bool = False,
) -> dict[str, Any]:
    """Run a separate supplement without modifying the bound core run."""

    preflight = preflight_supplement(
        workspace,
        run_id=run_id,
        source_run_id=source_run_id,
        arxiv_ids=arxiv_ids,
        supplement_type=supplement_type,
    )
    if preflight_only:
        return preflight
    if adapter is None:
        raise ValueError(
            "no real supplement model adapter is registered; no run was created"
        )
    run_dir = workspace / SUPPLEMENT_ROOT / run_id
    run_dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.mkdir(run_dir)
    except FileExistsError as exc:
        raise FileExistsError(f"supplement run already exists: {run_id}") from exc
    config = {
        "schema": schema_ref("benchmark.supplement_run_config"),
        "created_at": _utc_now(),
        **preflight,
    }
    config["run_created"] = True
    _atomic_write_json(run_dir / "run_config.json", config)
    outputs: dict[str, str] = {}
    for arxiv_id in arxiv_ids:
        _, core = _load_core(workspace, source_run_id, arxiv_id)
        payload = adapter(supplement_type, core)
        _validate_payload(supplement_type, payload, core)
        schema_name = (
            "full_fields_supplement"
            if supplement_type == "full_fields"
            else "method_chain_supplement"
        )
        artifact = {
            "schema": schema_ref(schema_name),
            "generated_at": _utc_now(),
            "campaign_id": "hvs-extraction-v5",
            "source_run_id": source_run_id,
            "paper": {"arxiv_id": arxiv_id},
            "core_artifact_sha256": preflight["core_artifact_sha256"][
                arxiv_id
            ],
            **payload,
        }
        output_path = run_dir / "papers" / arxiv_id / f"{schema_name}.json"
        _atomic_write_json(output_path, artifact)
        outputs[arxiv_id] = output_path.relative_to(run_dir).as_posix()
    summary = {
        "run_id": run_id,
        "status": "complete",
        "outputs": outputs,
    }
    _atomic_write_json(run_dir / "run_summary.json", summary)
    return summary
