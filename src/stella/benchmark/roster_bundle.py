"""Surface-neutral candidate-roster artifacts shared within one method."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any, Callable

from stella.schema_registry import require_schema, schema_ref


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def roster_shared_key(
    *,
    method: str,
    arxiv_id: str,
    model: str,
    provider: dict[str, Any],
    prompt_sha256: str,
    rule_sha256: str,
    context_sha256: str,
    code_version: str,
) -> tuple[str, dict[str, Any]]:
    components = {
        "method": method,
        "arxiv_id": arxiv_id,
        "model": model,
        "provider": provider,
        "prompt_sha256": prompt_sha256,
        "rule_sha256": rule_sha256,
        "context_sha256": context_sha256,
        "code_version": code_version,
    }
    return canonical_sha256(components), components


def roster_stubs(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = bundle.get("candidates")
    if not isinstance(candidates, list):
        return []
    return [
        {"identifiers": dict(candidate.get("identifiers") or {})}
        for candidate in candidates
        if isinstance(candidate, dict)
    ]


def roster_structure_errors(payload: Any, arxiv_id: str) -> list[str]:
    if not isinstance(payload, dict):
        return ["roster is not a JSON object"]
    errors: list[str] = []
    extraction = payload.get("extraction")
    status = extraction.get("status") if isinstance(extraction, dict) else ""
    if status not in {"candidates_found", "no_candidates"}:
        errors.append("extraction.status must be candidates_found or no_candidates")
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        errors.append("candidates must be a list")
        candidates = []
    if status == "candidates_found" and not candidates:
        errors.append("candidates_found requires at least one candidate")
    if status == "no_candidates" and candidates:
        errors.append("no_candidates requires an empty candidate list")
    if not isinstance(payload.get("candidate_groups_considered"), list):
        errors.append("candidate_groups_considered must be a list")
    seen: set[str] = set()
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            errors.append(f"candidates[{index}] must be an object")
            continue
        unexpected = set(candidate) - {"identifiers", "inclusion_anchor"}
        if unexpected:
            errors.append(
                f"candidates[{index}] may contain only identifiers and inclusion_anchor"
            )
        identifiers = candidate.get("identifiers")
        if not isinstance(identifiers, dict):
            errors.append(f"candidates[{index}].identifiers must be an object")
            continue
        record_id = str(identifiers.get("record_id") or "")
        if not record_id.startswith(f"{arxiv_id}:cand-"):
            errors.append(
                f"candidates[{index}].identifiers.record_id must look like "
                f"'{arxiv_id}:cand-001'"
            )
        if record_id in seen:
            errors.append(f"duplicate record_id {record_id}")
        seen.add(record_id)
        anchor = candidate.get("inclusion_anchor")
        if not isinstance(anchor, dict):
            errors.append(f"candidates[{index}].inclusion_anchor must be an object")
            continue
        if not str(anchor.get("summary") or "").strip():
            errors.append(f"candidates[{index}].inclusion_anchor.summary is required")
        if not isinstance(anchor.get("source_refs"), list) or not anchor.get("source_refs"):
            errors.append(f"candidates[{index}].inclusion_anchor.source_refs is required")
    return errors


def frozen_roster_errors(
    document: Any,
    frozen_stubs: list[dict[str, Any]],
) -> list[str]:
    if not isinstance(document, dict):
        return ["scaffold is not a JSON object"]
    roster = document.get("candidates")
    if roster != frozen_stubs:
        return [
            "candidates must exactly preserve the frozen shared roster "
            "(same identifiers, order, and count); downstream stages may not add, delete, or reorder candidates"
        ]
    return []


def _copy_attempts(source: Path, destination: Path) -> None:
    if not source.is_dir():
        return
    destination.mkdir(parents=True, exist_ok=True)
    for path in source.glob("roster-call-*"):
        if path.is_file():
            shutil.copy2(path, destination / path.name)


def get_or_create_roster_bundle(
    *,
    cache_root: Path,
    shared_key: str,
    key_components: dict[str, Any],
    paper_dir: Path,
    producer: Callable[[], dict[str, Any]],
) -> tuple[dict[str, Any], bool]:
    """Load or atomically produce one shared roster under an advisory lock."""

    cache_root.mkdir(parents=True, exist_ok=True)
    bundle_root = cache_root / shared_key
    bundle_path = bundle_root / "roster_bundle.json"
    lock_path = cache_root / f"{shared_key}.lock"
    lock_path.touch(exist_ok=True)
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        cache_hit = bundle_path.is_file()
        if cache_hit:
            bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
            require_schema(bundle, "benchmark.roster_bundle", require_current=True)
            if bundle.get("shared_key") != shared_key:
                raise ValueError("cached roster shared_key mismatch")
            if bundle.get("key_components") != key_components:
                raise ValueError("cached roster key components mismatch")
            expected_bundle_id = canonical_sha256(
                {key: value for key, value in bundle.items() if key != "bundle_id"}
            )
            if bundle.get("bundle_id") != expected_bundle_id:
                raise ValueError("cached roster bundle hash mismatch")
            structure_errors = roster_structure_errors(
                bundle, str(key_components.get("arxiv_id") or "")
            )
            if structure_errors:
                raise ValueError(
                    "cached roster bundle is invalid: " + "; ".join(structure_errors)
                )
        else:
            produced = producer()
            structure_errors = roster_structure_errors(
                produced, str(key_components.get("arxiv_id") or "")
            )
            if structure_errors:
                raise ValueError(
                    "produced roster bundle is invalid: " + "; ".join(structure_errors)
                )
            bundle = {
                "schema": schema_ref("benchmark.roster_bundle"),
                "shared_key": shared_key,
                "key_components": key_components,
                **produced,
            }
            bundle["bundle_id"] = canonical_sha256(
                {key: value for key, value in bundle.items() if key != "bundle_id"}
            )
            bundle_root.mkdir(parents=True, exist_ok=True)
            temporary = bundle_path.with_name(f".{bundle_path.name}.{os.getpid()}.tmp")
            temporary.write_text(
                json.dumps(bundle, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, bundle_path)
            _copy_attempts(paper_dir / "attempts", bundle_root / "attempts")
        paper_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(bundle_path, paper_dir / "roster_bundle.json")
        _copy_attempts(bundle_root / "attempts", paper_dir / "attempts")
        return bundle, cache_hit
