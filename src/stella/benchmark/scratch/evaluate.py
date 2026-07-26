"""Development evaluation driver for scratch runs (D043).

Reuses the repository's existing default scoring behavior: the projection is
scored by the unchanged ``score_run`` with default weights and configuration.
No scoring semantics are redesigned here. The gold store is read through the
same authorized scoring channel as the formal scorer; the scratch extraction
pipeline itself never reads gold. Public scorecards land in the scratch run
directory; private per-item details go only to the external private
repository (``<gold store>/../scoring-details/scratch/<run_id>/``), mirroring
the dev-console convention. The D041 uncertainty-scoring gap is recorded in
the implementation log, not worked around.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stella.benchmark.paths import require_external_path
from stella.benchmark.scratch.prepare import RUNS_RELATIVE_DIR
from stella.benchmark.scratch.projection import project_paper_result
from stella.benchmark.scratch.roster_stage import _atomic_write_json
from stella.benchmark.scoring import load_gold_annotations, score_run
from stella.schema_registry import schema_ref


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def evaluate_scratch_run(
    workspace: Path,
    run_id: str,
    *,
    gold_dir: Path,
    arxiv_ids: list[str] | None = None,
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Score one scratch run with the unchanged default scorer.

    Returns the evaluation record written to the run's ``evaluation/`` tree.
    """

    gold_dir = require_external_path(gold_dir, workspace=workspace, label="gold directory")
    run_dir = workspace / RUNS_RELATIVE_DIR / run_id
    if arxiv_ids is None:
        arxiv_ids = sorted(
            path.name for path in (run_dir / "papers").iterdir() if path.is_dir()
        )

    ai_documents: dict[str, dict[str, Any]] = {}
    for arxiv_id in arxiv_ids:
        path = run_dir / "papers" / arxiv_id / "paper_result.json"
        if not path.is_file():
            continue
        result = json.loads(path.read_text(encoding="utf-8"))
        ai_documents[arxiv_id] = project_paper_result(result)

    gold_annotations = {
        arxiv_id: document
        for arxiv_id, document in load_gold_annotations(gold_dir).items()
        if arxiv_id in set(arxiv_ids)
    }
    missing_gold = sorted(set(arxiv_ids) - set(gold_annotations))
    if missing_gold:
        raise ValueError(f"no gold annotation for papers: {', '.join(missing_gold)}")

    if weights is None:
        weights = {arxiv_id: 1.0 for arxiv_id in gold_annotations}
    scorecard, private_details = score_run(
        gold_annotations=gold_annotations,
        ai_documents=ai_documents,
        weights=weights,
        run_label=run_id,
        run_source={
            "pipeline": "hvs_extraction_scratch",
            "run_id": run_id,
            "ai_documents": sorted(ai_documents),
        },
    )

    evaluation_dir = run_dir / "evaluation"
    _atomic_write_json(evaluation_dir / "scorecard.json", scorecard)

    details_dir = gold_dir.parent / "scoring-details" / "scratch" / run_id
    details_dir.mkdir(parents=True, exist_ok=True)
    details_path = details_dir / "details.json"
    temporary = details_path.with_name(details_path.name + ".tmp")
    temporary.write_text(
        json.dumps(private_details, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(details_path)

    record = {
        "schema": schema_ref("benchmark.hvs_extraction_scratch.run_summary"),
        "generated_at": _utc_now(),
        "run_id": run_id,
        "kind": "scratch_evaluation",
        "papers": sorted(ai_documents),
        "scorecard_path": (evaluation_dir / "scorecard.json")
        .relative_to(workspace)
        .as_posix(),
        "details_path": str(details_path),
        "scoring_note": (
            "unchanged default scorer; AI-transcribed uncertainty is not "
            "compared (confirmed D041 gap, see implementation log)"
        ),
    }
    _atomic_write_json(evaluation_dir / "evaluation.json", record)
    return record
