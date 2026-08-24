"""Operation adapter for the unified workflow runtime.

``run_paper`` executes the contribution chain for one paper inside one fresh
worker process, publishes the canonical document under ``literature/``
atomically, and enforces the explicit supersede authority for replacing an
existing canonical artifact. Provider transports are injected: a scripted
transcript (``STELLA_WORKER_TRANSCRIPT``) is the offline/testing path; no
provider-specific behavior is hard-coded here.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from stella.lit.extraction.method_config import HvsContributionMethodConfig
from stella.lit.extraction.paper_runner import run_contribution_paper
from stella.lit.extraction.run_policy import (
    contribution_run_dir,
    new_contribution_run_id,
    reserve_contribution_run_dir,
)
from stella.lit.hvs_contribution_models import (
    validate_literature_hvs_contributions_document,
)

CANONICAL_FILENAME = "literature_hvs_contributions.json"


def canonical_path(root: Path, paper_id: str) -> Path:
    return Path(root) / "literature" / paper_id / CANONICAL_FILENAME


def scripted_tool_response(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "call_scripted",
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": json.dumps(
                                    arguments, ensure_ascii=False
                                ),
                            },
                        },
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ]
    }


class ScriptedTransport:
    """Replay canned provider tool responses in call order."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses = [
            scripted_tool_response(item["tool_name"], item.get("arguments", {}))
            for item in responses
        ]
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if not self._responses:
            raise RuntimeError("scripted transport exhausted")
        return self._responses.pop(0)


def supersede_guard(
    root: Path, paper_id: str, payload: dict[str, Any]
) -> str | None:
    """Return the previous canonical hash, or fail closed without authority."""

    target = canonical_path(root, paper_id)
    if not target.exists():
        return None
    authorities = (payload.get("authorities") or {}).get("supersede", False)
    if not authorities:
        raise PermissionError(
            f"replacing {target} requires explicit supersede authority"
        )
    return hashlib.sha256(target.read_bytes()).hexdigest()


def publish_canonical_document(
    root: Path, paper_id: str, source: Path, *, allow_replace: bool = False
) -> str:
    """Validate and atomically publish the canonical contribution document."""

    payload = json.loads(Path(source).read_text(encoding="utf-8"))
    validate_literature_hvs_contributions_document(payload)
    target = canonical_path(root, paper_id)
    if target.exists() and not allow_replace:
        raise PermissionError(
            f"canonical document already exists at {target}; supersede authority "
            "is enforced by supersede_guard before publication"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    temporary.replace(target)
    return str(target)


def run_paper(
    payload: dict[str, Any],
    *,
    root: Path,
    paper_id: str | None = None,
) -> dict[str, Any]:
    """One-paper contribution extraction operation adapter."""

    if paper_id is None:
        return {
            "status": "failed",
            "reason": "run_paper requires a paper-scoped worker",
        }
    authorities = payload.get("authorities") or {}
    if not authorities.get("llm"):
        return {
            "status": "failed",
            "reason": "contribution extraction requires the llm authority",
            "missing_authority": ["llm"],
        }
    try:
        previous_sha256 = supersede_guard(root, paper_id, payload)
    except PermissionError as error:
        return {
            "status": "failed",
            "reason": str(error),
            "missing_authority": ["supersede"],
        }
    config_path = os.environ.get("STELLA_WORKER_METHOD_CONFIG")
    transcript_path = os.environ.get("STELLA_WORKER_TRANSCRIPT")
    if not config_path or not transcript_path:
        return {
            "status": "failed",
            "reason": (
                "worker execution inputs missing: STELLA_WORKER_METHOD_CONFIG and "
                "STELLA_WORKER_TRANSCRIPT must point to the frozen method config "
                "and the authorized provider transcript"
            ),
        }
    transcript_file = Path(transcript_path)
    if transcript_file.is_dir():
        transcript_file = transcript_file / f"{paper_id}.json"
    try:
        config = HvsContributionMethodConfig.model_validate(
            json.loads(Path(config_path).read_text(encoding="utf-8"))
        )
        transcript = json.loads(transcript_file.read_text(encoding="utf-8"))
    except Exception as error:  # noqa: BLE001 - surfaced as structured failure
        return {"status": "failed", "reason": f"invalid worker inputs: {error}"}
    transport = ScriptedTransport(transcript.get("responses", []))
    run_id = os.environ.get("STELLA_WORKER_CONTRIBUTION_RUN_ID") or (
        new_contribution_run_id()
    )
    try:
        run_dir = reserve_contribution_run_dir(Path(root), run_id)
        result = run_contribution_paper(
            Path(root),
            run_id,
            paper_id,
            config=config,
            transport=transport,
            sleep=lambda _: None,
            run_dir=run_dir,
        )
    except Exception as error:  # noqa: BLE001 - one paper never aborts the run
        return {
            "status": "failed",
            "reason": f"contribution extraction failed: {error}",
        }
    source = Path(result["canonical_path"])
    if result["status"] in ("complete", "partial") and source.is_file():
        try:
            published = publish_canonical_document(
                root, paper_id, source, allow_replace=previous_sha256 is not None
            )
        except PermissionError as error:
            return {"status": "failed", "reason": str(error)}
        return {
            "status": result["status"],
            "paper_id": paper_id,
            "canonical_path": published,
            "superseded_previous_sha256": previous_sha256,
            "contribution_run_id": run_id,
        }
    return {
        "status": "failed",
        "paper_id": paper_id,
        "reason": f"no validated canonical document was produced ({result['status']})",
    }
