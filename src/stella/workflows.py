"""Deterministic workflow and operation catalogs plus request models.

This module owns the Pydantic contract for the two YAML catalogs under
``workflows/``: ``stella_workflows.yaml`` (the three public product
workflows) and ``operations.yaml`` (internal operation metadata). It also
defines the workflow request models referenced by those catalogs. Catalog
paths are resolved relative to the repository that owns this module, never
relative to the process working directory.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

DEFAULT_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_INDEX_PATH = Path("workflows") / "stella_workflows.yaml"
OPERATION_CATALOG_PATH = Path("workflows") / "operations.yaml"

AuthorityKind = Literal[
    "network",
    "llm",
    "gold_private",
    "scoring",
    "supersede",
    "publication",
]
AUTHORITY_KINDS: tuple[str, ...] = (
    "network",
    "llm",
    "gold_private",
    "scoring",
    "supersede",
    "publication",
)


class ContractModel(BaseModel):
    """Base model for catalog and request contracts."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class WorkflowPhaseSpec(ContractModel):
    id: str
    operations: list[str] = Field(min_length=1)
    optional: bool = False
    gate: str | None = None


class WorkflowSpec(ContractModel):
    id: str
    human_intents: list[str] = Field(min_length=1)
    input_model: str
    output_model: str
    phases: list[WorkflowPhaseSpec] = Field(min_length=1)
    default_behavior: Literal["plan"] = "plan"
    authority_gates: dict[str, str] = Field(min_length=1)
    failure_policy: Literal["complete", "partial"]

    @field_validator("authority_gates")
    @classmethod
    def _known_authority_kinds(cls, value: dict[str, str]) -> dict[str, str]:
        unknown = sorted(set(value) - set(AUTHORITY_KINDS))
        if unknown:
            raise ValueError(f"unknown authority kinds: {unknown}")
        return value
    @property
    def operation_ids(self) -> list[str]:
        return [
            operation_id
            for phase in self.phases
            for operation_id in phase.operations
        ]


class WorkflowCatalog(ContractModel):
    version: int
    workflows: list[WorkflowSpec] = Field(min_length=1)

    @property
    def by_id(self) -> dict[str, WorkflowSpec]:
        return {spec.id: spec for spec in self.workflows}


class OperationSpec(ContractModel):
    id: str
    owner: str
    callable: str
    input_model: str | None = None
    output_model: str | None = None
    reads: list[str] = Field(default_factory=list)
    writes: list[str] = Field(default_factory=list)
    validators: list[str] = Field(default_factory=list)
    authorities: list[AuthorityKind] = Field(default_factory=list)
    per_paper: Literal["worker_per_paper", "workflow_scoped"]
    retry_classification: Literal["network_retryable", "terminal"]
    risk: str = ""
    contracts: list[str] = Field(default_factory=list)
    tests: list[str] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _namespaced_id(cls, value: str) -> str:
        if value.count(".") != 1 or not all(value.split(".")):
            raise ValueError("operation id must be 'namespace.leaf'")
        return value

    @field_validator("callable", "input_model", "output_model")
    @classmethod
    def _reference_shape(cls, value: str | None) -> str | None:
        if value is None:
            return value
        module, sep, attribute = value.partition(":")
        if not sep or not module or not attribute:
            raise ValueError(f"reference must be 'module:attribute': {value!r}")
        return value


class OperationCatalog(ContractModel):
    version: int
    operations: list[OperationSpec] = Field(min_length=1)

    @property
    def by_id(self) -> dict[str, OperationSpec]:
        return {spec.id: spec for spec in self.operations}


class Authorities(ContractModel):
    """Explicit, fail-closed authority grants carried by every request."""

    execute: bool = False
    network: bool = False
    llm: bool = False
    gold_private: bool = False
    scoring: bool = False
    supersede: bool = False
    publication: bool = False

    def granted(self) -> list[str]:
        return [kind for kind in AUTHORITY_KINDS if getattr(self, kind)]


class WorkflowRequest(ContractModel):
    authorities: Authorities = Field(default_factory=Authorities)


class LiteraturePipelineRequest(WorkflowRequest):
    """One-paper or many-paper literature pipeline request.

    Cardinality is input data: there is no separate batch workflow.
    """

    papers: list[str] = Field(min_length=1)
    phases: list[str] | None = None
    fetch_months: list[str] | None = None


class GoldAnnotationRequest(WorkflowRequest):
    """One human action over the private contribution Gold store.

    Each invocation performs exactly one action: list the queue, open the
    form for one paper, validate the current draft, save with the expert
    approval gate, or prepare/publish the value-free selection manifest.
    """

    expert: str
    papers: list[str] = Field(min_length=1)
    action: Literal["queue", "open", "validate", "save", "selection"] = "queue"
    expert_approved: bool = False
    retain_migration_work: bool = False
    selection_id: str | None = None
    legacy_selection_id: str | None = None
    legacy_preservation_ref: str | None = None
    base_selection_id: str | None = None
    expected_current_sha256: str | None = None
    # Explicit phases override the action default for single-phase reuse;
    # unattended open->validate->save chains are never implied.
    phases: list[str] | None = None


# One action maps to exactly the phases it needs, never the whole chain.
GOLD_ACTION_PHASES: dict[str, list[str]] = {
    "queue": ["queue"],
    "open": ["annotate"],
    "validate": ["validate"],
    "save": ["save"],
    "selection": ["selection"],
}


class BenchmarkRequest(WorkflowRequest):
    """One benchmark request; phases select the lifecycle segment.

    The default runs prepare, freeze, run, and finalize; the optional
    ``resume`` and ``score`` phases join only when explicitly requested,
    so an extraction-only request never demands Gold or scoring authority.
    """

    run_id: str | None = None
    profile: Literal["dev10", "full50"] = "dev10"
    full50_explicitly_authorized: bool = False
    papers: list[str] | None = None
    phases: list[str] | None = None
    gold_selection_id: str | None = None
    # Request-carried frozen method settings (provider/model parameters,
    # budgets, ladders); validated against the contribution method model.
    # Omitting it uses the documented validated defaults.
    method: dict[str, Any] | None = None

    @field_validator("run_id")
    @classmethod
    def _safe_run_id(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value):
            raise ValueError(
                "run_id must contain only letters, digits, '.', '_' or '-'"
            )
        return value


def default_requested_phases(
    workflow_id: str, request: WorkflowRequest
) -> list[str] | None:
    """Phase ids a request asks for before optional-phase filtering.

    Only ``gold_annotation`` derives phases from its single human action;
    other workflows run their non-optional phases unless ``phases`` is set.
    """

    explicit = getattr(request, "phases", None)
    if explicit is not None:
        return explicit
    if workflow_id == "gold_annotation":
        return list(GOLD_ACTION_PHASES[request.action])  # type: ignore[attr-defined]
    return None


WORKFLOW_REQUEST_MODELS: dict[str, type[WorkflowRequest]] = {
    "literature_pipeline": LiteraturePipelineRequest,
    "gold_annotation": GoldAnnotationRequest,
    "benchmark": BenchmarkRequest,
}


class PaperRunStatus(ContractModel):
    paper_id: str
    status: Literal["pending", "running", "complete", "failed"]


OperationStatus = Literal[
    "complete",
    "partial",
    "blocked",
    "failed",
    "network_failed",
    "skipped",
]
OPERATION_STATUSES: tuple[str, ...] = (
    "complete",
    "partial",
    "blocked",
    "failed",
    "network_failed",
    "skipped",
)


class FailureDetail(ContractModel):
    """Structured failure classification for one operation result."""

    kind: Literal[
        "authority", "network", "validation", "precondition", "internal"
    ]
    detail: str = ""


class OperationResult(ContractModel):
    """The one envelope every operation callable must return.

    Scientific success and transport failure are statuses, never free-form
    messages: ``network_failed`` is resumable, ``failed`` is terminal, and
    ``blocked`` means a gate (authority, missing input) stopped the work
    before any scientific call happened.
    """

    operation_id: str = ""
    status: OperationStatus
    paper_id: str | None = None
    artifacts: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    next_action: str = ""
    failure: FailureDetail | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


def operation_failed(
    detail: str,
    *,
    kind: str = "internal",
    blockers: list[str] | None = None,
    next_action: str = "",
    warnings: list[str] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build the failure envelope shared by every operation adapter."""

    return {
        "status": "network_failed" if kind == "network" else "failed",
        "failure": {"kind": kind, "detail": detail},
        "blockers": blockers or [],
        "next_action": next_action,
        "warnings": warnings or [],
        "detail": dict(extra),
    }


def operation_complete(
    *,
    artifacts: list[str] | None = None,
    warnings: list[str] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build the success envelope shared by every operation adapter."""

    return {
        "status": "complete",
        "artifacts": artifacts or [],
        "warnings": warnings or [],
        "detail": dict(extra),
    }


class WorkflowRunSummary(ContractModel):
    workflow_id: str
    run_id: str
    status: Literal["planned", "running", "complete", "partial", "failed"]
    papers: list[PaperRunStatus] = Field(default_factory=list)
    detail: dict[str, Any] = Field(default_factory=dict)


class StellaError(Exception):
    """Structured CLI error with a stable code and next action."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        missing_authority: list[str] | None = None,
        missing_input: list[str] | None = None,
        next_action: str = "",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.missing_authority = missing_authority or []
        self.missing_input = missing_input or []
        self.next_action = next_action

    def payload(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "missing_authority": self.missing_authority,
            "missing_input": self.missing_input,
            "next_action": self.next_action,
        }


def resolve_reference(reference: str) -> Any:
    """Import a ``module:attribute`` reference without touching the cwd."""

    module_name, _, attribute = reference.partition(":")
    module = importlib.import_module(module_name)
    try:
        return getattr(module, attribute)
    except AttributeError as error:
        raise StellaError(
            "OPERATION_NOT_IMPLEMENTED",
            f"reference {reference!r} does not resolve",
            next_action="implement the operation callable or model before executing",
        ) from error


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected a YAML mapping in {path}")
    return payload


def _repo_root(root: Path | None) -> Path:
    return Path(root).resolve() if root is not None else DEFAULT_ROOT


def load_workflow_catalog(root: Path | None = None) -> WorkflowCatalog:
    repo_root = _repo_root(root)
    payload = _load_yaml(repo_root / WORKFLOW_INDEX_PATH)
    return WorkflowCatalog.model_validate(payload)


def load_operation_catalog(root: Path | None = None) -> OperationCatalog:
    repo_root = _repo_root(root)
    payload = _load_yaml(repo_root / OPERATION_CATALOG_PATH)
    return OperationCatalog.model_validate(payload)


def get_workflow(workflow_id: str, root: Path | None = None) -> WorkflowSpec:
    catalog = load_workflow_catalog(root)
    spec = catalog.by_id.get(workflow_id)
    if spec is None:
        raise StellaError(
            "UNKNOWN_WORKFLOW",
            f"unknown workflow id: {workflow_id}",
            next_action="run 'python -m stella workflow list --json' to see products",
        )
    return spec


def get_operation(operation_id: str, root: Path | None = None) -> OperationSpec:
    catalog = load_operation_catalog(root)
    spec = catalog.by_id.get(operation_id)
    if spec is None:
        raise StellaError(
            "UNKNOWN_OPERATION",
            f"unknown operation id: {operation_id}",
            next_action="run 'python -m stella workflow show <id> --json' to list operations",
        )
    return spec


def request_model_for(workflow_id: str) -> type[WorkflowRequest]:
    spec = get_workflow(workflow_id)
    model = resolve_reference(spec.input_model)
    if not isinstance(model, type) or not issubclass(model, WorkflowRequest):
        raise StellaError(
            "INTERNAL",
            f"workflow {workflow_id} references an invalid request model",
        )
    return model
