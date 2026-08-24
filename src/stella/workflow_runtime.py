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
    DEFAULT_ROOT,
    OperationSpec,
    WorkflowRequest,
    WorkflowSpec,
    get_operation,
    load_operation_catalog,
    load_workflow_catalog,
    resolve_reference,
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
        operation: str | None = None,
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
        if operation is not None:
            payload["operation"] = operation
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


def effective_phases(spec: WorkflowSpec, request: WorkflowRequest) -> list[Any]:
    """The single phase resolver shared by planning and execution.

    An explicit ``phases`` list wins; otherwise a request-derived default
    (the gold action) applies; otherwise the non-optional phases run.
    Planning, execution, resume, and finalization must all agree on this
    list, so no other phase-selection logic may exist.
    """

    from stella.workflows import StellaError, default_requested_phases

    requested = default_requested_phases(spec.id, request)
    if requested is None:
        return [phase for phase in spec.phases if not phase.optional]
    by_id = {phase.id: phase for phase in spec.phases}
    unknown = sorted(set(requested) - set(by_id))
    if unknown:
        raise StellaError(
            "INVALID_INPUT",
            f"unknown phases for {spec.id}: {unknown}",
            missing_input=unknown,
            next_action=f"choose phases from {[phase.id for phase in spec.phases]}",
        )
    return [by_id[phase_id] for phase_id in requested]


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

    catalog = load_workflow_catalog(DEFAULT_ROOT)
    spec = catalog.by_id[workflow_id]
    phases = effective_phases(spec, request)
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


def resolve_operation_contract(
    operation: OperationSpec, *, root: Path
) -> dict[str, Any]:
    """Resolve every declaration of one operation or fail closed.

    The catalog is an executable contract: callable, output model,
    validators, contract paths, and test paths must all resolve before
    anything executes. Decorative YAML is a defect, not documentation.
    """

    from pydantic import BaseModel

    from stella.workflows import StellaError, resolve_reference

    broken: list[str] = []
    try:
        callable_ = resolve_reference(operation.callable)
        if not callable(callable_):
            broken.append(f"{operation.callable} is not callable")
    except StellaError as error:
        callable_ = None
        broken.append(str(error))
    output_model = None
    if operation.output_model:
        try:
            output_model = resolve_reference(operation.output_model)
            if not (isinstance(output_model, type) and issubclass(output_model, BaseModel)):
                broken.append(f"output model {operation.output_model} is not a pydantic model")
        except StellaError as error:
            broken.append(str(error))
    validators: dict[str, Any] = {}
    for reference in operation.validators:
        try:
            validator = resolve_reference(reference)
            if not callable(validator):
                broken.append(f"validator {reference} is not callable")
            else:
                validators[reference] = validator
        except StellaError as error:
            broken.append(str(error))
    repo_root = DEFAULT_ROOT
    for contract in operation.contracts:
        if not (repo_root / contract).exists():
            broken.append(f"contract path missing: {contract}")
    for test in operation.tests:
        if not (repo_root / test).exists():
            broken.append(f"test path missing: {test}")
    if broken:
        raise StellaError(
            "OPERATION_NOT_IMPLEMENTED",
            f"operation {operation.id} has broken catalog declarations: "
            + "; ".join(broken),
            next_action="fix workflows/operations.yaml or its owner module",
        )
    return {
        "callable": callable_,
        "output_model": output_model,
        "validators": list(validators.values()),
    }


def execute_operation(
    operation: OperationSpec,
    payload: dict[str, Any],
    *,
    root: Path,
    paper_id: str | None = None,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run one operation and enforce its declared contract.

    The callable's return value must validate against the declared output
    model, then every declared validator runs against the result and the
    artifact state on disk. Any violation becomes a typed failed result and
    blocks downstream paper-local execution.
    """

    from pydantic import ValidationError

    from stella.workflows import OperationResult

    resolved = contract or resolve_operation_contract(operation, root=root)
    callable_ = resolved["callable"]
    try:
        result = callable_(payload, root=Path(root), paper_id=paper_id)
    except Exception as error:  # noqa: BLE001 - structured worker failure
        return {
            "operation_id": operation.id,
            "paper_id": paper_id,
            "status": "failed",
            "failure": {"kind": "internal", "detail": f"{type(error).__name__}: {error}"},
            "blockers": [],
            "next_action": "inspect the operation implementation",
            "warnings": [],
            "detail": {},
        }
    if not isinstance(result, dict):
        return {
            "operation_id": operation.id,
            "paper_id": paper_id,
            "status": "failed",
            "failure": {"kind": "internal", "detail": "operation callable must return a dict envelope"},
            "blockers": [],
            "next_action": "return an OperationResult envelope from the callable",
            "warnings": [],
            "detail": {},
        }
    result = dict(result)
    result.setdefault("operation_id", operation.id)
    if paper_id is not None:
        result.setdefault("paper_id", paper_id)
    output_model = resolved.get("output_model")
    if output_model is not None:
        try:
            output_model.model_validate(result)
        except ValidationError as error:
            return {
                "operation_id": operation.id,
                "paper_id": paper_id,
                "status": "failed",
                "failure": {
                    "kind": "validation",
                    "detail": f"result violates {operation.output_model}: {error}",
                },
                "blockers": [],
                "next_action": "fix the operation to return the declared envelope",
                "warnings": [],
                "detail": {},
            }
    validator_errors: list[str] = []
    for validator in resolved.get("validators") or []:
        try:
            validator_errors.extend(validator(payload, result, root=Path(root)) or [])
        except Exception as error:  # noqa: BLE001 - validator crash is a defect
            validator_errors.append(
                f"validator {getattr(validator, '__name__', validator)} crashed: {error}"
            )
    if validator_errors:
        return {
            "operation_id": operation.id,
            "paper_id": paper_id,
            "status": "failed",
            "failure": {
                "kind": "validation",
                "detail": "; ".join(validator_errors),
            },
            "blockers": validator_errors,
            "next_action": "repair the declared artifacts before continuing",
            "warnings": [],
            "detail": {},
        }
    return result


# --- Workflow execution -------------------------------------------------------


def _summarize_statuses(statuses: list[str]) -> str:
    """Aggregate paper statuses without ever synthesizing success."""

    if not statuses:
        return "failed"
    if all(status == "failed" for status in statuses):
        return "failed"
    if any(status == "failed" for status in statuses):
        return "partial"
    if any(status == "partial" for status in statuses):
        return "partial"
    return "complete"


def _spawn_paper_worker(
    *,
    root: Path,
    operation: Any,
    paper_id: str,
    payload: dict,
    attempt_dir: Path,
    env_extra: dict[str, str],
) -> dict[str, Any]:
    """Run one operation for one paper in a fresh worker process."""

    import os
    import subprocess
    import sys

    request_path = attempt_dir / "request.json"
    result_path = attempt_dir / "result.json"
    telemetry_path = attempt_dir / "telemetry.json"
    request_path.parent.mkdir(parents=True, exist_ok=True)
    request_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    env = {**os.environ, **env_extra}
    src_root = str(Path(__file__).resolve().parents[2] / "src")
    env["PYTHONPATH"] = src_root + os.pathsep + env.get("PYTHONPATH", "")
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "stella.workflow_runtime",
            "worker",
            operation.id,
            "--paper",
            paper_id,
            "--request",
            str(request_path),
            "--result",
            str(result_path),
            "--telemetry",
            str(telemetry_path),
            "--root",
            str(Path(root).resolve()),
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=int(env.get("STELLA_WORKER_TIMEOUT", "600")),
    )
    if result_path.is_file():
        result = json.loads(result_path.read_text(encoding="utf-8"))
    else:
        result = {
            "status": "failed",
            "reason": (
                f"worker exited with code {completed.returncode}: "
                f"{completed.stderr.strip()[-500:]}"
            ),
        }
    if telemetry_path.is_file():
        result.setdefault("telemetry", json.loads(telemetry_path.read_text(encoding="utf-8")))
    return result


def run_workflow(
    *,
    root: Path,
    workflow_id: str,
    request: WorkflowRequest,
    run_id: str | None = None,
    env_extra: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Execute a validated workflow request through operation adapters.

    One fresh worker process handles each (operation, paper) pair for
    worker-per-paper operations; an independent paper failure never aborts
    other papers. The returned summary and the on-disk run directory are the
    audit trail; run configuration was frozen by ``create_run``.
    """

    import os

    from stella.workflows import DEFAULT_ROOT, StellaError

    catalog = load_workflow_catalog(DEFAULT_ROOT)
    spec = catalog.by_id[workflow_id]
    operations_catalog = load_operation_catalog(DEFAULT_ROOT)
    phases = effective_phases(spec, request)
    # Execute in declared phase order; authority checks may sort freely.
    ordered_ids: list[str] = []
    for phase in phases:
        for operation_id in phase.operations:
            if operation_id not in ordered_ids:
                ordered_ids.append(operation_id)
    operations = [operations_catalog.by_id[operation_id] for operation_id in ordered_ids]
    contracts = {
        operation.id: resolve_operation_contract(operation, root=Path(root))
        for operation in operations
    }
    required = required_authorities(operations)
    missing = [kind for kind in required if not getattr(request.authorities, kind)]
    if missing:
        # Fail before any run directory exists; conditional kinds
        # (supersede/publication) stay enforced at their write paths.
        raise StellaError(
            "MISSING_AUTHORITY",
            "execution is blocked by missing authorities",
            missing_authority=missing,
            next_action="grant each authority explicitly with its --allow flag",
        )
    payload = request.model_dump(mode="json")
    papers = list(getattr(request, "papers") or [])
    resolved_run_id = run_id or new_run_id()
    state = create_run(
        root=root,
        workflow_id=workflow_id,
        request=request,
        run_id=resolved_run_id,
        extra={"phases": [phase.id for phase in phases]},
    )
    directory = run_dir(root, workflow_id, resolved_run_id)
    env_extra = dict(env_extra or {})
    env_extra.setdefault("STELLA_WORKER_RUN_ID", resolved_run_id)
    papers_root = directory / "papers"

    failures: list[str] = []
    paper_status: dict[str, str] = {}
    supersede_events: list[dict[str, Any]] = []
    concurrency = _initial_concurrency()
    for operation in operations:
        if operation.per_paper == "workflow_scoped":
            append_event(
                root,
                workflow_id,
                resolved_run_id,
                RunEvent("operation_started", operation=operation.id),
            )
            result = execute_operation(
                operation,
                payload,
                root=Path(root),
                contract=contracts[operation.id],
            )
            append_event(
                root,
                workflow_id,
                resolved_run_id,
                RunEvent(
                    "operation_finished",
                    operation=operation.id,
                    detail={"status": result.get("status")},
                ),
            )
            if result.get("status") in ("failed", "network_failed"):
                failures.append(operation.id)
                break
            superseded = (result.get("detail") or {}).get(
                "superseded_previous_sha256"
            )
            if superseded:
                supersede_events.append(
                    {"operation": operation.id, "previous_sha256": superseded}
                )
        else:
            eligible = [
                paper
                for paper in papers
                if attempt_allowed(
                    root,
                    workflow_id,
                    resolved_run_id,
                    paper,
                    operation_id=operation.id,
                )
            ]
            outcome = _run_papers_bounded(
                root=root,
                workflow_id=workflow_id,
                run_id=resolved_run_id,
                operation=operation,
                payload=payload,
                papers=eligible,
                env_extra=env_extra,
                concurrency=concurrency,
            )
            concurrency = outcome["next_concurrency"]
            for paper_id in papers:
                result = outcome["results"].get(paper_id)
                if result is None:
                    continue
                status = result.get("status", "failed")
                superseded = (result.get("detail") or {}).get(
                    "superseded_previous_sha256"
                )
                if superseded:
                    supersede_events.append(
                        {
                            "operation": operation.id,
                            "paper_id": paper_id,
                            "previous_sha256": superseded,
                        }
                    )
                    append_event(
                        root,
                        workflow_id,
                        resolved_run_id,
                        RunEvent(
                            "superseded",
                            paper_id=paper_id,
                            operation=operation.id,
                            detail={"previous_sha256": superseded},
                        ),
                    )
                previous = paper_status.get(paper_id)
                if status == "failed" or previous == "failed":
                    paper_status[paper_id] = "failed"
                    failures.append(f"{operation.id}:{paper_id}")
                elif status == "partial":
                    paper_status[paper_id] = "partial"
                else:
                    paper_status.setdefault(paper_id, "complete")

    statuses = list(paper_status.values())
    has_per_paper = any(
        operation.per_paper == "worker_per_paper" for operation in operations
    )
    if statuses or has_per_paper:
        # An empty executable paper set is a failed precondition, never a
        # synthesized success.
        summary_status = _summarize_statuses(statuses)
    elif failures:
        summary_status = "failed"
    else:
        summary_status = "complete"
    if papers and all(status == "failed" for status in paper_status.values()):
        summary_status = "failed"
    summary = {
        "workflow_id": workflow_id,
        "run_id": resolved_run_id,
        "status": summary_status,
        "papers": [
            {"paper_id": paper_id, "status": paper_status.get(paper_id, "pending")}
            for paper_id in papers
        ],
        "operations_failed": sorted(set(failures)),
        "superseded": supersede_events,
        "run_dir": str(directory),
    }
    (directory / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    append_event(
        root,
        workflow_id,
        resolved_run_id,
        RunEvent("run_finished", detail={"status": summary_status}),
    )
    state["state"] = "finalized"
    return summary


def _worker_main(argv: list[str]) -> int:
    """Fresh-worker entry point: one operation, one paper, then exit."""

    import argparse
    import os
    import platform

    parser = argparse.ArgumentParser(prog="stella.workflow_runtime worker")
    parser.add_argument("operation_id")
    parser.add_argument("--paper", required=True)
    parser.add_argument("--request", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--telemetry", required=True)
    parser.add_argument("--root", required=True)
    args = parser.parse_args(argv)

    from stella.workflows import DEFAULT_ROOT

    operation = get_operation(args.operation_id, DEFAULT_ROOT)
    payload = json.loads(Path(args.request).read_text(encoding="utf-8"))
    payload.setdefault("papers", [args.paper])
    try:
        result = execute_operation(
            operation,
            payload,
            root=Path(args.root),
            paper_id=args.paper,
        )
    except Exception as error:  # noqa: BLE001 - structured worker failure
        result = {
            "operation_id": args.operation_id,
            "paper_id": args.paper,
            "status": "failed",
            "failure": {"kind": "internal", "detail": f"{type(error).__name__}: {error}"},
            "blockers": [],
            "next_action": "inspect the operation catalog and implementation",
            "warnings": [],
            "detail": {},
        }
    result["worker_pid"] = os.getpid()
    Path(args.result).parent.mkdir(parents=True, exist_ok=True)
    Path(args.result).write_text(
        json.dumps(result, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    Path(args.telemetry).write_text(
        json.dumps(
            {
                "worker_pid": os.getpid(),
                "python": platform.python_version(),
                "started_from_pid": os.environ.get("STELLA_PARENT_PID"),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return 0 if result.get("status") != "failed" else 1


if __name__ == "__main__":
    import sys

    argv = sys.argv[1:]
    if argv and argv[0] == "worker":
        argv = argv[1:]
    sys.exit(_worker_main(argv))


# --- Run lifecycle invariants -----------------------------------------------

RESUMABLE_PAPER_STATUSES = ("pending", "running", "network_failed")


def paper_status(root: Path, workflow_id: str, run_id: str, paper_id: str) -> str | None:
    status_path = run_dir(root, workflow_id, run_id) / "papers" / paper_id / "status.json"
    if not status_path.is_file():
        return None
    return json.loads(status_path.read_text(encoding="utf-8")).get("status")


def operation_status(
    root: Path, workflow_id: str, run_id: str, paper_id: str, operation_id: str
) -> str | None:
    status_path = run_dir(root, workflow_id, run_id) / "papers" / paper_id / "status.json"
    if not status_path.is_file():
        return None
    payload = json.loads(status_path.read_text(encoding="utf-8"))
    return (payload.get("operations") or {}).get(operation_id)


def record_paper_result(
    root: Path,
    workflow_id: str,
    run_id: str,
    paper_id: str,
    status: str,
    *,
    attempt: str | None = None,
    result: dict[str, Any] | None = None,
) -> None:
    """Append one attempt result and refresh the paper status (append-only)."""

    paper_dir = run_dir(root, workflow_id, run_id) / "papers" / paper_id
    if attempt is not None:
        attempt_dir = paper_dir / "attempts" / attempt
        attempt_dir.mkdir(parents=True, exist_ok=True)
        (attempt_dir / "result.json").write_text(
            json.dumps(result or {"status": status}, indent=2, sort_keys=True, default=str)
            + "\n",
            encoding="utf-8",
        )
    paper_dir.mkdir(parents=True, exist_ok=True)
    status_path = paper_dir / "status.json"
    payload: dict[str, Any] = {"status": status, "operations": {}}
    if status_path.is_file():
        try:
            payload = json.loads(status_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {"status": status, "operations": {}}
        payload.setdefault("operations", {})
    if attempt is not None:
        operation_id = attempt.rsplit("-", 1)[0]
        payload["operations"][operation_id] = status
    statuses = list(payload["operations"].values()) or [status]
    if any(item == "failed" for item in statuses):
        payload["status"] = "failed"
    elif statuses and all(item == "complete" for item in statuses):
        payload["status"] = "complete"
    else:
        payload["status"] = "partial"
    status_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _is_finalized(root: Path, workflow_id: str, run_id: str) -> bool:
    return (run_dir(root, workflow_id, run_id) / "finalized.json").is_file()


def attempt_allowed(
    root: Path,
    workflow_id: str,
    run_id: str,
    paper_id: str,
    *,
    operation_id: str | None = None,
) -> bool:
    """Finalized runs, successful papers, and successful (operation, paper)
    pairs never accept new attempts."""

    if _is_finalized(root, workflow_id, run_id):
        return False
    if operation_id is not None:
        return (
            operation_status(root, workflow_id, run_id, paper_id, operation_id)
            != "complete"
        )
    return paper_status(root, workflow_id, run_id, paper_id) != "complete"


def resume_eligible_papers(
    root: Path, workflow_id: str, run_id: str, papers: list[str]
) -> list[str]:
    """Only unfinished or explicitly network-failed papers may resume."""

    if _is_finalized(root, workflow_id, run_id):
        return []
    return [
        paper
        for paper in papers
        if (paper_status(root, workflow_id, run_id, paper) or "pending")
        not in ("complete", "failed")
    ]


def finalize_run(root: Path, workflow_id: str, run_id: str) -> str:
    """One-way finalize; returns the terminal complete/partial status."""

    directory = run_dir(root, workflow_id, run_id)
    marker = directory / "finalized.json"
    if marker.is_file():
        raise ValueError(f"run {run_id} is already finalized and immutable")
    requested = load_run(root, workflow_id, run_id).get("request", {}).get(
        "papers", []
    )
    states = {
        path.parent.name: json.loads(path.read_text(encoding="utf-8")).get("status")
        for path in (directory / "papers").glob("*/status.json")
    }
    ordered = [states.get(paper) for paper in requested] or list(states.values())
    if ordered and all(state == "complete" for state in ordered):
        final_status = "complete"
    else:
        final_status = "partial"
    marker.write_text(
        json.dumps({"final_status": final_status}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    append_event(
        root,
        workflow_id,
        run_id,
        RunEvent("run_finalized", detail={"final_status": final_status}),
    )
    return final_status


def _initial_concurrency() -> int:
    import os

    return max(1, min(8, int(os.environ.get("STELLA_RUN_CONCURRENCY", "2"))))


def _run_papers_bounded(
    *,
    root: Path,
    workflow_id: str,
    run_id: str,
    operation: Any,
    payload: dict,
    papers: list[str],
    env_extra: dict[str, str],
    concurrency: int,
) -> dict[str, Any]:
    """Run one per-paper operation under bounded adaptive concurrency.

    Each paper still gets a fresh worker process; the parent only owns
    scheduling, event logging, and deterministic ordering. A failure halves
    the next round's concurrency; a clean round recovers one slot.
    """

    from concurrent.futures import ThreadPoolExecutor

    directory = run_dir(root, workflow_id, run_id)
    results: dict[str, dict[str, Any]] = {}
    for paper_id in papers:
        append_event(
            root,
            workflow_id,
            run_id,
            RunEvent("attempt_started", paper_id=paper_id, operation=operation.id),
        )

    def _one(paper_id: str) -> tuple[str, str, dict[str, Any]]:
        attempt_id = _next_attempt_id(directory, paper_id, operation.id)
        attempt_dir = directory / "papers" / paper_id / "attempts" / attempt_id
        result = _spawn_paper_worker(
            root=root,
            operation=operation,
            paper_id=paper_id,
            payload=payload,
            attempt_dir=attempt_dir,
            env_extra=env_extra,
        )
        return paper_id, attempt_id, result

    workers = max(1, min(concurrency, len(papers) or 1))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for paper_id, attempt_id, result in pool.map(_one, papers):
            results[paper_id] = result
            status = result.get("status", "failed")
            record_paper_result(
                root,
                workflow_id,
                run_id,
                paper_id,
                status,
                attempt=attempt_id,
                result=result,
            )
            append_event(
                root,
                workflow_id,
                run_id,
                RunEvent(
                    "attempt_finished",
                    paper_id=paper_id,
                    operation=operation.id,
                    detail={"status": status},
                ),
            )
    failed = sum(
        1 for result in results.values() if result.get("status") == "failed"
    )
    if failed:
        next_concurrency = max(1, concurrency // 2)
    elif len(papers) > concurrency:
        next_concurrency = min(8, concurrency + 1)
    else:
        next_concurrency = concurrency
    return {"results": results, "next_concurrency": next_concurrency}


def _next_attempt_id(directory: Path, paper_id: str, operation_id: str) -> str:
    attempts = (directory / "papers" / paper_id / "attempts").glob(f"{operation_id}-*")
    return f"{operation_id}-{sum(1 for _ in attempts) + 1}"


def attempt_dir_name(operation_id: str, result: dict[str, Any]) -> str:
    return str(result.get("attempt") or f"{operation_id}-latest")
