"""Repair archived ADS API metadata and paper-level HVS bibcodes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import requests

from .literature_assets import (
    DEFAULT_TIMEOUT,
    fetch_ads_api_metadata,
    write_ads_api_payload,
)


HVS_CANDIDATES_FILENAME = "literature_hvs_candidates.json"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def ads_bibcode_from_payload(payload: dict[str, Any]) -> str:
    docs = ((payload.get("response") or {}).get("docs") or []) if isinstance(payload, dict) else []
    if not docs or not isinstance(docs[0], dict):
        return ""
    return str(docs[0].get("bibcode") or "").strip()


def resolve_audit_path(local_path: str, *, paper_dir: Path) -> Path:
    path = Path(local_path)
    if path.is_absolute():
        return path
    workspace = paper_dir.parent.parent
    workspace_path = workspace / path
    if workspace_path.exists() or len(path.parts) > 1:
        return workspace_path
    return paper_dir / path


def ads_metadata_payload_path(audit: dict[str, Any], *, paper_dir: Path) -> Path | None:
    metadata = audit.get("ads_metadata")
    if isinstance(metadata, dict):
        local_path = str(metadata.get("local_path") or "").strip()
        if local_path:
            return resolve_audit_path(local_path, paper_dir=paper_dir)
    ads_api = audit.get("ads_api")
    if isinstance(ads_api, dict):
        local_path = str(ads_api.get("local_path") or "").strip()
        if local_path:
            return resolve_audit_path(local_path, paper_dir=paper_dir)
    default_path = paper_dir / "ads_metadata.json"
    if default_path.exists():
        return default_path
    return None


def audit_bibcode(audit: dict[str, Any], *, paper_dir: Path) -> str:
    metadata = audit.get("ads_metadata")
    if isinstance(metadata, dict):
        legacy_bibcode = str(metadata.get("ads_bibcode") or "").strip()
        if legacy_bibcode:
            return legacy_bibcode
    payload_path = ads_metadata_payload_path(audit, paper_dir=paper_dir)
    if payload_path is None or not payload_path.exists():
        return ""
    try:
        return ads_bibcode_from_payload(read_json(payload_path))
    except Exception:
        return ""


def ads_api_ok(audit: dict[str, Any]) -> bool:
    ads_api = audit.get("ads_api")
    return isinstance(ads_api, dict) and bool(ads_api.get("success"))


def ads_api_payload_ok(audit: dict[str, Any], *, paper_dir: Path) -> bool:
    path = ads_metadata_payload_path(audit, paper_dir=paper_dir)
    if path is None:
        return False
    return path.exists() and path.stat().st_size > 0


def hvs_paper_bibcode(path: Path) -> str:
    if not path.exists():
        return ""
    payload = read_json(path)
    paper = payload.get("paper")
    if not isinstance(paper, dict):
        return ""
    return str(paper.get("bibcode") or "").strip()


def hvs_needs_paper_bibcode(path: Path) -> bool:
    if not path.exists():
        return False
    payload = read_json(path)
    paper = payload.get("paper")
    return isinstance(paper, dict) and not str(paper.get("bibcode") or "").strip()


def update_hvs_paper_bibcode(path: Path, *, bibcode: str) -> bool:
    payload = read_json(path)
    paper = payload.get("paper")
    if not isinstance(paper, dict):
        return False
    existing = str(paper.get("bibcode") or "").strip()
    if existing:
        return False
    paper["bibcode"] = bibcode
    write_json(path, payload)
    return True


def iter_audit_paths(literature_dir: Path) -> list[Path]:
    return sorted(path for path in literature_dir.glob("*/audit.json") if path.is_file())


def repair_one_ads_metadata(
    paper_dir: Path,
    *,
    session: requests.Session,
    timeout: int = DEFAULT_TIMEOUT,
    dry_run: bool = False,
    ads_token: str = "",
    force: bool = False,
) -> dict[str, Any]:
    audit_path = paper_dir / "audit.json"
    result: dict[str, Any] = {
        "arxiv_id": paper_dir.name,
        "audit_path": str(audit_path),
        "ads_retry_needed": False,
        "ads_retry_attempted": False,
        "ads_success": False,
        "ads_api_attempted": False,
        "ads_api_success": False,
        "ads_bibcode": "",
        "audit_updated": False,
        "hvs_candidates_path": None,
        "hvs_update_needed": False,
        "hvs_updated": False,
        "hvs_bibcode_conflict": None,
        "errors": [],
        "status": "already_ok",
    }
    if not audit_path.exists():
        result["errors"].append("audit.json missing")
        result["status"] = "failed"
        return result

    try:
        audit = read_json(audit_path)
    except Exception as exc:
        result["errors"].append(f"failed to read audit.json: {type(exc).__name__}: {exc}")
        result["status"] = "failed"
        return result
    arxiv_id = str(audit.get("arxiv_id") or paper_dir.name).strip()
    result["arxiv_id"] = arxiv_id
    hvs_path = paper_dir / HVS_CANDIDATES_FILENAME
    if hvs_path.exists():
        result["hvs_candidates_path"] = str(hvs_path)

    known_bibcode = audit_bibcode(audit, paper_dir=paper_dir)
    ads_retry_needed = (
        force
        or (not ads_api_ok(audit))
        or (not ads_api_payload_ok(audit, paper_dir=paper_dir))
        or not known_bibcode
    )
    try:
        hvs_update_needed = hvs_needs_paper_bibcode(hvs_path)
    except Exception as exc:
        hvs_update_needed = False
        result["errors"].append(f"failed to inspect {HVS_CANDIDATES_FILENAME}: {type(exc).__name__}: {exc}")
    result["ads_retry_needed"] = ads_retry_needed
    result["hvs_update_needed"] = hvs_update_needed
    result["ads_success"] = False
    result["ads_api_success"] = ads_api_ok(audit)
    result["ads_bibcode"] = known_bibcode

    if dry_run:
        if result["errors"]:
            result["status"] = "failed"
        elif ads_retry_needed or (hvs_update_needed and known_bibcode):
            result["status"] = "would_change"
        return result

    if ads_retry_needed:
        result["ads_retry_attempted"] = True
        result["ads_api_attempted"] = True
        ads_api_result, parsed_metadata, ads_api_payload = fetch_ads_api_metadata(
            session,
            arxiv_id=arxiv_id,
            token=ads_token,
            timeout=timeout,
        )
        if ads_api_payload:
            ads_metadata_path = write_ads_api_payload(
                paper_dir,
                payload=ads_api_payload,
                workspace=paper_dir.parent.parent,
            )
            ads_api_result["local_path"] = ads_metadata_path
            audit["ads_metadata"] = {"local_path": ads_metadata_path}
        else:
            audit["ads_metadata"] = {}
        audit["ads_api"] = ads_api_result
        audit.pop("ads_abstract", None)
        (paper_dir / "ads_abstract.html").unlink(missing_ok=True)
        write_json(audit_path, audit)
        result["audit_updated"] = True
        result["ads_api_success"] = bool(ads_api_result.get("success"))
        known_bibcode = str(parsed_metadata.get("ads_bibcode") or "").strip()
        result["ads_bibcode"] = known_bibcode
        if not ads_api_result.get("success"):
            result["errors"].append(f"ADS API failed: {ads_api_result.get('error') or 'unknown error'}")
        if not known_bibcode:
            result["errors"].append("ADS bibcode remains empty")

    if hvs_path.exists() and known_bibcode:
        try:
            existing_hvs_bibcode = hvs_paper_bibcode(hvs_path)
            if not existing_hvs_bibcode:
                result["hvs_updated"] = update_hvs_paper_bibcode(hvs_path, bibcode=known_bibcode)
            elif existing_hvs_bibcode != known_bibcode:
                result["hvs_bibcode_conflict"] = {
                    "paper_bibcode": existing_hvs_bibcode,
                    "audit_bibcode": known_bibcode,
                }
        except Exception as exc:
            result["errors"].append(f"failed to update {HVS_CANDIDATES_FILENAME}: {type(exc).__name__}: {exc}")

    if result["errors"]:
        result["status"] = "partial" if known_bibcode or result["hvs_updated"] else "failed"
    elif result["audit_updated"] or result["hvs_updated"]:
        result["status"] = "fixed"
    return result


def repair_ads_metadata(
    *,
    literature_dir: Path,
    session: requests.Session,
    timeout: int = DEFAULT_TIMEOUT,
    arxiv_ids: list[str] | None = None,
    dry_run: bool = False,
    ads_token: str = "",
    force: bool = False,
) -> dict[str, Any]:
    selected: list[Path] = []
    skipped: list[dict[str, str]] = []
    if arxiv_ids:
        for arxiv_id in arxiv_ids:
            audit_path = literature_dir / arxiv_id / "audit.json"
            if audit_path.exists():
                selected.append(audit_path)
            else:
                skipped.append({"arxiv_id": arxiv_id, "reason": "audit-json-missing"})
    else:
        selected = iter_audit_paths(literature_dir)

    results = [
        repair_one_ads_metadata(
            audit_path.parent,
            session=session,
            timeout=timeout,
            dry_run=dry_run,
            ads_token=ads_token,
            force=force,
        )
        for audit_path in selected
    ]
    summary = {
        "selected_count": len(results),
        "skipped_count": len(skipped),
        "would_change_count": sum(1 for item in results if item.get("status") == "would_change"),
        "already_ok_count": sum(1 for item in results if item.get("status") == "already_ok"),
        "fixed_count": sum(1 for item in results if item.get("status") == "fixed"),
        "partial_count": sum(1 for item in results if item.get("status") == "partial"),
        "failed_count": sum(1 for item in results if item.get("status") == "failed"),
        "ads_retry_needed_count": sum(1 for item in results if item.get("ads_retry_needed") is True),
        "ads_retry_attempted_count": sum(1 for item in results if item.get("ads_retry_attempted") is True),
        "ads_api_attempted_count": sum(1 for item in results if item.get("ads_api_attempted") is True),
        "ads_api_success_count": sum(1 for item in results if item.get("ads_api_success") is True),
        "ads_bibcode_found_count": sum(1 for item in results if bool(item.get("ads_bibcode"))),
        "hvs_update_needed_count": sum(1 for item in results if item.get("hvs_update_needed") is True),
        "hvs_updated_count": sum(1 for item in results if item.get("hvs_updated") is True),
    }
    return {
        "dry_run": dry_run,
        "force": force,
        "literature_dir": str(literature_dir),
        "selected": results,
        "skipped": skipped,
        "summary": summary,
    }
