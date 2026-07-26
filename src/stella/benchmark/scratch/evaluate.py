"""Private-gold dev evaluation for immutable v2 scratch runs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stella.benchmark.paths import require_external_path
from stella.benchmark.scratch.prepare import RUNS_RELATIVE_DIR
from stella.benchmark.scratch.projection import project_paper_result
from stella.benchmark.scratch.roster_stage import _atomic_write_json
from stella.benchmark.scratch.run import load_run_config
from stella.benchmark.scoring import load_gold_annotations, score_run
from stella.schema_registry import require_schema, schema_ref


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_consistent_run(
    workspace: Path, run_id: str
) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
    run_dir = workspace / RUNS_RELATIVE_DIR / run_id
    config = load_run_config(workspace, run_id)
    if config["scope"] == "test_smoke":
        raise ValueError("test_smoke runs are never scoreable")
    summary_path = run_dir / "run_summary.json"
    if not summary_path.is_file():
        raise ValueError("run_summary.json is required before evaluation")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    require_schema(
        summary,
        "benchmark.hvs_extraction_scratch.run_summary",
        require_current=True,
    )
    if summary.get("run_id") != run_id:
        raise ValueError("run config and summary run_id mismatch")
    if summary.get("run_fingerprint") != config.get("run_fingerprint"):
        raise ValueError("run config and summary fingerprint mismatch")
    configured = list(config["papers"])
    if list((summary.get("papers") or {}).keys()) != configured:
        raise ValueError("run config and summary paper collections differ")
    papers_dir = run_dir / "papers"
    actual_dirs = (
        {path.name for path in papers_dir.iterdir() if path.is_dir()}
        if papers_dir.is_dir()
        else set()
    )
    extras = sorted(actual_dirs - set(configured))
    if extras:
        raise ValueError(
            "paper directories are not declared by run config: "
            + ", ".join(extras)
        )
    results: dict[str, dict[str, Any]] = {}
    for arxiv_id in configured:
        summary_status = summary["papers"][arxiv_id].get("status")
        result_path = papers_dir / arxiv_id / "paper_result.json"
        if summary_status == "missing":
            if result_path.exists():
                raise ValueError(
                    f"{arxiv_id} is missing in summary but has paper_result.json"
                )
            continue
        if not result_path.is_file():
            raise ValueError(
                f"{arxiv_id} is {summary_status} in summary but lacks paper_result.json"
            )
        result = json.loads(result_path.read_text(encoding="utf-8"))
        require_schema(
            result,
            "benchmark.hvs_extraction_scratch.paper_result",
            require_current=True,
        )
        if (result.get("paper") or {}).get("arxiv_id") != arxiv_id:
            raise ValueError(f"{arxiv_id} paper_result identity mismatch")
        if result.get("run_id") != run_id:
            raise ValueError(f"{arxiv_id} paper_result run_id mismatch")
        if result.get("status") != summary_status:
            raise ValueError(f"{arxiv_id} summary and paper_result status mismatch")
        results[arxiv_id] = result
    return run_dir, config, summary, results


def _field_coverage(scorecard: dict[str, Any]) -> dict[str, dict[str, Any]]:
    coverage: dict[str, dict[str, Any]] = {}
    for field_name, counts in scorecard["l2"]["per_field"].items():
        gold = int(counts.get("gold_quantities") or 0)
        compared = sum(
            int(counts.get(status) or 0)
            for status in (
                "value_match",
                "value_match_cross_format",
                "within_gold_error",
                "value_mismatch",
                "unit_mismatch",
                "limit_kind_mismatch",
            )
        )
        coverage[field_name] = {
            "gold_quantities": gold,
            "compared": compared,
            "coverage": round(compared / gold, 6) if gold else None,
        }
    return coverage


def _walk_attempts(value: Any):
    if isinstance(value, dict):
        if {
            "started_at",
            "finished_at",
            "duration_ms",
            "outcome",
        }.issubset(value):
            yield value
        for child in value.values():
            yield from _walk_attempts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_attempts(child)


def _operational_metrics(
    summary: dict[str, Any], results: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    format_repairs = 0
    evidence_repairs = 0
    attempts: list[dict[str, Any]] = []
    for result in results.values():
        roster_provenance = (result.get("roster") or {}).get("provenance") or {}
        for slot in roster_provenance.get("extractor_repair_history") or []:
            for repair in slot.get("repair_history") or []:
                format_repairs += repair.get("type") == "format_correction"
                evidence_repairs += repair.get("type") == "evidence_correction"
        for repair in roster_provenance.get("adjudicator_repair_history") or []:
            format_repairs += repair.get("type") == "format_correction"
            evidence_repairs += repair.get("type") == "evidence_correction"
        for candidate in result.get("candidates") or []:
            for repair in candidate.get("repair_history") or []:
                format_repairs += repair.get("type") == "format_correction"
                evidence_repairs += repair.get("type") == "evidence_correction"
        attempts.extend(_walk_attempts(result))
    return {
        "format_corrections": int(format_repairs),
        "evidence_corrections": int(evidence_repairs),
        "tail_truncation_salvages": sum(
            1 for attempt in attempts if attempt.get("salvage")
        ),
        "physical_api_attempts": int(summary["totals"].get("api_calls") or 0),
        "tokens": int(summary["totals"].get("tokens") or 0),
        "elapsed_seconds": float(
            summary["totals"].get("elapsed_seconds") or 0.0
        ),
    }


def _delivery_metrics(
    config: dict[str, Any],
    summary: dict[str, Any],
    scorecard: dict[str, Any],
) -> dict[str, Any]:
    l1_by_paper = {
        row["arxiv_id"]: row for row in scorecard["l1"]["per_paper"]
    }
    per_paper: list[dict[str, Any]] = []
    for arxiv_id in config["papers"]:
        l1 = l1_by_paper[arxiv_id]
        per_paper.append(
            {
                "arxiv_id": arxiv_id,
                "delivery_status": summary["papers"][arxiv_id]["status"],
                "gold_status": l1["gold_status"],
                "gold_candidates": l1["gold_candidates"],
                "ai_candidates": l1["ai_candidates"],
                "l1_tp": l1["tp"],
                "l1_fp": l1["fp"],
                "l1_fn": l1["fn"],
            }
        )
    return {
        "complete": summary["totals"]["complete"],
        "partial": summary["totals"]["partial"],
        "failed": summary["totals"]["failed"],
        "missing": summary["totals"]["missing"],
        "expected": summary["totals"]["expected"],
        "delivered": summary["totals"]["delivered"],
        "delivery_rate": summary["totals"]["delivery_rate"],
        "per_paper": per_paper,
    }


def evaluate_scratch_run(
    workspace: Path,
    run_id: str,
    *,
    gold_dir: Path,
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Score a consistent v2 dev run; no threshold or pass/fail is applied."""

    gold_dir = require_external_path(
        gold_dir, workspace=workspace, label="gold directory"
    )
    run_dir, config, summary, results = _load_consistent_run(workspace, run_id)
    papers = list(config["papers"])
    ai_documents = {
        arxiv_id: project_paper_result(result)
        for arxiv_id, result in results.items()
    }
    available_gold = load_gold_annotations(gold_dir)
    gold_annotations = {
        arxiv_id: available_gold[arxiv_id]
        for arxiv_id in papers
        if arxiv_id in available_gold
    }
    missing_gold = [paper for paper in papers if paper not in gold_annotations]
    if missing_gold:
        raise ValueError(f"no gold annotation for papers: {', '.join(missing_gold)}")
    if weights is None:
        weights = {arxiv_id: 1.0 for arxiv_id in papers}
    scorecard, private_details = score_run(
        gold_annotations=gold_annotations,
        ai_documents=ai_documents,
        weights=weights,
        run_label=run_id,
        run_source={
            "pipeline": "hvs_extraction_scratch",
            "run_id": run_id,
            "run_fingerprint": config["run_fingerprint"],
            "papers": papers,
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

    l2_micro = scorecard["l2"]["micro"]
    report = {
        "schema": schema_ref("benchmark.hvs_extraction_scratch.evaluation"),
        "generated_at": _utc_now(),
        "run_id": run_id,
        "run_fingerprint": config["run_fingerprint"],
        "scope": config["scope"],
        "papers": papers,
        "delivery": _delivery_metrics(config, summary, scorecard),
        "l1": {
            "precision": scorecard["l1"]["micro"]["precision"],
            "recall": scorecard["l1"]["micro"]["recall"],
            "f1": scorecard["l1"]["micro"]["f1"],
            "tp": scorecard["l1"]["micro"]["tp"],
            "fp": scorecard["l1"]["micro"]["fp"],
            "fn": scorecard["l1"]["micro"]["fn"],
        },
        "l2": {
            "strict_agreement": l2_micro["agreement_over_compared_strict"],
            "lenient_agreement": l2_micro["agreement_over_compared_lenient"],
            "coverage": l2_micro["coverage"],
            "fill_precision_strict": l2_micro["fill_precision_strict"],
            "fill_precision_lenient": l2_micro["fill_precision_lenient"],
        },
        "per_field_coverage": _field_coverage(scorecard),
        "operations": _operational_metrics(summary, results),
        "scorecard_path": (evaluation_dir / "scorecard.json")
        .relative_to(workspace)
        .as_posix(),
        "private_details_path": str(details_path),
        "uncertainty_note": (
            "D041/D042 uncertainty transcription is preserved but is not "
            "formally scored yet, per D043."
        ),
        "decision_policy": (
            "No composite score, numeric threshold, automatic pass, or "
            "automatic fail is produced."
        ),
    }
    _atomic_write_json(evaluation_dir / "evaluation.json", report)
    return report


def render_terminal_report(report: dict[str, Any]) -> str:
    """Readable metric sections with no synthetic overall verdict."""

    delivery = report["delivery"]
    l1 = report["l1"]
    l2 = report["l2"]
    operations = report["operations"]
    lines = [
        f"Scratch dev evaluation: {report['run_id']}",
        "",
        "Delivery",
        (
            f"  complete={delivery['complete']} partial={delivery['partial']} "
            f"failed={delivery['failed']} missing={delivery['missing']} "
            f"delivery_rate={delivery['delivery_rate']}"
        ),
    ]
    for paper in delivery["per_paper"]:
        lines.append(
            "  "
            f"{paper['arxiv_id']}: delivery={paper['delivery_status']} "
            f"gold_candidates={paper['gold_candidates']} "
            f"ai_candidates={paper['ai_candidates']} "
            f"tp={paper['l1_tp']} fp={paper['l1_fp']} fn={paper['l1_fn']}"
        )
    lines.extend(
        [
            "",
            "L1",
            (
                f"  precision={l1['precision']} recall={l1['recall']} "
                f"f1={l1['f1']}"
            ),
            "",
            "L2",
            (
                f"  strict_agreement={l2['strict_agreement']} "
                f"lenient_agreement={l2['lenient_agreement']} "
                f"coverage={l2['coverage']} "
                f"fill_precision_strict={l2['fill_precision_strict']} "
                f"fill_precision_lenient={l2['fill_precision_lenient']}"
            ),
            "",
            "Per-field coverage",
        ]
    )
    for field_name, field in report["per_field_coverage"].items():
        lines.append(
            f"  {field_name}: {field['coverage']} "
            f"({field['compared']}/{field['gold_quantities']})"
        )
    lines.extend(
        [
            "",
            "Operations",
            (
                f"  format_corrections={operations['format_corrections']} "
                f"evidence_corrections={operations['evidence_corrections']} "
                f"tail_truncation_salvages={operations['tail_truncation_salvages']} "
                f"physical_api_attempts={operations['physical_api_attempts']} "
                f"tokens={operations['tokens']} "
                f"elapsed_seconds={operations['elapsed_seconds']}"
            ),
            "",
            report["uncertainty_note"],
            report["decision_policy"],
        ]
    )
    return "\n".join(lines)
