"""Surface-neutral candidate-roster artifacts shared within one method."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from pydantic import TypeAdapter, ValidationError

from stella.lit.schema_models import CandidateIdentifiers, SourceRef
from stella.schema_registry import require_schema, schema_ref


_GAIA_SOURCE_ID_RE = re.compile(r"^Gaia (?:DR[0-9]+|EDR[0-9]+) [0-9]+$")
_SOURCE_REFS_ADAPTER = TypeAdapter(list[SourceRef])
ROSTER_REVIEW_DECISIONS = frozenset({"accept", "revise"})


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def final_roster_sha256(bundle: dict[str, Any]) -> str:
    """Hash only the sealed scientific roster, independently of cache metadata."""

    return canonical_sha256(
        {
            "method": bundle.get("method"),
            "arxiv_id": bundle.get("arxiv_id"),
            "extraction": bundle.get("extraction"),
            "candidates": bundle.get("candidates"),
            "candidate_groups_considered": bundle.get("candidate_groups_considered"),
        }
    )


def _validate_v3_review_contract(bundle: dict[str, Any]) -> None:
    review = bundle.get("review")
    if not isinstance(review, dict) or set(review) != {
        "status",
        "contract",
        "provenance",
    }:
        raise ValueError("roster bundle requires the v3 review contract")
    status = review.get("status")
    contract = review.get("contract")
    provenance = review.get("provenance")
    if status == "not_requested":
        if contract is not None or provenance is not None:
            raise ValueError("unreviewed roster must not record reviewer provenance")
    elif status in {"accepted", "revised"}:
        if not isinstance(contract, dict) or not contract:
            raise ValueError("reviewed roster requires a non-empty review contract")
        if not isinstance(provenance, dict) or not provenance:
            raise ValueError("reviewed roster requires reviewer provenance")
        comparison = contract.get("comparison") if isinstance(contract, dict) else None
        if not isinstance(comparison, dict) or not isinstance(
            comparison.get("match"), bool
        ):
            raise ValueError("reviewed roster requires deterministic comparison")
    else:
        raise ValueError("roster bundle has invalid review status")
    if bundle.get("final_roster_sha256") != final_roster_sha256(bundle):
        raise ValueError("cached roster final roster hash mismatch")


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
    reviewer_model: str,
    reviewer_provider: dict[str, Any],
    reviewer_prompt_sha256: str,
    reviewer_rule_sha256: str,
    roster_context_manifest_sha256: str = "",
) -> tuple[str, dict[str, Any]]:
    components = {
        "method": method,
        "arxiv_id": arxiv_id,
        "model": model,
        "provider": provider,
        "prompt_sha256": prompt_sha256,
        "rule_sha256": rule_sha256,
        "context_sha256": context_sha256,
        "roster_context_manifest_sha256": roster_context_manifest_sha256,
        "code_version": code_version,
        # The roster is sealed only after the independent roster review, so
        # the reviewer contract is part of the cache identity: a bundle
        # sealed under a different reviewer must never be a cache hit.
        "reviewer_model": reviewer_model,
        "reviewer_provider": reviewer_provider,
        "reviewer_prompt_sha256": reviewer_prompt_sha256,
        "reviewer_rule_sha256": reviewer_rule_sha256,
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


def roster_inclusion_anchor_map(bundle: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Map record_id -> sealed inclusion_anchor for downstream evidence envelopes.

    The anchors stay OUTSIDE the identifier stubs so frozen-roster equality
    keeps covering only identifiers; downstream prompts receive them as
    read-only evidence, never as mutable candidate fields.
    """

    anchors: dict[str, dict[str, Any]] = {}
    candidates = bundle.get("candidates")
    if not isinstance(candidates, list):
        return anchors
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        identifiers = candidate.get("identifiers")
        anchor = candidate.get("inclusion_anchor")
        if not isinstance(identifiers, dict) or not isinstance(anchor, dict):
            continue
        record_id = str(identifiers.get("record_id") or "")
        if record_id:
            anchors[record_id] = anchor
    return anchors


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
        " For ecsv_cell refs, column is the exact machine name from the ECSV header row; "
        "the human display label belongs only in column_header."
    )


def roster_payload_json_schema() -> dict[str, Any]:
    """Strict transport schema for roster producer/reviewer submissions."""

    text_ref = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "kind": {"const": "text"},
            "path": {"type": "string"},
            "start_line": {"type": "integer"},
            "end_line": {"type": "integer"},
            "context": {"type": "string"},
        },
        "required": ["kind", "path", "start_line", "end_line", "context"],
    }
    ecsv_ref = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "kind": {"const": "ecsv_cell"},
            "path": {"type": "string"},
            "line": {"type": "integer"},
            "column": {"type": "string"},
            "column_header": {"type": "string"},
            "raw_value": {"type": "string"},
            "component_raw_value": {"type": "string"},
        },
        "required": ["kind", "path", "line", "column", "column_header", "raw_value"],
    }
    source_ref = {"oneOf": [text_ref, ecsv_ref]}
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "extraction": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "status": {"enum": ["candidates_found", "no_candidates"]},
                    "summary": {"type": "string"},
                },
                "required": ["status", "summary"],
            },
            "candidates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "identifiers": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "record_id": {"type": "string"},
                                "paper_candidate_id": {"type": "string"},
                                "gaia_source_id": {"type": "string"},
                                "all": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "additionalProperties": False,
                                        "properties": {
                                            "value": {"type": "string"},
                                            "source_refs": {"type": "array", "items": source_ref},
                                        },
                                        "required": ["value", "source_refs"],
                                    },
                                },
                            },
                            "required": ["record_id", "paper_candidate_id", "gaia_source_id", "all"],
                        },
                        "inclusion_anchor": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "summary": {"type": "string"},
                                "source_refs": {"type": "array", "items": source_ref},
                            },
                            "required": ["summary", "source_refs"],
                        },
                    },
                    "required": ["identifiers", "inclusion_anchor"],
                },
            },
            "candidate_groups_considered": {"type": "array"},
        },
        "required": ["extraction", "candidates", "candidate_groups_considered"],
    }


def roster_comparison(produced: dict[str, Any], reviewed: dict[str, Any]) -> dict[str, Any]:
    """Return a stable, value-preserving comparison of two complete rosters."""

    def scientific_sha(value: dict[str, Any]) -> str:
        return canonical_sha256(
            {
                "extraction": value.get("extraction"),
                "candidates": value.get("candidates"),
                "candidate_groups_considered": value.get("candidate_groups_considered"),
            }
        )

    producer_sha = scientific_sha(produced)
    reviewer_sha = scientific_sha(reviewed)
    return {
        "match": producer_sha == reviewer_sha,
        "producer_roster_sha256": producer_sha,
        "reviewer_roster_sha256": reviewer_sha,
        "producer_record_ids": [
            str((item.get("identifiers") or {}).get("record_id") or "")
            for item in produced.get("candidates", [])
            if isinstance(item, dict)
        ],
        "reviewer_record_ids": [
            str((item.get("identifiers") or {}).get("record_id") or "")
            for item in reviewed.get("candidates", [])
            if isinstance(item, dict)
        ],
    }


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
        expected_record_id = f"{arxiv_id}:cand-{index + 1:03d}"
        if not re.fullmatch(rf"{re.escape(arxiv_id)}:cand-[0-9]{{3}}", record_id):
            errors.append(
                f"candidates[{index}].identifiers.record_id must look like "
                f"'{arxiv_id}:cand-001'"
            )
        elif record_id != expected_record_id:
            errors.append(
                f"candidates[{index}].identifiers.record_id must equal "
                f"'{expected_record_id}'"
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


def roster_review_structure_errors(payload: Any, arxiv_id: str) -> list[str]:
    """Validate the compact pre-seal roster-review payload.

    Shape: {"decision": "accept"|"revise", "challenges": [...], "summary": str,
    "revised_roster": {...}}. The corrected roster is required exactly when the
    decision is "revise" and must itself pass ``roster_structure_errors`` — at
    most one revision exists, so it has to be complete and self-consistent.
    """

    if not isinstance(payload, dict):
        return ["roster review is not a JSON object"]
    errors: list[str] = []
    decision = str(payload.get("decision") or "")
    if decision not in ROSTER_REVIEW_DECISIONS:
        errors.append(
            "decision must be one of " + ", ".join(sorted(ROSTER_REVIEW_DECISIONS))
        )
    if not str(payload.get("summary") or "").strip():
        errors.append("summary is required")
    challenges = payload.get("challenges")
    if not isinstance(challenges, list):
        errors.append("challenges must be a list")
        challenges = []
    for index, challenge in enumerate(challenges):
        if not isinstance(challenge, dict):
            errors.append(f"challenges[{index}] must be an object")
            continue
        if not str(challenge.get("issue") or "").strip():
            errors.append(f"challenges[{index}].issue is required")
        if "record_id" in challenge and not isinstance(
            challenge.get("record_id"), str
        ):
            errors.append(f"challenges[{index}].record_id must be a string")
    revised = payload.get("revised_roster")
    if decision == "revise":
        if not challenges:
            errors.append("decision 'revise' requires at least one challenge")
        if not isinstance(revised, dict):
            errors.append("decision 'revise' requires a revised_roster object")
        else:
            errors.extend(
                f"revised_roster.{error}"
                for error in roster_structure_errors(revised, arxiv_id)
            )
    elif revised is not None:
        errors.append("revised_roster is only allowed when decision is 'revise'")
    return errors


@dataclass(frozen=True)
class RosterReviewVerdict:
    """One validated roster-review decision handed to the bundle seal."""

    payload: dict[str, Any]
    provenance: dict[str, Any]
    usage: dict[str, int] = field(default_factory=dict)


def _merge_usage(base: Any, extra: Any) -> dict[str, int]:
    merged: dict[str, int] = {}
    for source in (base, extra):
        if not isinstance(source, dict):
            continue
        for key, value in source.items():
            if isinstance(value, int) and value:
                merged[str(key)] = merged.get(str(key), 0) + value
    return merged


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
    for pattern in ("roster-call-*", "roster-review-call-*"):
        for path in source.glob(pattern):
            if path.is_file():
                shutil.copy2(path, destination / path.name)


def _apply_roster_review(
    produced: dict[str, Any],
    verdict: RosterReviewVerdict,
    arxiv_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply one pre-seal roster review; return (sealed fields, review block).

    Deterministic equality seals the produced roster; a mismatch may seal only
    the single bounded reconciliation result. The v3 review block records the
    independent hashes/comparison and reviewer provenance.
    """

    review_errors = roster_review_structure_errors(verdict.payload, arxiv_id)
    if review_errors:
        raise ValueError(
            "roster review payload is invalid: " + "; ".join(review_errors)
        )
    decision = str(verdict.payload.get("decision"))
    sealed = dict(produced)
    if decision == "revise":
        revised = verdict.payload["revised_roster"]
        sealed["extraction"] = revised.get("extraction", {})
        sealed["candidates"] = revised.get("candidates", [])
        sealed["candidate_groups_considered"] = revised.get(
            "candidate_groups_considered", []
        )
    sealed["usage"] = _merge_usage(produced.get("usage"), verdict.usage)
    comparison = verdict.payload.get("comparison")
    if not isinstance(comparison, dict):
        comparison = roster_comparison(produced, sealed)
    review = {
        "status": "accepted" if decision == "accept" else "revised",
        "contract": {
            "decision": decision,
            "challenges": verdict.payload.get("challenges", []),
            "summary": verdict.payload.get("summary", ""),
            "producer_roster_sha256": final_roster_sha256(produced),
            "comparison": dict(comparison),
            "reconciliation": dict(verdict.payload.get("reconciliation") or {}),
        },
        "provenance": dict(verdict.provenance),
    }
    return sealed, review


def get_or_create_roster_bundle(
    *,
    cache_root: Path,
    shared_key: str,
    key_components: dict[str, Any],
    paper_dir: Path,
    producer: Callable[[], dict[str, Any]],
    reviewer: Callable[[dict[str, Any]], RosterReviewVerdict] | None = None,
) -> tuple[dict[str, Any], bool]:
    """Load or atomically produce one shared roster under an advisory lock.

    On a cache miss the callback obtains one independently discovered reviewer
    roster, compares it deterministically with the producer, and performs at
    most one reconciliation before returning its verdict. The bundle seals the
    resulting roster and comparison provenance. A missing reviewer keeps the
    legacy unreviewed ``not_requested`` state.
    """

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
            _validate_v3_review_contract(bundle)
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
            if reviewer is not None:
                sealed, review = _apply_roster_review(
                    produced,
                    reviewer(produced),
                    str(key_components.get("arxiv_id") or ""),
                )
            else:
                sealed, review = produced, {
                    "status": "not_requested",
                    "contract": None,
                    "provenance": None,
                }
            bundle = {
                "schema": schema_ref("benchmark.roster_bundle"),
                "shared_key": shared_key,
                "key_components": key_components,
                **sealed,
                "review": review,
            }
            bundle["final_roster_sha256"] = final_roster_sha256(bundle)
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
