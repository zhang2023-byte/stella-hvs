"""Literature baseline scoring: paper-local candidates vs selected expert gold.

This is a diagnostic comparison, not a formal campaign run: the AI side comes
from ``literature/<arxiv_id>/literature_hvs_candidates.json`` rather than a
sealed run archive, so there is no L0/operations envelope. The aggregate
scorecard and the item-level details are both written beside the external
private gold store; nothing is added to a campaign's public scoring directory.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from stella.benchmark.campaign import papers_for_split, sha256_file
from stella.benchmark.paths import validate_path_segment
from stella.benchmark.scoring import (
    DEFAULT_BOOTSTRAP_ITERATIONS,
    DEFAULT_BOOTSTRAP_SEED,
    load_ai_document,
    load_formal_gold_snapshot,
    score_run,
)
from stella.schema_registry import require_campaign_writable, require_schema

HVS_CANDIDATES_FILENAME = "literature_hvs_candidates.json"
BASELINE_KIND = "literature_baseline"


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
    return payload


def _value_marker(text: str) -> str:
    return text.strip() if any(ch.isalpha() for ch in text.strip()) else ""


def gold_marker_strings(private_details: dict[str, Any]) -> set[str]:
    """Identity and value strings that must never leak into an aggregate."""

    markers: set[str] = set()
    for paper in private_details.get("papers", []):
        for pair in paper.get("pairs", []):
            markers.add(str(pair.get("gold_id") or ""))
            for row in pair.get("l2", []):
                markers.add(_value_marker(str(row.get("gold") or "")))
                markers.add(_value_marker(str(row.get("gold_note") or "")))
        for missed in paper.get("unmatched_gold", []):
            markers.add(str(missed.get("gold_id") or ""))
            for row in missed.get("l2", []):
                markers.add(_value_marker(str(row.get("gold") or "")))
    return {marker for marker in markers if len(marker) >= 4}


def score_literature_baseline(
    *,
    campaign_path: Path,
    split: str,
    literature_dir: Path,
    gold_dir: Path,
    gold_manifest_path: Path,
    gold_selection_path: Path,
    run_label: str,
    bootstrap_iterations: int = DEFAULT_BOOTSTRAP_ITERATIONS,
    bootstrap_seed: int = DEFAULT_BOOTSTRAP_SEED,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Score literature candidates for one campaign split against selected gold.

    Returns (aggregate scorecard, private details). The aggregate keeps the
    current scorecard schema but carries no L0/operations blocks and is marked
    as a diagnostic baseline in its provenance.
    """

    campaign_path = campaign_path.resolve()
    campaign = _load_json_object(campaign_path, label="campaign manifest")
    require_schema(campaign, "benchmark.campaign", require_current=True)
    campaign_hash = sha256_file(campaign_path)
    campaign_id = require_campaign_writable(str(campaign.get("campaign_id") or ""))
    expected = papers_for_split(campaign, split)
    gold_annotations, gold_snapshot = load_formal_gold_snapshot(
        gold_dir=gold_dir.resolve(),
        gold_manifest_path=gold_manifest_path.resolve(),
        gold_selection_path=gold_selection_path.resolve(),
        paper_ids=expected,
        campaign_id=campaign_id,
        campaign_sha256=campaign_hash,
        split=split,
    )
    literature_dir = literature_dir.resolve()
    ai_documents: dict[str, dict[str, Any] | None] = {
        arxiv_id: load_ai_document(literature_dir / arxiv_id / HVS_CANDIDATES_FILENAME)
        for arxiv_id in expected
    }
    label = validate_path_segment(run_label, "run label")
    primary, private_details = score_run(
        gold_annotations=gold_annotations,
        ai_documents=ai_documents,
        weights={arxiv_id: 1.0 for arxiv_id in expected},
        run_label=label,
        run_source={"mode": "legacy_literature"},
        bootstrap_iterations=bootstrap_iterations,
        bootstrap_seed=bootstrap_seed,
    )
    formal = {
        "campaign": {"campaign_id": campaign_id, "sha256": campaign_hash},
        "split": split,
        "run_id": None,
        "gold_snapshot_sha256": gold_snapshot["selected_records_sha256"],
        "gold_selection": {
            "selection_id": gold_snapshot["selection_id"],
            "manifest_sha256": gold_snapshot["manifest_sha256"],
            "selected_records_sha256": gold_snapshot["selected_records_sha256"],
        },
        "baseline": BASELINE_KIND,
        "test_release": None,
    }
    primary["formal"] = formal
    primary["provenance"] = {
        "evaluation_label": label,
        "gold_snapshot": {
            "manifest_sha256": gold_snapshot["gold_manifest_sha256"],
            "selection_manifest_sha256": gold_snapshot["manifest_sha256"],
            "selected_records_sha256": gold_snapshot["selected_records_sha256"],
        },
        "supersedes": None,
        "diagnostic": (
            "literature baseline over paper-local candidates; not a formal "
            "campaign run and not comparable in L0/operations"
        ),
    }
    private_details["formal"] = primary["formal"]
    private_details["gold_selection"] = {
        **primary["formal"]["gold_selection"],
        "annotators": gold_snapshot["annotators"],
    }
    for paper in private_details.get("papers", []):
        paper["gold_annotator"] = gold_snapshot["annotators"][paper["arxiv_id"]]
    return primary, private_details


def write_baseline_outputs(
    output_dir: Path,
    scorecard: dict[str, Any],
    private_details: dict[str, Any],
) -> tuple[Path, Path]:
    """Write aggregate scorecard.json and private details.json side by side.

    Both files stay in the external private repository. The content is
    deterministic for fixed inputs, so regeneration overwrites in place.
    """

    label = validate_path_segment(str(scorecard.get("run_label") or ""), "run label")
    scorecard_text = json.dumps(scorecard, ensure_ascii=False, indent=2) + "\n"
    leaked = [
        marker
        for marker in sorted(gold_marker_strings(private_details))
        if marker in scorecard_text
    ]
    if leaked:
        raise ValueError(
            "leak guard: aggregate scorecard contains gold strings: " + ", ".join(leaked)
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    scorecard_path = output_dir / "scorecard.json"
    details_path = output_dir / "details.json"
    scorecard_path.write_text(scorecard_text, encoding="utf-8")
    details_path.write_text(
        json.dumps(private_details, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return scorecard_path, details_path
