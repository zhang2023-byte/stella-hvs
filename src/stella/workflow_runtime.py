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
    operations: list[OperationSpec],
    papers: list[str] | None,
    root: Path,
    *,
    replacements: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    """Best-effort read-path existence checks with no side effects."""

    checks: list[dict[str, str]] = []
    for operation in operations:
        for read in operation.reads:
            resolved_read = read
            for key, value in (replacements or {}).items():
                resolved_read = resolved_read.replace(f"<{key}>", value)
            if "<paper_id>" in resolved_read and papers:
                for paper_id in papers:
                    paper_read = resolved_read.replace("<paper_id>", paper_id)
                    path = Path(root) / paper_read
                    checks.append(
                        {
                            "operation": operation.id,
                            "read": paper_read,
                            "status": "present" if path.exists() else "absent",
                        }
                    )
            elif "<" not in resolved_read:
                path = Path(root) / resolved_read
                checks.append(
                    {
                        "operation": operation.id,
                        "read": resolved_read,
                        "status": "present" if path.exists() else "absent",
                    }
                )
            else:
                checks.append(
                    {
                        "operation": operation.id,
                        "read": resolved_read,
                        "status": "unresolved",
                    }
                )
    return checks


def _resolved_plan_inputs(
    workflow_id: str, request: WorkflowRequest
) -> tuple[list[str], dict[str, str]]:
    """Resolve stable repository-owned defaults without executing operations."""

    papers = list(getattr(request, "papers", None) or [])
    replacements: dict[str, str] = {}
    run_id = str(getattr(request, "run_id", None) or "")
    if run_id:
        replacements["run_id"] = run_id
    if workflow_id == "gold_annotation":
        return papers, replacements
    if workflow_id != "benchmark":
        return papers, replacements

    from stella.benchmark.campaign import papers_for_profile
    from stella.benchmark.gold_selection import contribution_selection_id
    from stella.schema_registry import ACTIVE_BENCHMARK_CAMPAIGN

    profile = str(getattr(request, "profile", "dev10"))
    selection_payload = {
        "gold_selection_id": getattr(request, "gold_selection_id", None)
    }
    replacements["selection_id"] = contribution_selection_id(
        selection_payload,
        profile=profile,
    )
    if papers:
        return papers, replacements

    campaign_path = (
        DEFAULT_ROOT
        / "benchmark"
        / "campaigns"
        / ACTIVE_BENCHMARK_CAMPAIGN
        / "manifest"
        / "campaign_manifest.json"
    )
    campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
    papers = papers_for_profile(campaign, profile)
    return papers, replacements


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
    papers, replacements = _resolved_plan_inputs(workflow_id, request)
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
        "resolved_inputs": replacements,
        "preflight_checks": preflight_checks(
            operations,
            papers,
            root,
            replacements=replacements,
        ),
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


def _papers_from_frozen_campaign(
    root: Path, workflow_id: str, run_id: str
) -> list[str]:
    """Resolve an empty paper set from the run's frozen campaign sample."""

    campaign_path = run_dir(root, workflow_id, run_id) / "campaign.json"
    if not campaign_path.is_file():
        return []
    try:
        campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
    except ValueError:
        return []
    return [
        str(paper.get("arxiv_id"))
        for paper in campaign.get("papers") or []
        if paper.get("arxiv_id")
    ]


def _summarize_statuses(statuses: list[str]) -> str:
    """Aggregate paper statuses without ever synthesizing success.

    Failures dominate; network failures stay resumable; any incomplete
    paper keeps the run partial rather than complete.
    """

    if not statuses:
        return "failed"
    if all(status == "failed" for status in statuses):
        return "failed"
    if any(status == "failed" for status in statuses):
        return "partial"
    if any(status == "interrupted" for status in statuses):
        return "interrupted"
    if any(status == "network_failed" for status in statuses):
        return "network_failed"
    if any(status in ("partial", "pending", "running", "skipped") for status in statuses):
        return "partial"
    return "complete"


def _merge_chain_status(current: str, result_status: str) -> str:
    """Keep the strongest typed outcome seen in one worker chain."""

    if result_status in ("failed", "network_failed", "interrupted"):
        return result_status
    if result_status == "partial" and current == "complete":
        return "partial"
    return current


def _spawn_paper_worker(
    *,
    root: Path,
    workflow_id: str,
    run_id: str,
    operations: list[Any],
    paper_id: str,
    payload: dict,
    result_path: Path,
    env_extra: dict[str, str],
) -> dict[str, Any]:
    """Run one paper's whole operation chain in one fresh worker process."""

    import os
    import subprocess
    import sys

    result_path.parent.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, **env_extra}
    src_root = str(Path(__file__).resolve().parents[2] / "src")
    env["PYTHONPATH"] = src_root + os.pathsep + env.get("PYTHONPATH", "")
    command = [
        sys.executable,
        "-m",
        "stella.workflow_runtime",
        "worker",
        "--paper",
        paper_id,
        "--operations",
        ",".join(operation.id for operation in operations),
        "--workflow",
        workflow_id,
        "--run-id",
        run_id,
        "--request-payload",
        json.dumps(payload, sort_keys=True),
        "--result",
        str(result_path),
        "--root",
        str(Path(root).resolve()),
    ]
    timeout_text = env.get("STELLA_WORKER_TIMEOUT")
    timeout = int(timeout_text) if timeout_text else None
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        operation_id = operations[0].id if operations else "worker"
        interrupted = {
            "status": "interrupted",
            "failure": {
                "kind": "timeout",
                "detail": f"worker exceeded the explicit {error.timeout}s deadline",
            },
        }
        return {
            "paper_id": paper_id,
            "status": "interrupted",
            "operations": [
                {"operation_id": operation_id, "result": interrupted}
            ],
            "skipped": [operation.id for operation in operations[1:]],
            "failure": interrupted["failure"],
        }
    if result_path.is_file():
        return json.loads(result_path.read_text(encoding="utf-8"))
    return {
        "paper_id": paper_id,
        "status": "failed",
        "operations": [],
        "failure": {
            "kind": "internal",
            "detail": (
                f"worker exited with code {completed.returncode}: "
                f"{completed.stderr.strip()[-800:]}"
            ),
        },
    }


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
    request_run_id = getattr(request, "run_id", None)
    if run_id and request_run_id and run_id != request_run_id:
        raise StellaError(
            "INVALID_INPUT",
            "the explicit run id disagrees with the request run_id",
            next_action="select exactly one existing run id",
        )
    resolved_run_id = run_id or request_run_id or new_run_id()
    payload = request.model_dump(mode="json")
    papers = list(getattr(request, "papers") or [])
    # Every adapter receives the outer run id: no implicit side-run ids.
    payload["run_id"] = resolved_run_id
    existing_dir = run_dir(Path(root), workflow_id, resolved_run_id)
    if existing_dir.is_dir():
        # Resume mode: the frozen run record stays authoritative; only
        # eligible papers (see attempt_allowed) execute again.
        state = load_run(Path(root), workflow_id, resolved_run_id)
        if state.get("workflow_id") != workflow_id:
            raise StellaError(
                "INVALID_INPUT",
                f"run id {resolved_run_id} belongs to another workflow",
                next_action="choose a fresh run id",
            )
        if workflow_id == "benchmark":
            creation_operations = {
                "benchmark.prepare_campaign",
                "benchmark.freeze_method",
                "benchmark.execute",
            }
            if any(
                operation.id in creation_operations for operation in operations
            ):
                raise StellaError(
                    "INVALID_LIFECYCLE",
                    "an existing benchmark run cannot repeat prepare, freeze, or run",
                    next_action="select resume, finalize, or score for this run id",
                )
        post_finalize_operations = {
            "benchmark.score",
            "benchmark.emit_scorecard",
        }
        if (existing_dir / "finalized.json").is_file() and any(
            operation.id not in post_finalize_operations
            for operation in operations
        ):
            raise StellaError(
                "RUN_FINALIZED",
                f"run {resolved_run_id} is finalized and immutable",
                next_action="select only the score phase or create a new run",
            )
        # An existing run's scientific configuration is immutable.  A new
        # request supplies only lifecycle phases and fresh authority grants;
        # papers, profile, and method come from the frozen run record.
        frozen_payload = dict(state.get("request") or {})
        payload = {
            **frozen_payload,
            "authorities": request.authorities.model_dump(mode="json"),
            "phases": getattr(request, "phases", None),
            "run_id": resolved_run_id,
        }
        if workflow_id == "benchmark":
            payload["finalize_partial_explicitly_authorized"] = getattr(
                request, "finalize_partial_explicitly_authorized", False
            )
        papers = list(frozen_payload.get("papers") or [])
    else:
        state = create_run(
            root=root,
            workflow_id=workflow_id,
            request=request,
            run_id=resolved_run_id,
            extra={"phases": [phase.id for phase in phases]},
        )
    if not papers:
        papers = _papers_from_frozen_campaign(
            Path(root), workflow_id, resolved_run_id
        )
    if papers:
        payload["papers"] = list(papers)
    directory = run_dir(root, workflow_id, resolved_run_id)
    env_extra = dict(env_extra or {})
    env_extra.setdefault("STELLA_WORKER_RUN_ID", resolved_run_id)
    # Workflow-scoped operations run in this process, so the declared run
    # environment (session injections, credentials) must be visible here
    # exactly as it is in every worker process.
    restored_env: dict[str, str | None] = {}
    for key, value in env_extra.items():
        restored_env[key] = os.environ.get(key)
        os.environ[key] = value
    try:
        return _execute_workflow_plan(
            root=root,
            workflow_id=workflow_id,
            resolved_run_id=resolved_run_id,
            state=state,
            payload=payload,
            papers=papers,
            phases=phases,
            operations=operations,
            contracts=contracts,
            env_extra=env_extra,
        )
    finally:
        for key, previous in restored_env.items():
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous


def _execute_workflow_plan(
    *,
    root: Path,
    workflow_id: str,
    resolved_run_id: str,
    state: dict[str, Any],
    payload: dict[str, Any],
    papers: list[str],
    phases: list[Any],
    operations: list[OperationSpec],
    contracts: dict[str, dict[str, Any]],
    env_extra: dict[str, str],
) -> dict[str, Any]:
    import os

    directory = run_dir(root, workflow_id, resolved_run_id)
    papers_root = directory / "papers"

    failures: list[str] = []
    paper_states: dict[str, str] = {
        paper: paper_status(root, workflow_id, resolved_run_id, paper) or "pending"
        for paper in papers
    }
    supersede_events: list[dict[str, Any]] = []
    finalized_status: str | None = None
    concurrency = _initial_concurrency(workflow_id, payload)

    # Segment the ordered operations: contiguous workflow-scoped runs become
    # parent-side barriers between per-paper chain segments, preserving phase
    # order (fetch -> archive/catalog/contributions -> indexes).
    segments: list[dict[str, Any]] = []
    for operation in operations:
        kind = (
            "scoped" if operation.per_paper == "workflow_scoped" else "pp"
        )
        if segments and segments[-1]["kind"] == kind:
            segments[-1]["operations"].append(operation)
        else:
            segments.append({"kind": kind, "operations": [operation]})

    aborted = False
    for segment in segments:
        if aborted:
            break
        if segment["kind"] == "scoped":
            for operation in segment["operations"]:
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
                    aborted = True
                    break
                operation_final_status = (result.get("detail") or {}).get(
                    "final_status"
                )
                if operation_final_status in ("complete", "partial"):
                    finalized_status = operation_final_status
                if not papers:
                    papers.extend(
                        _papers_from_frozen_campaign(
                            Path(root), workflow_id, resolved_run_id
                        )
                    )
                    if papers:
                        payload["papers"] = list(papers)
                superseded = (result.get("detail") or {}).get(
                    "superseded_previous_sha256"
                )
                if superseded:
                    supersede_events.append(
                        {"operation": operation.id, "previous_sha256": superseded}
                    )
            continue
        is_resume = any(
            operation.id == "benchmark.resume"
            for operation in segment["operations"]
        )
        eligible = (
            resume_eligible_papers(root, workflow_id, resolved_run_id, papers)
            if is_resume
            else [
                paper
                for paper in papers
                if attempt_allowed(root, workflow_id, resolved_run_id, paper)
            ]
        )
        if not eligible:
            continue
        outcome = _run_papers_bounded(
            root=root,
            workflow_id=workflow_id,
            run_id=resolved_run_id,
            operations=segment["operations"],
            payload=payload,
            papers=eligible,
            env_extra=env_extra,
            concurrency=concurrency,
        )
        concurrency = outcome["next_concurrency"]
        for paper_id, worker_outcome in outcome["results"].items():
            status = worker_outcome.get("status", "failed")
            paper_states[paper_id] = status
            for entry in worker_outcome.get("operations", []):
                operation_id = entry["operation_id"]
                op_result = entry["result"]
                if op_result.get("status") in (
                    "failed",
                    "network_failed",
                    "interrupted",
                ):
                    failures.append(f"{operation_id}:{paper_id}")
                superseded = (op_result.get("detail") or {}).get(
                    "superseded_previous_sha256"
                )
                if superseded:
                    supersede_events.append(
                        {
                            "operation": operation_id,
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
                            operation=operation_id,
                            detail={"previous_sha256": superseded},
                        ),
                    )

    paper_states = {
        paper: paper_status(root, workflow_id, resolved_run_id, paper)
        or paper_states.get(paper, "pending")
        for paper in papers
    }
    statuses = list(paper_states.values())
    has_per_paper = any(
        segment["kind"] == "pp" for segment in segments
    )
    if finalized_status is not None:
        summary_status = finalized_status
    elif has_per_paper:
        # An empty executable paper set is a failed precondition, never a
        # synthesized success.
        summary_status = _summarize_statuses(statuses)
    elif failures:
        summary_status = "failed"
    else:
        summary_status = "complete"
    if papers and paper_states and all(
        status == "failed" for status in paper_states.values()
    ):
        summary_status = "failed"
    summary = {
        "workflow_id": workflow_id,
        "run_id": resolved_run_id,
        "status": summary_status,
        "papers": [
            {"paper_id": paper_id, "status": paper_states.get(paper_id, "pending")}
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
    state["state"] = summary_status
    save_run_state(root, workflow_id, resolved_run_id, state)
    return summary


def _worker_main(argv: list[str]) -> int:
    """Fresh-worker entry point: one paper, its ordered chain, then exit."""

    import argparse
    import os
    import platform

    parser = argparse.ArgumentParser(prog="stella.workflow_runtime worker")
    parser.add_argument("--paper", required=True)
    parser.add_argument("--operations", required=True)
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--request-payload", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--root", required=True)
    args = parser.parse_args(argv)

    paper_id = args.paper
    operation_ids = [item for item in args.operations.split(",") if item]
    payload = json.loads(args.request_payload)
    # Hard single-paper isolation: a worker may never retain the complete
    # multi-paper request or see another paper's context.
    payload["papers"] = [paper_id]
    payload["run_id"] = args.run_id

    executed: list[dict[str, Any]] = []
    skipped: list[str] = []
    worker_notes: dict[str, Any] = {
        "worker_pid": os.getpid(),
        "python": platform.python_version(),
        "started_from_pid": os.environ.get("STELLA_PARENT_PID"),
        "papers": [paper_id],
        "operations": operation_ids,
    }
    chain_status = "complete"
    attempt_ids = dict(payload.get("_workflow_attempt_ids") or {})
    directory = run_dir(Path(args.root), args.workflow, args.run_id)
    for operation_id in operation_ids:
        operation = get_operation(operation_id, DEFAULT_ROOT)
        if chain_status in ("failed", "network_failed", "interrupted"):
            skipped.append(operation_id)
            continue
        attempt_id = attempt_ids.get(operation_id)
        if attempt_id is None:
            attempt_id = _reserve_attempt_id(directory, paper_id, operation_id)
            attempt_ids[operation_id] = attempt_id
        result = execute_operation(
            operation,
            payload,
            root=Path(args.root),
            paper_id=paper_id,
        )
        executed.append(
            {
                "operation_id": operation_id,
                "attempt_id": attempt_id,
                "result": result,
            }
        )
        chain_status = _merge_chain_status(
            chain_status, str(result.get("status") or "failed")
        )
    if skipped:
        chain_status = "failed" if chain_status == "failed" else chain_status
    outcome: dict[str, Any] = {
        "paper_id": paper_id,
        "operations": executed,
        "skipped": skipped,
        "status": chain_status,
        "telemetry": worker_notes,
    }
    Path(args.result).parent.mkdir(parents=True, exist_ok=True)
    Path(args.result).write_text(
        json.dumps(outcome, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    return 0 if outcome["status"] not in ("failed", "network_failed", "interrupted") else 1


# --- Run lifecycle invariants -----------------------------------------------

RESUMABLE_PAPER_STATUSES = ("pending", "running", "network_failed", "interrupted")


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


def _aggregate_operation_statuses(statuses: list[str]) -> str:
    """Aggregate per-operation statuses; failures dominate, network is resumable."""

    if any(item == "failed" for item in statuses):
        return "failed"
    if any(item == "interrupted" for item in statuses):
        return "interrupted"
    if any(item == "network_failed" for item in statuses):
        return "network_failed"
    if statuses and all(item == "complete" for item in statuses):
        return "complete"
    if statuses and all(item == "pending" for item in statuses):
        return "pending"
    if statuses and all(item in ("pending", "running") for item in statuses):
        return "running"
    if not statuses:
        return "pending"
    return "partial"


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
            json.dumps(
                result or {"status": status}, indent=2, sort_keys=True, default=str
            )
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
    payload["status"] = _aggregate_operation_statuses(
        list(payload["operations"].values()) or [status]
    )
    status_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def record_operation_status(
    root: Path,
    workflow_id: str,
    run_id: str,
    paper_id: str,
    operation_id: str,
    status: str,
) -> None:
    """Record an operation-level status without creating an attempt."""

    paper_dir = run_dir(root, workflow_id, run_id) / "papers" / paper_id
    paper_dir.mkdir(parents=True, exist_ok=True)
    status_path = paper_dir / "status.json"
    payload: dict[str, Any] = {"status": "pending", "operations": {}}
    if status_path.is_file():
        try:
            payload = json.loads(status_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {"status": "pending", "operations": {}}
        payload.setdefault("operations", {})
    payload["operations"][operation_id] = status
    payload["status"] = _aggregate_operation_statuses(
        list(payload["operations"].values())
    )
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
        in RESUMABLE_PAPER_STATUSES
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


def _initial_concurrency(
    workflow_id: str = "", payload: dict[str, Any] | None = None
) -> int:
    import os

    if workflow_id == "benchmark":
        policy = dict((payload or {}).get("execution_policy") or {})
        return int(policy.get("paper_workers") or 10)
    return max(1, min(8, int(os.environ.get("STELLA_RUN_CONCURRENCY", "2"))))


def _run_papers_bounded(
    *,
    root: Path,
    workflow_id: str,
    run_id: str,
    operations: list[Any],
    payload: dict,
    papers: list[str],
    env_extra: dict[str, str],
    concurrency: int,
) -> dict[str, Any]:
    """Run each paper's whole chain under bounded adaptive concurrency.

    Each paper owns exactly one fresh worker process for its ordered
    paper-local chain; the parent only owns scheduling, artifact/event
    recording, and deterministic ordering. A failure halves the next
    round's concurrency; a clean round recovers one slot.
    """

    from concurrent.futures import ThreadPoolExecutor, as_completed

    directory = run_dir(root, workflow_id, run_id)
    results: dict[str, dict[str, Any]] = {}
    for paper_id in papers:
        append_event(
            root,
            workflow_id,
            run_id,
            RunEvent(
                "paper_worker_queued",
                paper_id=paper_id,
                detail={
                    "operations": [operation.id for operation in operations]
                },
            ),
        )

    def _one(paper_id: str) -> tuple[str, dict[str, Any]]:
        first_operation = operations[0]
        attempt_ids = {
            first_operation.id: _reserve_attempt_id(
                directory, paper_id, first_operation.id
            )
        }
        first_attempt = next(iter(attempt_ids.values()))
        scratch = (
            directory / "papers" / paper_id / "attempts" / first_attempt
            / "worker-result.json"
        )
        worker_payload = dict(payload)
        worker_payload["_workflow_attempt_ids"] = attempt_ids
        paper_attempts = directory / "papers" / paper_id / "attempts"
        benchmark_attempts = list(paper_attempts.glob("benchmark.execute-*"))
        benchmark_attempts += list(paper_attempts.glob("benchmark.resume-*"))
        if benchmark_attempts:
            worker_payload["_benchmark_execution_attempt"] = len(benchmark_attempts)
        append_event(
            root,
            workflow_id,
            run_id,
            RunEvent(
                "paper_worker_started",
                paper_id=paper_id,
                detail={
                    "operations": [operation.id for operation in operations],
                    "attempts": attempt_ids,
                },
            ),
        )
        try:
            outcome = _spawn_paper_worker(
                root=root,
                workflow_id=workflow_id,
                run_id=run_id,
                operations=operations,
                paper_id=paper_id,
                payload=worker_payload,
                result_path=scratch,
                env_extra=env_extra,
            )
        except Exception as error:  # noqa: BLE001 - isolate parent-side failures
            operation_id = operations[0].id
            interrupted = {
                "status": "interrupted",
                "failure": {
                    "kind": "internal",
                    "detail": (
                        "paper worker orchestration failed: "
                        f"{type(error).__name__}: {error}"
                    ),
                },
            }
            outcome = {
                "paper_id": paper_id,
                "operations": [
                    {"operation_id": operation_id, "result": interrupted}
                ],
                "skipped": [operation.id for operation in operations[1:]],
                "status": "interrupted",
                "failure": interrupted["failure"],
            }
        _record_paper_outcome(
            root=root,
            workflow_id=workflow_id,
            run_id=run_id,
            paper_id=paper_id,
            outcome=outcome,
            attempt_ids=attempt_ids,
        )
        append_event(
            root,
            workflow_id,
            run_id,
            RunEvent(
                "paper_worker_finished",
                paper_id=paper_id,
                detail={"status": outcome.get("status")},
            ),
        )
        return paper_id, outcome

    workers = max(1, min(concurrency, len(papers) or 1))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_one, paper_id): paper_id for paper_id in papers}
        for future in as_completed(futures):
            paper_id, outcome = future.result()
            results[paper_id] = outcome
    failed = sum(
        1 for outcome in results.values()
        if outcome.get("status") in ("failed", "network_failed", "interrupted")
    )
    if failed:
        next_concurrency = max(1, concurrency // 2)
    elif len(papers) > concurrency:
        next_concurrency = min(8, concurrency + 1)
    else:
        next_concurrency = concurrency
    return {"results": results, "next_concurrency": next_concurrency}


def _record_paper_outcome(
    *,
    root: Path,
    workflow_id: str,
    run_id: str,
    paper_id: str,
    outcome: dict[str, Any],
    attempt_ids: dict[str, str],
) -> None:
    """Persist one worker outcome as append-only attempts and statuses."""

    directory = run_dir(root, workflow_id, run_id)
    telemetry = outcome.get("telemetry") or {}
    for entry in outcome.get("operations", []):
        operation_id = entry["operation_id"]
        result = entry["result"]
        attempt_id = entry.get("attempt_id") or attempt_ids[operation_id]
        attempt_dir = directory / "papers" / paper_id / "attempts" / attempt_id
        attempt_dir.mkdir(parents=True, exist_ok=True)
        if telemetry.get("worker_pid"):
            result = dict(result)
            result["worker_pid"] = telemetry["worker_pid"]
        (attempt_dir / "result.json").write_text(
            json.dumps(result, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
        if telemetry:
            (attempt_dir / "telemetry.json").write_text(
                json.dumps(telemetry, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        record_paper_result(
            root,
            workflow_id,
            run_id,
            paper_id,
            result.get("status", "failed"),
            attempt=attempt_id,
            result=result,
        )
        if operation_id == "benchmark.resume" and result.get("status") in (
            "complete",
            "partial",
        ):
            # Resume is a new audit event for the same scientific execution.
            # Replace the stale network-failed execution status while keeping
            # every attempt directory append-only.
            record_operation_status(
                root,
                workflow_id,
                run_id,
                paper_id,
                "benchmark.execute",
                result.get("status", "failed"),
            )
        append_event(
            root,
            workflow_id,
            run_id,
            RunEvent(
                "attempt_finished",
                paper_id=paper_id,
                operation=operation_id,
                detail={"status": result.get("status")},
            ),
        )
    for operation_id in outcome.get("skipped", []):
        record_operation_status(
            root, workflow_id, run_id, paper_id, operation_id, "skipped"
        )
        append_event(
            root,
            workflow_id,
            run_id,
            RunEvent(
                "operation_skipped",
                paper_id=paper_id,
                operation=operation_id,
                detail={"reason": "upstream failure"},
            ),
        )


def _reserve_attempt_id(directory: Path, paper_id: str, operation_id: str) -> str:
    """Atomically reserve an append-only attempt directory before spawning."""

    attempts_root = directory / "papers" / paper_id / "attempts"
    attempts_root.mkdir(parents=True, exist_ok=True)
    ordinal = 1
    while True:
        attempt_id = f"{operation_id}-{ordinal}"
        try:
            (attempts_root / attempt_id).mkdir()
        except FileExistsError:
            ordinal += 1
            continue
        return attempt_id


def attempt_dir_name(operation_id: str, result: dict[str, Any]) -> str:
    return str(result.get("attempt") or f"{operation_id}-latest")


if __name__ == "__main__":
    import sys

    argv = sys.argv[1:]
    if argv and argv[0] == "worker":
        argv = argv[1:]
    sys.exit(_worker_main(argv))
