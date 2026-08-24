"""Contribution paper-level assembly and terminal states.

Once the contribution roster succeeds, the complete frozen roster is
preserved even when quantity extraction fails for one or more objects.
Successful object results stay deliverable in roster order; every failed
object keeps an explicit program-owned failure record. A null quantity set
(successful judgment of absence) and failed quantity extraction (no
trustworthy judgment delivered) never share one serialized representation.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stella.hvs_contribution_extraction.roster_stage import (
    ROSTER_COMPLETE,
    _atomic_write_json,
)
from stella.schema_registry import schema_ref

PAPER_COMPLETE = "complete"
PAPER_PARTIAL = "partial"
PAPER_FAILED = "failed"

QUANTITY_EXTRACTION_COMPLETE = "complete"
QUANTITY_EXTRACTION_FAILED = "failed"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def assemble_contribution_paper_result(
    workspace: Path,
    run_id: str,
    arxiv_id: str,
    *,
    run_dir: Path,
) -> dict[str, Any]:
    """Assemble and persist the paper_result artifact for one paper."""

    paper_dir = Path(run_dir) / "papers" / arxiv_id
    objects_dir = paper_dir / "object_quantities"
    base: dict[str, Any] = {
        "schema": schema_ref("hvs_contribution_extraction.paper_result"),
        "generated_at": _utc_now(),
        "paper": {"arxiv_id": arxiv_id},
        "run_id": run_id,
    }

    roster_path = paper_dir / "contribution_roster_final.json"
    if not roster_path.is_file():
        artifact = base | {
            "status": PAPER_FAILED,
            "roster_status": None,
            "failure": {
                "code": "missing_roster_artifact",
                "detail": "no trusted final contribution roster was produced",
            },
            "roster": None,
            "object_quantities": [],
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
            "object_quantities": [],
        }
        _atomic_write_json(paper_dir / "paper_result.json", artifact)
        return artifact

    entries: list[dict[str, Any]] = []
    for contribution in roster["object_contributions"]:
        record_id = contribution["record_id"]
        object_path = objects_dir / f"{record_id}.json"
        if object_path.is_file():
            record = json.loads(object_path.read_text(encoding="utf-8"))
            entries.append(
                {
                    "record_id": record_id,
                    "status": record["status"],
                    "quantities": record.get("quantities") or [],
                    "failure": record.get("failure"),
                    "attempts": record.get("attempts") or [],
                    "usages": record.get("usages") or [],
                    "repair_history": record.get("repair_history") or [],
                    "provenance": record.get("provenance"),
                }
            )
        else:
            # Crash between the quantity stage and finalization: keep the
            # frozen contribution with an explicit program-owned failure.
            entries.append(
                {
                    "record_id": record_id,
                    "status": QUANTITY_EXTRACTION_FAILED,
                    "quantities": [],
                    "failure": {
                        "code": "missing_object_artifact",
                        "detail": "the quantity stage ended without persisting an object artifact",
                        "attempts": [],
                    },
                    "attempts": [],
                    "usages": [],
                    "repair_history": [],
                    "provenance": None,
                }
            )

    if not roster["object_contributions"]:
        status = PAPER_COMPLETE
    elif all(entry["status"] == QUANTITY_EXTRACTION_COMPLETE for entry in entries):
        status = PAPER_COMPLETE
    else:
        status = PAPER_PARTIAL

    artifact = base | {
        "status": status,
        "roster_status": roster["roster_status"],
        "failure": None,
        "roster": {
            "status": roster["status"],
            "object_contributions": roster["object_contributions"],
            "reviewed_exclusions": roster["reviewed_exclusions"],
            "proposals": roster.get("proposals"),
            "provenance": roster.get("provenance"),
        },
        "object_quantities": entries,
    }
    _atomic_write_json(paper_dir / "paper_result.json", artifact)
    return artifact
