"""Load, save, and completeness-check expert adjudications.

Item id conventions (shared with the review UI and gold assembly):
- candidate presence: item_id == cluster_id
- field value: item_id == "<cluster_id>:<field_path>"
- candidate addition: free-form item_id (e.g. "missing-001")
- paper status lives in the dedicated paper_status_verdict field
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from .models import AdjudicationItem, AdjudicationRecord, AlignmentRecord

PAPER_STATUS_ITEM = "paper_status"


def load_adjudication(path: Path) -> AdjudicationRecord | None:
    if not path.exists():
        return None
    return AdjudicationRecord.model_validate(json.loads(path.read_text(encoding="utf-8")))


def atomic_save_adjudication(path: Path, record: AdjudicationRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(json.loads(record.model_dump_json()), ensure_ascii=False, indent=2) + "\n"
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    )
    try:
        handle.write(payload)
        handle.close()
        os.replace(handle.name, path)
    except BaseException:
        handle.close()
        os.unlink(handle.name)
        raise


def upsert_verdict(record: AdjudicationRecord, item: AdjudicationItem) -> AdjudicationRecord:
    items = [existing for existing in record.items if existing.item_id != item.item_id]
    items.append(item)
    items.sort(key=lambda entry: entry.item_id)
    return record.model_copy(
        update={"items": items, "updated_at": datetime.now().isoformat(timespec="seconds")}
    )


def required_item_ids(alignment: AlignmentRecord) -> list[str]:
    """Items that must carry a verdict before gold can be finalized.

    Every cluster's presence, every disagreement field, and every consensus
    spot-check item; the paper status verdict is tracked separately.
    """
    required: list[str] = []
    for cluster in alignment.clusters:
        required.append(cluster.cluster_id)
        for field in cluster.fields:
            if not field.agreement:
                required.append(f"{cluster.cluster_id}:{field.field_path}")
    for item_id in alignment.consensus_spot_checks:
        if item_id not in required:
            required.append(item_id)
    return required


def missing_items(
    alignment: AlignmentRecord, adjudication: AdjudicationRecord | None
) -> list[str]:
    decided = {item.item_id for item in adjudication.items} if adjudication else set()
    missing = [item_id for item_id in required_item_ids(alignment) if item_id not in decided]
    if adjudication is None or adjudication.paper_status_verdict is None:
        missing.insert(0, PAPER_STATUS_ITEM)
    return missing
