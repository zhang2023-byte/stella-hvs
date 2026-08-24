"""finalize_and_archive: paper-level assembly and terminal states.

Once roster extraction succeeds, the complete frozen roster is preserved
even when field extraction fails for one or more candidates. Successful
candidate results stay deliverable in roster order; every failed candidate
keeps an explicit program-owned failure record — nothing is silently dropped
and no normal field record is synthesized for a failed candidate. A null
quantity (successful judgment of absence) and field_extraction_failed (no
trustworthy judgment delivered) never share one serialized representation.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stella.hvs_extraction.roster_stage import ROSTER_COMPLETE, _atomic_write_json
from stella.schema_registry import schema_ref

PAPER_COMPLETE = "complete"
PAPER_PARTIAL = "partial"
PAPER_FAILED = "failed"

FIELDS_COMPLETE = "fields_complete"
FIELD_EXTRACTION_FAILED = "field_extraction_failed"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def assemble_paper_result(
    workspace: Path,
    run_id: str,
    arxiv_id: str,
    *,
    run_dir: Path | None = None,
) -> dict[str, Any]:
    """Assemble and persist the paper_result artifact for one paper."""

    from stella.lit.extraction.prepare import resolve_run_dir

    paper_dir = (
        resolve_run_dir(workspace, run_id, run_dir=run_dir)
        / "papers"
        / arxiv_id
    )
    candidates_dir = paper_dir / "candidates"
    base: dict[str, Any] = {
        "schema": schema_ref("hvs_extraction.paper_result"),
        "generated_at": _utc_now(),
        "paper": {"arxiv_id": arxiv_id},
        "run_id": run_id,
    }

    roster_path = paper_dir / "roster_final.json"
    if not roster_path.is_file():
        artifact = base | {
            "status": PAPER_FAILED,
            "roster_status": None,
            "failure": {
                "code": "missing_roster_artifact",
                "detail": "no trusted final roster was produced",
            },
            "roster": None,
            "candidates": [],
        }
        _atomic_write_json(paper_dir / "paper_result.json", artifact)
        return artifact

    roster = json.loads(roster_path.read_text(encoding="utf-8"))
    if roster["status"] != ROSTER_COMPLETE:
        artifact = base | {
            "status": PAPER_FAILED,
            "roster_status": None,
            "failure": roster.get("failure")
            or {"code": "roster_failed", "detail": "no trusted final roster"},
            "roster": {
                "status": roster["status"],
                "provenance": roster.get("provenance"),
            },
            "candidates": [],
        }
        _atomic_write_json(paper_dir / "paper_result.json", artifact)
        return artifact

    entries: list[dict[str, Any]] = []
    for candidate in roster["candidates"]:
        record_id = candidate["record_id"]
        candidate_path = candidates_dir / f"{record_id}.json"
        if candidate_path.is_file():
            record = json.loads(candidate_path.read_text(encoding="utf-8"))
            entries.append(
                {
                    "record_id": record_id,
                    "display_name": candidate.get("display_name"),
                    "status": record["status"],
                    "fields": record.get("fields"),
                    "bibliography": record.get("bibliography"),
                    "failure": record.get("failure"),
                    "attempts": record.get("attempts") or [],
                    "usages": record.get("usages") or [],
                    "repair_history": record.get("repair_history") or [],
                    "provenance": record.get("provenance"),
                }
            )
        else:
            # Crash between the field stage and finalization: keep the frozen
            # candidate with an explicit program-owned failure record.
            entries.append(
                {
                    "record_id": record_id,
                    "display_name": candidate.get("display_name"),
                    "status": FIELD_EXTRACTION_FAILED,
                    "fields": None,
                    "bibliography": None,
                    "failure": {
                        "code": "missing_candidate_artifact",
                        "detail": "the field stage ended without persisting a candidate artifact",
                        "attempts": [],
                    },
                    "attempts": [],
                    "usages": [],
                    "repair_history": [],
                    "provenance": None,
                }
            )

    if not roster["candidates"]:
        status = PAPER_COMPLETE
    elif all(entry["status"] == FIELDS_COMPLETE for entry in entries):
        status = PAPER_COMPLETE
    else:
        status = PAPER_PARTIAL

    artifact = base | {
        "status": status,
        "roster_status": roster["roster_status"],
        "failure": None,
        "roster": {
            "status": roster["status"],
            "candidates": roster["candidates"],
            "reviewed_exclusions": roster["reviewed_exclusions"],
            "proposals": roster.get("proposals"),
            "provenance": roster.get("provenance"),
        },
        "candidates": entries,
    }
    _atomic_write_json(paper_dir / "paper_result.json", artifact)
    return artifact
