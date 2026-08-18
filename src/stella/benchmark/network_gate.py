"""Gold-blind network diagnostic for terminal benchmark runs and debug runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from stella.benchmark.campaign import sha256_file
from stella.schema_registry import require_schema

FORMAL_SCOPES = {"full_dev", "full_test"}

POLICY = (
    "diagnostic status report; recovered transport errors allowed; "
    "terminal network failures reported"
)


def _objects(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from _objects(child)


def _is_terminal_network_failure(node: dict[str, Any]) -> bool:
    """Match candidate-level and roster-level terminal transport deaths.

    Candidate failures carry ``code == "transport_failure"``; roster deaths
    wrap the same envelope as ``status == "transport_failure"`` inside
    ``proposal_failures`` under an ``extractor_terminal_failure`` paper
    failure. Both are terminal network failures.
    """

    transport = node.get("transport_error")
    if not isinstance(transport, dict) or transport.get("category") != "network":
        return False
    return node.get("code") == "transport_failure" or node.get("status") == "transport_failure"


def _scan_paper_results(
    run_dir: Path, papers: list[str] | dict[str, Any]
) -> tuple[list[dict[str, str]], int]:
    terminal: list[dict[str, str]] = []
    network_attempts = 0
    paper_ids = list(papers)
    for arxiv_id in paper_ids:
        path = run_dir / "papers" / arxiv_id / "paper_result.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        for node in _objects(payload):
            if node.get("error_class") == "network" and node.get("outcome") == "transport_error":
                network_attempts += 1
            if _is_terminal_network_failure(node):
                terminal.append({"arxiv_id": arxiv_id, "code": "transport_failure"})
    return terminal, network_attempts


def _unique(terminal: list[dict[str, str]]) -> list[dict[str, str]]:
    unique = [dict(item) for item in {tuple(sorted(item.items())) for item in terminal}]
    unique.sort(key=lambda item: item["arxiv_id"])
    return unique


def _copied_file_integrity(run_dir: Path, result: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    checked = 0
    for paper in result.get("papers", []):
        for relative, expected in sorted((paper.get("copied_files") or {}).items()):
            checked += 1
            path = run_dir / relative
            if not path.is_file():
                errors.append({"file": relative, "error": "missing"})
                continue
            if sha256_file(path) != expected:
                errors.append({"file": relative, "error": "sha256_mismatch"})
    return {"checked_files": checked, "errors": errors}


def _evaluate_debug_run(run_dir: Path) -> dict[str, Any]:
    config = json.loads((run_dir / "debug_config.json").read_text(encoding="utf-8"))
    require_schema(config, "benchmark.network_debug_config", require_current=True)
    if config.get("state") != "clean":
        raise ValueError("network diagnostic requires a finalized clean debug run")
    result_path = run_dir / "debug_result.json"
    if not result_path.is_file():
        raise ValueError("network diagnostic requires a finalized clean debug run")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    require_schema(result, "benchmark.network_debug_result", require_current=True)

    terminal, network_attempts = _scan_paper_results(run_dir, config.get("papers", []))
    integrity = _copied_file_integrity(run_dir, result)
    unique_terminal = _unique(terminal)
    return {
        "run_id": config["debug_run_id"],
        "mode": "network_debug",
        "source_run_id": config["source_run"]["run_id"],
        "scope": config["source_run"]["scope"],
        "passed": not unique_terminal and not integrity["errors"],
        "network_attempt_errors": network_attempts,
        "terminal_network_failures": unique_terminal,
        "copy_integrity": integrity,
        "policy": POLICY,
    }


def evaluate_network_gate(run_dir: Path) -> dict[str, Any]:
    """Report terminal network failure status for a formal or debug run.

    Formal runs require one terminal ``full_dev``/``full_test`` summary.
    Debug runs require a finalized clean ``debug_config``/``debug_result``
    pair and additionally verify copied-file hashes (fail closed).
    """

    run_dir = run_dir.resolve()
    if (run_dir / "debug_config.json").is_file():
        return _evaluate_debug_run(run_dir)
    summary = json.loads((run_dir / "run_summary.json").read_text(encoding="utf-8"))
    require_schema(summary, "benchmark.run_summary", require_current=True)
    if summary.get("scope") not in FORMAL_SCOPES or summary.get("state") != "completed":
        raise ValueError("network diagnostic requires one completed full_dev or full_test run")

    terminal, network_attempts = _scan_paper_results(run_dir, summary.get("papers", {}))
    unique_terminal = _unique(terminal)
    return {
        "run_id": summary["run_id"],
        "mode": "formal_run",
        "scope": summary["scope"],
        "passed": not unique_terminal,
        "network_attempt_errors": network_attempts,
        "terminal_network_failures": unique_terminal,
        "policy": POLICY,
    }
