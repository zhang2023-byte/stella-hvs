"""Deterministic run state, event log, and plan/preflight runtime.

The parent process owns run directories under ``runs/<workflow_id>/<run_id>/``
with an immutable ``run.json``, an append-only ``events.jsonl`` log, and one
directory per paper. It owns no scientific model context: papers execute in
fresh worker processes through operation adapters registered by their owner
packages. Real operation execution is wired in later tasks; this module
defines the invariants the adapters must satisfy.
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stella.workflows import (
    AUTHORITY_KINDS,
    OperationSpec,
    WorkflowRequest,
    WorkflowSpec,
    load_operation_catalog,
    load_workflow_catalog,
)

FROZEN_RUN_FIELDS = ("workflow_id", "run_id", "created_at", "request")

# Supersede and publication are conditionally required: supersede only when
# replacing an existing canonical artifact, publication only when publishing
# externally. They are reported by plan and enforced at the write path, not
# as unconditional execution preconditions.
CONDITIONAL_AUTHORITY_KINDS = ("supersede", "publication")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{secrets.token_hex(3)}"


class RunEvent(dict):
    """One append-only event record in ``events.jsonl``."""

    def __init__(
        self,
        event: str,
        *,
        workflow_id: str | None = None,
        run_id: str | None = None,
        paper_id: str | None = None,
        detail: dict[str, Any] | None = None,
        at: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {"event": event, "at": at or _utc_now()}
        if workflow_id is not None:
            payload["workflow_id"] = workflow_id
        if run_id is not None:
            payload["run_id"] = run_id
        if paper_id is not None:
            payload["paper_id"] = paper_id
        if detail:
            payload["detail"] = detail
        super().__init__(payload)


def run_dir(root: Path, workflow_id: str, run_id: str) -> Path:
    return Path(root) / "runs" / workflow_id / run_id


def create_run(
    *,
    root: Path,
    workflow_id: str,
    request: WorkflowRequest,
    run_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a new active run directory with frozen configuration."""

    resolved_run_id = run_id or new_run_id()
    directory = run_dir(root, workflow_id, resolved_run_id)
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "papers").mkdir()
    state: dict[str, Any] = {
        "workflow_id": workflow_id,
        "run_id": resolved_run_id,
        "created_at": _utc_now(),
        "state": "active",
        "request": request.model_dump(mode="json"),
    }
    if extra:
        state.update(extra)
    run_json = directory / "run.json"
    run_json.write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    events_path = directory / "events.jsonl"
    events_path.write_text(
        json.dumps(
            RunEvent("run_created", workflow_id=workflow_id, run_id=resolved_run_id),
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return state


def load_run(root: Path, workflow_id: str, run_id: str) -> dict[str, Any]:
    path = run_dir(root, workflow_id, run_id) / "run.json"
    return json.loads(path.read_text(encoding="utf-8"))


def save_run_state(
    root: Path, workflow_id: str, run_id: str, state: dict[str, Any]
) -> None:
    """Persist run state while refusing to touch frozen fields."""

    existing = load_run(root, workflow_id, run_id)
    for field in FROZEN_RUN_FIELDS:
        if state.get(field) != existing.get(field):
            raise ValueError(
                f"run.json field {field!r} is frozen and cannot change"
            )
    path = run_dir(root, workflow_id, run_id) / "run.json"
    path.write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def append_event(
    root: Path, workflow_id: str, run_id: str, event: RunEvent
) -> None:
    path = run_dir(root, workflow_id, run_id) / "events.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")


def resolve_phases(
    spec: WorkflowSpec, requested_phases: list[str] | None
) -> list[Any]:
    """Return the ordered phases to execute for a request."""

    if requested_phases is None:
        return list(spec.phases)
    by_id = {phase.id: phase for phase in spec.phases}
    unknown = sorted(set(requested_phases) - set(by_id))
    if unknown:
        from stella.workflows import StellaError

        raise StellaError(
            "INVALID_INPUT",
            f"unknown phases for {spec.id}: {unknown}",
            missing_input=unknown,
            next_action=f"choose phases from {[phase.id for phase in spec.phases]}",
        )
    return [by_id[phase_id] for phase_id in requested_phases]


def operations_for_phases(
    phases: list[Any], catalog_root: Path | None = None
) -> list[OperationSpec]:
    catalog = load_operation_catalog(catalog_root)
    specs: dict[str, OperationSpec] = {}
    for phase in phases:
        for operation_id in phase.operations:
            specs[operation_id] = catalog.by_id[operation_id]
    return [specs[operation_id] for operation_id in sorted(specs)]


def required_authorities(
    operations: list[OperationSpec], *, include_conditional: bool = False
) -> list[str]:
    kinds: set[str] = set()
    for operation in operations:
        kinds.update(operation.authorities)
    if not include_conditional:
        kinds -= set(CONDITIONAL_AUTHORITY_KINDS)
    return sorted(kinds, key=AUTHORITY_KINDS.index)


def preflight_checks(
    operations: list[OperationSpec], papers: list[str] | None, root: Path
) -> list[dict[str, str]]:
    """Best-effort read-path existence checks with no side effects."""

    checks: list[dict[str, str]] = []
    for operation in operations:
        for read in operation.reads:
            if "<paper_id>" in read and papers:
                for paper_id in papers:
                    path = Path(root) / read.replace("<paper_id>", paper_id)
                    checks.append(
                        {
                            "operation": operation.id,
                            "read": read.replace("<paper_id>", paper_id),
                            "status": "present" if path.exists() else "absent",
                        }
                    )
            elif "<" not in read:
                path = Path(root) / read
                checks.append(
                    {
                        "operation": operation.id,
                        "read": read,
                        "status": "present" if path.exists() else "absent",
                    }
                )
            else:
                checks.append(
                    {"operation": operation.id, "read": read, "status": "unresolved"}
                )
    return checks


def plan_workflow(
    *,
    root: Path,
    workflow_id: str,
    request: WorkflowRequest,
) -> dict[str, Any]:
    """Plan/preflight a workflow request without external calls or writes."""

    catalog = load_workflow_catalog(root)
    spec = catalog.by_id[workflow_id]
    phases = resolve_phases(spec, getattr(request, "phases", None))
    operations = operations_for_phases(phases, root)
    required = required_authorities(operations)
    conditional = required_authorities(operations, include_conditional=True)
    granted = request.authorities.granted()
    papers = getattr(request, "papers", None) or []
    return {
        "workflow_id": workflow_id,
        "status": "planned",
        "phases": [
            {
                "id": phase.id,
                "operations": phase.operations,
                "optional": phase.optional,
                "gate": phase.gate,
            }
            for phase in phases
        ],
        "request": request.model_dump(mode="json"),
        "papers": list(papers),
        "required_authorities": required,
        "conditional_authorities": sorted(
            set(conditional) - set(required), key=AUTHORITY_KINDS.index
        ),
        "granted_authorities": granted,
        "missing_authorities": sorted(
            set(required) - set(granted), key=AUTHORITY_KINDS.index
        ),
        "preflight_checks": preflight_checks(operations, papers, root),
        "notes": [
            "plan/preflight only: no network calls and no canonical writes",
        ],
    }


def check_execution_authorities(
    plan: dict[str, Any]
) -> list[str]:
    """Return the authority kinds still missing for execution."""

    return list(plan["missing_authorities"])


def resolve_operation_callables(
    operations: list[OperationSpec]
) -> dict[str, Any]:
    """Import every operation callable eagerly, failing closed."""

    from stella.workflows import resolve_reference

    callables: dict[str, Any] = {}
    for operation in operations:
        callables[operation.id] = resolve_reference(operation.callable)
    return callables
