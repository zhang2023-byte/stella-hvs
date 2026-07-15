"""Surface-neutral candidate-roster artifacts shared within one method."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, Callable

from pydantic import TypeAdapter, ValidationError

from stella.lit.schema_models import CandidateIdentifiers, SourceRef
from stella.schema_registry import require_schema, schema_ref


_GAIA_SOURCE_ID_RE = re.compile(r"^Gaia (?:DR[0-9]+|EDR[0-9]+) [0-9]+$")
_SOURCE_REFS_ADAPTER = TypeAdapter(list[SourceRef])


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


def roster_identifier_contract(arxiv_id: str) -> str:
    """Return the compact canonical identifier contract shared by B and C prompts."""

    example = {
        "record_id": f"{arxiv_id}:cand-001",
        "paper_candidate_id": "paper-visible candidate name",
        "gaia_source_id": "",
        "all": [
            {
                "value": "paper-visible candidate name",
                "source_refs": [
                    {
                        "kind": "text",
                        "path": f"literature/{arxiv_id}/arxiv_source/paper.tex",
                        "start_line": 1,
                        "end_line": 1,
                        "context": "exact nearby paper text",
                    }
                ],
            }
        ],
    }
    return (
        "Every identifiers object MUST have exactly the canonical four keys and shape below:\n"
        + json.dumps(example, ensure_ascii=False, indent=2)
        + "\nUse an empty string when the paper has no strict Gaia identifier. Never use null. "
        "Every paper_candidate_id and non-empty gaia_source_id must also appear verbatim in "
        "all[].value. Every all[] item has exactly value and source_refs; do not use label, "
        "catalog, id, aliases, paper_name, hv_survey_name, gaia_dr2_id, or gaia_dr3_source_id. "
        "A source ref is a canonical text object as shown above or an ecsv_cell object with "
        "kind, path, line, column, column_header, raw_value, and optional component_raw_value."
    )


def _pydantic_errors(prefix: str, exc: ValidationError) -> list[str]:
    errors: list[str] = []
    for item in exc.errors(include_url=False):
        location = ".".join(str(part) for part in item.get("loc") or ())
        path = f"{prefix}.{location}" if location else prefix
        errors.append(f"{path}: {item.get('msg') or 'invalid value'}")
    return errors


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
    seen_paper_candidate_ids: set[str] = set()
    seen_gaia_source_ids: set[str] = set()
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
        prefix = f"candidates[{index}].identifiers"
        try:
            parsed_identifiers = CandidateIdentifiers.model_validate(identifiers)
        except ValidationError as exc:
            errors.extend(_pydantic_errors(prefix, exc))
            parsed_identifiers = None
        record_id = str(identifiers.get("record_id") or "")
        if not re.fullmatch(rf"{re.escape(arxiv_id)}:cand-[0-9]{{3}}", record_id):
            errors.append(
                f"candidates[{index}].identifiers.record_id must look like "
                f"'{arxiv_id}:cand-001'"
            )
        if record_id in seen:
            errors.append(f"duplicate record_id {record_id}")
        seen.add(record_id)
        if parsed_identifiers is not None:
            paper_candidate_id = parsed_identifiers.paper_candidate_id.strip()
            gaia_source_id = parsed_identifiers.gaia_source_id.strip()
            if paper_candidate_id in seen_paper_candidate_ids:
                errors.append(
                    f"{prefix}.paper_candidate_id: duplicate paper_candidate_id {paper_candidate_id!r}"
                )
            seen_paper_candidate_ids.add(paper_candidate_id)
            if gaia_source_id:
                if not _GAIA_SOURCE_ID_RE.fullmatch(gaia_source_id):
                    errors.append(
                        f"{prefix}.gaia_source_id: expected empty string or strict Gaia source id "
                        "like 'Gaia DR3 123456789'"
                    )
                if gaia_source_id in seen_gaia_source_ids:
                    errors.append(
                        f"{prefix}.gaia_source_id: duplicate gaia_source_id {gaia_source_id!r}"
                    )
                seen_gaia_source_ids.add(gaia_source_id)
            if not parsed_identifiers.all:
                errors.append(f"{prefix}.all: must be non-empty")
            all_values: set[str] = set()
            for all_index, identifier in enumerate(parsed_identifiers.all):
                value = identifier.value.strip()
                if not value:
                    errors.append(f"{prefix}.all.{all_index}.value: must be non-empty")
                elif value in all_values:
                    errors.append(
                        f"{prefix}.all.{all_index}.value: duplicate identifier value {value!r}"
                    )
                all_values.add(value)
                if not identifier.source_refs:
                    errors.append(
                        f"{prefix}.all.{all_index}.source_refs: at least one source reference is required"
                    )
            if paper_candidate_id and paper_candidate_id not in all_values:
                errors.append(
                    f"{prefix}.paper_candidate_id: must also appear in identifiers.all[].value"
                )
            if gaia_source_id and gaia_source_id not in all_values:
                errors.append(
                    f"{prefix}.gaia_source_id: must also appear in identifiers.all[].value"
                )
            if not gaia_source_id and any(
                _GAIA_SOURCE_ID_RE.fullmatch(value) for value in all_values
            ):
                errors.append(
                    f"{prefix}.gaia_source_id: must be set when identifiers.all contains a strict Gaia source id"
                )
        anchor = candidate.get("inclusion_anchor")
        if not isinstance(anchor, dict):
            errors.append(f"candidates[{index}].inclusion_anchor must be an object")
            continue
        if not str(anchor.get("summary") or "").strip():
            errors.append(f"candidates[{index}].inclusion_anchor.summary is required")
        anchor_refs = anchor.get("source_refs")
        if not isinstance(anchor_refs, list) or not anchor_refs:
            errors.append(f"candidates[{index}].inclusion_anchor.source_refs is required")
        else:
            try:
                _SOURCE_REFS_ADAPTER.validate_python(anchor_refs)
            except ValidationError as exc:
                errors.extend(
                    _pydantic_errors(
                        f"candidates[{index}].inclusion_anchor.source_refs", exc
                    )
                )
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
