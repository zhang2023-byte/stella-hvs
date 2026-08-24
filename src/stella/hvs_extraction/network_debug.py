"""Network debug runs: single containers for manual node-level recovery.

A network debug run is not a formal benchmark run. It is initialized from
one terminal formal run of the active campaign, imports every successful
artifact byte-identically, and then allows manual, node-granular retries of
terminal network failures — roster deaths, failed candidate field
extractions, and transport-failed peer-consistency reviews — until every
paper is transport-clean. Retries keep prior attempts/usages/repair
history (append-only semantics), the command log is append-only, and the
source formal archive is never touched. Finalization assembles per-paper
paper_result/core artifacts plus a lineage-bound result certificate that
the network diagnostic and formal scoring can evaluate.

Only network-category terminal failures are retryable. Scientific
failures (invalid requests, validation refusals, oversized contexts) are
imported as-is and marked non-retryable.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stella.benchmark.campaign import sha256_file
from stella.benchmark.network_gate import _scan_paper_results
from stella.benchmark.pricing import (
    estimate_api_cost_for_routes,
    load_pricing_snapshot,
)
from stella.benchmark.run_contract import canonical_sha256
from stella.lit.extraction.bounded_call import Transport
from stella.hvs_extraction.field_stage import (
    FIELDS_COMPLETE,
    PEER_CONSISTENCY_REVIEW,
    run_field_stage,
)
from stella.hvs_extraction.finalize import assemble_paper_result
from stella.hvs_extraction.method_config import HvsExtractionMethodConfig
from stella.hvs_extraction.paper_runner import _write_core_delivery, run_paper
from stella.lit.extraction.prepare import (
    RUNS_RELATIVE_DIR,
    build_prepared_input,
)
from stella.hvs_extraction.roster_stage import ROSTER_COMPLETE, _atomic_write_json
from stella.hvs_extraction.run import (
    USAGE_NUMERIC_FIELDS,
    _aggregate_usage,
    _component_hashes,
    _format_validation,
    validate_hvs_extraction_run_id,
)
from stella.schema_registry import require_schema, schema_ref

DEBUG_ROOT = RUNS_RELATIVE_DIR.parent / "debug"
DEBUG_STATES = {"initialized", "recovering", "clean"}
SOURCE_SCOPES = {"full_dev", "full_test"}
PREPARED_STABLE_KEYS = ("manuscript", "ecsv", "bibliography", "context")
FINALIZE_SKIP_FILES = {"paper_result.json", "literature_hvs_candidates.json"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def debug_run_root(workspace: Path) -> Path:
    return workspace / DEBUG_ROOT


def debug_run_dir(workspace: Path, debug_run_id: str) -> Path:
    validate_hvs_extraction_run_id(debug_run_id)
    return debug_run_root(workspace) / debug_run_id


def source_run_dir(workspace: Path, source_run_id: str) -> Path:
    validate_hvs_extraction_run_id(source_run_id)
    return workspace / RUNS_RELATIVE_DIR / source_run_id


# ---------------------------------------------------------------------------
# Node classification
# ---------------------------------------------------------------------------


def _is_network_transport_failure(failure: dict[str, Any] | None) -> bool:
    if not isinstance(failure, dict):
        return False
    transport = failure.get("transport_error")
    return failure.get("code") == "transport_failure" and (
        isinstance(transport, dict) and transport.get("category") == "network"
    )


def _roster_network_death(roster: dict[str, Any]) -> bool:
    failure = roster.get("failure")
    if not isinstance(failure, dict):
        return False
    for proposal_failure in failure.get("proposal_failures") or []:
        inner = (
            proposal_failure.get("failure")
            if isinstance(proposal_failure, dict)
            else None
        )
        if not isinstance(inner, dict):
            continue
        transport = inner.get("transport_error")
        if inner.get("status") == "transport_failure" and (
            isinstance(transport, dict) and transport.get("category") == "network"
        ):
            return True
    return False


def _review_transport_death(artifact: dict[str, Any]) -> bool:
    # Only the latest peer-consistency review pass describes the current
    # node: a transport failure that a later successful retry recovered
    # must not keep the node retryable forever.
    latest: dict[str, Any] | None = None
    for repair in artifact.get("repair_history") or []:
        if isinstance(repair, dict) and repair.get("type") == PEER_CONSISTENCY_REVIEW:
            latest = repair
    return (
        latest is not None
        and str(latest.get("final_status")) == "transport_failure"
    )


def derive_paper_state(paper_dir: Path, arxiv_id: str) -> dict[str, Any]:
    """Derive transport node states from the current stage artifacts."""

    state: dict[str, Any] = {
        "arxiv_id": arxiv_id,
        "roster": "missing",
        "candidates": {},
        "retry_nodes": [],
        "transport_clean": False,
    }
    roster_path = paper_dir / "roster_final.json"
    if not roster_path.is_file():
        return state
    roster = json.loads(roster_path.read_text(encoding="utf-8"))
    if roster.get("status") != ROSTER_COMPLETE:
        state["roster"] = (
            "network_failed" if _roster_network_death(roster) else "non_retryable"
        )
        if state["roster"] == "network_failed":
            state["retry_nodes"].append("roster")
        state["transport_clean"] = not state["retry_nodes"]
        return state
    state["roster"] = "clean"
    for candidate in roster.get("candidates") or []:
        record_id = candidate["record_id"]
        artifact_path = paper_dir / "candidates" / f"{record_id}.json"
        if not artifact_path.is_file():
            state["candidates"][record_id] = {"state": "missing", "review": "clean"}
            state["retry_nodes"].append(f"candidate:{record_id}")
            continue
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        if artifact.get("status") == FIELDS_COMPLETE:
            review = "network_failed" if _review_transport_death(artifact) else "clean"
            state["candidates"][record_id] = {"state": "clean", "review": review}
            if review == "network_failed":
                state["retry_nodes"].append(f"peer-review:{record_id}")
            continue
        retryable = _is_network_transport_failure(artifact.get("failure"))
        state["candidates"][record_id] = {
            "state": "network_failed" if retryable else "non_retryable",
            "review": "clean",
        }
        if retryable:
            state["retry_nodes"].append(f"candidate:{record_id}")
    state["transport_clean"] = not state["retry_nodes"]
    return state


def derive_debug_state(workspace: Path, debug_run_id: str) -> dict[str, Any]:
    config = load_debug_config(workspace, debug_run_id)
    run_dir = debug_run_dir(workspace, debug_run_id)
    papers = [
        derive_paper_state(run_dir / "papers" / arxiv_id, arxiv_id)
        for arxiv_id in config["papers"]
    ]
    return {
        "schema": schema_ref("benchmark.network_debug_state"),
        "generated_at": _utc_now(),
        "debug_run_id": debug_run_id,
        "state": config["state"],
        "papers": papers,
        "retry_node_count": sum(len(paper["retry_nodes"]) for paper in papers),
        "transport_clean": all(paper["transport_clean"] for paper in papers),
    }


# ---------------------------------------------------------------------------
# Config / event / state IO
# ---------------------------------------------------------------------------


def _with_content_hash(artifact: dict[str, Any]) -> dict[str, Any]:
    stable = {
        key: value for key, value in artifact.items() if key != "content_sha256"
    }
    artifact["content_sha256"] = canonical_sha256(stable)
    return artifact


def load_debug_config(workspace: Path, debug_run_id: str) -> dict[str, Any]:
    path = debug_run_dir(workspace, debug_run_id) / "debug_config.json"
    artifact = json.loads(path.read_text(encoding="utf-8"))
    require_schema(artifact, "benchmark.network_debug_config", require_current=True)
    if artifact.get("state") not in DEBUG_STATES:
        raise ValueError("network debug config has an unknown state")
    return artifact


def _write_debug_config(
    workspace: Path, debug_run_id: str, config: dict[str, Any]
) -> None:
    _atomic_write_json(
        debug_run_dir(workspace, debug_run_id) / "debug_config.json",
        _with_content_hash(config),
    )


def _write_state(workspace: Path, debug_run_id: str) -> dict[str, Any]:
    state = derive_debug_state(workspace, debug_run_id)
    _atomic_write_json(
        debug_run_dir(workspace, debug_run_id) / "debug_state.json", state
    )
    return state


def append_debug_event(
    workspace: Path, debug_run_id: str, event: dict[str, Any]
) -> None:
    event = {
        "schema": schema_ref("benchmark.network_debug_event"),
        "ts": _utc_now(),
        "debug_run_id": debug_run_id,
        **event,
    }
    path = debug_run_dir(workspace, debug_run_id) / "debug_events.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def read_debug_events(workspace: Path, debug_run_id: str) -> list[dict[str, Any]]:
    path = debug_run_dir(workspace, debug_run_id) / "debug_events.jsonl"
    if not path.is_file():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------


def _prepared_fingerprint(artifact: dict[str, Any]) -> str:
    return canonical_sha256({key: artifact.get(key) for key in PREPARED_STABLE_KEYS})


def _verify_workspace_stability(
    workspace: Path,
    method: HvsExtractionMethodConfig,
    run_dir: Path,
    papers: list[str],
) -> None:
    """Fail when the workspace no longer matches the imported preparation."""

    for arxiv_id in papers:
        imported = json.loads(
            (run_dir / "prepared_inputs" / f"{arxiv_id}.json").read_text(
                encoding="utf-8"
            )
        )
        rebuilt = build_prepared_input(
            workspace,
            arxiv_id,
            roster_budget=method.roster_context_budget,
            field_budget=method.field_context_budget,
        )
        if _prepared_fingerprint(rebuilt) != _prepared_fingerprint(imported):
            raise ValueError(
                f"workspace drifted from the imported preparation: {arxiv_id}"
            )


def load_method_config(workspace: Path, debug_run_id: str) -> HvsExtractionMethodConfig:
    """Rebuild the frozen method from the source run config the debug binds."""

    config = load_debug_config(workspace, debug_run_id)
    source = source_run_dir(workspace, config["source_run"]["run_id"])
    run_config = json.loads(
        (source / "run_config.json").read_text(encoding="utf-8")
    )
    method = HvsExtractionMethodConfig.model_validate(run_config["method"])
    if method.method_fingerprint() != config["method_fingerprint"]:
        raise ValueError(
            "source run method no longer matches the debug method fingerprint"
        )
    method.assert_frozen()
    return method


def _guard_retry_environment(
    workspace: Path,
    debug_run_id: str,
    config: dict[str, Any],
    method: HvsExtractionMethodConfig,
    *,
    api_key: str,
    base_url: str,
) -> Path:
    if not api_key or not base_url:
        raise ValueError("network debug retries require gateway credentials")
    run_dir = debug_run_dir(workspace, debug_run_id)
    _verify_workspace_stability(workspace, method, run_dir, config["papers"])
    return run_dir


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------


def init_network_debug_run(
    workspace: Path,
    *,
    source_run_id: str,
    debug_run_id: str,
    pricing_snapshot_id: str | None = None,
) -> dict[str, Any]:
    """Create one debug container imported from a terminal formal run."""

    validate_hvs_extraction_run_id(debug_run_id)
    source_dir = source_run_dir(workspace, source_run_id)

    run_config = json.loads(
        (source_dir / "run_config.json").read_text(encoding="utf-8")
    )
    require_schema(run_config, "benchmark.run_config", require_current=True)
    summary = json.loads(
        (source_dir / "run_summary.json").read_text(encoding="utf-8")
    )
    require_schema(summary, "benchmark.run_summary", require_current=True)
    if summary.get("state") not in {"completed", "interrupted"}:
        raise ValueError(
            "network debug requires a terminal source run "
            "(completed or interrupted)"
        )
    if run_config["scope"] not in SOURCE_SCOPES:
        raise ValueError("network debug source run must be full_dev or full_test")
    if run_config["campaign"]["campaign_id"] != "hvs-extraction-v6":
        raise ValueError("network debug requires the active campaign")

    method = HvsExtractionMethodConfig.model_validate(run_config["method"])
    method.assert_frozen()
    if method.method_fingerprint() != run_config["method_fingerprint"]:
        raise ValueError("source run method fingerprint is inconsistent")

    run_cost_path = source_dir / "run_cost.json"
    if not run_cost_path.is_file():
        raise ValueError("network debug requires a source run cost artifact")
    run_cost = json.loads(run_cost_path.read_text(encoding="utf-8"))
    snapshot = run_cost["estimated_api_cost"]["pricing_snapshot"]
    snapshot_id = snapshot["snapshot_id"]
    if pricing_snapshot_id is not None and pricing_snapshot_id != snapshot_id:
        raise ValueError(
            "pricing snapshot must match the source run snapshot: " + snapshot_id
        )
    snapshot_path = (
        workspace
        / "benchmark"
        / "pricing"
        / "tokendance"
        / f"{snapshot_id}.json"
    )
    load_pricing_snapshot(snapshot_path)

    papers = list(run_config["papers"])
    _verify_source_inputs(workspace, method, source_dir, papers)

    current_hashes = _component_hashes(workspace, method)
    debug_dir = _reserve_debug_directory(workspace, debug_run_id)
    imported = _import_source_artifacts(source_dir, debug_dir, papers)

    config = _with_content_hash(
        {
            "schema": schema_ref("benchmark.network_debug_config"),
            "created_at": _utc_now(),
            "debug_run_id": debug_run_id,
            "campaign": dict(run_config["campaign"]),
            "source_run": {
                "run_id": source_run_id,
                "scope": run_config["scope"],
                "state": summary["state"],
                "run_config_sha256": sha256_file(
                    source_dir / "run_config.json"
                ),
                "run_summary_sha256": sha256_file(
                    source_dir / "run_summary.json"
                ),
                "run_manifest_sha256": (
                    sha256_file(source_dir / "run_manifest.json")
                    if (source_dir / "run_manifest.json").is_file()
                    else None
                ),
            },
            "papers": papers,
            "method_fingerprint": run_config["method_fingerprint"],
            "models": dict(run_config["models"]),
            "pricing_snapshot": {
                "snapshot_id": snapshot_id,
                "sha256": snapshot["sha256"],
            },
            "component_hashes": {
                "source": dict(run_config["component_hashes"]),
                "current": current_hashes,
            },
            "state": "initialized",
        }
    )
    _atomic_write_json(debug_dir / "debug_config.json", config)
    state = _write_state(workspace, debug_run_id)
    append_debug_event(
        workspace,
        debug_run_id,
        {
            "command": "init",
            "params": {"source_run_id": source_run_id},
            "outcome": "imported",
            "papers": papers,
            "imported_files": imported,
            "initial_retry_nodes": {
                paper["arxiv_id"]: paper["retry_nodes"]
                for paper in state["papers"]
                if paper["retry_nodes"]
            },
        },
    )
    return state


def _verify_source_inputs(
    workspace: Path,
    method: HvsExtractionMethodConfig,
    source_dir: Path,
    papers: list[str],
) -> None:
    for arxiv_id in papers:
        path = source_dir / "prepared_inputs" / f"{arxiv_id}.json"
        if not path.is_file():
            raise ValueError(f"source run is missing a prepared input: {arxiv_id}")
        imported = json.loads(path.read_text(encoding="utf-8"))
        rebuilt = build_prepared_input(
            workspace,
            arxiv_id,
            roster_budget=method.roster_context_budget,
            field_budget=method.field_context_budget,
        )
        if _prepared_fingerprint(rebuilt) != _prepared_fingerprint(imported):
            raise ValueError(
                f"workspace drifted from the source preparation: {arxiv_id}"
            )


def _reserve_debug_directory(workspace: Path, debug_run_id: str) -> Path:
    root = debug_run_root(workspace)
    lock_dir = root.parent / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    debug_dir = root / debug_run_id
    if debug_dir.exists():
        raise FileExistsError(f"network debug run already exists: {debug_run_id}")
    lock_path = lock_dir / f"{debug_run_id}.lock"
    try:
        descriptor = os.open(
            lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
        )
    except FileExistsError as exc:
        raise FileExistsError(
            f"network debug run lock already exists: {debug_run_id}"
        ) from exc
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(_utc_now() + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    try:
        debug_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise FileExistsError(
            f"network debug run already exists: {debug_run_id}"
        ) from exc
    return debug_dir


def _import_source_artifacts(
    source_dir: Path, debug_dir: Path, papers: list[str]
) -> int:
    imported = 0
    (debug_dir / "prepared_inputs").mkdir(parents=True, exist_ok=True)
    for arxiv_id in papers:
        shutil.copy2(
            source_dir / "prepared_inputs" / f"{arxiv_id}.json",
            debug_dir / "prepared_inputs" / f"{arxiv_id}.json",
        )
        imported += 1
        source_paper = source_dir / "papers" / arxiv_id
        if source_paper.is_dir():
            shutil.copytree(source_paper, debug_dir / "papers" / arxiv_id)
            imported += sum(
                1
                for path in (debug_dir / "papers" / arxiv_id).rglob("*")
                if path.is_file()
            )
    return imported


# ---------------------------------------------------------------------------
# Retry
# ---------------------------------------------------------------------------


def _parse_node(node: str) -> tuple[str, str]:
    try:
        arxiv_id, kind = node.split(":", 1)
    except ValueError as exc:
        raise ValueError(
            f"node id must be <arxiv_id>:<roster|candidate-NNN|peer-review>: {node}"
        ) from exc
    if kind not in {"roster", "peer-review"} and not kind.startswith("candidate-"):
        raise ValueError(f"unknown node kind in {node!r}")
    return arxiv_id, kind


def _snapshot_artifacts(paper_dir: Path) -> dict[str, dict[str, Any]]:
    snapshot: dict[str, dict[str, Any]] = {}
    if not paper_dir.is_dir():
        return snapshot
    for path in sorted(paper_dir.rglob("*.json")):
        snapshot[str(path.relative_to(paper_dir))] = json.loads(
            path.read_text(encoding="utf-8")
        )
    return snapshot


def _restore_merged_history(
    paper_dir: Path, snapshot: dict[str, dict[str, Any]]
) -> None:
    """Prepend pre-retry history into artifacts the retry rewrote.

    Untouched artifacts are byte-identical to the snapshot and stay as-is;
    regenerated paper-level files are excluded from history merging.
    """

    for relative, prior in snapshot.items():
        if Path(relative).name in FINALIZE_SKIP_FILES:
            continue
        path = paper_dir / relative
        if not path.is_file():
            continue
        current = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(current, dict) or current == prior:
            continue
        changed = False
        for key in ("attempts", "usages", "repair_history"):
            prior_list = prior.get(key) or []
            if prior_list:
                current[key] = [*prior_list, *(current.get(key) or [])]
                changed = True
        if changed:
            _atomic_write_json(path, current)


def retry_network_nodes(
    workspace: Path,
    debug_run_id: str,
    *,
    transport: Transport,
    api_key: str = "",
    base_url: str = "",
    papers: list[str] | None = None,
    nodes: list[str] | None = None,
    sleep=time.sleep,
    candidate_workers: int = 4,
) -> dict[str, Any]:
    """Manually retry the selected (or all) network-terminal nodes."""

    config = load_debug_config(workspace, debug_run_id)
    if config["state"] not in {"initialized", "recovering"}:
        raise ValueError("network debug run is already finalized")
    if (
        debug_run_dir(workspace, debug_run_id) / "debug_result.json"
    ).is_file():
        raise ValueError("network debug run is already finalized")
    method = load_method_config(workspace, debug_run_id)
    run_dir = _guard_retry_environment(
        workspace, debug_run_id, config, method, api_key=api_key, base_url=base_url
    )

    state = derive_debug_state(workspace, debug_run_id)
    by_paper = _select_retry_targets(config, state, papers=papers, nodes=nodes)

    try:
        for arxiv_id, kinds in by_paper.items():
            _retry_one_paper(
                workspace,
                debug_run_id,
                run_dir,
                arxiv_id,
                kinds,
                method=method,
                transport=transport,
                api_key=api_key,
                base_url=base_url,
                sleep=sleep,
                candidate_workers=candidate_workers,
            )
    except KeyboardInterrupt:
        config["state"] = "recovering"
        _write_debug_config(workspace, debug_run_id, config)
        append_debug_event(
            workspace,
            debug_run_id,
            {
                "command": "retry",
                "params": {"papers": list(by_paper)},
                "outcome": "interrupted",
            },
        )
        raise

    new_state = _write_state(workspace, debug_run_id)
    if config["state"] != "recovering":
        config["state"] = "recovering"
        _write_debug_config(workspace, debug_run_id, config)
    before = {paper["arxiv_id"]: paper["retry_nodes"] for paper in state["papers"]}
    after = {
        paper["arxiv_id"]: paper["retry_nodes"] for paper in new_state["papers"]
    }
    append_debug_event(
        workspace,
        debug_run_id,
        {
            "command": "retry",
            "params": {"papers": list(by_paper), "nodes": nodes or []},
            "outcome": "completed",
            "nodes_before": before,
            "nodes_after": after,
        },
    )
    return {
        "debug_run_id": debug_run_id,
        "retried_papers": list(by_paper),
        "nodes_after": after,
        "transport_clean": new_state["transport_clean"],
    }


def _select_retry_targets(
    config: dict[str, Any],
    state: dict[str, Any],
    *,
    papers: list[str] | None,
    nodes: list[str] | None,
) -> dict[str, set[str]]:
    known = set(config["papers"])
    retryable = {
        paper["arxiv_id"]: set(paper["retry_nodes"]) for paper in state["papers"]
    }
    if nodes is not None:
        targets: dict[str, set[str]] = {}
        for node in nodes:
            arxiv_id, kind = _parse_node(node)
            if arxiv_id not in known:
                raise ValueError(f"node references unknown paper: {node}")
            normalized = (
                kind if kind in {"roster", "peer-review"} else f"candidate:{kind}"
            )
            if normalized not in retryable.get(arxiv_id, set()):
                raise ValueError(
                    f"node is not currently network-retryable: {node} "
                    f"(available: {sorted(retryable.get(arxiv_id, set()))})"
                )
            targets.setdefault(arxiv_id, set()).add(normalized)
        return targets
    selected = set(papers) if papers is not None else known
    unknown = sorted(selected - known)
    if unknown:
        raise ValueError(f"unknown papers for this debug run: {unknown}")
    return {
        arxiv_id: kinds
        for arxiv_id, kinds in retryable.items()
        if arxiv_id in selected and kinds
    }


def rerun_roster_paper(
    workspace: Path,
    debug_run_id: str,
    *,
    arxiv_id: str,
    transport: Transport,
    api_key: str = "",
    base_url: str = "",
    sleep=time.sleep,
    candidate_workers: int = 4,
) -> dict[str, Any]:
    """Re-run one paper whose roster failed for a repaired non-network defect.

    Normal network retries stay unavailable to scientific failures by
    contract. This separate, explicit channel exists for the operator-repaired
    case (for example a false ``context_mutation`` caused by an ingestion
    defect): the paper's roster must currently be in a failed non-network
    state, the whole chain is re-run against the repaired code, and the
    command log keeps the prior failure for audit.
    """

    config = load_debug_config(workspace, debug_run_id)
    if config["state"] not in {"initialized", "recovering"}:
        raise ValueError("network debug run is already finalized")
    if (debug_run_dir(workspace, debug_run_id) / "debug_result.json").is_file():
        raise ValueError("network debug run is already finalized")
    if arxiv_id not in config["papers"]:
        raise ValueError(f"unknown paper for this debug run: {arxiv_id}")
    state = derive_debug_state(workspace, debug_run_id)
    paper_state = next(
        paper for paper in state["papers"] if paper["arxiv_id"] == arxiv_id
    )
    if paper_state["roster"] != "non_retryable":
        raise ValueError(
            "rerun_roster requires a failed non-network roster state; "
            f"{arxiv_id} roster is {paper_state['roster']}"
        )
    method = load_method_config(workspace, debug_run_id)
    run_dir = _guard_retry_environment(
        workspace,
        debug_run_id,
        config,
        method,
        api_key=api_key,
        base_url=base_url,
    )
    prior_failure = json.loads(
        (run_dir / "papers" / arxiv_id / "roster_final.json").read_text(
            encoding="utf-8"
        )
    ).get("failure")

    _retry_one_paper(
        workspace,
        debug_run_id,
        run_dir,
        arxiv_id,
        {"roster"},
        method=method,
        transport=transport,
        api_key=api_key,
        base_url=base_url,
        sleep=sleep,
        candidate_workers=candidate_workers,
    )

    new_state = _write_state(workspace, debug_run_id)
    if config["state"] != "recovering":
        config["state"] = "recovering"
        _write_debug_config(workspace, debug_run_id, config)
    append_debug_event(
        workspace,
        debug_run_id,
        {
            "command": "rerun_roster",
            "params": {"papers": [arxiv_id], "prior_failure": prior_failure},
            "outcome": "completed",
            "paper_state_after": next(
                paper
                for paper in new_state["papers"]
                if paper["arxiv_id"] == arxiv_id
            ),
        },
    )
    return {
        "debug_run_id": debug_run_id,
        "rerun_papers": [arxiv_id],
        "prior_failure": prior_failure,
        "nodes_after": {
            paper["arxiv_id"]: paper["retry_nodes"]
            for paper in new_state["papers"]
        },
        "transport_clean": new_state["transport_clean"],
    }


def _retry_one_paper(
    workspace: Path,
    debug_run_id: str,
    run_dir: Path,
    arxiv_id: str,
    kinds: set[str],
    *,
    method: HvsExtractionMethodConfig,
    transport: Transport,
    api_key: str,
    base_url: str,
    sleep,
    candidate_workers: int,
) -> None:
    paper_dir = run_dir / "papers" / arxiv_id
    paper_dir.mkdir(parents=True, exist_ok=True)
    snapshot = _snapshot_artifacts(paper_dir)
    if "roster" in kinds or not (paper_dir / "roster_final.json").is_file():
        # Roster death (or a never-started paper): rerun the whole chain.
        run_paper(
            workspace,
            debug_run_id,
            arxiv_id,
            config=method,
            transport=transport,
            api_key=api_key,
            base_url=base_url,
            sleep=sleep,
            candidate_workers=candidate_workers,
            run_dir=run_dir,
        )
    else:
        retry_only = {
            kind.split(":", 1)[1]
            for kind in kinds
            if kind.startswith("candidate:")
        }
        run_field_stage(
            workspace,
            debug_run_id,
            arxiv_id,
            config=method,
            transport=transport,
            api_key=api_key,
            base_url=base_url,
            sleep=sleep,
            max_workers=candidate_workers,
            run_dir=run_dir,
            retry_only=retry_only,
        )
        assemble_paper_result(workspace, debug_run_id, arxiv_id, run_dir=run_dir)
        result = json.loads(
            (paper_dir / "paper_result.json").read_text(encoding="utf-8")
        )
        _write_core_delivery(
            workspace, debug_run_id, arxiv_id, result, config=method, run_dir=run_dir
        )
    _restore_merged_history(paper_dir, snapshot)


# ---------------------------------------------------------------------------
# Finalize
# ---------------------------------------------------------------------------


def finalize_network_debug_run(workspace: Path, debug_run_id: str) -> dict[str, Any]:
    """Certify one transport-clean debug container and its lineage."""

    config = load_debug_config(workspace, debug_run_id)
    if config["state"] == "clean" or (
        debug_run_dir(workspace, debug_run_id) / "debug_result.json"
    ).is_file():
        raise ValueError("network debug run is already finalized")
    method = load_method_config(workspace, debug_run_id)
    state = derive_debug_state(workspace, debug_run_id)
    remaining = {
        paper["arxiv_id"]: paper["retry_nodes"]
        for paper in state["papers"]
        if paper["retry_nodes"]
    }
    if remaining:
        raise ValueError(
            "cannot finalize with network-terminal nodes remaining: "
            + json.dumps(remaining, ensure_ascii=False)
        )

    run_dir = debug_run_dir(workspace, debug_run_id)
    source_dir = source_run_dir(workspace, config["source_run"]["run_id"])
    retry_counts = _retry_command_counts(workspace, debug_run_id)
    papers_report: list[dict[str, Any]] = []

    for arxiv_id in config["papers"]:
        paper_dir = run_dir / "papers" / arxiv_id
        touched = _paper_touched(source_dir, run_dir, arxiv_id)
        if touched:
            assemble_paper_result(
                workspace, debug_run_id, arxiv_id, run_dir=run_dir
            )
            result = json.loads(
                (paper_dir / "paper_result.json").read_text(encoding="utf-8")
            )
            _write_core_delivery(
                workspace,
                debug_run_id,
                arxiv_id,
                result,
                config=method,
                run_dir=run_dir,
            )
            papers_report.append(
                {
                    "arxiv_id": arxiv_id,
                    "status": result["status"],
                    "origin": "recovered",
                    "retry_commands": retry_counts.get(arxiv_id, 0),
                    "copied_files": {},
                }
            )
        else:
            result = json.loads(
                (paper_dir / "paper_result.json").read_text(encoding="utf-8")
            )
            papers_report.append(
                {
                    "arxiv_id": arxiv_id,
                    "status": result["status"],
                    "origin": "copied",
                    "retry_commands": 0,
                    "copied_files": _copied_files(source_dir, run_dir, arxiv_id),
                }
            )

    usage, format_validation = _aggregate_debug_usage(run_dir, config["papers"])
    snapshot_path = (
        workspace
        / "benchmark"
        / "pricing"
        / "tokendance"
        / f"{config['pricing_snapshot']['snapshot_id']}.json"
    )
    cost = estimate_api_cost_for_routes(
        snapshot=load_pricing_snapshot(snapshot_path),
        snapshot_path=snapshot_path,
        routes={
            "roster": (
                str(method.roster_model.provider),
                str(method.roster_model.model),
            ),
            "core_fields": (
                str(method.core_field_model.provider),
                str(method.core_field_model.model),
            ),
        },
        usage=usage,
    )
    terminal, network_attempts = _scan_paper_results(run_dir, config["papers"])

    result_artifact = _with_content_hash(
        {
            "schema": schema_ref("benchmark.network_debug_result"),
            "generated_at": _utc_now(),
            "debug_run_id": debug_run_id,
            "source_run": dict(config["source_run"]),
            "scope": config["source_run"]["scope"],
            "papers": papers_report,
            "retry_commands": sum(retry_counts.values()),
            "usage": usage,
            "format_validation": format_validation,
            "estimated_api_cost": cost,
            "network_attempt_errors": network_attempts,
            "terminal_network_failures": terminal,
            "terminal_network_check": {"passed": not terminal},
        }
    )
    _atomic_write_json(run_dir / "debug_result.json", result_artifact)
    config["state"] = "clean"
    _write_debug_config(workspace, debug_run_id, config)
    _write_state(workspace, debug_run_id)
    append_debug_event(
        workspace,
        debug_run_id,
        {
            "command": "finalize",
            "params": {},
            "outcome": "clean" if not terminal else "terminal_failures_present",
            "recovered_papers": sorted(
                paper["arxiv_id"]
                for paper in papers_report
                if paper["origin"] == "recovered"
            ),
        },
    )
    return result_artifact


def _retry_command_counts(workspace: Path, debug_run_id: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in read_debug_events(workspace, debug_run_id):
        if event.get("command") not in {"retry", "rerun_roster"}:
            continue
        for arxiv_id in event.get("params", {}).get("papers") or []:
            counts[arxiv_id] = counts.get(arxiv_id, 0) + 1
    return counts


def _paper_touched(source_dir: Path, run_dir: Path, arxiv_id: str) -> bool:
    source_paper = source_dir / "papers" / arxiv_id
    debug_paper = run_dir / "papers" / arxiv_id
    if not source_paper.is_dir() or not debug_paper.is_dir():
        return True
    source_files = {
        str(path.relative_to(source_paper)): sha256_file(path)
        for path in sorted(source_paper.rglob("*"))
        if path.is_file()
    }
    debug_files = {
        str(path.relative_to(debug_paper)): sha256_file(path)
        for path in sorted(debug_paper.rglob("*"))
        if path.is_file()
    }
    if set(source_files) != set(debug_files):
        return True
    return any(source_files[name] != debug_files[name] for name in source_files)


def _copied_files(source_dir: Path, run_dir: Path, arxiv_id: str) -> dict[str, str]:
    source_paper = source_dir / "papers" / arxiv_id
    debug_paper = run_dir / "papers" / arxiv_id
    copied: dict[str, str] = {}
    if not source_paper.is_dir():
        return copied
    for path in sorted(source_paper.rglob("*")):
        if not path.is_file():
            continue
        relative = str(path.relative_to(source_paper))
        debug_path = debug_paper / relative
        digest = sha256_file(path)
        if debug_path.is_file() and sha256_file(debug_path) == digest:
            copied[f"papers/{arxiv_id}/{relative}"] = digest
    return copied


def _aggregate_debug_usage(
    run_dir: Path, papers: list[str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    roster_units: list[dict[str, Any]] = []
    field_units: list[dict[str, Any]] = []
    format_units: list[tuple[dict[str, Any], str]] = []
    for arxiv_id in papers:
        paper_dir = run_dir / "papers" / arxiv_id
        for proposal_path in sorted(paper_dir.glob("roster_proposal-slot-*.json")):
            proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
            roster_units.append(proposal)
            format_units.append((proposal, "valid"))
        candidates_dir = paper_dir / "candidates"
        if candidates_dir.is_dir():
            for artifact_path in sorted(candidates_dir.glob("*.json")):
                artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
                field_units.append(artifact)
                format_units.append((artifact, "fields_complete"))
    by_role = {
        "roster": _aggregate_usage(roster_units),
        "core_fields": _aggregate_usage(field_units),
    }
    total = {key: 0 for key in USAGE_NUMERIC_FIELDS}
    for usage in by_role.values():
        for key in USAGE_NUMERIC_FIELDS:
            total[key] += usage[key]
    total["api_calls"] = sum(usage["api_calls"] for usage in by_role.values())
    statuses = {usage["telemetry_status"] for usage in by_role.values()}
    if statuses <= {"not_applicable"}:
        total["telemetry_status"] = "not_applicable"
    elif "unavailable" in statuses and not any(
        usage["total_tokens"] for usage in by_role.values()
    ):
        total["telemetry_status"] = "unavailable"
    elif statuses <= {"complete", "not_applicable"}:
        total["telemetry_status"] = "complete"
    else:
        total["telemetry_status"] = "partial"
    total["warnings"] = sorted(
        {warning for usage in by_role.values() for warning in usage["warnings"]}
    )
    return {"by_role": by_role, "total": total}, _format_validation(format_units)
