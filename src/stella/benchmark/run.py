"""Benchmark run operation adapters on the unified workflow runtime.

The benchmark reuses the contribution extractor through ``lit.extraction``
but never writes into ``literature/``: paper execution happens under the
single requested run id only. The frozen method carries real provider and
model settings, budgets, rule/schema/prompt hashes, campaign identity,
and a canonical fingerprint. Resume retries only unfinished or
network-failed papers; successful attempts are immutable; finalize is
one-way and persisted.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

RESUMABLE_STATUSES = ("pending", "running", "network_failed", "interrupted")

# Documented validated default model route for benchmark freezes; requests
# may override every field through the request-carried method dictionary.
DEFAULT_PROVIDER = "bigmodel"
DEFAULT_MODEL = "glm-4.6"
DEFAULT_CONCURRENCY = 2
DEFAULT_TRANSPORT_RETRIES = 2


class _MissingRunId(Exception):
    def __init__(self, result: dict) -> None:
        super().__init__(result.get("failure", {}).get("detail", ""))
        self.result = result


def _run_dir(root: Path, payload: dict | None = None) -> Path:
    run_id = ((payload or {}).get("run_id")) or os.environ.get(
        "STELLA_WORKER_RUN_ID", ""
    )
    if not run_id:
        from stella.workflows import operation_failed

        raise _MissingRunId(operation_failed(
            "benchmark operations require the outer run id in the payload",
            kind="precondition",
            next_action="run the benchmark workflow through the runtime",
        ))
    return Path(root) / "runs" / "benchmark" / run_id


def _default_method_dict() -> dict[str, Any]:
    from stella.lit.extraction.method_config import (
        HvsContributionMethodConfig,
    )

    budget = {
        "model_context_limit": 128000,
        "reserve_system_and_rules": 16000,
        "reserve_tool_schema": 4000,
        "reserve_candidate_suffix": 2000,
        "reserve_output": 16000,
        "reserve_provider_framing": 2000,
    }
    config = HvsContributionMethodConfig.model_validate(
        {
            "roster_model": {
                "provider": DEFAULT_PROVIDER,
                "model": DEFAULT_MODEL,
            },
            "quantity_model": {
                "provider": DEFAULT_PROVIDER,
                "model": DEFAULT_MODEL,
            },
            "roster_context_budget": budget,
            "quantity_context_budget": budget,
        }
    )
    return config.model_dump(mode="json", by_alias=True)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _freeze_runtime_components() -> dict[str, str]:
    stella_root = Path(__file__).resolve().parents[1]
    files = (
        "benchmark/run.py",
        "lit/extraction/paper_runner.py",
        "lit/extraction/run_policy.py",
        "workflow_runtime.py",
    )
    return {name: _sha256_file(stella_root / name) for name in files}


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def freeze_method(
    payload: dict, *, root: Path, paper_id: str | None = None
) -> dict[str, Any]:
    """benchmark.freeze_method adapter: freeze the complete method contract.

    The frozen configuration includes provider and model settings for the
    roster and quantity stages, request policies and budgets, component
    hashes (rules, prompts, submission schemas), the campaign identity
    and its hash, concurrency and retry policy, and the canonical method
    fingerprint, semantic implementation hashes, and runtime implementation
    hashes.
    """

    from stella.lit.extraction.method_config import (
        HvsContributionMethodConfig,
    )
    from stella.lit.extraction.run import freeze_contribution_components
    from stella.workflows import operation_complete, operation_failed

    try:
        run_dir = _run_dir(Path(root), payload)
    except _MissingRunId as missing:
        return missing.result
    method_payload = (payload or {}).get("method")
    if method_payload is None:
        from stella.lit.session_injection import (
            load_session,
            session_method_config,
        )

        try:
            session = load_session()
        except (OSError, ValueError):
            session = None
        method_payload = (
            session_method_config(session) if session is not None else None
        )
    if method_payload is None:
        method_payload = _default_method_dict()
    try:
        config = HvsContributionMethodConfig.model_validate(method_payload)
    except Exception as error:  # noqa: BLE001 - request-shaped failure
        return operation_failed(
            f"invalid method configuration: {error}", kind="validation"
        )
    from stella.workflows import DEFAULT_ROOT

    # Rule/prompt/schema hashes are repository scientific contracts; the
    # execution root only receives the frozen run record.
    frozen_components = freeze_contribution_components(DEFAULT_ROOT)
    frozen = config.model_copy(
        update={
            "components": type(config.components)(
                **{
                    **config.components.model_dump(),
                    **frozen_components,
                }
            )
        }
    )
    fingerprint = frozen.method_fingerprint()
    campaign_path = run_dir / "campaign.json"
    document = {
        "method": frozen.model_dump(mode="json", by_alias=True),
        "method_fingerprint": fingerprint,
        "profile": (payload or {}).get("profile") or "dev10",
        "campaign": {
            "path": str(campaign_path),
            "sha256": (
                hashlib.sha256(campaign_path.read_bytes()).hexdigest()
                if campaign_path.is_file()
                else None
            ),
        },
        "concurrency": int(
            (payload or {}).get("concurrency")
            or os.environ.get("STELLA_RUN_CONCURRENCY")
            or DEFAULT_CONCURRENCY
        ),
        "retry_policy": {
            "default_transport_retries": DEFAULT_TRANSPORT_RETRIES,
            "roster_ladder": frozen.roster_request_policy.model_dump(),
            "quantity_ladder": frozen.quantity_request_policy.model_dump(),
        },
        "runtime_implementation_sha256": _freeze_runtime_components(),
    }
    document["run_fingerprint"] = _canonical_sha256(document)
    run_dir.mkdir(parents=True, exist_ok=True)
    method_path = run_dir / "method_config.json"
    method_path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return operation_complete(
        artifacts=[str(method_path)], method_fingerprint=fingerprint
    )


def validate_method_freeze(payload: dict, result: dict, *, root: Path) -> list[str]:
    """A completed freeze must leave a fingerprinted method config on disk."""

    if result.get("status") != "complete":
        return []
    try:
        run_dir = _run_dir(Path(root), payload)
    except _MissingRunId:
        return ["freeze result does not identify its run"]
    method_path = run_dir / "method_config.json"
    if not method_path.is_file():
        return [f"method freeze reported complete but {method_path} is missing"]
    try:
        frozen = json.loads(method_path.read_text(encoding="utf-8"))
    except ValueError as error:
        return [f"frozen method config is not parseable: {error}"]
    if not frozen.get("method_fingerprint"):
        return ["frozen method config carries no fingerprint"]
    method_text = json.dumps(frozen.get("method") or {})
    if "model" not in method_text:
        return ["frozen method config carries no model settings"]
    if "components" not in method_text:
        return ["frozen method config carries no component hashes"]
    reported = (result.get("detail") or {}).get("method_fingerprint")
    if reported and reported != frozen.get("method_fingerprint"):
        return ["freeze result fingerprint disagrees with the frozen config"]
    return []


def execute(payload: dict, *, root: Path, paper_id: str | None = None) -> dict:
    """benchmark.execute adapter: run the extractor under the run id.

    Paper execution reuses the maintained contribution chain with the
    frozen method and the declared transport (session replay in tests,
    provider gateway in production). All artifacts stay under
    ``runs/benchmark/<run_id>/`` and the contribution workspace; nothing
    is written into the canonical ``literature/`` tree.
    """

    from stella.lit.extraction.method_config import (
        HvsContributionMethodConfig,
    )
    from stella.lit.extraction.paper_runner import run_contribution_paper
    from stella.lit.extraction.run_policy import (
        reserve_benchmark_contribution_run_dir,
    )
    from stella.lit.extraction.runner import ObservingTransport
    from stella.lit.extraction.transport import build_transport
    from stella.lit.session_injection import (
        load_session,
        session_model_responses,
    )
    from stella.workflows import operation_failed

    authorities = (payload or {}).get("authorities") or {}
    missing = [
        kind for kind in ("llm", "network") if not authorities.get(kind)
    ]
    if missing:
        return operation_failed(
            "benchmark execution calls provider models through gateways",
            kind="authority",
            blockers=missing,
        )
    if paper_id is None:
        return operation_failed(
            "execute is a per-paper operation", kind="precondition"
        )
    try:
        run_dir = _run_dir(Path(root), payload)
    except _MissingRunId as missing_id:
        return missing_id.result
    method_path = run_dir / "method_config.json"
    if not method_path.is_file():
        return operation_failed(
            "the frozen method is required before execution",
            kind="precondition",
            next_action="run the freeze phase before the run phase",
        )
    try:
        frozen = json.loads(method_path.read_text(encoding="utf-8"))
        config = HvsContributionMethodConfig.model_validate(
            frozen["method"]
        )
    except Exception as error:  # noqa: BLE001
        return operation_failed(
            f"invalid frozen method: {error}", kind="validation"
        )
    from stella.lit.extraction.run import freeze_contribution_components
    from stella.workflows import DEFAULT_ROOT

    current_components = freeze_contribution_components(DEFAULT_ROOT)
    if config.components.model_dump() != current_components:
        return operation_failed(
            "the contribution method implementation no longer matches the frozen run",
            kind="precondition",
            next_action="start a new immutable benchmark run for the changed method",
        )
    if (
        frozen.get("runtime_implementation_sha256")
        != _freeze_runtime_components()
    ):
        return operation_failed(
            "the benchmark runtime implementation no longer matches the frozen run",
            kind="precondition",
            next_action="start a new immutable benchmark run for the changed runtime",
        )
    try:
        session = load_session()
    except (OSError, ValueError) as error:
        return operation_failed(
            f"invalid test session: {error}", kind="validation"
        )
    responses = (
        session_model_responses(session, paper_id)
        if session is not None
        else None
    )
    transcript_path = os.environ.get("STELLA_WORKER_TRANSCRIPT", "")
    try:
        transport = ObservingTransport(
            build_transport(
                config,
                session_model_responses=responses,
                transcript_path=transcript_path or None,
            )
        )
    except Exception as error:  # noqa: BLE001
        return operation_failed(
            f"transport construction failed: {error}", kind="precondition"
        )
    # Contribution run ids are never reusable: each execution attempt
    # derives its own id from the benchmark run, paper, and attempt count.
    attempt_count = int((payload or {}).get("_benchmark_execution_attempt") or 1)
    contribution_run_id = (
        f"benchmark-{(payload or {}).get('run_id')}-{paper_id}"
        f"-{attempt_count}".replace("/", "-")
    )
    try:
        contribution_dir = reserve_benchmark_contribution_run_dir(
            Path(root), str((payload or {}).get("run_id")), contribution_run_id
        )
        result = run_contribution_paper(
            Path(root),
            contribution_run_id,
            paper_id,
            config=config,
            transport=transport,
            sleep=lambda _: None,
            run_dir=contribution_dir,
        )
    except Exception as error:  # noqa: BLE001
        return operation_failed(
            f"benchmark paper execution failed: {type(error).__name__}: {error}",
            kind="internal",
        )
    if result["status"] not in ("complete", "partial"):
        if transport.network_failures:
            return operation_failed(
                "provider transport failed: "
                + "; ".join(transport.network_failures[:3]),
                kind="network",
                paper_id=paper_id,
                next_action="resume the run after the provider recovers",
            )
        return operation_failed(
            f"paper execution failed without producing a validated result "
            f"({result['status']})",
            kind="internal",
            paper_id=paper_id,
        )
    from stella.workflows import operation_complete

    paper_record = run_dir / "papers" / paper_id / "paper_result.json"
    paper_record.parent.mkdir(parents=True, exist_ok=True)
    paper_record.write_text(
        json.dumps(result, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    completed = operation_complete(
        artifacts=[str(paper_record)],
        extraction_status=result["status"],
        contribution_run_id=contribution_run_id,
    )
    completed["status"] = result["status"]
    return completed


def validate_run_output(payload: dict, result: dict, *, root: Path) -> list[str]:
    """A completed paper execution must record its result in the run."""

    if result.get("status") not in ("complete", "partial"):
        return []
    paper_id = result.get("paper_id")
    if not paper_id:
        return ["execution result does not identify its paper"]
    try:
        run_dir = _run_dir(Path(root), payload)
    except _MissingRunId:
        return ["execution result does not identify its run"]
    record = run_dir / "papers" / paper_id / "paper_result.json"
    if not record.is_file():
        return [
            f"execution reported success but {record} is missing"
        ]
    return []


def resume(payload: dict, *, root: Path, paper_id: str | None = None) -> dict:
    """benchmark.resume adapter: only unfinished or network-failed papers."""

    from stella.workflows import operation_complete, operation_failed

    try:
        run_dir = _run_dir(Path(root), payload)
    except _MissingRunId as missing_id:
        return missing_id.result
    if (run_dir / "finalized.json").is_file():
        return operation_failed(
            "the run is finalized and immutable; nothing to resume",
            kind="precondition",
        )
    if paper_id is None:
        return operation_failed(
            "resume is a per-paper operation", kind="precondition"
        )
    status_path = run_dir / "papers" / paper_id / "status.json"
    status = "pending"
    if status_path.is_file():
        status = json.loads(status_path.read_text(encoding="utf-8")).get(
            "status", "pending"
        )
    if status not in RESUMABLE_STATUSES:
        return operation_failed(
            f"paper {paper_id} has terminal status {status!r}",
            kind="precondition",
        )
    result = execute(payload, root=Path(root), paper_id=paper_id)
    result.setdefault("detail", {})["resumed"] = True
    return result


def validate_resume_eligibility(
    payload: dict, result: dict, *, root: Path
) -> list[str]:
    """A completed resume decision must list only resumable papers."""

    if result.get("status") != "complete":
        return []
    try:
        run_dir = _run_dir(Path(root), payload)
    except _MissingRunId:
        return ["resume result does not identify its run"]
    paper_id = result.get("paper_id")
    if not paper_id:
        return ["resume result does not identify its paper"]
    status_path = run_dir / "papers" / str(paper_id) / "status.json"
    prior_status = "pending"
    if status_path.is_file():
        try:
            prior_status = json.loads(
                status_path.read_text(encoding="utf-8")
            ).get("status", "pending")
        except ValueError as error:
            return [f"resume paper status is not parseable: {error}"]
    if prior_status not in RESUMABLE_STATUSES:
        return [
            f"resume executed for {paper_id} with non-resumable status {prior_status!r}"
        ]
    detail = result.get("detail") or {}
    if detail.get("resumed") is not True:
        return ["resume result does not declare a real retry"]
    record = run_dir / "papers" / str(paper_id) / "paper_result.json"
    if not record.is_file():
        return [f"resume reported success but {record} is missing"]
    return []


def finalize(payload: dict, *, root: Path, paper_id: str | None = None) -> dict:
    """benchmark.finalize adapter: one-way finalize to complete/partial."""

    from stella.workflows import operation_complete, operation_failed

    try:
        run_dir = _run_dir(Path(root), payload)
    except _MissingRunId as missing_id:
        return missing_id.result
    marker = run_dir / "finalized.json"
    if marker.is_file():
        return operation_failed(
            "the run is already finalized and immutable; no further attempts",
            kind="precondition",
        )
    requested = (payload or {}).get("papers") or []
    states: dict[str, str] = {
        path.parent.name: json.loads(path.read_text(encoding="utf-8")).get(
            "status"
        )
        for path in (run_dir / "papers").glob("*/status.json")
    }
    ordered_pairs = (
        [(paper, states.get(paper)) for paper in requested]
        if requested
        else list(states.items())
    )
    ordered = [state for _, state in ordered_pairs]
    if not ordered:
        return operation_failed(
            "an empty execution set cannot be finalized as complete",
            kind="precondition",
        )
    resumable = [
        paper
        for paper, state in ordered_pairs
        if state in RESUMABLE_STATUSES
    ]
    if resumable and not (payload or {}).get(
        "finalize_partial_explicitly_authorized", False
    ):
        return operation_failed(
            "resumable papers remain; finalization would abandon retries: "
            + ", ".join(resumable),
            kind="precondition",
            next_action=(
                "resume interrupted/network-failed papers, or explicitly authorize "
                "partial finalization"
            ),
        )
    if all(state == "complete" for state in ordered):
        final_status = "complete"
    else:
        final_status = "partial"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps({"final_status": final_status}, indent=2) + "\n",
        encoding="utf-8",
    )
    return operation_complete(
        artifacts=[str(marker)],
        final_status=final_status,
        note="finalize is one-way; successful papers cannot be re-attempted",
    )


def validate_finalize(payload: dict, result: dict, *, root: Path) -> list[str]:
    """A completed finalize must leave its one-way marker on disk."""

    if result.get("status") != "complete":
        return []
    try:
        run_dir = _run_dir(Path(root), payload)
    except _MissingRunId:
        return ["finalize result does not identify its run"]
    marker = run_dir / "finalized.json"
    if not marker.is_file():
        return [f"finalize reported complete but {marker} is missing"]
    final_status = (result.get("detail") or {}).get("final_status")
    if final_status not in ("complete", "partial"):
        return [f"finalize reported an invalid terminal status: {final_status!r}"]
    return []
