"""Gold-blind network-readiness audit for terminal benchmark runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from stella.schema_registry import require_schema


def _objects(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from _objects(child)


def evaluate_network_gate(run_dir: Path) -> dict[str, Any]:
    """Pass when a completed dev10 has no terminal network failure envelope."""

    run_dir = run_dir.resolve()
    summary = json.loads((run_dir / "run_summary.json").read_text(encoding="utf-8"))
    require_schema(summary, "benchmark.run_summary", require_current=True)
    if summary.get("scope") != "full_dev" or summary.get("state") != "completed":
        raise ValueError("network gate requires one completed full_dev run")

    terminal: list[dict[str, str]] = []
    network_attempts = 0
    for arxiv_id in summary.get("papers", {}):
        path = run_dir / "papers" / arxiv_id / "paper_result.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        for node in _objects(payload):
            if node.get("error_class") == "network" and node.get("outcome") == "transport_error":
                network_attempts += 1
            transport = node.get("transport_error")
            if (
                node.get("code") == "transport_failure"
                and isinstance(transport, dict)
                and transport.get("category") == "network"
            ):
                terminal.append({"arxiv_id": arxiv_id, "code": "transport_failure"})

    unique_terminal = [dict(item) for item in {tuple(sorted(item.items())) for item in terminal}]
    unique_terminal.sort(key=lambda item: item["arxiv_id"])
    return {
        "run_id": summary["run_id"],
        "scope": summary["scope"],
        "passed": not unique_terminal,
        "network_attempt_errors": network_attempts,
        "terminal_network_failures": unique_terminal,
        "policy": "recovered transport errors allowed; terminal network failures forbidden",
    }
